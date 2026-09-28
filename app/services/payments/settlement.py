"""Settlement — recording verified money against an invoice, idempotently."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from flask import current_app

from app.extensions import db
from app.models import Invoice, Payment, PaymentInstallment
from app.payments import PaymentStatus

from .ledger import recompute_ledger


# ------------------------------------------------------------------- settlement
def settle(invoice: Invoice, status: PaymentStatus) -> Payment | None:
    """Record a verified settlement. Idempotent on (provider, provider_payment_id).

    Returns the Payment (new or pre-existing) when paid, else None. Marks the
    invoice + linked installment paid and refreshes the student ledger.
    """
    if not status.paid:
        return None

    txn_id = status.provider_payment_id or invoice.sender_invoice_no
    existing = Payment.query.filter_by(
        provider=invoice.provider, provider_payment_id=txn_id
    ).first()
    if existing is not None:
        if _is_short(invoice, existing.amount):
            return None
        _mark_invoice_paid(invoice, existing.paid_at)  # ensure invoice reflects it
        db.session.commit()
        return existing

    received = status.amount if status.amount is not None else invoice.amount
    if _is_short(invoice, received):
        _record_short_payment(invoice, status, txn_id, received)
        return None

    if invoice.status == "cancelled":
        # Retired when the buyer switched gateway, and paid anyway. The money is
        # real and is recorded, but the booking now points at the other invoice.
        current_app.logger.warning(
            "cancelled invoice %s (%s) was paid — link it to its booking by hand",
            invoice.id, invoice.sender_invoice_no,
        )
    payment = Payment(
        invoice_id=invoice.id,
        provider=invoice.provider,
        provider_payment_id=txn_id,
        amount=received,
        currency=invoice.currency,
        status="paid",
        method=status.method,
        paid_at=status.paid_at or datetime.utcnow(),
        raw=status.raw,
    )
    db.session.add(payment)
    _mark_invoice_paid(invoice, payment.paid_at)
    if invoice.installment_id:
        _mark_installment_paid(invoice.installment_id, payment.paid_at)
    db.session.flush()
    if invoice.enrollment_id:
        recompute_ledger(invoice.enrollment_id)
    db.session.commit()
    _issue_ebarimt(payment)
    return payment


def _is_short(invoice: Invoice, received) -> bool:
    return received is not None and Decimal(str(received)) < Decimal(str(invoice.amount))


def _record_short_payment(invoice: Invoice, status: PaymentStatus, txn_id, received):
    """Book money that arrived short of the invoice, without settling anything.

    The money is real, so it is recorded and counts toward the ledger — but the
    invoice stays open and its installment unpaid: marking them paid would clear
    a debt the buyer has not covered. No receipt is issued either; the seat and
    the tax receipt wait for finance, who find these by the log line below.
    """
    payment = Payment(
        invoice_id=invoice.id,
        provider=invoice.provider,
        provider_payment_id=txn_id,
        amount=received,
        currency=invoice.currency,
        status="paid",
        method=status.method,
        paid_at=status.paid_at or datetime.utcnow(),
        raw=status.raw,
    )
    db.session.add(payment)
    db.session.flush()
    if invoice.enrollment_id:
        recompute_ledger(invoice.enrollment_id)
    db.session.commit()
    current_app.logger.warning(
        "underpayment on invoice %s (%s): received %s of %s — left open for finance",
        invoice.id, invoice.sender_invoice_no, received, invoice.amount,
    )


def _issue_ebarimt(payment: Payment):
    """Auto-issue an eBarimt receipt for a fresh settlement (best-effort, temp-aware)."""
    from app.services import ebarimt as ebarimt_svc  # local import avoids import cycle
    ebarimt_svc.issue_if_enabled(payment)


def _mark_invoice_paid(invoice: Invoice, when):
    invoice.status = "paid"
    invoice.paid_at = invoice.paid_at or when or datetime.utcnow()


def _mark_installment_paid(installment_id, when):
    inst = db.session.get(PaymentInstallment, installment_id)
    if inst is not None and inst.status != "paid":
        inst.status = "paid"
        inst.paid_at = when or datetime.utcnow()
