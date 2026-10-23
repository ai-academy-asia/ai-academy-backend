"""Laying a cohort's schedule out as class sessions, and re-laying it after a change.

One session per meeting day between the cohort's dates, at its start/end time.
A date that already has a session never gets a second one. With ``regenerate``
the cohort's future sessions are brought in line with the schedule: moved to the
new time, or removed on a day it no longer meets — except a session that has
already happened, has attendance, or has a handover request, which is history
and stays as it is. ``assign_lessons`` then hands the course's lessons, in order,
to the sessions that have none yet.
"""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Attendance, ClassSession, ScheduleChangeRequest
from app.services.access import cohort_for_teacher
from app.services.errors import ServiceError

from . import clock
from .sessions import session_dict

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _meeting_dates(cohort) -> list:
    days = cohort.meeting_days if isinstance(cohort.meeting_days, list) else []
    weekdays = {WEEKDAYS.index(d) for d in days if d in WEEKDAYS}
    if not (cohort.start_date and cohort.end_date and weekdays and cohort.start_time):
        raise ServiceError(400, "cohort_schedule_incomplete")
    dates, day = [], cohort.start_date
    while day <= cohort.end_date:
        if day.weekday() in weekdays:
            dates.append(day)
        day += timedelta(days=1)
    return dates


def _protected_ids(sessions) -> set:
    """Sessions that are history: today or earlier, marked, or with a handover."""
    ids = [s.id for s in sessions]
    if not ids:
        return set()
    today = clock.local_today()
    marked = {row[0] for row in db.session.query(Attendance.class_session_id)
              .filter(Attendance.class_session_id.in_(ids)).distinct()}
    handed = {row[0] for row in db.session.query(ScheduleChangeRequest.class_session_id)
              .filter(ScheduleChangeRequest.class_session_id.in_(ids)).distinct()}
    return {s.id for s in sessions if s.session_date <= today} | marked | handed


def _assign_lessons(cohort, sessions) -> int:
    from app.services.learning import path  # learning imports access, as we do

    taken = {s.lesson_id for s in sessions if s.lesson_id}
    queue = [lesson for _, lessons in path.ordered_content(cohort.course_id)
             for lesson in lessons if lesson.id not in taken]
    assigned = 0
    for session in sorted(sessions, key=lambda s: (s.session_date, s.start_time or "")):
        if session.lesson_id or not queue:
            continue
        lesson = queue.pop(0)
        session.lesson_id, session.topic_id = lesson.id, lesson.topic_id
        assigned += 1
    return assigned


def generate_sessions(account, cohort_id, *, regenerate=False, assign_lessons=False) -> dict:
    cohort = cohort_for_teacher(account, cohort_id)
    dates = _meeting_dates(cohort)
    existing = ClassSession.query.filter_by(cohort_id=cohort.id).all()
    protected = _protected_ids(existing) if regenerate else set()
    by_date = defaultdict(list)
    for session in existing:
        by_date[session.session_date].append(session)

    created, moved, removed, kept = [], [], 0, 0
    for day in dates:
        rows = by_date.pop(day, [])
        if not rows:
            created.append(ClassSession(cohort_id=cohort.id, session_date=day,
                                        start_time=cohort.start_time, end_time=cohort.end_time))
            continue
        kept += 1
        if not regenerate or any(r.start_time == cohort.start_time for r in rows):
            continue
        movable = [r for r in rows if r.id not in protected]
        if movable:
            movable[0].start_time, movable[0].end_time = cohort.start_time, cohort.end_time
            moved.append(movable[0])
            kept -= 1
    if regenerate:  # days the cohort no longer meets
        for rows in by_date.values():
            for session in rows:
                if session.id not in protected:
                    db.session.delete(session)
                    removed += 1
    db.session.add_all(created)
    db.session.flush()
    assigned = 0
    if assign_lessons:
        live = ClassSession.query.filter_by(cohort_id=cohort.id).all()
        assigned = _assign_lessons(cohort, live)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ServiceError(409, "session_exists") from None
    return {"created": len(created), "moved": len(moved), "removed": removed,
            "skipped": kept, "lessons_assigned": assigned,
            "sessions": [session_dict(s) for s in created + moved]}
