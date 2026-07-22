"""Course (program) endpoints.

Public: list + detail (published courses only).
Staff with ``course:edit``: create / update / delete + template file upload.
"""
import io
import mimetypes
import os
from datetime import date

from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    jsonify,
    make_response,
    request,
    send_file,
)
from sqlalchemy.exc import IntegrityError

from app.auth import has_permission, require_permission
from app.extensions import db
from app.models import COURSE_LEVELS, COURSE_STATUSES, Course
from app.storage import (
    S3StorageError,
    build_key,
    delete_object,
    download_stream,
    upload_fileobj,
)

bp = Blueprint("courses", __name__, url_prefix="/courses")

# Body fields a client may set (templates are handled by the file endpoints).
_WRITABLE = {
    "slug", "category", "level", "status",
    "title_mn", "title_en", "tagline_mn", "tagline_en",
    "age_min", "age_max", "duration_weeks", "format",
    "price_amount", "currency", "discount_percent",
    "banner_image_url", "icon",
    "description_mn", "description_en", "prerequisites_mn", "prerequisites_en",
    "capacity", "final_project_type",
    "curriculum", "whats_included", "instructors",
}
_DATE_FIELDS = {"start_date", "end_date"}

# Template files: kind -> (key column, name column).
_TEMPLATE_KINDS = {
    "cert": ("cert_template_key", "cert_template_name"),
    "contract": ("contract_template_key", "contract_template_name"),
}
_ALLOWED_EXT = {".pdf", ".doc", ".docx"}


# ---------------------------------------------------------------- helpers
def _fail(status, error, **extra):
    """Abort with a JSON error body (raises, never returns)."""
    abort(make_response(jsonify(error=error, **extra), status))


def _can_edit() -> bool:
    user = getattr(g, "current_user", None)
    return user is not None and has_permission(user.role, "course:edit")


def _apply_fields(course: Course, data: dict):
    """Assign whitelisted fields from the request body onto the course."""
    for key in _WRITABLE:
        if key in data:
            setattr(course, key, data[key])
    for key in _DATE_FIELDS:
        if key in data:
            value = data[key]
            if value in (None, ""):
                setattr(course, key, None)
                continue
            try:
                setattr(course, key, date.fromisoformat(value))  # 'YYYY-MM-DD'
            except (ValueError, TypeError):
                _fail(400, "invalid_date", field=key)


def _validate_or_fail(course: Course):
    if not course.slug:
        _fail(400, "slug_required")
    if not course.title_mn:
        _fail(400, "title_mn_required")
    if course.status not in COURSE_STATUSES:
        _fail(400, "invalid_status")
    if course.level is not None and course.level not in COURSE_LEVELS:
        _fail(400, "invalid_level")


def _commit_or_fail():
    """Commit, translating a slug-uniqueness violation into 409."""
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        _fail(409, "slug_taken")


def _get_course(id_or_slug) -> Course:
    """Resolve by numeric id or slug, or abort 404."""
    if str(id_or_slug).isdigit():
        course = db.session.get(Course, int(id_or_slug))
    else:
        course = Course.query.filter_by(slug=id_or_slug).first()
    if course is None:
        _fail(404, "not_found")
    return course


def _template_target(id_or_slug, kind):
    """Validate kind + resolve course; return (course, key_col, name_col)."""
    if kind not in _TEMPLATE_KINDS:
        _fail(400, "invalid_kind")
    course = _get_course(id_or_slug)
    key_col, name_col = _TEMPLATE_KINDS[kind]
    return course, key_col, name_col


# ---------------------------------------------------------------- public read
@bp.get("")
def list_courses():
    q = Course.query
    if _can_edit():
        status = request.args.get("status")
        if status:
            q = q.filter_by(status=status)
    else:
        q = q.filter(Course.status.in_(("open", "closed")))

    for field in ("level", "category"):
        val = request.args.get(field)
        if val:
            q = q.filter(getattr(Course, field) == val)

    q = q.order_by(Course.start_date.is_(None), Course.start_date.asc(), Course.id.desc())
    return jsonify(courses=[c.to_summary() for c in q.all()])


