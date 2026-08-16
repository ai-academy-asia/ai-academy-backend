"""Public enrolment funnel: programme list → lead → seat hold → payment → receipt.

Drives the unauthenticated flow the marketing site uses (see the web repo's
``docs/enrolment-api.md``). Two rules shape everything here:

- **No session, so the token is the authority.** Every step after booking is
  addressed by ``payment_token`` — an opaque random handle. Whoever holds it may
  read that checkout's invoice, status and receipt, and nothing else.
- **The server owns the amount.** Clients may send a figure; it is ignored. The
  charge is derived from the cohort/course price and the promotion actually
  found in the database, so a tampered payload cannot change what is charged.

Field names follow the front-end contract rather than our internal vocabulary,
so the routes stay one-liners: their *classroom course* is our ``Course``, their
*schedule* is our ``Cohort``.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    ClassroomRequest,
    Cohort,
    CohortLegacySchedule,
    Course,
    EBarimtReceipt,
    Payment,
    Promotion,
    SeatBooking,
    new_payment_token,
)
from app.models.enrolment import DEFAULT_HOLD_MINUTES
from app.timeutil import iso

from . import ebarimt as ebarimt_svc
from . import payments as pay_svc
from .errors import ServiceError

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
            Cohort.status.in_(("open", "published")),
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
        Course.query.filter_by(status="published")
        .order_by(Course.sort_order.is_(None), Course.sort_order, Course.id)
        .all()
    )
    out = []
    for course in courses:
        card = _programme(course, next_bookable_cohort(course.id), locale)
        card.pop("_seats", None)
        out.append(card)
    return out


# ------------------------------------------ classroom courses (programme page)
# The nav groups programmes by audience using these exact words.
_SEGMENT_BY_LEVEL = {"junior": "Kids", "adult": "Individual", "corporate": "Company"}


def _classroom_course(course: Course) -> dict:
    """A course in the front-end's ``ClassroomCourse`` shape."""
    delivery = _DELIVERY_BY_FORMAT.get((course.format or "").lower())
    fee = Decimal(str(course.price_amount or 0))
    discount = int(course.discount_percent or 0)
    return {
        "_id": public_course_id(course),
        "name": course.title_mn or course.title_en or "",
        "about": course.tagline_mn or course.tagline_en,
        "description": course.description_mn or course.description_en,
        "type": _SEGMENT_BY_LEVEL.get((course.level or "").lower()),
        "locale_uuid": course.slug,
        # FileRef is {_id, name}; we serve images by URL, so there is no file id
        # to hand back — null keeps the UI on its placeholder rather than
        # inventing an id that ``files.url()`` could not resolve.
        "logo": None,
        "image": None,
        "price": float((fee * (100 - discount) / 100).quantize(Decimal("0.01"))),
        "duration": course.duration_label,
        "format": "Онлайн" if delivery == "online" else "Танхим",
    }


def list_classroom_courses() -> list[dict]:
    rows = (
        Course.query.filter_by(status="published")
        .order_by(Course.sort_order.is_(None), Course.sort_order, Course.id)
        .all()
    )
    return [_classroom_course(c) for c in rows]


def get_classroom_course(course_id) -> dict:
    course = course_for_public_id(course_id)
    if course is None or course.status != "published":
        raise ServiceError(404, "course_not_found")
    return _classroom_course(course)


# ------------------------------------------------------------------- 1. lead
def create_request(body: dict) -> ClassroomRequest:
    course_id = body.get("classroom_course_id")
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    phone = (body.get("phone_num") or "").strip()
    register = (body.get("register_num") or "").strip().upper()

    if not name or not email or not phone:
        raise ServiceError(400, "name_email_phone_required")
    if "@" not in email:
        raise ServiceError(400, "invalid_email")
    if register and not REGISTER_RE.match(register):
        raise ServiceError(400, "invalid_register_num")
    # Unbounded Text on an anonymous endpoint is a free write-amplification
    # primitive against RDS. Nothing legitimate needs more than a paragraph.
    plan = (body.get("student_plan") or "").strip()[:MAX_STUDENT_PLAN] or None
    course = course_for_public_id(course_id) if course_id is not None else None
    if course_id is not None and course is None:
        raise ServiceError(404, "course_not_found")

    request = ClassroomRequest(
        course_id=course.id if course is not None else None,
        name=name, email=email, phone_num=phone,
        phone_num2=(body.get("phone_num2") or "").strip() or None,
        register_num=register or None,
        student_plan=plan,
        status="new",
    )
    db.session.add(request)
    db.session.commit()
    return request


