"""How money gets confirmed: gateway callbacks, status polling, Golomt reconcile.

Each path re-verifies with the gateway and then hands off to :func:`settle`.
"""
from __future__ import annotations

from datetime import date

# Look the provider up through the gateway package at call time (not a name
# imported here), so a test that patches ``app.payments.get_provider`` reaches
# every submodule of this package.
from app import payments as gateways
from app.models import Invoice
from app.payments import SUPPORTED_PROVIDERS, PaymentGatewayError, PaymentStatus

from ..errors import ServiceError
from .helpers import _as_service_error, get_invoice_by_ref
from .settlement import settle


# ------------------------------------------------------------------- callbacks
def handle_callback(provider: str, ref: str | None, payload: dict, headers: dict) -> dict:
    """Process an inbound gateway webhook. Always re-verifies with the gateway
    (never trusts the callback body) before settling."""
    if provider not in SUPPORTED_PROVIDERS:
        raise ServiceError(400, "unsupported_provider")
    invoice = _find_invoice_for_callback(provider, ref, payload)
    # Verify with the gateway that actually raised this invoice, not the one
    # named in the URL. Trusting the path would let anyone settle a QPay
    # invoice by posting to another provider's callback with its reference.
    if invoice.provider != provider:
        raise ServiceError(404, "invoice_not_found")
    try:
        status = gateways.get_provider(invoice.provider).verify_callback(invoice, payload, headers)
    except PaymentGatewayError as exc:
        raise _as_service_error(exc) from exc
    payment = settle(invoice, status)
    return {
        "ref": invoice.sender_invoice_no,
        "invoice_id": invoice.id,
        "status": invoice.status,
        "paid": bool(payment),
    }


def _find_invoice_for_callback(provider, ref, payload):
    if ref:
        return get_invoice_by_ref(ref)
    # Fall back to provider-specific ids echoed in the body.
    candidates = [
        payload.get("sender_invoice_no"),
        payload.get("orderId"),
        payload.get("reference"),
    ]
    for value in candidates:
        if value:
            inv = Invoice.query.filter_by(sender_invoice_no=value).first()
            if inv:
                return inv
    provider_id = payload.get("invoice_id") or payload.get("loanId") or payload.get("payment_id")
    if provider_id:
        inv = Invoice.query.filter_by(
            provider=provider, provider_invoice_id=str(provider_id)
        ).first()
        if inv:
            return inv
    raise ServiceError(404, "invoice_not_found")


# ------------------------------------------------------------- status / polling
def check_status(invoice: Invoice) -> Invoice:
    """Poll the gateway and settle if newly paid. Safe to call repeatedly."""
    if invoice.status == "paid":
        return invoice
    try:
        status = gateways.get_provider(invoice.provider).check_invoice(invoice)
    except PaymentGatewayError as exc:
        raise _as_service_error(exc) from exc
    settle(invoice, status)
    return invoice


# ----------------------------------------------------------- Golomt reconcile
def reconcile_golomt(from_date: date, to_date: date) -> dict:
    """Pull the Golomt corporate statement and settle any pending bank-transfer
    invoices whose reference + amount match a credit. Returns a summary."""
    provider = gateways.get_provider("golomt")
    try:
        txns = provider.fetch_all_statements(from_date, to_date)
    except PaymentGatewayError as exc:
        raise _as_service_error(exc) from exc

    pending = Invoice.query.filter_by(provider="golomt", status="pending").all()
    matched, settled = [], 0
    for invoice in pending:
        for txn in txns:
            if provider.matches(invoice, txn):
                status = PaymentStatus(
                    paid=True, provider_payment_id=txn.txn_id or invoice.sender_invoice_no,
                    amount=txn.amount, paid_at=txn.posted_at, method="transfer", raw=txn.raw,
                )
                if settle(invoice, status):
                    settled += 1
                    matched.append({"invoice_id": invoice.id, "ref": invoice.sender_invoice_no,
                                    "txn_id": txn.txn_id, "amount": float(txn.amount),
                                    "account": txn.account})
                break
    return {
        "from": from_date.isoformat(), "to": to_date.isoformat(),
        "statement_txns": len(txns), "pending_invoices": len(pending),
        "settled": settled, "matched": matched,
    }
