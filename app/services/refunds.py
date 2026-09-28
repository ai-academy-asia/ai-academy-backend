"""Refund orchestration — money, tax receipt and seat, settled in one call.

A refund is three facts that have to agree afterwards: the :class:`Payment` row,
the eBarimt receipt the tax authority holds a copy of, and the seat the buyer no
longer occupies. Doing them through three endpoints means every partial failure
leaves the books disagreeing with the tax record — the worst of which, money back
with a live receipt, is a tax problem rather than a bookkeeping one.

**Reference.** Finance does not hold our internal ids. What they have is the
receipt in the buyer's hand, so any of these identifies the refund:
``payment_id``, ``payment_token`` (public checkout), ``invoice_id``,
``receipt_id``, ``ebarimt_id`` (ДДТД) or ``lottery`` (e.g. ``"HQ 92232007"``).

**Order.** The PosAPI void runs first: it is the only step that leaves our
database, and PosAPI is not idempotent — voiding the same DDTD twice answers
``500 UNIQUE constraint failed``. If the money step then fails, the same call can
simply be retried: an already-returned receipt is skipped, not re-voided, and an
already-refunded payment likewise. Every step reports what it did in ``steps``,
so a retry is readable rather than guesswork.

**Partial refunds.** eBarimt cannot void half a receipt. Returning the whole one
and stopping there would leave the kept half of the sale unreceipted, so a
partial refund voids the original and issues a replacement for what the buyer
kept, linked back through ``replaces_receipt_id``. That is why the refund figure
is computed *before* the void: the receipt work depends on the remainder, and
the PosAPI calls have to bracket the database write.
"""
from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models import (
    Cohort,
    Course,
    EBarimtReceipt,
    Enrollment,
    Invoice,
    Payment,
    SeatBooking,
    StudentLedger,
)

from . import ebarimt as ebarimt_svc
from . import payments as pay_svc
from .errors import ServiceError
from .refund_refs import REFERENCE_KEYS, _as_int, detect_reference, resolve

__all__ = ["REFERENCE_KEYS", "detect_reference", "lookup", "refund", "resolve"]


def lookup(data: dict) -> dict:
    """Everything a person needs to recognise the sale — and nothing changed.

    A refund cannot be undone (the PosAPI void least of all), so the number is
    resolved and shown back first: who bought what, for how much, which receipt
    stands. ``refundable`` is what a full refund would return, so the form can
    offer it without anyone retyping a figure off a screen.
    """
    payment, receipt = resolve(data)
    invoice = payment.invoice or db.session.get(Invoice, payment.invoice_id)
    booking = (SeatBooking.query.filter_by(invoice_id=payment.invoice_id).first()
               if payment.invoice_id else None)
    request = booking.request if booking is not None else None
    cohort = db.session.get(Cohort, booking.cohort_id) if booking is not None else None
    course = db.session.get(Course, cohort.course_id) if cohort is not None else None

    paid = Decimal(str(payment.amount or 0))
    refunded = Decimal(str(payment.refunded_amount or 0))
    return {
        "payment": payment.to_dict(),
        "receipt": receipt.to_dict() if receipt is not None else None,
        "invoice": {
            "id": invoice.id, "description": invoice.description, "status": invoice.status,
        } if invoice is not None else None,
        "buyer": {
            "name": request.name, "email": request.email, "phone": request.phone_num,
        } if request is not None else None,
        "course": {
            "title": course.title_mn if course is not None else None,
            "cohort": cohort.name if cohort is not None else None,
            "seat": booking.number_of_seat if booking is not None else None,
            "booking_status": booking.status if booking is not None else None,
        } if booking is not None else None,
        # What is still left to hand back — the amount already returned is not
        # owed twice. Display only: a refund's ``amount`` is the running total,
        # so a full refund sends ``full_refund_amount``, not this.
        "refundable": float(max(paid - refunded, Decimal(0))),
        "refunded": float(refunded),
        "full_refund_amount": float(paid),
    }


def refund(data: dict) -> dict:
    """Refund one payment: void its receipt, return the money, free the seat.

    ``amount`` (the total returned, earlier partial refunds included — so a
    retried request cannot pay out twice) or ``pct_attended`` (pilot rule: <20%
    attended → half back) decides how much. ``void_receipt`` defaults to true — a refund
    that leaves the tax receipt standing has to be asked for.
    """
    payment, receipt = resolve(data)
    void = _as_bool(data.get("void_receipt", True))
    kept = _kept_after_refund(payment, data)
    issued_ids = _receipt_ids_of(payment)

    steps = {"receipt": _void_step(receipt, void=void, kept=kept)}  # 1. tax first
    steps["payment"] = _money_step(payment, data)                   # 2. money
    replacement, steps["replacement"] = _replacement_step(          # 2b. kept half
        payment, receipt, void=void, kept=kept, voided=steps["receipt"], issued_ids=issued_ids)

    # Nothing left to undo — say so rather than report a successful no-op.
    if steps["payment"] == "already_refunded" and steps["receipt"] in (
        "already_returned", "none", "skipped_not_issued",
    ):
        raise ServiceError(409, "already_refunded", payment_id=payment.id)

    # 3. The seat, and only on a full refund: a part-refunded buyer is still
    #    coming to class.
    booking, enrollment = (None, None)
    if payment.status == "refunded":
        booking, enrollment = _give_back_seat(payment)
        steps["seat"] = "cancelled" if booking is not None else "none"
    else:
        steps["seat"] = "kept"

    return {
        "steps": steps,
        "payment": payment.to_dict(),
        "receipt": receipt.to_dict() if receipt is not None else None,
        "replacement_receipt": replacement.to_dict() if replacement is not None else None,
        "seat_booking": _booking_dict(booking),
        "enrollment": enrollment.to_dict(with_student=False) if enrollment is not None else None,
        "ledger": _ledger_dict(payment),
    }


