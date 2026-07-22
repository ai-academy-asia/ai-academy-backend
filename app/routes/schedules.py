"""Derived schedules (хувиар): a teacher's / classroom's assigned cohorts, and
a student's own enrolled cohorts. Date-range based (no per-session rows)."""
from flask import Blueprint, g, jsonify

from app.auth import actor_required, has_permission
from app.extensions import db
from app.models import Classroom, Cohort, Enrollment, Teacher
from app.routes.common import json_fail

bp = Blueprint("schedules", __name__)


def _require_login():
    if getattr(g, "current_user", None) is None:
        json_fail(401, "authentication_required")


def _cohorts_for(column, value):
    return (
        Cohort.query.filter(column == value)
        .order_by(Cohort.start_date.is_(None), Cohort.start_date.asc())
        .all()
    )


@bp.get("/teachers/<int:teacher_id>/schedule")
def teacher_schedule(teacher_id):
    _require_login()
    user = g.current_user
    is_self = user.actor_type == "teacher" and user.actor_id == teacher_id
    is_staff = has_permission(user.role, "cohort:manage") or has_permission(user.role, "schedule:manage")
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
    if not (has_permission(user.role, "cohort:manage") or has_permission(user.role, "classroom:manage")):
        json_fail(403, "forbidden")
    if db.session.get(Classroom, classroom_id) is None:
        json_fail(404, "not_found")
    rows = _cohorts_for(Cohort.classroom_id, classroom_id)
    return jsonify(classroom_id=classroom_id, cohorts=[c.to_dict() for c in rows])


@bp.get("/me/cohorts")
@actor_required("student")
def my_cohorts():
    """The logged-in student's active enrollments (their schedule)."""
    enrollments = (
        Enrollment.query.filter_by(student_id=g.current_user.actor_id, status="active").all()
    )
    cohorts = [e.cohort.to_dict() for e in enrollments if e.cohort is not None]
    return jsonify(cohorts=cohorts)
