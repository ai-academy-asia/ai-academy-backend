"""Shared helpers for the payment service: amounts, references, lookups, errors."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import uuid4

from app.models import Invoice
from app.payments import PaymentGatewayError

from ..errors import ServiceError, from_integration_error
from ..params import get_by_id


def _to_amount(value) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ServiceError(400, "invalid_amount") from None
    if not amount.is_finite():  # NaN / Infinity parse fine and then break arithmetic
        raise ServiceError(400, "invalid_amount")
    if amount <= 0:
        raise ServiceError(400, "amount_must_be_positive")
    return amount.quantize(Decimal("0.01"))


def _gen_reference(provider: str) -> str:
    """Globally-unique merchant reference: AIAA-QP-<12 hex>. This is what we send
    to the gateway and match a Golomt statement credit on."""
    return f"AIAA-{provider[:2].upper()}-{uuid4().hex[:12].upper()}"


def get_invoice(invoice_id) -> Invoice:
    invoice = get_by_id(Invoice, invoice_id)
    if invoice is None:
        raise ServiceError(404, "invoice_not_found")
    return invoice


def get_invoice_by_ref(ref: str) -> Invoice:
    invoice = Invoice.query.filter_by(sender_invoice_no=ref).first()
    if invoice is None:
        raise ServiceError(404, "invoice_not_found")
    return invoice


# --------------------------------------------------------------------- errors
def _as_service_error(exc: PaymentGatewayError) -> ServiceError:
    """Translate a low-level gateway failure into an HTTP-shaped ServiceError.

    Configuration problems are ours, not the gateway's, so they get their own
    statuses; everything else follows the shared retriable -> 503/502 rule.
    """
    if exc.message in ("not_configured", "unsupported_provider"):
        status = 501 if exc.message == "not_configured" else 400
        return ServiceError(
            status, f"gateway_{exc.message}", provider=exc.provider,
            internal=exc.detail,
        )
    return from_integration_error(exc, prefix="gateway_", provider=exc.provider)