@bp.get("/<id_or_slug>")
def get_course(id_or_slug):
    course = _get_course(id_or_slug)
    # Drafts are invisible to the public.
    if not course.is_public and not _can_edit():
        _fail(404, "not_found")
    return jsonify(course.to_detail())


# ---------------------------------------------------------------- write (staff)
@bp.post("")
@require_permission("course:edit")
def create_course():
    course = Course(status="draft")
    _apply_fields(course, request.get_json(silent=True) or {})
    _validate_or_fail(course)
    db.session.add(course)
    _commit_or_fail()
    return jsonify(course.to_detail()), 201


@bp.patch("/<id_or_slug>")
@require_permission("course:edit")
def update_course(id_or_slug):
    course = _get_course(id_or_slug)
    _apply_fields(course, request.get_json(silent=True) or {})
    _validate_or_fail(course)
    _commit_or_fail()
    return jsonify(course.to_detail())


@bp.delete("/<id_or_slug>")
@require_permission("course:edit")
def delete_course(id_or_slug):
    course = _get_course(id_or_slug)
    # Best-effort cleanup of S3 objects.
    for key_col, _ in _TEMPLATE_KINDS.values():
        key = getattr(course, key_col)
        if key:
            try:
                delete_object(key)
            except S3StorageError:
                pass
    db.session.delete(course)
    db.session.commit()
    return jsonify(status="deleted")


# ---------------------------------------------------------------- template files
@bp.put("/<id_or_slug>/templates/<kind>")
@require_permission("course:edit")
def upload_template(id_or_slug, kind):
    course, key_col, name_col = _template_target(id_or_slug, kind)

    file = request.files.get("file")
    if file is None or not file.filename:
        _fail(400, "file_required")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _ALLOWED_EXT:
        _fail(400, "unsupported_file_type", allowed=sorted(_ALLOWED_EXT))

    max_bytes = current_app.config["MAX_TEMPLATE_BYTES"]
    if request.content_length and request.content_length > max_bytes:
        _fail(413, "file_too_large", max_bytes=max_bytes)

    key = build_key("courses", str(course.id), f"{kind}_template{ext}")
    content_type = file.mimetype or mimetypes.guess_type(file.filename)[0]
    try:
        upload_fileobj(file.stream, key, content_type)
    except S3StorageError:
        _fail(502, "storage_error")

    setattr(course, key_col, key)
    setattr(course, name_col, file.filename)
    db.session.commit()
    return jsonify(status="ok", kind=kind, filename=file.filename)


@bp.get("/<id_or_slug>/templates/<kind>")
@require_permission("course:edit")
def download_template(id_or_slug, kind):
    course, key_col, name_col = _template_target(id_or_slug, kind)
    key = getattr(course, key_col)
    if not key:
        _fail(404, "not_found")

    try:
        body, content_type = download_stream(key)
        data = body.read()
    except S3StorageError:
        _fail(502, "storage_error")

    name = getattr(course, name_col) or os.path.basename(key)
    return send_file(
        io.BytesIO(data),
        mimetype=content_type or mimetypes.guess_type(name)[0] or "application/octet-stream",
        as_attachment=True,
        download_name=name,
    )


@bp.delete("/<id_or_slug>/templates/<kind>")
@require_permission("course:edit")
def delete_template(id_or_slug, kind):
    course, key_col, name_col = _template_target(id_or_slug, kind)
    key = getattr(course, key_col)
    if key:
        try:
            delete_object(key)
        except S3StorageError:
            _fail(502, "storage_error")
        setattr(course, key_col, None)
        setattr(course, name_col, None)
        db.session.commit()
    return jsonify(status="deleted")
