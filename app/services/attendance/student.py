"""A student's own attendance in a course, and the attendance percentage.

A session counts once it has ended (Ulaanbaatar time; see ``clock.local_end``) or
once it has a record — a student who checked in this morning is not left out. An
ended session with no record counts as ``absent``; before it ends its status is
``None``, so the morning of a class never lowers the percentage. ``present`` and
``late`` count as attended; ``excused`` is neither attended nor excluded.
"""
from app.models import Attendance, ClassSession
from app.services.access import course_by_slug, enrollment_for_course
from app.services.errors import ServiceError
from app.timeutil import iso

from . import clock

ATTENDED = ("present", "late")


def _rows(enrollment):
    sessions = (
        ClassSession.query.filter_by(cohort_id=enrollment.cohort_id)
        .order_by(ClassSession.session_date, ClassSession.start_time)
        .all()
    )
    ids = [s.id for s in sessions]
    records = {}
    if ids:
        records = {
            a.class_session_id: a.status
            for a in Attendance.query.filter(
                Attendance.class_session_id.in_(ids),
                Attendance.student_id == enrollment.student_id,
            ).all()
        }
    rows = []
    for s in sessions:
        ended = clock.has_ended(s)
        status = records.get(s.id) or ("absent" if ended else None)
        rows.append((s, status, ended or s.id in records))
    return rows


def _summary(rows) -> dict:
    total = sum(1 for _, _, past in rows if past)
    attended = sum(1 for _, status, past in rows if past and status in ATTENDED)
    percent = (attended * 100) // total if total else 0
    return {"attended": attended, "total_past": total, "percent": percent}


def attendance_percent(enrollment) -> int:
    """Floor of attended / past sessions × 100 for this enrollment's cohort (0 if none)."""
    return _summary(_rows(enrollment))["percent"]


def my_attendance(student_id, course_slug) -> dict:
    if not course_slug:
        raise ServiceError(400, "course_required")
    course = course_by_slug(course_slug)
    enrollment = enrollment_for_course(student_id, course.id)
    rows = _rows(enrollment)
    return {
        "course_id": course.id,
        "cohort_id": enrollment.cohort_id,
        "sessions": [
            {
                "session_id": s.id,
                "date": iso(s.session_date),
                "start_time": s.start_time,
                "end_time": s.end_time,
                "topic_id": s.topic_id,
                "status": status,
            }
            for s, status, _ in rows
        ],
        "summary": _summary(rows),
    }
