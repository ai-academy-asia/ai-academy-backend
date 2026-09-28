"""Step 3 and 7: holding a seat at a server-derived price, and coupon checks."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import ClassroomRequest, Cohort, Promotion, SeatBooking, new_payment_token
from app.models.enrolment import DEFAULT_HOLD_MINUTES

from ..errors import ServiceError
from ._common import (
    BOOKABLE_COHORT_STATUSES,
    _seat_counts,
    charge_fraction,
    cohort_for_public_id,
    cohort_price,
    courses_for_public_id,
)


# ----------------------------------------------------------------- 3. booking
def book_seat(course_id, body: dict) -> SeatBooking:
    """Hold a seat and mint the payment token the rest of the flow uses."""
    request_id = body.get("classroom_request_id")
    cohort_id = body.get("classroom_course_schedule_id")

    request = db.session.get(ClassroomRequest, request_id) if request_id else None
    if request is None:
        raise ServiceError(404, "classroom_request_not_found")
    # The schedule id is the authority — it is unique, and it alone decides which run
    # is booked. The course id in the path is checked for consistency only.
    cohort = cohort_for_public_id(cohort_id) if cohort_id else None
    allowed = {c.id for c in courses_for_public_id(course_id)}
    if cohort is None or (allowed and cohort.course_id not in allowed):
        raise ServiceError(404, "schedule_not_found")
    # Only runs that are actually on sale. Seeding leaves cohorts as "draft"
    # unless --publish is passed, and a draft or finished run must not take
    # money even if someone still holds its schedule id.
    if cohort.status not in BOOKABLE_COHORT_STATUSES:
        raise ServiceError(409, "schedule_not_bookable")

    _retire_lapsed_holds(cohort)
    booking = _build_booking(request, cohort, body)
    seat = booking.number_of_seat
    request.status = "booked"
    db.session.add(booking)
    try:
        db.session.commit()
    except IntegrityError:
        # Another buyer took this seat between our read and our insert. The
        # partial unique index is what makes that a rejection instead of a
        # double sale; retry once against a freshly-read seat map.
        db.session.rollback()
        return _rebook_next_free(request, cohort, body, seat)
    return booking


def _retire_lapsed_holds(cohort: Cohort) -> int:
    """Retire this run's lapsed holds before anyone counts its seats.

    ``_seat_counts`` treats an expired hold as free, but the partial unique
    index does not — it keys on ``status in ('held','paid')``, so a lapsed row
    still owns its seat number in the database. Left standing, every booking is
    handed a seat the index then refuses, and the buyer is told the run is full
    when it is empty. ``release_expired_holds`` fixes the same drift, but it
    only runs on the hourly tick — the checkout cannot wait for it.
    """
    freed = SeatBooking.query.filter(
        SeatBooking.cohort_id == cohort.id,
        SeatBooking.status == "held",
        SeatBooking.expires_at.isnot(None),
        SeatBooking.expires_at < datetime.utcnow(),
    ).update({"status": "released"}, synchronize_session=False)
    if freed:
        db.session.commit()
    return freed


def _build_booking(
    request: ClassroomRequest, cohort: Cohort, body: dict, taken: set | None = None
) -> SeatBooking:
    """A held seat priced by the server. Raises 409 when the run is full."""
    _, seats, paid, held = _seat_counts(cohort)
    occupied = set(paid) | set(held) | (taken or set())
    free = [s for s in seats if s not in occupied]
    if not free:
        raise ServiceError(409, "no_seats_left")

    # The contract allows handing out the next free seat if the requested one
    # went in the meantime — the front-end doesn't check which it got.
    wanted = body.get("number_of_seat")
    seat = wanted if wanted in free else free[0]

    amount = cohort_price(cohort)
    code = (body.get("promotion_code") or "").strip() or None
    promotion = _valid_promotion(code, cohort.course_id) if code else None
    # An unverifiable code changes nothing: the client's figure is advisory.
    promo_amount = _discount_for(promotion, amount) if promotion else Decimal("0")
    amount = max(Decimal("0"), amount - promo_amount)

    # The schedule id also carries the payment terms — a deposit id bills a
    # share of the price. Applied after the promotion, matching what the site
    # shows the buyer (discount first, then the deposit share of what is left).
    fraction = charge_fraction(body.get("classroom_course_schedule_id"))
    amount = (amount * fraction).quantize(Decimal("0.01"))

    return SeatBooking(
        classroom_request_id=request.id, cohort_id=cohort.id, number_of_seat=seat,
        payment_token=new_payment_token(), status="held",
        promotion_code=code if promotion else None,
        promotion_name=promotion.name if promotion is not None else None,
        promotion_amount=promo_amount or None,
        amount=amount, currency="MNT",
        expires_at=SeatBooking.default_expiry(
            int(current_app.config.get("SEAT_HOLD_MINUTES", DEFAULT_HOLD_MINUTES))
        ),
    )


def _rebook_next_free(
    request: ClassroomRequest, cohort: Cohort, body: dict, collided: int | None = None
) -> SeatBooking:
    """One retry after a seat race. A second collision means the run really is
    full — better a clear 409 than an unbounded loop under contention.

    The seat that just collided is excluded by hand: the winning transaction may
    not be visible to our fresh read yet, and re-picking the same number would
    make the retry fail exactly as the first attempt did.
    """
    booking = _build_booking(
        request, cohort, {**body, "number_of_seat": None},
        taken={collided} if collided else None,
    )
    # The rollback undid this too, and the row is about to have a booking again.
    request.status = "booked"
    db.session.add(booking)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ServiceError(409, "no_seats_left") from None
    return booking


# --------------------------------------------------------------- 7. promotion
def _valid_promotion(code: str, course_id=None) -> Promotion | None:
    promotion = Promotion.query.filter_by(code=code).first()
    if promotion is None or not promotion.is_valid_now(course_id):
        return None
    return promotion


def _discount_for(promotion: Promotion, amount: Decimal) -> Decimal:
    value = Decimal(str(promotion.discount_value))
    if promotion.discount_type == "percent":
        return (amount * value / 100).quantize(Decimal("0.01"))
    return min(amount, value)


def apply_coupon(request_id, body: dict) -> Promotion:
    """404 on an unknown or expired code — the UI shows 'код олдсонгүй'."""
    if db.session.get(ClassroomRequest, request_id) is None:
        raise ServiceError(404, "classroom_request_not_found")
    code = (body.get("promotion_code") or "").strip()
    promotion = Promotion.query.filter_by(code=code).first() if code else None
    # The site sends its public (often legacy) course id; a promotion is scoped to
    # ours. One public id can stand for several of our courses, so any will do.
    public_id = body.get("classroom_course_id")
    course_ids = ([c.id for c in courses_for_public_id(public_id)]
                  if public_id not in (None, "") else [])
    if promotion is None or not any(promotion.is_valid_now(cid) for cid in course_ids or [None]):
        raise ServiceError(404, "promotion_not_found")
    return promotion