# -------------------------------------------------------------- 2. schedules
def list_schedules(course_id) -> list[dict]:
    """Every run of a course, with its seat map.

    Accepts a legacy course id, which may span several of our courses — the site
    asks for one id and expects every run it could book underneath it.
    """
    courses = courses_for_public_id(course_id)
    if not courses:
        raise ServiceError(404, "course_not_found")
    cohorts = (
        Cohort.query.filter(Cohort.course_id.in_([c.id for c in courses]))
        .order_by(Cohort.start_date).all()
    )
    out = []
    for cohort in cohorts:
        capacity, seats, paid, held = _seat_counts(cohort)
        taken = set(paid) | set(held)
        start = cohort.start_date
        when = (f"{start.isoformat()}T{cohort.start_time or '00:00'}:00"
                if start else None)
        out.append({
            "_id": public_schedule_id(cohort),
            "classroom_course_id": public_course_id(
                cohort.course or db.session.get(Course, cohort.course_id)),
            "schedule_date": when,
            "schedule_days": ", ".join(
                _DAY_LABELS.get(str(d).lower()[:3], str(d))
                for d in (cohort.meeting_days or [])
            ) or None,
            "schedule_time": (f"{cohort.start_time}-{cohort.end_time}"
                              if cohort.start_time and cohort.end_time else None),
            "available_seats": [s for s in seats if s not in taken],
            "number_of_seats": capacity,
            "seats": seats,
            "locked_seats": [{"_id": n, "number_of_seat": n, "is_locked": True}
                             for n in held],
            "paid_seats": [{"_id": n, "number_of_seat": n, "is_paid": True}
                           for n in paid],
            "price": _price_or_none(cohort),
        })
    return out


def _price_or_none(cohort: Cohort):
    """Listing price, or ``null`` when the course isn't priced in MNT yet."""
    try:
        return float(cohort_price(cohort))
    except ServiceError:
        return None


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
    promotion = _valid_promotion(code, body.get("classroom_course_id")) if code else None
    if promotion is None:
        raise ServiceError(404, "promotion_not_found")
    return promotion


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
    invoice = booking.invoice
    if invoice is None or invoice.status not in ("pending", "paid"):
        invoice = pay_svc.create_invoice(
            _provider_for("qpay"),
            amount=booking.amount,
            callback_base=current_app.config.get("PUBLIC_BASE_URL", ""),
            description=_describe(booking),
            customer=_customer(booking),
        )
        booking.invoice_id = invoice.id
        db.session.commit()
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


# Who the receipt is made out to. The tax authority models these as different
# document types, and a company one is worthless without the company's TIN.
# A run has to be on sale before it can take money.
BOOKABLE_COHORT_STATUSES = ("open", "published")

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
    invoice = booking.invoice
    if invoice is None or invoice.status not in ("pending", "paid"):
        invoice = pay_svc.create_invoice(
            _provider_for("storepay"),
            amount=booking.amount,
            callback_base=current_app.config.get("PUBLIC_BASE_URL", ""),
            description=body.get("description") or _describe(booking),
            customer={**_customer(booking), "phone": body.get("phone")},
        )
        booking.invoice_id = invoice.id
        db.session.commit()
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
    if booking.is_expired:
        _, _, paid, held = _seat_counts(booking.cohort)
        if booking.number_of_seat in set(paid) | set(held):
            raise ServiceError(409, "seat_taken_after_hold_expired",
                               booking_id=booking.id)
    booking.status = "paid"
    booking.paid_at = datetime.utcnow()
    if booking.request is not None:
        booking.request.status = "paid"
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
