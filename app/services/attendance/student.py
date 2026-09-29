"""A student's own attendance in a course, and the attendance percentage.

"Past" means the session's date is today or earlier (Ulaanbaatar). A past
session with no record counts as ``absent``; ``present`` and ``late`` count as
attended; ``excused`` is neither attended nor excluded from the total.
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
    today = clock.local_today()
    rows = []
    for s in sessions:
        past = s.session_date <= today
        status = records.get(s.id) or ("absent" if past else None)
        rows.append((s, status, past))
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
