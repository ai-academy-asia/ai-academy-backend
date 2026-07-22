"""Teacher-facing router: a teacher's own schedule (staff may view any)."""
from flask import Blueprint, jsonify

from app.services import schedules as sched_svc
from app.services.errors import ServiceError

from ._shared import can_any, current_user

bp = Blueprint("teacher", __name__)


@bp.get("/teachers/<int:teacher_id>/schedule")
def teacher_schedule(teacher_id):
    user = current_user()
    if user is None:
        raise ServiceError(401, "authentication_required")
    is_self = user.actor_type == "teacher" and user.actor_id == teacher_id
    if not (is_self or can_any("cohort:manage", "schedule:manage")):
        raise ServiceError(403, "forbidden")
    return jsonify(teacher_id=teacher_id, cohorts=sched_svc.teacher_schedule(teacher_id))
