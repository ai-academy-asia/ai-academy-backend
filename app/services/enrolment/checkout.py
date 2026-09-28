"""Steps 4–6 and 8: the token-keyed checkout — QPay, StorePay, settlement."""
from __future__ import annotations

from datetime import datetime

from flask import current_app

from app.extensions import db
from app.models import Promotion, SeatBooking

from .. import payments as pay_svc
from ..errors import ServiceError
from ._common import _seat_counts


# ------------------------------------------------------- 4-6. token-keyed flow
def _provider_for(preferred: str) -> str:
    """Which gateway a public checkout should use.

    Sandbox overrides the caller's choice on purpose: the front-end has a QPay
    and a StorePay button, and in demo mode both must settle rather than 501.
    """
    return "sandbox" if _cfg("PAYMENTS_SANDBOX") else preferred


def _cfg(key, default=None):
    return current_app.config.get(key, default)


def booking_for_token(token: str) -> SeatBooking:
    booking = SeatBooking.query.filter_by(payment_token=(token or "").strip()).first()
    if booking is None:
        raise ServiceError(404, "payment_token_not_found")
    return booking


def qpay_invoice(token: str) -> dict:
    """Create (or reuse) the QPay invoice for this checkout.

    Reused rather than recreated on repeat calls: the front-end re-fetches on
    remount, and a fresh invoice per render would leave orphan QRs the buyer
    might still pay against.
    """
    booking = booking_for_token(token)
    invoice = _invoice_for(booking, _provider_for("qpay"),
                           description=_describe(booking), customer=_customer(booking))
    return {
        "invoice_id": invoice.provider_invoice_id or str(invoice.id),
        "qr_image": invoice.qr_image,
        "qr_text": invoice.qr_text,
        "qPay_shortUrl": invoice.payment_url,
        "urls": invoice.urls or [],
        # Visible to whoever is looking at the QR, so a demo can never be
        # mistaken for a real payment request.
        "sandbox": invoice.provider == "sandbox",
    }


def invoice_status(token: str) -> dict:
    """``status_id._id == 2`` means paid; anything else is 'not yet'."""
    booking = booking_for_token(token)
    invoice = booking.invoice
    if invoice is not None and invoice.status != "paid":
        invoice = pay_svc.check_status(invoice)
    paid = invoice is not None and invoice.status == "paid"
    if paid and booking.status != "paid":
        _mark_paid(booking)
    return {"status_id": {"_id": 2 if paid else 1,
                          "name": "Төлөгдсөн" if paid else "Хүлээгдэж буй"}}


# -------------------------------------------------------------- 8. StorePay
def storepay_invoice(body: dict) -> dict:
    """Amount comes from the booking, not the body — the client's is advisory.

    Keyed on ``payment_token`` like every other post-booking step. It used to
    accept ``classroomRequestId`` as a fallback, which is a sequential integer:
    anyone could enumerate it and open a BNPL loan in a stranger's name, using
    the name, phone and register number we hold for them.
    """
    booking = booking_for_token(
        body.get("payment_token") or body.get("pt") or ""
    )
    invoice = _invoice_for(booking, _provider_for("storepay"),
                           description=body.get("description") or _describe(booking),
                           customer={**_customer(booking), "phone": body.get("phone")})
    return {
        # The token, not the invoice id: this value goes into a URL the browser
        # then polls, and a sequential id there is an enumeration handle.
        "requestId": booking.payment_token,
        "invoiceId": invoice.provider_invoice_id or str(invoice.id),
        "qrData": invoice.qr_text,
        "sandbox": invoice.provider == "sandbox",
    }


def storepay_status(token: str) -> dict:
    booking = booking_for_token(token)
    invoice = booking.invoice
    if invoice is None:
        raise ServiceError(404, "payment_token_not_found")
    if invoice.status != "paid":
        invoice = pay_svc.check_status(invoice)
    if invoice.status == "paid" and booking.status != "paid":
        _mark_paid(booking)
    return {
        "isConfirmed": invoice.status == "paid",
        "isCancelled": invoice.status in ("cancelled", "expired", "failed"),
    }


# ------------------------------------------------------------------- helpers
def _invoice_for(booking: SeatBooking, provider: str, *, description, customer):
    """The booking's invoice at ``provider`` — reused, or raised fresh.

    Reused while pending at the same gateway: the front-end re-fetches on
    remount, and a fresh invoice per render would leave orphan QRs the buyer
    might still pay against. A paid invoice is never replaced, whichever
    gateway took the money.

    Switching gateway (QPay QR opened, then StorePay chosen) checks the old
    invoice first — the buyer may have paid it in the meantime — and only then
    retires it. A booking points at one invoice, so a payment that still lands
    on the retired one is flagged by ``payments.settle`` for finance.
    """
    invoice = booking.invoice
    if invoice is not None and invoice.status == "pending" and invoice.provider != provider:
        invoice = pay_svc.check_status(invoice)
        if invoice.status == "pending":
            invoice.status = "cancelled"
            db.session.commit()
    if invoice is not None and (
        invoice.status == "paid" or (invoice.status == "pending" and invoice.provider == provider)
    ):
        return invoice

    invoice = pay_svc.create_invoice(
        provider,
        amount=booking.amount,
        callback_base=current_app.config.get("PUBLIC_BASE_URL", ""),
        description=description,
        customer=customer,
    )
    booking.invoice_id = invoice.id
    db.session.commit()
    return invoice


def _describe(booking: SeatBooking) -> str:
    cohort = booking.cohort
    return cohort.name if cohort is not None else f"AIAA booking {booking.id}"


def _customer(booking: SeatBooking) -> dict:
    request = booking.request
    if request is None:
        return {}
    # No register_num. It is a national ID; gateways have no use for it and it
    # would end up echoed into provider_meta.
    return {"name": request.name, "phone": request.phone_num,
            "email": request.email}


def _mark_paid(booking: SeatBooking) -> None:
    """Turn a hold into a sale.

    Refuses an expired hold whose seat has since been taken: the QR stays valid
    in the buyer's browser long after the hold lapses, and settling it then
    would put two paid bookings on one seat. The money is already in, so this
    needs a human — hence a distinct code finance can search for.
    """
    # "released" is the same lapsed hold after book_seat or the sweeper retired
    # it — by then its seat may well have gone to someone else.
    if booking.is_expired or booking.status == "released":
        _, _, paid, held = _seat_counts(booking.cohort)
        if booking.number_of_seat in set(paid) | set(held):
            raise ServiceError(409, "seat_taken_after_hold_expired",
                               booking_id=booking.id)
    booking.status = "paid"
    booking.paid_at = datetime.utcnow()
    if booking.request is not None:
        booking.request.status = "paid"
    if booking.promotion_code:
        # Counted at sale, not at hold: an abandoned checkout must not burn a use.
        Promotion.query.filter_by(code=booking.promotion_code).update(
            {Promotion.used_count: Promotion.used_count + 1}, synchronize_session=False)
    db.session.commit()


def release_expired_holds() -> int:
    """Free seats whose hold ran out. Without this ``available_seats`` drifts."""
    rows = SeatBooking.query.filter(
        SeatBooking.status == "held",
        SeatBooking.expires_at.isnot(None),
        SeatBooking.expires_at < datetime.utcnow(),
    ).all()
    for booking in rows:
        booking.status = "released"
    if rows:
        db.session.commit()
    return len(rows)
