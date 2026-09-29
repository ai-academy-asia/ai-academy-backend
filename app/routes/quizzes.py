"""Student quiz attempts, graded per answer (contract §2.7)."""
from flask import Blueprint, g, jsonify

from app.auth import actor_required
from app.services.quizzes import attempts as attempts_svc

from ._shared import body

bp = Blueprint("quizzes", __name__)


@bp.post("/me/quizzes/<int:quiz_id>/attempts")
@actor_required("student")
def start_attempt(quiz_id):
    payload, created = attempts_svc.start_attempt(g.current_user.actor_id, quiz_id)
    return jsonify(payload), 201 if created else 200


@bp.post("/me/quiz-attempts/<int:attempt_id>/answers")
@actor_required("student")
def answer_question(attempt_id):
    return jsonify(attempts_svc.answer_question(g.current_user.actor_id, attempt_id, body()))


@bp.post("/me/quiz-attempts/<int:attempt_id>/finish")
@actor_required("student")
def finish_attempt(attempt_id):
    return jsonify(attempts_svc.finish_attempt(g.current_user.actor_id, attempt_id))


@bp.get("/me/quiz-attempts/<int:attempt_id>")
@actor_required("student")
def get_attempt(attempt_id):
    return jsonify(attempts_svc.get_attempt(g.current_user.actor_id, attempt_id))
