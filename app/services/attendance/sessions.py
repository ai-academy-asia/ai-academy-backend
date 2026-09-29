"""Class sessions of a cohort: list, create, edit, delete, generate, roster.

Every function takes the caller's account and resolves the cohort through
:func:`app.services.access.cohort_for_teacher`, so a teacher only ever touches
their own cohorts (others' answer 404) and ``cohort:manage`` staff touch any.
"""
import re
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import ClassSession, Cohort, CourseTopic, Enrollment, Student
from app.services.access import cohort_for_teacher
from app.services.errors import ServiceError
from app.services.params import get_by_id
from app.timeutil import iso

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# ----------------------------------------------------------------- serialisers
def session_dict(session: ClassSession) -> dict:
    return {
        "id": session.id,
        "cohort_id": session.cohort_id,
        "topic_id": session.topic_id,
        "session_date": iso(session.session_date),
        "start_time": session.start_time,
        "end_time": session.end_time,
        "created_at": iso(session.created_at),
    }


def student_name(student) -> str:
    return f"{student.first_name} {student.last_name or ''}".strip()


# ----------------------------------------------------------------- lookups
def session_for_teacher(account, session_id) -> ClassSession:
    """A session of a cohort the caller may teach; anything else is 404."""
    session = get_by_id(ClassSession, session_id)
    if session is None:
        raise ServiceError(404, "session_not_found")
    try:
        cohort_for_teacher(account, session.cohort_id)
    except ServiceError:
        raise ServiceError(404, "session_not_found") from None
    return session


def roster(cohort_id) -> list:
    """Active enrollments of the cohort as (enrollment, student), by name."""
    return (
        db.session.query(Enrollment, Student)
        .join(Student, Enrollment.student_id == Student.id)
        .filter(Enrollment.cohort_id == cohort_id, Enrollment.status == "active")
        .order_by(Student.first_name, Student.last_name, Student.id)
        .all()
    )


def cohort_students(account, cohort_id) -> list:
    cohort = cohort_for_teacher(account, cohort_id)
    return [
        {"student_id": s.id, "enrollment_id": e.id, "name": student_name(s), "phone": s.phone}
        for e, s in roster(cohort.id)
    ]


# ----------------------------------------------------------------- parsing
def _parse_date(value, code):
    if not isinstance(value, str):
        raise ServiceError(400, code)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ServiceError(400, code) from None


def _parse_time(value, code):
    if not isinstance(value, str) or not _TIME_RE.match(value):
        raise ServiceError(400, code)
    return value


def _parse_topic(value, cohort):
    if value is None:
        return None
    topic = get_by_id(CourseTopic, value)
    if topic is None or topic.course_id != cohort.course_id:
        raise ServiceError(400, "invalid_topic_id")
    return topic.id


def _apply(session, data, cohort, *, creating):
    if creating or "session_date" in data:
        if data.get("session_date") in (None, ""):
            raise ServiceError(400, "session_date_required")
        session.session_date = _parse_date(data["session_date"], "invalid_session_date")
    if creating or "start_time" in data:
        if data.get("start_time") in (None, ""):
            raise ServiceError(400, "start_time_required")
        session.start_time = _parse_time(data["start_time"], "invalid_start_time")
    if "end_time" in data:
        end = data["end_time"]
        session.end_time = None if end in (None, "") else _parse_time(end, "invalid_end_time")
    if session.end_time and session.end_time <= session.start_time:
        raise ServiceError(400, "invalid_time_range")
    if "topic_id" in data:
        session.topic_id = _parse_topic(data["topic_id"], cohort)


def _slot_taken(session) -> bool:
    query = ClassSession.query.filter_by(
        cohort_id=session.cohort_id, session_date=session.session_date,
        start_time=session.start_time,
    )
    if session.id is not None:
        query = query.filter(ClassSession.id != session.id)
    return db.session.query(query.exists()).scalar()


def _save(session):
    with db.session.no_autoflush:
        taken = _slot_taken(session)
    if taken:
        db.session.rollback()
        raise ServiceError(409, "session_exists")
    try:
        db.session.commit()
    except IntegrityError:  # a concurrent insert won the slot
        db.session.rollback()
        raise ServiceError(409, "session_exists") from None
    return session


# ----------------------------------------------------------------- CRUD
def list_sessions(account, cohort_id, *, date_from=None, date_to=None) -> list:
    cohort = cohort_for_teacher(account, cohort_id)
    query = ClassSession.query.filter_by(cohort_id=cohort.id)
    if date_from:
        query = query.filter(ClassSession.session_date >= _parse_date(date_from, "invalid_from"))
    if date_to:
        query = query.filter(ClassSession.session_date <= _parse_date(date_to, "invalid_to"))
    rows = query.order_by(ClassSession.session_date, ClassSession.start_time).all()
    return [session_dict(s) for s in rows]


def create_session(account, cohort_id, data) -> ClassSession:
    cohort = cohort_for_teacher(account, cohort_id)
    session = ClassSession(cohort_id=cohort.id)
    with db.session.no_autoflush:
        _apply(session, data, cohort, creating=True)
    db.session.add(session)
    return _save(session)


def update_session(account, session_id, data) -> ClassSession:
    session = session_for_teacher(account, session_id)
    with db.session.no_autoflush:
        try:
            _apply(session, data, session_cohort(session), creating=False)
        except ServiceError:
            db.session.rollback()
            raise
    return _save(session)


def delete_session(account, session_id) -> None:
    session = session_for_teacher(account, session_id)
    db.session.delete(session)
    db.session.commit()


def session_cohort(session) -> Cohort:
    return db.session.get(Cohort, session.cohort_id)


# ----------------------------------------------------------------- generate
def generate_sessions(account, cohort_id) -> dict:
    """One session per meeting day between the cohort's dates; existing slots kept."""
    cohort = cohort_for_teacher(account, cohort_id)
    days = cohort.meeting_days if isinstance(cohort.meeting_days, list) else []
    weekdays = {WEEKDAYS.index(d) for d in days if d in WEEKDAYS}
    if not (cohort.start_date and cohort.end_date and weekdays and cohort.start_time):
        raise ServiceError(400, "cohort_schedule_incomplete")
    existing = {
        (s.session_date, s.start_time)
        for s in ClassSession.query.filter_by(cohort_id=cohort.id).all()
    }
    created, skipped = [], 0
    day = cohort.start_date
    while day <= cohort.end_date:
        if day.weekday() in weekdays:
            if (day, cohort.start_time) in existing:
                skipped += 1
            else:
                created.append(ClassSession(
                    cohort_id=cohort.id, session_date=day,
                    start_time=cohort.start_time, end_time=cohort.end_time,
                ))
        day += timedelta(days=1)
    db.session.add_all(created)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ServiceError(409, "session_exists") from None
    return {"created": len(created), "skipped": skipped,
            "sessions": [session_dict(s) for s in created]}

