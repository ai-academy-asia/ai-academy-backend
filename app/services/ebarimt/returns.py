"""Voiding receipts and re-receipting what a partial refund kept."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.ebarimt import EBarimtError
from app.extensions import db
from app.models import EBarimtReceipt, Payment
from app.timeutil import local
from app.utils import dig

from ..errors import ServiceError
from ._common import _as_service_error, _cfg, _posapi, is_temp_mode
from .delivery import _email_receipt_quietly
from .issuance import _description_of, _persist_or_void, _send_to_posapi
from .payload import build_payload, compute_taxes


# ------------------------------------------------------------------- returns
def issued_at_for_posapi(receipt: EBarimtReceipt) -> str | None:
    """When the receipt was created, in the clock the PosAPI keeps.

    A void names the receipt it undoes by id *and* by the moment that receipt
    was written. Getting that moment wrong is not a formatting detail: the
    return is filed against a sale the tax authority timestamps differently, and
    ours are stored in UTC — handing `issued_at` over as-is would date every
    void eight hours before the receipt it cancels.

    So the figure PosAPI itself reported is preferred, verbatim: it is already
    the right clock and the right format. Only when that is missing (an older
    row, a re-issued one) is the stored UTC converted to Mongolian time.
    """
    raw = receipt.raw if isinstance(receipt.raw, dict) else {}
    stamped = dig(raw, "response", "date")
    if isinstance(stamped, str) and stamped.strip():
        return stamped.strip()
    when = local(receipt.issued_at or receipt.created_at)
    return when.strftime("%Y-%m-%d %H:%M:%S") if when else None


def return_receipt(receipt: EBarimtReceipt) -> EBarimtReceipt:
    """Void a receipt (e.g. on refund). Temp receipts are voided locally."""
    if receipt.status == "returned":
        raise ServiceError(409, "already_returned")
    if not receipt.is_temp_mode and receipt.ebarimt_id:
        try:
            _posapi().return_receipt(
                receipt.ebarimt_id, date=issued_at_for_posapi(receipt)
            )
        except EBarimtError as exc:
            raise _as_service_error(exc) from exc
    receipt.status = "returned"
    receipt.returned_at = datetime.utcnow()
    db.session.commit()
    return receipt


def issue_replacement(original: EBarimtReceipt, amount, *, description=None) -> EBarimtReceipt:
    """Receipt the part of a sale that survived a partial refund.

    eBarimt has no partial void — a receipt is returned whole — so a buyer who
    got half their money back is left holding a receipt for a sale that no longer
    exists, and the kept half has none. The fix the tax authority expects is a
    second receipt for what was actually kept, which is what this issues, linked
    to the voided one through ``replaces_receipt_id``.

    Idempotent per ``(payment, amount)``: an existing live replacement for the
    same figure is returned untouched, so a retried refund does not mint a second
    receipt for money that was only kept once.
    """
    total = Decimal(str(amount))
    if total <= 0:
        raise ServiceError(400, "replacement_amount_required")
    if original.payment_id is None:
        raise ServiceError(409, "receipt_has_no_payment", receipt_id=original.id)

    existing = next(
        (r for r in EBarimtReceipt.query.filter_by(payment_id=original.payment_id).all()
         if r.status != "returned" and Decimal(str(r.total_amount)) == total),
        None,
    )
    if existing is not None:
        return existing

    payment = original.payment or db.session.get(Payment, original.payment_id)
    vat, city_tax = compute_taxes(total)
    receipt = EBarimtReceipt(
        payment_id=original.payment_id,
        invoice_id=original.invoice_id,
        replaces_receipt_id=original.id,
        type=original.type,
        customer_register=original.customer_register,
        total_amount=total,
        vat_amount=vat,
        city_tax_amount=city_tax,
        district_code=_cfg("EBARIMT_DISTRICT_CODE"),
        pos_no=_cfg("EBARIMT_POS_NO"),
        is_temp_mode=True,
        status="temp",
    )
    payload = build_payload(
        receipt, description=description or _description_of(original), payment=payment
    )
    receipt.raw = payload

    if not is_temp_mode():
        _send_to_posapi(receipt, payload)

    _persist_or_void(receipt)
    if not receipt.is_temp_mode:
        _email_receipt_quietly(receipt)
    return receipt
