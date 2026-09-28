"""The student ledger — an enrollment's receivable summary, rebuilt from source rows."""
from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models import Enrollment, Invoice, Payment, PaymentInstallment, StudentLedger

from ..errors import ServiceError


# ------------------------------------------------------------------- ledger
def recompute_ledger(enrollment_id) -> StudentLedger:
    """Rebuild the enrollment's receivable summary from source rows.

    total_paid  = Σ verified Payments (net of refunds) on this enrollment's invoices
    total_due   = Σ installment amounts if a plan exists, else total_paid
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
        total_due = sum((i.amount or Decimal(0) for i in installments), Decimal(0))
        unpaid = [i for i in installments if i.status not in ("paid", "waived") and i.due_date]
        next_due = min((i.due_date for i in unpaid), default=None)
    else:
        total_due = Decimal(str(paid))
        next_due = None

    ledger = StudentLedger.query.filter_by(enrollment_id=enrollment_id).first()
    if ledger is None:
        ledger = StudentLedger(student_id=enr.student_id, enrollment_id=enrollment_id)
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
