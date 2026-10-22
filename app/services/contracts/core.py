"""Contract rows: when they exist, what money they quote, and rendering their PDF.

A contract is **materialised lazily**: every enrollment in a course whose contract
template is a PDF gets a ``pending`` contract the first time anyone lists
contracts. That covers every way an enrollment is made (web checkout, the app,
staff) without hooking each of them. A pending contract whose enrollment is
cancelled turns ``cancelled`` (and back to ``pending`` if it is re-activated); a
signed one stays signed — it is a record of what was agreed.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import contains_eager

from app.extensions import db
from app.models import Cohort, Course, Enrollment, StudentContract, StudentLedger
from app.storage import S3StorageError, read_template
from app.timeutil import utcnow

from ..errors import ServiceError
from ..payments.ledger import price_for
from . import fields
from .pdf import TemplateError, fill_contract


def has_pdf_template(course) -> bool:
    return course is not None and course.has_pdf_contract_template


def _new_contract(enr, year: int) -> StudentContract:
    """The number comes from the row's own id (taken from the sequence first), so two
    concurrent syncs can never pick the same one."""
    pk = db.session.execute(text("SELECT nextval('student_contracts_id_seq')")).scalar()
    return StudentContract(
        id=pk, enrollment_id=enr.id, student_id=enr.student_id,
        course_id=enr.cohort.course_id, cohort_id=enr.cohort_id,
        contract_number=f"AIAA-C-{year}-{pk:05d}", status="pending")


def _sync_once(enrollments) -> None:
    existing = {c.enrollment_id: c for c in StudentContract.query.filter(
        StudentContract.enrollment_id.in_([e.id for e in enrollments]))} if enrollments else {}
    now = utcnow()
    for enr in enrollments:
        contract = existing.get(enr.id)
        active = enr.status == "active"
        if contract is None:
            if active:
                db.session.add(_new_contract(enr, now.year))
            continue
        if contract.status == "pending" and not active:
            contract.status, contract.cancelled_at = "cancelled", now
        elif contract.status == "cancelled" and active:
            contract.status, contract.cancelled_at = "pending", None
        if contract.status != "signed" and contract.cohort_id != enr.cohort_id:
            contract.cohort_id = enr.cohort_id  # moved to another cohort of the course
    if db.session.new or db.session.dirty:
        db.session.commit()


def sync(*, student_id=None, course_id=None, cohort_id=None) -> None:
    """Create / cancel contracts to match the enrollments (see the module doc).

    Enrollments that already have a contract are followed even if their course's
    template has since been removed, so a cancellation still reaches the contract.
    """
    has_contract = db.session.query(StudentContract.enrollment_id)
    q = (Enrollment.query.join(Cohort, Enrollment.cohort_id == Cohort.id)
         .join(Course, Cohort.course_id == Course.id)
         .filter(or_(Course.contract_template_key.ilike("%.pdf"),
                     Enrollment.id.in_(has_contract))))
    if student_id is not None:
        q = q.filter(Enrollment.student_id == student_id)
    if course_id is not None:
        q = q.filter(Cohort.course_id == course_id)
    if cohort_id is not None:
        q = q.filter(Enrollment.cohort_id == cohort_id)
    enrollments = q.options(contains_eager(Enrollment.cohort)).order_by(Enrollment.id).all()
    for _ in range(3):  # a concurrent sync may have created the same enrollment's row
        try:
            _sync_once(enrollments)
            return
        except IntegrityError:
            db.session.rollback()
    raise ServiceError(503, "contract_sync_busy")


# ------------------------------------------------------------------- money & rules
def finance(contract: StudentContract) -> dict:
    """Due / paid / balance from the ledger; the frozen figures once signed."""
    course = contract.course
    if contract.status == "signed":
        due, paid, balance = contract.total_due, contract.total_paid, contract.balance
        discount = contract.discount_percent
    else:
        ledger = StudentLedger.query.filter_by(enrollment_id=contract.enrollment_id).first()
        if ledger is not None:
            due, paid, balance = ledger.total_due, ledger.total_paid, ledger.balance
        else:  # the price frozen at enrolment, not the course's current one
            due = price_for(contract.enrollment) if contract.enrollment else Decimal(0)
            paid, balance = Decimal(0), due
        discount = _discount(course, due)
    return {
        "total_due": float(due or 0), "total_paid": float(paid or 0),
        "balance": float(balance or 0), "discount_percent": discount,
        "currency": course.currency or "MNT",
    }


def _discount(course, due) -> int:
    """(list price − amount due) / list price, as the web form computed it."""
    price = course.price_amount
    if not price or due is None or due >= price:
        return 0
    return round((price - due) / price * 100)


def rules(contract: StudentContract, money: dict, today) -> dict:
    end = contract.cohort.end_date if contract.cohort is not None else None
    return {
        "guardian_required": contract.course.level == "junior",
        "final_payment_date_required": money["balance"] > 0,
        "final_payment_date_min": today.isoformat(),
        # A cohort that has already ended must not make the date impossible to pick.
        "final_payment_date_max": end.isoformat() if end and end >= today else None,
    }


# ------------------------------------------------------------------- PDF
def load_template(contract: StudentContract) -> bytes:
    course = contract.course
    if not has_pdf_template(course):
        raise ServiceError(409, "contract_template_missing")
    try:
        return read_template(course.contract_template_key, course.updated_at)
    except S3StorageError:
        raise ServiceError(502, "storage_error") from None


def render(contract: StudentContract, form: dict, money: dict, today,
           signature_png: bytes | None = None) -> bytes:
    values = fields.build_values(
        form, contract_number=contract.contract_number,
        programme=contract.course.title_mn, finance=money, today=today)
    try:
        return fill_contract(load_template(contract), values, signature_png)
    except TemplateError:
        raise ServiceError(409, "contract_template_invalid") from None
