"""Cohort domain logic: CRUD + time-precise double-booking detection."""
import re
from datetime import date

from app.extensions import db
from app.models import (
    COHORT_STATUSES,
    Classroom,
    Cohort,
    Course,
    Enrollment,
    Teacher,
)

from .errors import ServiceError

_WRITABLE = {"course_id", "parent_cohort_id", "name", "teacher_id", "classroom_id",
             "capacity", "status", "meeting_days", "start_time", "end_time", "schedule_note"}
_DATE_FIELDS = {"start_date", "end_date", "graduation_date"}

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def get_or_404(cohort_id) -> Cohort:
    cohort = db.session.get(Cohort, cohort_id)
    if cohort is None:
        raise ServiceError(404, "not_found")
    return cohort


def _apply(cohort, data):
    for key in _WRITABLE:
        if key in data:
            setattr(cohort, key, data[key])
    for key in _DATE_FIELDS:
        if key in data:
            value = data[key]
            if value in (None, ""):
                setattr(cohort, key, None)
                continue
            try:
                setattr(cohort, key, date.fromisoformat(value))
            except (ValueError, TypeError):
                raise ServiceError(400, "invalid_date", field=key) from None


def _validate(cohort):
    if not cohort.name:
        raise ServiceError(400, "name_required")
    if not cohort.course_id or db.session.get(Course, cohort.course_id) is None:
        raise ServiceError(400, "invalid_course_id")
    if cohort.status not in COHORT_STATUSES:
        raise ServiceError(400, "invalid_status")
    if cohort.teacher_id and db.session.get(Teacher, cohort.teacher_id) is None:
        raise ServiceError(400, "invalid_teacher_id")
    if cohort.classroom_id and db.session.get(Classroom, cohort.classroom_id) is None:
        raise ServiceError(400, "invalid_classroom_id")
    if cohort.start_date and cohort.end_date and cohort.end_date < cohort.start_date:
        raise ServiceError(400, "end_before_start")
    if cohort.meeting_days is not None and (
        not isinstance(cohort.meeting_days, list)
        or any(d not in WEEKDAYS for d in cohort.meeting_days)
    ):
        raise ServiceError(400, "invalid_meeting_days", valid=list(WEEKDAYS))
    for field in ("start_time", "end_time"):
        val = getattr(cohort, field)
        if val and not _TIME_RE.match(val):
            raise ServiceError(400, "invalid_time", field=field)
    if cohort.start_time and cohort.end_time and cohort.end_time <= cohort.start_time:
        raise ServiceError(400, "end_time_before_start")


def _days_overlap(a_days, b_days):
    if not a_days or not b_days:  # unknown days -> assume clash (fail safe)
        return True
    return bool(set(a_days) & set(b_days))


def _time_overlap(a_start, a_end, b_start, b_end):
    if not (a_start and a_end and b_start and b_end):  # unknown -> assume overlap
        return True
    return a_start < b_end and a_end > b_start


def _find_conflict(column, value, cohort):
    """A cohort sharing this teacher/classroom whose date range, weekday, AND
    time all overlap. Requires this cohort to have a date range."""
    if not (cohort.start_date and cohort.end_date):
        return None
    q = Cohort.query.filter(
        column == value,
        Cohort.start_date.isnot(None), Cohort.end_date.isnot(None),
        Cohort.start_date <= cohort.end_date,
        Cohort.end_date >= cohort.start_date,
    )
    if cohort.id:
        q = q.filter(Cohort.id != cohort.id)
    for other in q.all():
        if _days_overlap(cohort.meeting_days, other.meeting_days) and _time_overlap(
            cohort.start_time, cohort.end_time, other.start_time, other.end_time
        ):
            return other
    return None


def _conflict_payload(clash):
    return {
        "cohort_id": clash.id, "name": clash.name,
        "start_date": clash.start_date.isoformat() if clash.start_date else None,
        "end_date": clash.end_date.isoformat() if clash.end_date else None,
        "meeting_days": clash.meeting_days,
        "start_time": clash.start_time, "end_time": clash.end_time,
    }


def _check_conflicts(cohort):
    if cohort.teacher_id:
        clash = _find_conflict(Cohort.teacher_id, cohort.teacher_id, cohort)
        if clash is not None:
            raise ServiceError(409, "teacher_double_booked", conflict=_conflict_payload(clash))
    if cohort.classroom_id:
        clash = _find_conflict(Cohort.classroom_id, cohort.classroom_id, cohort)
        if clash is not None:
            raise ServiceError(409, "classroom_double_booked", conflict=_conflict_payload(clash))


# ---------------------------------------------------------------- staff CRUD
def list_admin(*, status=None, course_id=None, teacher_id=None, classroom_id=None):
    q = Cohort.query
    if status:
        q = q.filter_by(status=status)
    for val, col in ((course_id, Cohort.course_id), (teacher_id, Cohort.teacher_id),
                     (classroom_id, Cohort.classroom_id)):
        if val and str(val).isdigit():
            q = q.filter(col == int(val))
    return q.order_by(Cohort.start_date.is_(None), Cohort.start_date.asc(), Cohort.id.desc()).all()


def create_cohort(data) -> Cohort:
    cohort = Cohort(status="draft")
    _apply(cohort, data)
    _validate(cohort)
    _check_conflicts(cohort)
    db.session.add(cohort)
    db.session.commit()
    return cohort


def update_cohort(cohort, data) -> Cohort:
    _apply(cohort, data)
    _validate(cohort)
    _check_conflicts(cohort)
    db.session.commit()
    return cohort


def delete_cohort(cohort):
    Enrollment.query.filter_by(cohort_id=cohort.id).delete()
    db.session.delete(cohort)
    db.session.commit()


# ---------------------------------------------------------------- public browse
def list_public(*, course_id=None):
    q = Cohort.query.filter(Cohort.status.in_(("open", "closed")))
    if course_id and str(course_id).isdigit():
        q = q.filter(Cohort.course_id == int(course_id))
    return q.order_by(Cohort.start_date.is_(None), Cohort.start_date.asc()).all()


def get_public(cohort_id, *, can_manage) -> Cohort:
    cohort = get_or_404(cohort_id)
    if not cohort.is_public and not can_manage:
        raise ServiceError(404, "not_found")
    return cohort
