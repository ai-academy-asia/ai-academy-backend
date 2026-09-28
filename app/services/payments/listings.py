"""Read-side listings and lookups for invoices and payments."""
from __future__ import annotations

from app.models import Invoice, Payment

from ..errors import ServiceError
from ..params import get_by_id, parse_limit


# ------------------------------------------------------------------- listings
def list_invoices(*, provider=None, status=None, enrollment_id=None, student_id=None, limit=50):
    q = Invoice.query
    if provider:
        q = q.filter_by(provider=provider)
    if status:
        q = q.filter_by(status=status)
    if enrollment_id and str(enrollment_id).isdigit():
        q = q.filter_by(enrollment_id=int(enrollment_id))
    if student_id and str(student_id).isdigit():
        q = q.filter_by(student_id=int(student_id))
    return q.order_by(Invoice.id.desc()).limit(parse_limit(limit)).all()


def list_payments(*, provider=None, status=None, invoice_id=None, limit=50):
    q = Payment.query
    if provider:
        q = q.filter_by(provider=provider)
    if status:
        q = q.filter_by(status=status)
    if invoice_id and str(invoice_id).isdigit():
        q = q.filter_by(invoice_id=int(invoice_id))
    return q.order_by(Payment.id.desc()).limit(parse_limit(limit)).all()


def get_payment(payment_id) -> Payment:
    payment = get_by_id(Payment, payment_id)
    if payment is None:
        raise ServiceError(404, "payment_not_found")
    return payment
