"""Issuing receipts for payments, and replaying temp receipts once PosAPI is live."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from flask import current_app

from app.ebarimt import EBarimtError, PosAPIClient
from app.extensions import db
from app.models import EBarimtReceipt, Payment
from app.timeutil import from_local
from app.utils import dig

from ..errors import ServiceError
from ._common import _as_service_error, _cfg, _posapi, is_temp_mode
from .delivery import _email_receipt_quietly
from .payload import build_payload, compute_taxes


# ----------------------------------------------------------------- issuance
def issue_for_payment(payment: Payment, *, type_="B2C_RECEIPT", customer_register=None,
                      description=None) -> EBarimtReceipt:
    """Create (temp) or issue (live) an eBarimt receipt for a payment.

    Raises ServiceError on a live-mode PosAPI failure; in temp mode it always
    succeeds. Idempotent: returns the existing receipt if one already exists.
    """
    # Newest first: after a partial refund a payment carries the returned
    # original *and* the replacement, and the live one is the current truth.
    existing = (EBarimtReceipt.query.filter_by(payment_id=payment.id)
                .order_by(EBarimtReceipt.id.desc()).first())
    if existing is not None:
        return existing
    if type_ not in ("B2C_RECEIPT", "B2B_RECEIPT"):
        raise ServiceError(400, "invalid_receipt_type")
    if type_ == "B2B_RECEIPT" and not customer_register:
        raise ServiceError(400, "customer_register_required")

    total = Decimal(str(payment.amount))
    vat, city_tax = compute_taxes(total)
    description = description or (payment.invoice.description if payment.invoice else None) \
        or f"AIAA payment {payment.id}"

    receipt = EBarimtReceipt(
        payment_id=payment.id,
        invoice_id=payment.invoice_id,
        type=type_,
        customer_register=customer_register,
        total_amount=total,
        vat_amount=vat,
        city_tax_amount=city_tax,
        district_code=_cfg("EBARIMT_DISTRICT_CODE"),
        pos_no=_cfg("EBARIMT_POS_NO"),
        is_temp_mode=True,
        status="temp",
    )
    payload = build_payload(receipt, description=description, payment=payment)
    receipt.raw = payload

    if not is_temp_mode():
        _send_to_posapi(receipt, payload)

    _persist_or_void(receipt)
    # After commit: the receipt is durable before we attempt delivery, so a
    # slow or failing SMTP hop can't take the issued receipt down with it.
    if not receipt.is_temp_mode:
        _email_receipt_quietly(receipt)
    return receipt


def _persist_or_void(receipt: EBarimtReceipt) -> None:
    """Store the receipt row, and hand the DDTD back if that fails.

    The receipt is minted at the tax authority *before* its row is committed —
    it has to be, since the DDTD is what we store. So a failed insert leaves the
    tax authority holding a receipt our books have no trace of, which nothing
    later can reconcile: no local row means no DDTD to void by. Undo it while we
    still know the number, and if even that fails, log the DDTD plainly — it is
    then the only way to find the receipt again.
    """
    ddtd = None if receipt.is_temp_mode else receipt.ebarimt_id
    try:
        db.session.add(receipt)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if ddtd:
            try:
                _posapi().return_receipt(ddtd)
            except EBarimtError:
                current_app.logger.exception(
                    "eBarimt receipt %s was issued but neither stored nor voided — "
                    "void it by hand at the PosAPI", ddtd,
                )
        raise


def _send_to_posapi(receipt: EBarimtReceipt, payload: dict, *, client: PosAPIClient = None):
    """Post to the live PosAPI and stamp the DDTD / QR / lottery onto the receipt.

    ``client`` lets a batch reuse one connection instead of reconnecting per row.
    """
    try:
        resp = (client or _posapi()).create_receipt(payload)
    except EBarimtError as exc:
        raise _as_service_error(exc) from exc
    ddtd = resp.get("id") or resp.get("billId") or resp.get("ddtd")
    if not ddtd:
        raise ServiceError(502, "ebarimt_no_ddtd", internal=resp)
    receipt.is_temp_mode = False
    receipt.status = "issued"
    receipt.ebarimt_id = str(ddtd)
    receipt.lottery = resp.get("lottery")
    receipt.qr_data = resp.get("qrData") or resp.get("qr_data")
    # The receipt exists at the moment the tax authority says it does, not the
    # moment our HTTP call returned. Storing our own clock leaves the two
    # disagreeing by however long the round trip took — and every later
    # comparison (a void's date, a reconciliation, "when was this sold?") is
    # then off by that much. Fall back to ours only if the response has none.
    receipt.issued_at = from_local(resp.get("date")) or datetime.utcnow()
    receipt.raw = {"request": payload, "response": resp}


def issue_if_enabled(payment: Payment) -> EBarimtReceipt | None:
    """Best-effort auto-issue on settlement. Never raises — a receipt failure must
    not undo a confirmed payment. Called by the payments settle flow.

    Skipped for public checkouts: we do not yet know whether the buyer wants the
    receipt in their own name or their company's, and a B2B receipt needs the
    company's TIN. Those are issued once the buyer answers, via
    ``enrolment.set_receipt_customer``.
    """
    if not _cfg("EBARIMT_AUTO_ISSUE"):
        return None
    if _is_public_checkout(payment):
        return None
    try:
        return issue_for_payment(payment)
    except Exception as exc:  # noqa: BLE001 — deliberately swallow; settlement wins
        db.session.rollback()
        current_app.logger.warning("eBarimt auto-issue failed for payment %s: %s", payment.id, exc)
        return None


def _is_public_checkout(payment: Payment) -> bool:
    """True when this payment came from the anonymous enrolment funnel."""
    from app.models import SeatBooking  # local import keeps the module import-light

    if not payment.invoice_id:
        return False
    return SeatBooking.query.filter_by(invoice_id=payment.invoice_id).first() is not None


# ------------------------------------------------------------------- reissue
def _replay_payload(receipt: EBarimtReceipt) -> dict:
    """Rebuild a temp receipt's PosAPI body in the *current* payload shape.

    ``receipt.raw`` is the audit record of what we captured at temp time, not a
    replay source: a payload stored months earlier can predate PosAPI's field
    requirements (e.g. the mandatory ``barCodeType``, discovered 2026-08-05) or
    even be the old flat 2.0 ``stocks[]`` body, and would be rejected on reissue.
    Only the human-entered description is carried across.
    """
    return build_payload(receipt, description=_description_of(receipt))


def _description_of(receipt: EBarimtReceipt) -> str:
    """The human-entered line item, read back out of whichever payload shape we
    stored it in (3.0 nested items, legacy 2.0 stocks, or a bare request/response
    envelope written by :func:`_send_to_posapi`)."""
    raw = receipt.raw if isinstance(receipt.raw, dict) else {}
    return (
        dig(raw, "receipts", 0, "items", 0, "name")               # 3.0
        or dig(raw, "request", "receipts", 0, "items", 0, "name")  # issued: {request,response}
        or dig(raw, "stocks", 0, "name")                          # legacy 2.0
        or f"AIAA payment {receipt.payment_id}"
    )


def reissue(receipt: EBarimtReceipt) -> EBarimtReceipt:
    """Replay a temp receipt to the now-live PosAPI (once merchant rights arrive)."""
    if not receipt.is_temp_mode:
        raise ServiceError(409, "already_issued")
    if is_temp_mode():
        raise ServiceError(409, "still_in_temp_mode")
    _send_to_posapi(receipt, _replay_payload(receipt))
    db.session.commit()
    return receipt


def reissue_all_temp(limit: int = 200) -> dict:
    """Bulk-replay every temp receipt to the live PosAPI. Returns a summary."""
    if is_temp_mode():
        raise ServiceError(409, "still_in_temp_mode")
    rows = EBarimtReceipt.query.filter_by(is_temp_mode=True, status="temp").limit(limit).all()
    issued, failed = 0, []
    client = _posapi()  # one keep-alive session for the whole batch, not one per row
    for r in rows:
        try:
            _send_to_posapi(r, _replay_payload(r), client=client)
            db.session.commit()
            issued += 1
        except ServiceError as exc:
            db.session.rollback()
            failed.append({"receipt_id": r.id, "error": exc.code})
    return {"candidates": len(rows), "issued": issued, "failed": failed}