def _void_step(receipt, *, void: bool, kept: Decimal) -> str:
    """Void the receipt at the PosAPI unless there is nothing (left) to void."""
    if receipt is None:
        return "none"
    if not void:
        return "kept"
    if receipt.status == "returned":
        return "already_returned"
    if receipt.status == "failed":
        # Never accepted by the PosAPI, so there is nothing to void.
        return "skipped_not_issued"
    if kept > 0 and Decimal(str(receipt.total_amount)) == kept:
        # Already the replacement this same refund would issue — a retry, not a
        # second refund. Voiding it would undo the correction.
        return "already_corrected"
    ebarimt_svc.return_receipt(receipt)
    return "returned"


def _money_step(payment: Payment, data: dict) -> str:
    if payment.status == "refunded":
        return "already_refunded"
    pay_svc.refund(
        payment,
        pct_attended=_as_int(data.get("pct_attended")),
        amount=data.get("amount"),
        reason=data.get("reason"),
    )
    return payment.status


def _replacement_step(payment, receipt, *, void, kept, voided, issued_ids):
    """(replacement receipt or None, step label) for what the buyer kept."""
    if receipt is None or not void or voided == "skipped_not_issued":
        return None, "none"
    if kept <= 0 or payment.status != "partially_refunded":
        return None, "not_needed"
    replacement = ebarimt_svc.issue_replacement(receipt, kept)
    return replacement, ("issued" if replacement.id not in issued_ids else "reused")


def _kept_after_refund(payment: Payment, data: dict) -> Decimal:
    """What the buyer is left having paid once this refund lands.

    Read before anything moves, so the receipt step knows whether it is voiding
    a sale or correcting one — and so a bad body (no basis, more than was paid)
    is rejected while the receipt is still standing, instead of after we have
    voided it at the PosAPI. An already-fully-refunded payment keeps nothing, and
    is the one case that carries no basis to validate.
    """
    if payment.status == "refunded":
        return Decimal(0)
    back = pay_svc.compute_refund_amount(
        payment,
        pct_attended=_as_int(data.get("pct_attended")),
        amount=data.get("amount"),
    )
    return Decimal(str(payment.amount or 0)) - back


def _receipt_ids_of(payment: Payment) -> set:
    """Receipt ids this payment had before we touched it — the difference is how
    we can say whether a replacement was issued now or reused from a retry."""
    return {r.id for r in EBarimtReceipt.query.filter_by(payment_id=payment.id).all()}


# ----------------------------------------------------------------------- seat
def _give_back_seat(payment: Payment) -> tuple[SeatBooking | None, Enrollment | None]:
    """Put the seat back on sale and close the enrollment behind it.

    ``cancelled`` rather than ``released``: released is what the sweeper writes
    on a hold nobody paid for, and a refunded sale should not read the same in
    the audit trail. Either way the seat leaves the live-seat unique index, which
    is what makes it sellable again.
    """
    invoice = payment.invoice or db.session.get(Invoice, payment.invoice_id)
    booking = SeatBooking.query.filter_by(invoice_id=payment.invoice_id).first()
    if booking is not None and booking.status in ("held", "paid"):
        booking.status = "cancelled"
        if booking.request is not None:
            booking.request.status = "abandoned"

    enrollment = (db.session.get(Enrollment, invoice.enrollment_id)
                  if invoice is not None and invoice.enrollment_id else None)
    if enrollment is not None and enrollment.status == "active":
        enrollment.status = "cancelled"

    db.session.commit()
    return booking, enrollment


# ----------------------------------------------------------------- formatting
def _booking_dict(booking: SeatBooking | None) -> dict | None:
    if booking is None:
        return None
    return {
        "id": booking.id, "cohort_id": booking.cohort_id,
        "number_of_seat": booking.number_of_seat, "status": booking.status,
    }


def _ledger_dict(payment: Payment) -> dict | None:
    invoice = payment.invoice
    if invoice is None or not invoice.enrollment_id:
        return None
    ledger = StudentLedger.query.filter_by(enrollment_id=invoice.enrollment_id).first()
    return ledger.to_dict() if ledger is not None else None


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")
