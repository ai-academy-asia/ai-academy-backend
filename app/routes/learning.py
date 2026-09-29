"""Student learning path, lessons, materials, notes, progress (contract §2.1–2.5)."""
from flask import Blueprint, g, jsonify

from app.auth import actor_required
from app.services.learning import materials as materials_svc
from app.services.learning import student as learning_svc

from ._shared import body

bp = Blueprint("learning", __name__)


def _student_id():
    return g.current_user.actor_id


@bp.get("/me/courses/<slug>/learning")
@actor_required("student")
def learning_path(slug):
    return jsonify(learning_svc.learning_path(_student_id(), slug))


@bp.get("/me/modules/<module_id>/lessons")
@actor_required("student")
def module_lessons(module_id):
    return jsonify(learning_svc.module_lessons(_student_id(), module_id))


@bp.get("/me/lessons/<lesson_id>")
@actor_required("student")
def lesson_detail(lesson_id):
    return jsonify(learning_svc.lesson_detail(_student_id(), lesson_id))


@bp.post("/me/lessons/<lesson_id>/complete")
@actor_required("student")
def complete_lesson(lesson_id):
    return jsonify(learning_svc.complete_lesson(_student_id(), lesson_id))


@bp.put("/me/lessons/<lesson_id>/note")
@actor_required("student")
def put_note(lesson_id):
    note, created = learning_svc.put_note(_student_id(), lesson_id, body())
    return jsonify(note), 201 if created else 200


@bp.get("/me/materials/<material_id>/download")
@actor_required("student")
def download_material(material_id):
    return jsonify(materials_svc.download(_student_id(), material_id))
