"""Step 0: the programme catalogue — one card per published course."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models import Cohort, CohortLegacySchedule, Course
from app.timeutil import iso

from ._common import (
    _AUDIENCE_BY_LEVEL,
    _DAY_LABELS,
    _DELIVERY_BY_FORMAT,
    _SESSION_BY_HOUR,
    BOOKABLE_COHORT_STATUSES,
    _seat_counts,
    public_course_id,
    public_schedule_id,
)


# --------------------------------------------------------------- 0. catalogue
def _session_code(start_time: str | None) -> str | None:
    if not start_time:
        return None
    try:
        hour = int(start_time.split(":")[0])
    except (ValueError, IndexError):
        return None
    for boundary, code in _SESSION_BY_HOUR:
        if hour < boundary:
            return code
    return "evening"


def _programme(course: Course, cohort: Cohort | None, locale: str) -> dict:
    """One programme card. Codes for branching, ``*_label`` for display.

    ``cohort`` is the run the card books against — the next bookable one. It may
    be ``None``: a published course with no open run still belongs on the page,
    and the contract says a card without a ``schedule_id`` renders as
    not-yet-bookable rather than erroring.
    """
    mn = locale != "en"
    if cohort is not None:
        capacity, seats, paid, held = _seat_counts(cohort)
    else:
        capacity, seats, paid, held = int(course.capacity or 0), [], [], []
    taken = set(paid) | set(held)

    days = list((cohort.meeting_days if cohort is not None else None) or [])
    active_days = [_DAY_LABELS.get(str(d).lower()[:3], str(d)) for d in days]
    day_label = ", ".join(active_days)
    start_time = cohort.start_time if cohort is not None else None
    end_time = cohort.end_time if cohort is not None else None
    time_label = f"{start_time}–{end_time}" if start_time and end_time else None

    fee = Decimal(str(course.price_amount or 0))
    discount = int(course.discount_percent or 0)
    final_fee = (fee * (100 - discount) / 100).quantize(Decimal("1"))

    title = (course.title_mn if mn else (course.title_en or course.title_mn)) or ""
    audience = _AUDIENCE_BY_LEVEL.get((course.level or "").lower())
    delivery = _DELIVERY_BY_FORMAT.get((course.format or "").lower())
    session = _session_code(start_time)

    tags = [
        {"code": code, "label": label}
        for code, label in (
            (audience, course.target_audience or audience),
            (delivery, "Онлайн" if delivery == "online" else "Танхим"),
            (session, {"morning": "Өглөө", "afternoon": "Өдөр",
                       "evening": "Орой"}.get(session)),
        )
        if code and label
    ]

    start_date = cohort.start_date if cohort is not None else course.start_date
    end_date = cohort.end_date if cohort is not None else course.end_date

    return {
        # Card key. Stays OUR id: legacy course ids are not unique per card
        # (legacy 53 covers two programmes), and React needs a stable unique
        # key. Booking uses classroom_course_id / schedule_id below.
        "id": course.id,
        "title": title,
        "audience": audience,
        "delivery": delivery,
        "session": session,
        "class_type_label": {"morning": "Өглөөний анги", "afternoon": "Өдрийн анги",
                             "evening": "Оройн анги"}.get(session),
        "age_label": course.target_audience,
        "format_label": "Онлайн" if delivery == "online" else "Танхим",
        "day_label": day_label or None,
        "time_label": time_label,
        "duration_label": course.duration_label,
        "active_days": active_days,
        "start_date": iso(start_date),
        "end_date": iso(end_date),
        "total_classes": 0,
        "currency": course.currency or "MNT",
        "fee": float(fee),
        "discount_percent": discount,
        "final_fee": float(final_fee),
        "max_students": capacity,
        "enrolled": len(taken),
        "tags": tags,
        "features": list(course.whats_included or []),
        "badge": course.icon,
        # What a booking is made against.
        "classroom_course_id": public_course_id(course),
        "schedule_id": public_schedule_id(cohort) if cohort is not None else None,
        # Pricing variants. A fresh client should send `schedule_id` and state
        # its terms, but the marketing site still holds the legacy ids and posts
        # whichever the buyer picked, so we publish exactly the ones we resolve.
        **_variant_ids(cohort),
        "_seats": seats,  # stripped by the route; used by the schedules endpoint
    }


def _variant_ids(cohort: Cohort | None) -> dict:
    """The legacy schedule ids this run answers to, by payment terms."""
    empty = {
        "promo_code": None,
        "promo_discount_percent": 0,
        "promo_schedule_id": None,
        "deposit_schedule_id": None,
        "promo_deposit_schedule_id": None,
        "advance_payment_percent": 0,
    }
    if cohort is None:
        return empty
    rows = CohortLegacySchedule.query.filter_by(cohort_id=cohort.id).all()
    by_kind = {r.kind: r for r in rows}
    deposit = by_kind.get("deposit") or by_kind.get("promo_deposit")
    return {
        **empty,
        "promo_schedule_id": getattr(by_kind.get("promo"), "legacy_schedule_id", None),
        "deposit_schedule_id": getattr(by_kind.get("deposit"), "legacy_schedule_id", None),
        "promo_deposit_schedule_id": getattr(
            by_kind.get("promo_deposit"), "legacy_schedule_id", None
        ),
        "advance_payment_percent": int(deposit.charge_percent) if deposit else 0,
    }


def next_bookable_cohort(course_id) -> Cohort | None:
    """The run a card should book against: the soonest open one.

    Upcoming runs win over ones that already started, and among those the
    earliest — otherwise a course whose first intake began last month would send
    buyers at a class they cannot join.
    """
    cohorts = (
        Cohort.query.filter(
            Cohort.course_id == course_id,
            Cohort.status.in_(BOOKABLE_COHORT_STATUSES),
        ).all()
    )
    if not cohorts:
        return None
    today = date.today()
    upcoming = [c for c in cohorts if c.start_date and c.start_date >= today]
    pool = upcoming or cohorts
    return min(pool, key=lambda c: (c.start_date is None, c.start_date or today))


def list_programmes(locale: str = "mn") -> list[dict]:
    """One card per published course, booking against that course's next run.

    Course-level rather than run-level on purpose: three intakes of "AI Engineer"
    are one programme on the marketing page, not three cards competing with each
    other. The chosen run is exposed as ``schedule_id``.
    """
    courses = (
        Course.query.filter_by(status="open")
        .order_by(Course.sort_order.is_(None), Course.sort_order, Course.id)
        .all()
    )
    out = []
    for course in courses:
        card = _programme(course, next_bookable_cohort(course.id), locale)
        card.pop("_seats", None)
        out.append(card)
    return out
