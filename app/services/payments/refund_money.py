"""Refund money math — the payment row and ledger side of a refund only."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.extensions import db
from app.models import Payment

from ..errors import ServiceError
from .helpers import _to_amount
from .ledger import recompute_ledger


# ------------------------------------------------------------------- refunds
def compute_refund_amount(payment: Payment, *, pct_attended=None, amount=None) -> Decimal:
    """How much of ``payment`` has gone back once this refund lands — the running
    total, not the increment — without touching anything.

    Split out of :func:`refund` because the eBarimt side has to know the figure
    *before* the money moves: whether the tax receipt is voided outright or
    voided and re-issued for the remainder depends on what the buyer keeps, and
    the PosAPI call has to run before the database write (see
    :mod:`app.services.refunds`).
    """
    original = payment.amount or Decimal(0)
    already = payment.refunded_amount or Decimal(0)
    # The figure is the running total returned, not an increment: re-sending the
    # same request (a double-click, a retry after a timeout) must not pay out twice.
    if amount is not None:
        total = _to_amount(amount)
        if total > original:
            raise ServiceError(400, "refund_exceeds_payment")
    elif pct_attended is not None:
        total = (original * Decimal("0.5")) if int(pct_attended) < 20 else Decimal(0)
        if total <= 0 and already <= 0:
            raise ServiceError(409, "nothing_to_refund", pct_attended=int(pct_attended))
    else:
        raise ServiceError(400, "refund_basis_required")
    # Money already handed back cannot be taken back by a lower figure.
    if total < already:
        raise ServiceError(400, "refund_below_already_refunded",
                           already_refunded=float(already))
    return total


def refund(
    payment: Payment, *, pct_attended: int | None = None, amount=None, reason=None
) -> Payment:
    """Apply a refund. Pilot rule: attendance <20% → 50% back, ≥20% → nothing.

    ``amount`` overrides the computed refund (finance discretion) and is the
    total returned, including any earlier partial refund. Recomputes the ledger
    afterward.

    Money only — the tax receipt and the seat are the caller's business. Go
    through :mod:`app.services.refunds` unless you mean to touch just this row.
    """
    if payment.status == "refunded":
        raise ServiceError(409, "already_refunded")
    original = payment.amount or Decimal(0)
    total = compute_refund_amount(payment, pct_attended=pct_attended, amount=amount)

    payment.refunded_amount = total
    payment.refund_pct_attended = pct_attended
    payment.refund_reason = (str(reason).strip()[:255] or None) if reason else None
    payment.refunded_at = datetime.utcnow()
    payment.status = "refunded" if total >= original else "partially_refunded"
    db.session.flush()
    if payment.invoice and payment.invoice.enrollment_id:
        recompute_ledger(payment.invoice.enrollment_id)
    db.session.commit()
    return payment
