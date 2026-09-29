"""Student assignments, submissions and file uploads (contract §2.6, §2.8)."""
from flask import Blueprint, g, jsonify, request

from app.auth import actor_required
from app.services.assignments import files as files_svc
from app.services.assignments import student as student_svc

from ._shared import body

bp = Blueprint("assignments", __name__)


@bp.get("/me/assignments/<int:assignment_id>")
@actor_required("student")
def get_assignment(assignment_id):
    return jsonify(student_svc.get_for_student(g.current_user.actor_id, assignment_id))


@bp.post("/me/assignments/<int:assignment_id>/submissions")
@actor_required("student")
def submit(assignment_id):
    return jsonify(student_svc.submit(g.current_user.actor_id, assignment_id, body())), 201


@bp.post("/me/files")
@actor_required("student")
def upload_file():
    data = files_svc.upload(g.current_user.actor_id, request.files.get("file"),
                            content_length=request.content_length)
    return jsonify(data), 201


@bp.get("/me/files/<int:file_id>/download")
@actor_required("student")
def download_file(file_id):
    return jsonify(files_svc.download_own(g.current_user.actor_id, file_id))
