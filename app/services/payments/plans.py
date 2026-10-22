"""What an enrollment owes: the price frozen at enrolment and its installment plan.

Every enrolment freezes the course's discounted price on the enrollment row and
gets a default plan from the course's rule (``installment_count`` equal payments,
the first on the cohort's start date, then every ``installment_interval_months``).
Finance can then add, edit, remove or waive unpaid installments.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import ROUND_DOWN, Decimal

from app.extensions import db
from app.models import Enrollment, Invoice, PaymentInstallment

from ..errors import ServiceError
from .helpers import _to_amount
from .ledger import course_of, price_for, recompute_ledger

# Installments finance may still change; paid and waived ones are history.
EDITABLE_STATUSES = ("pending", "overdue")


# ------------------------------------------------------------------- price
def snapshot_price(enr: Enrollment) -> None:
    if enr.price_amount is None:
        course = course_of(enr)
        enr.price_amount = price_for(enr)
        enr.currency = (course.currency if course else None) or "MNT"


# ------------------------------------------------------------------- default plan
def _add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def split(total: Decimal, count: int) -> list[Decimal]:
    """Equal whole-tögrög parts; the first carries the remainder."""
    part = (total / count).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return [total - part * (count - 1)] + [part] * (count - 1)


def create_default_plan(enr: Enrollment) -> list[PaymentInstallment]:
    """The course-rule plan, unless the enrollment already has one or is free."""
    if PaymentInstallment.query.filter_by(enrollment_id=enr.id).first() is not None:
        raise ServiceError(409, "plan_exists")
    total = price_for(enr)
    if total <= 0:
        return []
    course = course_of(enr)
    count = max(1, int(getattr(course, "installment_count", None) or 1))
    every = max(1, int(getattr(course, "installment_interval_months", None) or 1))
    first = (enr.cohort.start_date if enr.cohort is not None else None) or date.today()
    rows = [
        PaymentInstallment(enrollment_id=enr.id, student_id=enr.student_id, seq=i + 1,
                           due_date=_add_months(first, i * every), amount=amount)
        for i, amount in enumerate(split(total, count))
    ]
    db.session.add_all(rows)
    return rows


def on_enrolled(enr: Enrollment) -> None:
    """Freeze the price, lay out the plan and open the ledger. Commits."""
    snapshot_price(enr)
    db.session.flush()
    if PaymentInstallment.query.filter_by(enrollment_id=enr.id).first() is None:
        create_default_plan(enr)
    db.session.flush()
    recompute_ledger(enr.id)
    db.session.commit()


# ------------------------------------------------------------------- finance edits
def get_enrollment(enrollment_id) -> Enrollment:
    enr = db.session.get(Enrollment, enrollment_id)
    if enr is None:
        raise ServiceError(404, "enrollment_not_found")
    return enr


def get_installment(installment_id) -> PaymentInstallment:
    inst = db.session.get(PaymentInstallment, installment_id)
    if inst is None:
        raise ServiceError(404, "installment_not_found")
    return inst


def plan(enr: Enrollment) -> dict:
    rows = (PaymentInstallment.query.filter_by(enrollment_id=enr.id)
            .order_by(PaymentInstallment.seq).all())
    ledger = recompute_ledger(enr.id)
    db.session.commit()
    return {"enrollment_id": enr.id, "price_amount": float(price_for(enr)),
            "currency": enr.currency or "MNT", "ledger": ledger.to_dict(),
            "installments": [i.to_dict() for i in rows]}


def _due_date(value) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ServiceError(400, "invalid_date", field="due_date") from None


def add_installment(enr: Enrollment, data: dict) -> PaymentInstallment:
    last = (db.session.query(db.func.max(PaymentInstallment.seq))
            .filter_by(enrollment_id=enr.id).scalar()) or 0
    inst = PaymentInstallment(
        enrollment_id=enr.id, student_id=enr.student_id, seq=last + 1,
        due_date=_due_date(data.get("due_date")), amount=_to_amount(data.get("amount")))
    db.session.add(inst)
    _settle_books(enr.id)
    return inst


def _editable(inst: PaymentInstallment) -> PaymentInstallment:
    if inst.status not in EDITABLE_STATUSES:
        raise ServiceError(409, "installment_settled", installment_status=inst.status)
    return inst


def update_installment(inst: PaymentInstallment, data: dict) -> PaymentInstallment:
    _editable(inst)
    if "amount" in data:
        inst.amount = _to_amount(data["amount"])
    if "due_date" in data:
        inst.due_date = _due_date(data["due_date"])
    _settle_books(inst.enrollment_id)
    return inst


def delete_installment(inst: PaymentInstallment) -> None:
    _editable(inst)
    if Invoice.query.filter_by(installment_id=inst.id).first() is not None:
        # An invoice (maybe still payable) points here; waive it instead.
        raise ServiceError(409, "installment_has_invoices")
    enrollment_id = inst.enrollment_id
    db.session.delete(inst)
    _settle_books(enrollment_id)


def waive_installment(inst: PaymentInstallment) -> PaymentInstallment:
    _editable(inst).status = "waived"
    _settle_books(inst.enrollment_id)
    return inst


def _settle_books(enrollment_id) -> None:
    db.session.flush()
    recompute_ledger(enrollment_id)
    db.session.commit()
