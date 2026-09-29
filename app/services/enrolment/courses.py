"""Programme page, lead capture and the per-course schedule list (steps 1–2)."""
from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models import ClassroomRequest, Cohort, Course

from ..errors import ServiceError
from ._common import (
    _DAY_LABELS,
    _DELIVERY_BY_FORMAT,
    MAX_STUDENT_PLAN,
    REGISTER_RE,
    _seat_counts,
    cohort_price,
    course_for_public_id,
    courses_for_public_id,
    public_course_id,
    public_schedule_id,
)

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
        Course.query.filter_by(status="open")
        .order_by(Course.sort_order.is_(None), Course.sort_order, Course.id)
        .all()
    )
    return [_classroom_course(c) for c in rows]


def get_classroom_course(course_id) -> dict:
    course = course_for_public_id(course_id)
    if course is None or course.status != "open":
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
