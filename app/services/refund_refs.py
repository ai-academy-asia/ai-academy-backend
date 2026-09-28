"""Refund references — turning whatever finance holds into (payment, receipt).

Split out of :mod:`app.services.refunds`, which re-exports the public names
(``REFERENCE_KEYS``, ``detect_reference``, ``resolve``).
"""
from __future__ import annotations

from app.extensions import db
from app.models import EBarimtReceipt, Payment, SeatBooking

from . import ebarimt as ebarimt_svc
from . import payments as pay_svc
from .errors import ServiceError

# What a caller may point at. Ordered most- to least-direct; the first key
# present in the body wins, so an explicit payment_id always beats a lottery
# number typed off a receipt.
REFERENCE_KEYS = (
    "payment_id", "payment_token", "invoice_id", "receipt_id", "ebarimt_id", "lottery",
)


def detect_reference(text) -> dict:
    """Turn one number typed off a receipt into the right reference key.

    Finance holds one number and does not know which of our six fields it is.
    Guessing is safe here because the shapes do not overlap: a payment token
    carries its ``pt_`` prefix, a lottery has letters or is the 8-digit tail of
    one, a ДДТД is a 33-digit string. Only a short bare number is genuinely
    ambiguous, and that is our own payment id.
    """
    value = " ".join(str(text or "").split())
    if not value:
        raise ServiceError(400, "refund_reference_required", accepts=list(REFERENCE_KEYS))
    if value.startswith("pt_"):
        return {"payment_token": value}
    digits = "".join(ch for ch in value if ch.isdigit())
    if any(ch.isalpha() for ch in value):
        return {"lottery": value}
    if len(digits) >= 20:
        return {"ebarimt_id": digits}
    if len(digits) >= 7:
        return {"lottery": digits}
    return {"payment_id": digits}


# ------------------------------------------------------------------ reference
def resolve(data: dict) -> tuple[Payment, EBarimtReceipt | None]:
    """(payment, receipt) for whichever reference the caller sent."""
    key = next((k for k in REFERENCE_KEYS if data.get(k) not in (None, "")), None)
    if key is None:
        raise ServiceError(400, "refund_reference_required", accepts=list(REFERENCE_KEYS))

    value = data[key]
    receipt = None
    if key == "payment_id":
        payment = pay_svc.get_payment(value)
    elif key == "payment_token":
        payment = _payment_for_invoice(_booking_for_token(value).invoice_id, ref=value)
    elif key == "invoice_id":
        payment = _payment_for_invoice(_as_int(value), ref=value)
    else:
        receipt = _receipt_by(key, value)
        if receipt.payment_id is None:
            raise ServiceError(409, "receipt_has_no_payment", receipt_id=receipt.id)
        payment = pay_svc.get_payment(receipt.payment_id)

    return payment, receipt if receipt is not None else _receipt_for(payment)


def _receipt_by(key: str, value) -> EBarimtReceipt:
    if key == "receipt_id":
        return ebarimt_svc.get_receipt(value)
    if key == "ebarimt_id":
        rows = EBarimtReceipt.query.filter_by(ebarimt_id=str(value).strip()).all()
    else:
        rows = _receipts_by_lottery(value)
    if not rows:
        raise ServiceError(404, "receipt_not_found", **{key: str(value)})
    if len(rows) > 1:
        # Two receipts answering one number is a data problem, not a refund the
        # server may pick a winner for.
        raise ServiceError(409, "ambiguous_reference", receipt_ids=[r.id for r in rows])
    return rows[0]


def _receipts_by_lottery(value) -> list:
    """Match a lottery number as printed, as typed, or as digits only.

    Receipts carry it as ``"HQ 92232007"``; people read the digits off the paper
    and drop the prefix or the space, and that should still find the receipt.
    """
    text = " ".join(str(value).split()).upper()
    digits = "".join(ch for ch in text if ch.isdigit())
    clauses = [db.func.upper(EBarimtReceipt.lottery) == text]
    if digits:
        clauses.append(
            db.func.replace(db.func.upper(EBarimtReceipt.lottery), " ", "").like(f"%{digits}")
        )
    return EBarimtReceipt.query.filter(db.or_(*clauses)).all()


def _receipt_for(payment: Payment) -> EBarimtReceipt | None:
    """This payment's live receipt — the one a refund would have to void."""
    rows = (EBarimtReceipt.query.filter_by(payment_id=payment.id)
            .order_by(EBarimtReceipt.id.desc()).all())
    return next((r for r in rows if r.status != "returned"), rows[0] if rows else None)


def _booking_for_token(token) -> SeatBooking:
    booking = SeatBooking.query.filter_by(payment_token=str(token).strip()).first()
    if booking is None:
        raise ServiceError(404, "payment_token_not_found")
    if booking.invoice_id is None:
        raise ServiceError(409, "booking_not_paid", booking_id=booking.id)
    return booking


def _payment_for_invoice(invoice_id, *, ref) -> Payment:
    payment = (Payment.query.filter_by(invoice_id=invoice_id)
               .order_by(Payment.id.desc()).first())
    if payment is None:
        raise ServiceError(404, "payment_not_found", reference=str(ref))
    return payment


def _as_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ServiceError(400, "invalid_number", value=str(value)) from exc
