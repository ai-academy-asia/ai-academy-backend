"""Assignment authoring and teacher review.

Callers: the cohort's own teacher, or staff with ``cohort:manage``. Anything in
a cohort the caller does not teach answers 404, like every other foreign id.
"""
from functools import wraps

from flask import Blueprint, g, jsonify

from app.auth import has_permission, login_required
from app.services.assignments import authoring as authoring_svc
from app.services.assignments import review as review_svc
from app.services.errors import ServiceError

from ._shared import body

bp = Blueprint("assignments_staff", __name__)


def teacher_or_manager(fn):
    """A teacher account, or staff whose role grants ``cohort:manage``."""

    @login_required
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = g.current_user
        if user.actor_type != "teacher" and not has_permission(user.role, "cohort:manage"):
            raise ServiceError(403, "forbidden")
        return fn(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------- authoring
@bp.get("/teacher/cohorts/<int:cohort_id>/assignments")
@teacher_or_manager
def list_assignments(cohort_id):
    rows = authoring_svc.list_for_cohort(g.current_user, cohort_id)
    return jsonify(cohort_id=cohort_id, count=len(rows), assignments=rows)


@bp.post("/teacher/cohorts/<int:cohort_id>/assignments")
@teacher_or_manager
def create_assignment(cohort_id):
    return jsonify(authoring_svc.create(g.current_user, cohort_id, body())), 201


@bp.get("/teacher/assignments/<int:assignment_id>")
@teacher_or_manager
def get_assignment(assignment_id):
    return jsonify(authoring_svc.get(g.current_user, assignment_id))


@bp.patch("/teacher/assignments/<int:assignment_id>")
@teacher_or_manager
def update_assignment(assignment_id):
    return jsonify(authoring_svc.update(g.current_user, assignment_id, body()))


@bp.delete("/teacher/assignments/<int:assignment_id>")
@teacher_or_manager
def delete_assignment(assignment_id):
    return jsonify(status=authoring_svc.delete(g.current_user, assignment_id))


# ---------------------------------------------------------------- review
@bp.get("/teacher/assignments/<int:assignment_id>/submissions")
@teacher_or_manager
def list_submissions(assignment_id):
    return jsonify(review_svc.list_submissions(g.current_user, assignment_id))


@bp.get("/teacher/submissions/<int:submission_id>")
@teacher_or_manager
def get_submission(submission_id):
    return jsonify(review_svc.get_submission(g.current_user, submission_id))


@bp.post("/teacher/submissions/<int:submission_id>/review")
@teacher_or_manager
def review_submission(submission_id):
    return jsonify(review_svc.review(g.current_user, submission_id, body()))


@bp.get("/teacher/submissions/<int:submission_id>/file")
@teacher_or_manager
def submission_file(submission_id):
    return jsonify(review_svc.submission_file(g.current_user, submission_id))
