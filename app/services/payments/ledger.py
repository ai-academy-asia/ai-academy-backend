"""The student ledger — an enrollment's receivable summary, rebuilt from source rows."""
from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models import Course, Enrollment, Invoice, Payment, PaymentInstallment, StudentLedger

from ..errors import ServiceError


# ------------------------------------------------------------------- price
def course_of(enr: Enrollment) -> Course | None:
    if enr.cohort is not None and enr.cohort.course is not None:
        return enr.cohort.course
    return db.session.get(Course, enr.course_id) if enr.course_id else None


def price_for(enr: Enrollment) -> Decimal:
    """The price frozen at enrolment; the course's current one only for a row
    that was never frozen."""
    if enr.price_amount is not None:
        return Decimal(str(enr.price_amount))
    course = course_of(enr)
    return Decimal(str((course.final_price_amount if course else None) or 0))


# ------------------------------------------------------------------- ledger
def recompute_ledger(enrollment_id) -> StudentLedger:
    """Rebuild the enrollment's receivable summary from source rows.

    total_paid  = Σ verified Payments (net of refunds) on this enrollment's invoices
    total_due   = Σ non-waived installment amounts if a plan exists, else the
                  enrollment's price — never what happened to be paid
    next_due    = earliest unpaid installment's due date
    """
    enr = db.session.get(Enrollment, enrollment_id)
    if enr is None:
        raise ServiceError(404, "enrollment_not_found")

    paid = db.session.query(db.func.coalesce(db.func.sum(
        Payment.amount - db.func.coalesce(Payment.refunded_amount, 0)
    ), 0)).join(Invoice, Payment.invoice_id == Invoice.id).filter(
        Invoice.enrollment_id == enrollment_id, Payment.status != "refunded"
    ).scalar() or Decimal(0)

    installments = PaymentInstallment.query.filter_by(enrollment_id=enrollment_id).all()
    if installments:
        total_due = sum((i.amount or Decimal(0) for i in installments
                         if i.status != "waived"), Decimal(0))
        unpaid = [i for i in installments if i.status not in ("paid", "waived") and i.due_date]
        next_due = min((i.due_date for i in unpaid), default=None)
    else:
        total_due = price_for(enr)
        next_due = None

    ledger = StudentLedger.query.filter_by(enrollment_id=enrollment_id).first()
    if ledger is None:
        ledger = StudentLedger(student_id=enr.student_id, enrollment_id=enrollment_id,
                               currency=enr.currency or "MNT")
        db.session.add(ledger)
    ledger.total_paid = Decimal(str(paid))
    ledger.total_due = Decimal(str(total_due))
    ledger.next_due_date = next_due
    ledger.recompute_balance()
    return ledger


def get_ledger(enrollment_id) -> StudentLedger:
    ledger = StudentLedger.query.filter_by(enrollment_id=enrollment_id).first()
    if ledger is None:
        raise ServiceError(404, "ledger_not_found")
    return ledger
