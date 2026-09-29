"""Class sessions, QR check-in, attendance and teacher rosters.

Teacher side (``/teacher/...``): the cohort's own teacher, or staff holding
``cohort:manage``. A cohort or session the caller may not teach answers 404.
Student side (``/me/attendance...``): student tokens only.
"""
from functools import wraps

from flask import Blueprint, g, jsonify, request

from app.auth import actor_required, has_permission
from app.services import attendance as svc
from app.services.errors import ServiceError

from ._shared import body, current_user

bp = Blueprint("attendance", __name__)


def teacher_or_manager(fn):
    """Teachers, or staff who may manage cohorts. Everyone else is 403."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            raise ServiceError(401, getattr(g, "auth_error", None) or "authentication_required")
        if user.actor_type != "teacher" and not has_permission(user.role, "cohort:manage"):
            raise ServiceError(403, "forbidden")
        return fn(*args, **kwargs)

    return wrapper


# ----------------------------------------------------------------- sessions
@bp.get("/teacher/cohorts/<int:cohort_id>/sessions")
@teacher_or_manager
def list_sessions(cohort_id):
    return jsonify(cohort_id=cohort_id, sessions=svc.list_sessions(
        g.current_user, cohort_id,
        date_from=request.args.get("from"), date_to=request.args.get("to"),
    ))


@bp.post("/teacher/cohorts/<int:cohort_id>/sessions")
@teacher_or_manager
def create_session(cohort_id):
    session = svc.create_session(g.current_user, cohort_id, body())
    return jsonify(svc.session_dict(session)), 201


@bp.post("/teacher/cohorts/<int:cohort_id>/sessions/generate")
@teacher_or_manager
def generate_sessions(cohort_id):
    return jsonify(svc.generate_sessions(g.current_user, cohort_id))


@bp.get("/teacher/cohorts/<int:cohort_id>/students")
@teacher_or_manager
def cohort_students(cohort_id):
    return jsonify(cohort_id=cohort_id, students=svc.cohort_students(g.current_user, cohort_id))


@bp.patch("/teacher/sessions/<int:session_id>")
@teacher_or_manager
def update_session(session_id):
    return jsonify(svc.session_dict(svc.update_session(g.current_user, session_id, body())))


@bp.delete("/teacher/sessions/<int:session_id>")
@teacher_or_manager
def delete_session(session_id):
    svc.delete_session(g.current_user, session_id)
    return jsonify(status="deleted")


# ----------------------------------------------------------------- attendance
@bp.post("/teacher/sessions/<int:session_id>/qr")
@teacher_or_manager
def issue_qr(session_id):
    return jsonify(svc.issue_qr(g.current_user, session_id))


@bp.get("/teacher/sessions/<int:session_id>/attendance")
@teacher_or_manager
def session_attendance(session_id):
    return jsonify(svc.session_attendance(g.current_user, session_id))


@bp.put("/teacher/sessions/<int:session_id>/attendance/<int:student_id>")
@teacher_or_manager
def mark_attendance(session_id, student_id):
    return jsonify(svc.mark(g.current_user, session_id, student_id, body().get("status")))


@bp.post("/me/attendance/check-in")
@actor_required("student")
def check_in():
    payload, created = svc.check_in(g.current_user.actor_id, body().get("token"))
    return jsonify(payload), 201 if created else 200


@bp.get("/me/attendance")
@actor_required("student")
def my_attendance():
    return jsonify(svc.my_attendance(g.current_user.actor_id, request.args.get("course")))
