"""Staff authoring of modules, lessons and materials (``course:edit``)."""
from flask import Blueprint, g, jsonify, request

from app.auth import require_permission
from app.services.learning import authoring as svc
from app.services.learning import materials as materials_svc
from app.services.learning.shapes import (
    staff_lesson_dict,
    staff_material_dict,
    staff_module_dict,
)

from ._shared import body

bp = Blueprint("learning_admin", __name__)
guard = require_permission("course:edit")


# ---------------------------------------------------------------- modules
@bp.get("/admin/courses/<course_id>/modules")
@guard
def list_modules(course_id):
    course = svc.get_course(course_id)
    return jsonify(modules=[staff_module_dict(t) for t in svc.list_modules(course)])


@bp.post("/admin/courses/<course_id>/modules")
@guard
def create_module(course_id):
    topic = svc.create_module(svc.get_course(course_id), body())
    return jsonify(staff_module_dict(topic)), 201


@bp.patch("/admin/modules/<module_id>")
@guard
def update_module(module_id):
    return jsonify(staff_module_dict(svc.update_module(svc.get_module(module_id), body())))


@bp.delete("/admin/modules/<module_id>")
@guard
def delete_module(module_id):
    svc.delete_module(svc.get_module(module_id))
    return jsonify(status="deleted")


# ---------------------------------------------------------------- lessons
@bp.get("/admin/modules/<module_id>/lessons")
@guard
def list_lessons(module_id):
    topic = svc.get_module(module_id)
    return jsonify(lessons=[staff_lesson_dict(lesson) for lesson in svc.list_lessons(topic)])


@bp.post("/admin/modules/<module_id>/lessons")
@guard
def create_lesson(module_id):
    lesson = svc.create_lesson(svc.get_module(module_id), body())
    return jsonify(staff_lesson_dict(lesson)), 201


@bp.get("/admin/lessons/<lesson_id>")
@guard
def get_lesson(lesson_id):
    lesson = svc.get_lesson(lesson_id)
    data = staff_lesson_dict(lesson)
    data["materials"] = [staff_material_dict(m) for m in materials_svc.list_materials(lesson)]
    return jsonify(data)


@bp.patch("/admin/lessons/<lesson_id>")
@guard
def update_lesson(lesson_id):
    return jsonify(staff_lesson_dict(svc.update_lesson(svc.get_lesson(lesson_id), body())))


@bp.delete("/admin/lessons/<lesson_id>")
@guard
def delete_lesson(lesson_id):
    svc.delete_lesson(svc.get_lesson(lesson_id))
    return jsonify(status="deleted")


# ---------------------------------------------------------------- materials
@bp.get("/admin/lessons/<lesson_id>/materials")
@guard
def list_materials(lesson_id):
    lesson = svc.get_lesson(lesson_id)
    return jsonify(materials=[staff_material_dict(m)
                              for m in materials_svc.list_materials(lesson)])


@bp.post("/admin/lessons/<lesson_id>/materials")
@guard
def create_material(lesson_id):
    lesson = svc.get_lesson(lesson_id)
    if request.mimetype == "multipart/form-data":
        data, file = request.form.to_dict(), request.files.get("file")
    else:
        data, file = body(), None
    material = materials_svc.create_material(
        lesson, data, file, account_id=g.current_user.id,
        content_length=request.content_length)
    return jsonify(staff_material_dict(material)), 201


@bp.patch("/admin/materials/<material_id>")
@guard
def update_material(material_id):
    material = materials_svc.update_material(materials_svc.get_material(material_id), body())
    return jsonify(staff_material_dict(material))


@bp.delete("/admin/materials/<material_id>")
@guard
def delete_material(material_id):
    materials_svc.delete_material(materials_svc.get_material(material_id))
    return jsonify(status="deleted")
