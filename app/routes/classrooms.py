"""Classroom (хичээлийн танхим) CRUD — super_admin only (classroom:manage)."""
from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.auth import require_permission
from app.extensions import db
from app.models import Classroom
from app.routes.common import json_fail

bp = Blueprint("classrooms", __name__, url_prefix="/admin/classrooms")

_WRITABLE = {"name", "center_name", "location", "capacity", "floor", "equipment", "is_active", "notes"}


def _apply(classroom, data):
    for key in _WRITABLE:
        if key in data:
            setattr(classroom, key, data[key])


def _get_or_404(classroom_id):
    classroom = db.session.get(Classroom, classroom_id)
    if classroom is None:
        json_fail(404, "not_found")
    return classroom


@bp.get("")
@require_permission("classroom:manage")
def list_classrooms():
    q = Classroom.query
    search = request.args.get("q")
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(Classroom.name.ilike(like), Classroom.center_name.ilike(like)))
    active = request.args.get("active")
    if active in ("true", "false"):
        q = q.filter(Classroom.is_active.is_(active == "true"))
    rows = q.order_by(Classroom.center_name.asc(), Classroom.name.asc()).all()
    return jsonify(classrooms=[c.to_dict() for c in rows])


@bp.get("/<int:classroom_id>")
@require_permission("classroom:manage")
def get_classroom(classroom_id):
    return jsonify(_get_or_404(classroom_id).to_dict())


@bp.post("")
@require_permission("classroom:manage")
def create_classroom():
    data = request.get_json(silent=True) or {}
    classroom = Classroom()
    _apply(classroom, data)
    if not classroom.name:
        json_fail(400, "name_required")
    db.session.add(classroom)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        json_fail(409, "classroom_exists")  # same (center_name, name)
    return jsonify(classroom.to_dict()), 201


@bp.patch("/<int:classroom_id>")
@require_permission("classroom:manage")
def update_classroom(classroom_id):
    classroom = _get_or_404(classroom_id)
    _apply(classroom, request.get_json(silent=True) or {})
    if not classroom.name:
        json_fail(400, "name_required")
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        json_fail(409, "classroom_exists")
    return jsonify(classroom.to_dict())


@bp.delete("/<int:classroom_id>")
@require_permission("classroom:manage")
def delete_classroom(classroom_id):
    classroom = _get_or_404(classroom_id)
    db.session.delete(classroom)
    db.session.commit()
    return jsonify(status="deleted")
