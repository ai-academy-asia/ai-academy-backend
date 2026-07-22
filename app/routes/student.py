"""Student-facing router: public course/cohort browse + student self-service
(enroll / cancel / my cohorts). Auth is shared via /auth."""
from flask import Blueprint, g, jsonify, request

from app.auth import actor_required
from app.services import cohorts as cohorts_svc
from app.services import courses as courses_svc
from app.services import enrollments as enroll_svc
from app.services import schedules as sched_svc

from ._shared import can

bp = Blueprint("student", __name__)


# ---------------------------------------------------------------- public browse
@bp.get("/courses")
def list_courses():
    return jsonify(courses=courses_svc.list_courses(
        can_edit=can("course:edit"),
        status=request.args.get("status"),
        level=request.args.get("level"),
        category=request.args.get("category"),
    ))


@bp.get("/courses/<id_or_slug>")
def get_course(id_or_slug):
    course = courses_svc.get_public_course(id_or_slug, can_edit=can("course:edit"))
    return jsonify(course.to_detail())


@bp.get("/cohorts")
def list_cohorts():
    rows = cohorts_svc.list_public(course_id=request.args.get("course_id"))
    return jsonify(cohorts=[c.to_dict() for c in rows])


@bp.get("/cohorts/<int:cohort_id>")
def get_cohort(cohort_id):
    cohort = cohorts_svc.get_public(cohort_id, can_manage=can("cohort:manage"))
    return jsonify(cohort.to_dict(detail=True))


# ---------------------------------------------------------------- student self-service
@bp.post("/cohorts/<int:cohort_id>/enroll")
@actor_required("student")
def enroll_self(cohort_id):
    cohort = cohorts_svc.get_or_404(cohort_id)
    enrollment = enroll_svc.enroll(
        cohort, g.current_user.actor_id, require_open=True, created_via="web"
    )
    return jsonify(enrollment.to_dict(with_student=False)), 201


@bp.delete("/cohorts/<int:cohort_id>/enroll")
@actor_required("student")
def cancel_self(cohort_id):
    cohort = cohorts_svc.get_or_404(cohort_id)
    enroll_svc.cancel(cohort, g.current_user.actor_id)
    return jsonify(status="cancelled")


@bp.get("/me/cohorts")
@actor_required("student")
def my_cohorts():
    return jsonify(cohorts=sched_svc.student_cohorts(g.current_user.actor_id))
