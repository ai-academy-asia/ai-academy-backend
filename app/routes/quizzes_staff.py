"""Quiz authoring (``course:edit``): quizzes, their question set, and attempt review.

The staff quiz payload carries the answer key; it is never served under ``/me``.
"""
from flask import Blueprint, jsonify, request

from app.auth import require_permission
from app.services.quizzes import authoring as authoring_svc
from app.services.quizzes import questions as questions_svc

from ._shared import body

bp = Blueprint("quizzes_staff", __name__)


@bp.get("/admin/courses/<int:course_id>/quizzes")
@require_permission("course:edit")
def list_quizzes(course_id):
    return jsonify(quizzes=authoring_svc.list_quizzes(course_id))


@bp.post("/admin/courses/<int:course_id>/quizzes")
@require_permission("course:edit")
def create_quiz(course_id):
    return jsonify(authoring_svc.create_quiz(course_id, body())), 201


@bp.get("/admin/quizzes/<int:quiz_id>")
@require_permission("course:edit")
def get_quiz(quiz_id):
    return jsonify(authoring_svc.get_quiz(quiz_id))


@bp.patch("/admin/quizzes/<int:quiz_id>")
@require_permission("course:edit")
def update_quiz(quiz_id):
    return jsonify(authoring_svc.update_quiz(quiz_id, body()))


@bp.delete("/admin/quizzes/<int:quiz_id>")
@require_permission("course:edit")
def delete_quiz(quiz_id):
    authoring_svc.delete_quiz(quiz_id, force=authoring_svc.parse_force(request.args.get("force")))
    return jsonify(status="deleted")


@bp.put("/admin/quizzes/<int:quiz_id>/questions")
@require_permission("course:edit")
def replace_questions(quiz_id):
    payload = request.get_json(silent=True)
    items = payload.get("questions") if isinstance(payload, dict) else payload
    return jsonify(questions_svc.replace_questions(
        quiz_id, items, force=authoring_svc.parse_force(request.args.get("force"))))


@bp.get("/admin/quizzes/<int:quiz_id>/attempts")
@require_permission("course:edit")
def list_attempts(quiz_id):
    return jsonify(attempts=questions_svc.list_attempts(
        quiz_id, limit=request.args.get("limit"),
        student_id=authoring_svc.parse_student_filter(request.args.get("student_id")),
    ))
