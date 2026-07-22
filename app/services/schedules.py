"""Derived-schedule (хувиар) domain logic: single teacher/classroom, period-wide
overviews across all teachers/classrooms, and a student's own cohorts."""
from collections import defaultdict
from datetime import date

from app.extensions import db
from app.models import Classroom, Cohort, Enrollment, Teacher

from .errors import ServiceError


def parse_range(raw_from, raw_to):
    """?from=YYYY-MM-DD&to=YYYY-MM-DD — both or neither. Returns (from, to)."""
    if not raw_from and not raw_to:
        return None, None
    if not (raw_from and raw_to):
        raise ServiceError(400, "from_and_to_required")
    try:
        return date.fromisoformat(raw_from), date.fromisoformat(raw_to)
    except (ValueError, TypeError):
        raise ServiceError(400, "invalid_date") from None


def range_meta(from_date, to_date):
    return {
        "from": from_date.isoformat() if from_date else None,
        "to": to_date.isoformat() if to_date else None,
    }


def _cohorts_for(column, value):
    return (
        Cohort.query.filter(column == value)
        .order_by(Cohort.start_date.is_(None), Cohort.start_date.asc())
        .all()
    )


def _cohorts_in_range(from_date, to_date):
    q = Cohort.query
    if from_date and to_date:
        q = q.filter(
            Cohort.start_date.isnot(None),
            Cohort.end_date.isnot(None),
            Cohort.start_date <= to_date,
            Cohort.end_date >= from_date,
        )
    return q.order_by(Cohort.start_date.is_(None), Cohort.start_date.asc()).all()


def teacher_schedule(teacher_id):
    if db.session.get(Teacher, teacher_id) is None:
        raise ServiceError(404, "not_found")
    return [c.to_dict() for c in _cohorts_for(Cohort.teacher_id, teacher_id)]


def classroom_schedule(classroom_id):
    if db.session.get(Classroom, classroom_id) is None:
        raise ServiceError(404, "not_found")
    return [c.to_dict() for c in _cohorts_for(Cohort.classroom_id, classroom_id)]


def overview_teachers(from_date, to_date, *, only_available):
    by_teacher = defaultdict(list)
    for c in _cohorts_in_range(from_date, to_date):
        if c.teacher_id:
            by_teacher[c.teacher_id].append(c)
    result = []
    for t in Teacher.query.order_by(Teacher.id).all():
        cohorts = by_teacher.get(t.id, [])
        if only_available and cohorts:
            continue
        result.append({
            "teacher": {"id": t.id, "name": f"{t.first_name} {t.last_name or ''}".strip()},
            "busy": len(cohorts) > 0,
            "cohort_count": len(cohorts),
            "cohorts": [c.to_dict() for c in cohorts],
        })
    return result


def overview_classrooms(from_date, to_date, *, only_available):
    by_room = defaultdict(list)
    for c in _cohorts_in_range(from_date, to_date):
        if c.classroom_id:
            by_room[c.classroom_id].append(c)
    result = []
    for room in Classroom.query.order_by(Classroom.center_name.asc(), Classroom.name.asc()).all():
        cohorts = by_room.get(room.id, [])
        if only_available and cohorts:
            continue
        result.append({
            "classroom": {"id": room.id, "name": room.name,
                          "center_name": room.center_name, "capacity": room.capacity,
                          "is_active": room.is_active},
            "busy": len(cohorts) > 0,
            "cohort_count": len(cohorts),
            "cohorts": [c.to_dict() for c in cohorts],
        })
    return result


def student_cohorts(student_id):
    enrollments = Enrollment.query.filter_by(student_id=student_id, status="active").all()
    return [e.cohort.to_dict() for e in enrollments if e.cohort is not None]
