"""Lesson materials: staff upload/link/delete, student pre-signed download (§2.4).

Files are private S3 objects under ``courses/<course_id>/lessons/<lesson_id>/``;
a student only ever gets a 5-minute pre-signed GET for one.
"""
import contextlib
import mimetypes
import os
import uuid
from datetime import timedelta

from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import Cohort, CourseLesson, LessonMaterial
from app.storage import (
    S3StorageError,
    build_key,
    delete_object,
    presigned_url,
    upload_fileobj,
)
from app.timeutil import iso, utcnow

from ..access import enrollment_for_course
from ..errors import ServiceError
from ..params import get_by_id
from . import fields

MAX_MATERIAL_BYTES = 50 * 1024 * 1024
DOWNLOAD_TTL_SECONDS = 300
TITLE_MAX = 200


def delete_files(keys):
    """Best-effort S3 cleanup after the rows are gone: an orphan beats a dangling row."""
    for key in keys:
        with contextlib.suppress(S3StorageError):
            delete_object(key)


# ---------------------------------------------------------------- student
def download(student_id, material_id) -> dict:
    material = get_by_id(LessonMaterial, material_id)
    if material is None:
        raise ServiceError(404, "material_not_found")
    lesson = db.session.get(CourseLesson, material.lesson_id)
    enrollment = enrollment_for_course(student_id, lesson.topic.course_id)
    if material.cohort_id is not None and material.cohort_id != enrollment.cohort_id:
        raise ServiceError(404, "material_not_found")
    if material.type == "link":
        raise ServiceError(400, "material_is_link", url=material.url)
    if not material.file_key:
        raise ServiceError(404, "material_not_found")
    try:
        url = presigned_url(material.file_key, expires=DOWNLOAD_TTL_SECONDS)
    except S3StorageError:
        raise ServiceError(503, "storage_error") from None
    return {
        "url": url,
        "expires_at": iso(utcnow() + timedelta(seconds=DOWNLOAD_TTL_SECONDS)),
        "file_name": material.file_name,
        "size_bytes": material.size_bytes,
    }


# ---------------------------------------------------------------- staff
def get_material(material_id) -> LessonMaterial:
    material = get_by_id(LessonMaterial, material_id)
    if material is None:
        raise ServiceError(404, "material_not_found")
    return material


def list_materials(lesson) -> list:
    return (LessonMaterial.query.filter_by(lesson_id=lesson.id)
            .order_by(LessonMaterial.sort_order, LessonMaterial.cohort_id.nullsfirst(),
                      LessonMaterial.id).all())


def _cohort_id(lesson, value):
    """``None`` (every cohort) or the id of a cohort of the lesson's course."""
    if value in (None, ""):
        return None
    cohort = get_by_id(Cohort, value)
    if cohort is None or cohort.course_id != lesson.topic.course_id:
        raise ServiceError(400, "invalid_cohort")
    return cohort.id


def _file_size(stream) -> int:
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


def _store_file(lesson, file, content_length) -> dict:
    if content_length and content_length > MAX_MATERIAL_BYTES:
        raise ServiceError(413, "file_too_large", max_bytes=MAX_MATERIAL_BYTES)
    size = _file_size(file.stream)
    if size > MAX_MATERIAL_BYTES:
        raise ServiceError(413, "file_too_large", max_bytes=MAX_MATERIAL_BYTES)
    name = os.path.basename(file.filename)[:255]
    ext = os.path.splitext(name)[1].lower()
    # secure_filename drops Cyrillic entirely; the original name is kept in file_name.
    safe = secure_filename(name) or f"file{ext}"
    key = build_key("courses", str(lesson.topic.course_id), "lessons", str(lesson.id),
                    f"{uuid.uuid4().hex}_{safe}")
    content_type = (file.mimetype if file.mimetype and file.mimetype != "application/octet-stream"
                    else None) or mimetypes.guess_type(name)[0] or "application/octet-stream"
    try:
        upload_fileobj(file.stream, key, content_type)
    except S3StorageError:
        raise ServiceError(502, "storage_error") from None
    return {"file_key": key, "file_name": name, "content_type": content_type,
            "size_bytes": size}


def create_material(lesson, data, file, *, account_id, content_length=None) -> LessonMaterial:
    """A file (multipart ``file``) or a link (``{"type": "link", "url": …}``)."""
    kind = data.get("type") or ("link" if data.get("url") and file is None else "file")
    if kind not in ("file", "link"):
        raise ServiceError(400, "invalid_type", allowed=["file", "link"])
    title = fields.text(data, "title", max_len=TITLE_MAX, required=kind == "link")
    cohort_id = _cohort_id(lesson, data.get("cohort_id"))
    sort_order = fields.integer(data, "sort_order") if data.get("sort_order") not in (
        None, "") else 0
    material = LessonMaterial(lesson_id=lesson.id, cohort_id=cohort_id, type=kind,
                              sort_order=sort_order, uploaded_by_account_id=account_id)
    if kind == "link":
        material.url = fields.http_url(data.get("url"))
        material.title = title
    else:
        if file is None or not file.filename:
            raise ServiceError(400, "file_required")
        stored = _store_file(lesson, file, content_length)
        for key, value in stored.items():
            setattr(material, key, value)
        material.title = title or stored["file_name"][:TITLE_MAX]
    db.session.add(material)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        if material.file_key:
            delete_files([material.file_key])
        raise
    return material


def update_material(material, data) -> LessonMaterial:
    """Title, cohort and position; the file or link itself is replaced by re-creating."""
    if "title" in data:
        material.title = fields.text(data, "title", max_len=TITLE_MAX, required=True)
    if "cohort_id" in data:
        lesson = db.session.get(CourseLesson, material.lesson_id)
        material.cohort_id = _cohort_id(lesson, data["cohort_id"])
    if "sort_order" in data:
        material.sort_order = fields.integer(data, "sort_order")
    db.session.commit()
    return material


def delete_material(material):
    key = material.file_key
    db.session.delete(material)
    db.session.commit()
    if key:
        delete_files([key])

