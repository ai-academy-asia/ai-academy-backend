"""Getting receipts to people (email) and to the tax authority (sendData)."""
from __future__ import annotations

from datetime import datetime

from flask import current_app

from app import mail
from app.ebarimt import EBarimtError
from app.extensions import db
from app.models import (
    ACTOR_STUDENT,
    AuthAccount,
    EBarimtReceipt,
    Invoice,
    SeatBooking,
    Student,
)

from ..errors import ServiceError
from ._common import _as_service_error, _cfg, _posapi


# -------------------------------------------------------- receipt delivery
def _recipient_for(receipt: EBarimtReceipt) -> tuple[str | None, str]:
    """(email, display name) of whoever paid, or (None, "").

    Two kinds of buyer reach this point and they carry their address in
    different places:

    - an enrolled **student** — no email column of their own, credentials live
      in ``auth_accounts``, so the profile gives the name and the account the
      address;
    - an anonymous **public checkout** — no account at all, the address is on
      the ``ClassroomRequest`` the buyer filled in.

    Checking only the first is why public bookings failed with
    ``no_recipient_email`` despite having an email on file.
    """
    invoice = receipt.payment.invoice if receipt.payment else None
    if invoice is None and receipt.invoice_id:
        invoice = db.session.get(Invoice, receipt.invoice_id)
    if invoice is None:
        return None, ""

    student_id = invoice.student_id
    if student_id:
        student = db.session.get(Student, student_id)
        name = (" ".join(filter(None, [student.first_name, student.last_name]))
                if student else "")
        account = AuthAccount.query.filter_by(
            actor_type=ACTOR_STUDENT, actor_id=student_id
        ).first()
        if account is not None:
            return account.email, name

    booking = SeatBooking.query.filter_by(invoice_id=invoice.id).first()
    request = booking.request if booking is not None else None
    if request is not None and request.email:
        return request.email, request.name or ""
    return None, ""


def email_receipt(receipt: EBarimtReceipt, *, to: str | None = None) -> dict:
    """Send the issued receipt to the student (or an explicit address).

    Refuses temp receipts: they carry no DDTD, lottery or QR, so the mail would
    show a receipt that does not legally exist yet.
    """
    if receipt.is_temp_mode or not receipt.ebarimt_id:
        raise ServiceError(409, "receipt_not_issued")
    if not mail.is_configured():
        raise ServiceError(503, "mail_not_configured")

    address, name = _recipient_for(receipt)
    address = to or address
    if not address:
        raise ServiceError(422, "no_recipient_email")

    message = mail.build_receipt_email(
        receipt, to=address,
        merchant_name=_cfg("MERCHANT_NAME"),
        merchant_tin=_cfg("EBARIMT_MERCHANT_TIN") or "",
        student_name=name,
        logo_path=_cfg("RECEIPT_LOGO_PATH"),
    )
    try:
        mail.send_message(message)
    except mail.MailError as exc:
        # Record the failure so it is answerable ("did this student get it?")
        # without grepping logs, and so the public receipt endpoint can say so.
        receipt.email_error = str(exc)[:500]
        receipt.emailed_at = None
        db.session.commit()
        raise ServiceError(502, "mail_send_failed", internal=str(exc)) from exc

    receipt.emailed_at = datetime.utcnow()
    receipt.emailed_to = address
    receipt.email_error = None
    db.session.commit()
    return {"sent": True, "to": address, "ebarimt_id": receipt.ebarimt_id}


def _email_receipt_quietly(receipt: EBarimtReceipt) -> None:
    """Best-effort delivery. A bounced email must never undo a paid receipt —
    it can always be re-sent from /admin/ebarimt/<id>/email."""
    if not _cfg("EBARIMT_EMAIL_RECEIPT") or not mail.is_configured():
        return
    try:
        email_receipt(receipt)
    except Exception as exc:  # noqa: BLE001 — receipt already issued; delivery is secondary
        current_app.logger.warning(
            "eBarimt receipt %s issued but not emailed: %s", receipt.id, exc
        )
        if receipt.email_error is None:      # email_receipt records its own SMTP failures
            try:
                receipt.email_error = str(exc)[:500]
                db.session.commit()
            except Exception:  # noqa: BLE001 — never let bookkeeping break settlement
                db.session.rollback()


# ------------------------------------------------------- tax authority sync
def flush_to_tax_authority() -> dict:
    """Push locally-issued receipts up to the tax authority (PosAPI ``sendData``).

    Issuing a receipt is instant — PosAPI hands out a DDTD from a pre-allocated
    lottery pool without touching the tax servers — so this batch flush is the
    step that actually transmits. It must run on a schedule; see the
    ``ebarimt-sender`` service in docker-compose.yml.

    PosAPI answers 200 with an empty body, so the only meaningful confirmation is
    the ``lastSentDate`` it reports afterwards — we read it back for the caller.
    A failed read-back is not a failed flush and is reported as ``None``.
    """
    client = _posapi()
    try:
        client.send_data()
    except EBarimtError as exc:
        raise _as_service_error(exc) from exc

    try:
        info = client.info()
    except EBarimtError:
        info = {}
    return {
        "sent": True,
        "last_sent_date": info.get("lastSentDate"),
        "left_lotteries": info.get("leftLotteries"),
        "merchants": [m.get("tin") for m in (info.get("merchants") or [])],
    }
