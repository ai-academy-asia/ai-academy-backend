"""Derived schedules (хувиар): a teacher's / classroom's assigned cohorts, a
student's own enrolled cohorts, and period-wide overviews across ALL teachers /
classrooms. Date-range based (no per-session rows)."""
from collections import defaultdict
from datetime import date

from flask import Blueprint, g, jsonify, request

from app.auth import actor_required, has_permission, require_permission
from app.extensions import db
from app.models import Classroom, Cohort, Enrollment, Teacher
from app.routes.common import json_fail

bp = Blueprint("schedules", __name__)


def _require_login():
    if getattr(g, "current_user", None) is None:
        json_fail(401, "authentication_required")


def _has_any(user, *perms):
    return any(has_permission(user.role, p) for p in perms)


def _cohorts_for(column, value):
    return (
        Cohort.query.filter(column == value)
        .order_by(Cohort.start_date.is_(None), Cohort.start_date.asc())
        .all()
    )


def _parse_range():
    """Optional ?from=YYYY-MM-DD&to=YYYY-MM-DD. Both or neither; returns (from, to)."""
    raw_from = request.args.get("from")
    raw_to = request.args.get("to")
    if not raw_from and not raw_to:
        return None, None
    if not (raw_from and raw_to):
        json_fail(400, "from_and_to_required")
    try:
        return date.fromisoformat(raw_from), date.fromisoformat(raw_to)
    except (ValueError, TypeError):
        json_fail(400, "invalid_date")


def _range_meta(from_date, to_date):
    return {
        "from": from_date.isoformat() if from_date else None,
        "to": to_date.isoformat() if to_date else None,
    }


def _cohorts_in_range(from_date, to_date):
    """All cohorts overlapping [from, to] (or all cohorts if no range)."""
    q = Cohort.query
    if from_date and to_date:
        q = q.filter(
            Cohort.start_date.isnot(None),
            Cohort.end_date.isnot(None),
            Cohort.start_date <= to_date,
            Cohort.end_date >= from_date,
        )
    return q.order_by(Cohort.start_date.is_(None), Cohort.start_date.asc()).all()


@bp.get("/teachers/<int:teacher_id>/schedule")
def teacher_schedule(teacher_id):
    _require_login()
    user = g.current_user
    is_self = user.actor_type == "teacher" and user.actor_id == teacher_id
    is_staff = _has_any(user, "cohort:manage", "schedule:manage")
    if not (is_self or is_staff):
        json_fail(403, "forbidden")
    if db.session.get(Teacher, teacher_id) is None:
        json_fail(404, "not_found")
    rows = _cohorts_for(Cohort.teacher_id, teacher_id)
    return jsonify(teacher_id=teacher_id, cohorts=[c.to_dict() for c in rows])


@bp.get("/classrooms/<int:classroom_id>/schedule")
def classroom_schedule(classroom_id):
    _require_login()
    user = g.current_user
    if not _has_any(user, "cohort:manage", "classroom:manage"):
        json_fail(403, "forbidden")
    if db.session.get(Classroom, classroom_id) is None:
        json_fail(404, "not_found")
    rows = _cohorts_for(Cohort.classroom_id, classroom_id)
    return jsonify(classroom_id=classroom_id, cohorts=[c.to_dict() for c in rows])


@bp.get("/admin/schedule/teachers")
@require_permission("schedule:manage")
def all_teacher_schedules():
    """Every teacher's cohorts within a period (or all-time). ?available=true
    returns only teachers with no cohort in the range (free to assign)."""
    from_date, to_date = _parse_range()
    only_available = request.args.get("available") == "true"

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
    return jsonify(
        **_range_meta(from_date, to_date), count=len(result), teachers=result
    )


@bp.get("/admin/schedule/classrooms")
@require_permission("schedule:manage")
def all_classroom_schedules():
    """Every classroom's cohorts within a period. ?available=true → only free."""
    from_date, to_date = _parse_range()
    only_available = request.args.get("available") == "true"

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
    return jsonify(
        **_range_meta(from_date, to_date), count=len(result), classrooms=result
    )


@bp.get("/me/cohorts")
@actor_required("student")
def my_cohorts():
    """The logged-in student's active enrollments (their schedule)."""
    enrollments = (
        Enrollment.query.filter_by(student_id=g.current_user.actor_id, status="active").all()
    )
    cohorts = [e.cohort.to_dict() for e in enrollments if e.cohort is not None]
    return jsonify(cohorts=cohorts)
