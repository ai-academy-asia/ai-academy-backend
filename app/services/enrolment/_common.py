"""Shared pieces of the enrolment funnel: vocabulary, public-id resolution, seat
maps and the server-side price."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from app.extensions import db
from app.models import Cohort, CohortLegacySchedule, Course, SeatBooking

from ..errors import ServiceError

# Mongolian national register number: two Cyrillic letters + eight digits.
# Validated in the browser too; re-checked here because it is what the receipt
# is issued against and the endpoint is unauthenticated.
MAX_STUDENT_PLAN = 2000
REGISTER_RE = re.compile(r"^[А-ЯӨҮЁ]{2}\d{8}$")

# Codes the UI branches on. Display text lives in the *_label fields alongside.
_SESSION_BY_HOUR = ((12, "morning"), (17, "afternoon"))
_DAY_LABELS = {"mon": "Да", "tue": "Мя", "wed": "Лх", "thu": "Пү",
               "fri": "Ба", "sat": "Бя", "sun": "Ня"}
_AUDIENCE_BY_LEVEL = {"junior": "junior", "adult": "adult", "corporate": "corporate"}
_DELIVERY_BY_FORMAT = {"online": "online", "in_person": "inclass", "hybrid": "inclass"}

# A run has to be on sale before it can take money.
BOOKABLE_COHORT_STATUSES = ("open",)


# ------------------------------------------------------------- id resolution
# The marketing site's cards carry the previous system's ids and send them at
# checkout, so every public id is "the legacy one when we have it, ours
# otherwise" — one rule, applied on the way out and on the way in. Without it
# the site posts backendCourseId=51 and gets course_not_found.


def public_course_id(course: Course) -> int:
    return course.legacy_course_id or course.id


def public_schedule_id(cohort: Cohort) -> int:
    return cohort.legacy_schedule_id or cohort.id


def courses_for_public_id(course_id) -> list[Course]:
    """Every course a public id refers to.

    A list, not one row: legacy course 49 covered three programmes we model
    separately, and the site asks for all their runs in one call.
    """
    try:
        course_id = int(course_id)
    except (TypeError, ValueError):
        return []
    rows = {c.id: c for c in Course.query.filter_by(legacy_course_id=course_id)}
    # Also reach courses only their runs point at.
    for cohort in Cohort.query.filter_by(legacy_course_id=course_id):
        course = cohort.course or db.session.get(Course, cohort.course_id)
        if course is not None:
            rows.setdefault(course.id, course)
    if rows:
        return list(rows.values())
    own = db.session.get(Course, course_id)
    return [own] if own is not None else []


def course_for_public_id(course_id) -> Course | None:
    """One course for a public id — the lowest-numbered when a legacy id spans
    several, so the same input always resolves the same way."""
    rows = courses_for_public_id(course_id)
    return min(rows, key=lambda c: c.id) if rows else None


def legacy_schedule(schedule_id) -> CohortLegacySchedule | None:
    """The payment-terms row a legacy schedule id stands for, if any.

    The old system had no "pay a deposit" flag: it published a second schedule
    row at a reduced price. The site still posts whichever id the buyer picked,
    so this is the only place that knows a given id means "50% of the price".
    """
    try:
        schedule_id = int(schedule_id)
    except (TypeError, ValueError):
        return None
    return db.session.get(CohortLegacySchedule, schedule_id)


def charge_fraction(schedule_id) -> Decimal:
    """What share of the price the chosen id bills. 1 for a plain full-price id."""
    row = legacy_schedule(schedule_id)
    if row is None:
        return Decimal("1")
    percent = Decimal(str(row.charge_percent or 100))
    return max(Decimal("0"), min(percent, Decimal("100"))) / 100


def cohort_for_public_id(schedule_id) -> Cohort | None:
    try:
        schedule_id = int(schedule_id)
    except (TypeError, ValueError):
        return None
    row = db.session.get(CohortLegacySchedule, schedule_id)
    if row is not None:
        return row.cohort or db.session.get(Cohort, row.cohort_id)
    return (
        Cohort.query.filter_by(legacy_schedule_id=schedule_id).first()
        or db.session.get(Cohort, schedule_id)
    )


def _seat_counts(cohort: Cohort) -> tuple[int, list[int], list[int], list[int]]:
    """(capacity, all seats, paid seat numbers, held seat numbers)."""
    capacity = int(cohort.capacity or 0)
    rows = SeatBooking.query.filter(
        SeatBooking.cohort_id == cohort.id,
        SeatBooking.status.in_(("held", "paid")),
    ).all()
    now = datetime.utcnow()
    paid, held = [], []
    for b in rows:
        if b.status == "paid":
            paid.append(b.number_of_seat)
        elif b.expires_at is None or b.expires_at > now:  # expired holds are free again
            held.append(b.number_of_seat)
    return capacity, list(range(1, capacity + 1)), sorted(paid), sorted(held)


def cohort_price(cohort: Cohort) -> Decimal:
    """What this run costs in MNT — the course price after its standing discount.

    Refuses a course priced in anything else. Some of the catalogue is quoted in
    USD with no MNT equivalent; charging that figure would take $1,600 as
    ₮1,600. Better a clear 409 than a sale at a thousandth of the price.
    """
    course = cohort.course if cohort.course is not None else db.session.get(
        Course, cohort.course_id
    )
    currency = (course.currency if course else None) or "MNT"
    if currency != "MNT":
        raise ServiceError(409, "price_not_in_mnt", currency=currency)
    fee = Decimal(str((course.price_amount if course else 0) or 0))
    discount = int((course.discount_percent if course else 0) or 0)
    return (fee * (100 - discount) / 100).quantize(Decimal("0.01"))
