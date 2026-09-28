"""The и-баримт step of a public checkout: who it is for, and how far it got."""
from __future__ import annotations

import re

from app.models import EBarimtReceipt, Payment, SeatBooking

from .. import ebarimt as ebarimt_svc
from ..errors import ServiceError
from .checkout import _describe, booking_for_token

# Who the receipt is made out to. The tax authority models these as different
# document types, and a company one is worthless without the company's TIN.
CUSTOMER_TYPES = ("individual", "organization")
_RECEIPT_TYPE = {"individual": "B2C_RECEIPT", "organization": "B2B_RECEIPT"}
# What a buyer types is their company's 7-digit **register number**; PosAPI
# files against the 11-14 digit **ТТД** behind it. Accept either — most people
# have the register to hand — and resolve to the TIN before issuing.
ORG_NUMBER_RE = re.compile(r"^(\d{7}|\d{11,14})$")


def _paid_booking(token: str) -> SeatBooking:
    booking = booking_for_token(token)
    if booking.status != "paid" or not booking.invoice_id:
        raise ServiceError(409, "payment_not_settled")
    return booking


def _receipt_for(booking: SeatBooking) -> EBarimtReceipt | None:
    if not booking.invoice_id:
        return None
    return (
        EBarimtReceipt.query.filter_by(invoice_id=booking.invoice_id)
        .order_by(EBarimtReceipt.id.desc()).first()
    )


def set_receipt_customer(token: str, body: dict) -> dict:
    """Record who the и-баримт is for, then issue and email it.

    Public checkouts deliberately do not auto-issue on settlement: only the
    buyer knows whether the receipt should be in their own name or their
    employer's, and a company receipt is filed against the company's TIN. This
    is where that answer arrives.

    Idempotent — asking twice returns the receipt already issued rather than
    filing a second one with the tax authority.
    """
    booking = _paid_booking(token)

    existing = _receipt_for(booking)
    if existing is not None:
        return _receipt_payload(booking, existing)

    kind = (body.get("customer_type") or "").strip().lower()
    if kind not in CUSTOMER_TYPES:
        raise ServiceError(400, "invalid_customer_type", allowed=list(CUSTOMER_TYPES))

    register = (body.get("customer_register") or "").strip()
    if kind == "organization":
        if not ORG_NUMBER_RE.match(register):
            raise ServiceError(400, "invalid_organization_register")
        # Resolve and confirm in one step: a receipt filed against a mistyped
        # number lands on a stranger's tax account and cannot be moved after.
        company = ebarimt_svc.find_taxpayer(register)
        if company is None:
            raise ServiceError(404, "organization_not_found", register=register)
        register = company["tin"]      # PosAPI only accepts the TIN
    else:
        # An individual's receipt carries no register at all — PosAPI rejects a
        # B2C document with a customerTin, and the buyer claims the receipt by
        # scanning its QR in the eBarimt app. The register number we collect on
        # the form stays with the lead, off the receipt.
        register = ""

    payment = Payment.query.filter_by(invoice_id=booking.invoice_id).first()
    if payment is None:
        raise ServiceError(409, "payment_not_settled")

    receipt = ebarimt_svc.issue_for_payment(
        payment,
        type_=_RECEIPT_TYPE[kind],
        customer_register=register or None,
        description=_describe(booking),
    )
    return _receipt_payload(booking, receipt)


def _receipt_payload(booking: SeatBooking, receipt: EBarimtReceipt | None) -> dict:
    email = booking.request.email if booking.request else None
    if receipt is None or receipt.is_temp_mode:
        return {"status": "pending", "email": email, "ebarimt_id": None, "error": None}
    if receipt.emailed_at:
        status, error = "sent", None
    elif receipt.email_error:
        status, error = "failed", receipt.email_error
    else:
        status, error = "pending", None
    return {
        "status": status,
        "email": receipt.emailed_to or email,
        "ebarimt_id": receipt.ebarimt_id,
        "error": error,
    }


def receipt_status(token: str) -> dict:
    """How far the и-баримт got: pending -> sent, or failed with a reason.

    404s while the platform is in eBarimt temp mode. Temp mode means we have no
    merchant rights yet, so settlement files a placeholder row and stops — no
    DDTD is requested and no email is sent. Reporting that as ``pending`` would
    leave the success screen saying "your receipt is being processed" forever,
    for a receipt that is not coming. The contract's answer is to 404 so the UI
    omits the line entirely rather than making a promise we cannot keep.

    Adds ``requires_customer_type``: after a public checkout settles we wait for
    the buyer to say individual-or-company before filing anything, so the UI
    must ask rather than poll.
    """
    booking = booking_for_token(token)
    if ebarimt_svc.is_temp_mode():
        raise ServiceError(404, "receipts_not_issued")

    receipt = _receipt_for(booking)
    payload = _receipt_payload(booking, receipt)
    payload["requires_customer_type"] = (
        receipt is None and booking.status == "paid"
    )
    return payload
