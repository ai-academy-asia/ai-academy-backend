"""Course domain logic: public read + staff CRUD + S3 template files."""
import contextlib
import mimetypes
import os
from datetime import date

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import COURSE_LEVELS, COURSE_STATUSES, Course
from app.storage import (
    S3StorageError,
    build_key,
    delete_object,
    download_stream,
    upload_fileobj,
)

from .errors import ServiceError

_WRITABLE = {
    "slug", "category", "level", "status",
    "title_mn", "title_en", "tagline_mn", "tagline_en",
    "target_audience", "age_min", "age_max",
    "duration_weeks", "duration_label", "format", "sort_order",
    "price_amount", "currency", "discount_percent",
    "banner_image_url", "icon",
    "description_mn", "description_en", "prerequisites_mn", "prerequisites_en",
    "capacity",
    "has_exam", "has_final_project", "final_project_type",
    "has_attendance", "attendance_method", "google_classroom_url",
    "curriculum", "whats_included", "instructors",
}
_DATE_FIELDS = {"start_date", "end_date"}

# Template files: kind -> (key column, name column).
TEMPLATE_KINDS = {
    "cert": ("cert_template_key", "cert_template_name"),
    "contract": ("contract_template_key", "contract_template_name"),
}
_ALLOWED_EXT = {".pdf", ".doc", ".docx"}


def _apply_fields(course, data):
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
                setattr(course, key, date.fromisoformat(value))
            except (ValueError, TypeError):
                raise ServiceError(400, "invalid_date", field=key) from None


def _validate(course):
    if not course.slug:
        raise ServiceError(400, "slug_required")
    if not course.title_mn:
        raise ServiceError(400, "title_mn_required")
    if course.status not in COURSE_STATUSES:
        raise ServiceError(400, "invalid_status")
    if course.level is not None and course.level not in COURSE_LEVELS:
        raise ServiceError(400, "invalid_level")


def _commit_or_slug_conflict():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ServiceError(409, "slug_taken") from None


def get_course(id_or_slug) -> Course:
    """Resolve by numeric id or slug, or raise 404."""
    if str(id_or_slug).isdigit():
        course = db.session.get(Course, int(id_or_slug))
    else:
        course = Course.query.filter_by(slug=id_or_slug).first()
    if course is None:
        raise ServiceError(404, "not_found")
    return course


# ---------------------------------------------------------------- read
def list_courses(*, can_edit, status=None, level=None, category=None):
    q = Course.query
    if can_edit:
        if status:
            q = q.filter_by(status=status)
    else:
        q = q.filter(Course.status.in_(("open", "closed")))
    if level:
        q = q.filter(Course.level == level)
    if category:
        q = q.filter(Course.category == category)
    q = q.order_by(Course.start_date.is_(None), Course.start_date.asc(), Course.id.desc())
    return [c.to_summary() for c in q.all()]


def get_public_course(id_or_slug, *, can_edit) -> Course:
    course = get_course(id_or_slug)
    if not course.is_public and not can_edit:
        raise ServiceError(404, "not_found")
    return course


# ---------------------------------------------------------------- write
def create_course(data) -> Course:
    course = Course(status="draft")
    _apply_fields(course, data)
    _validate(course)
    db.session.add(course)
    _commit_or_slug_conflict()
    return course


def update_course(course, data) -> Course:
    _apply_fields(course, data)
    _validate(course)
    _commit_or_slug_conflict()
    return course


def delete_course(course):
    template_keys = [
        getattr(course, key_col)
        for key_col, _ in TEMPLATE_KINDS.values()
        if getattr(course, key_col)
    ]
    db.session.delete(course)
    try:
        db.session.commit()
    except IntegrityError:
        # A cohort (or other row) still references this course (FK RESTRICT).
        db.session.rollback()
        raise ServiceError(409, "course_in_use") from None
    for key in template_keys:  # best-effort S3 cleanup after the DB delete
        with contextlib.suppress(S3StorageError):
            delete_object(key)


# ---------------------------------------------------------------- templates
def _template_columns(kind):
    if kind not in TEMPLATE_KINDS:
        raise ServiceError(400, "invalid_kind")
    return TEMPLATE_KINDS[kind]


def upload_template(course, kind, file, *, content_length, max_bytes) -> str:
    key_col, name_col = _template_columns(kind)
    if file is None or not file.filename:
        raise ServiceError(400, "file_required")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _ALLOWED_EXT:
        raise ServiceError(400, "unsupported_file_type", allowed=sorted(_ALLOWED_EXT))
    if content_length and content_length > max_bytes:
        raise ServiceError(413, "file_too_large", max_bytes=max_bytes)

    key = build_key("courses", str(course.id), f"{kind}_template{ext}")
    content_type = file.mimetype or mimetypes.guess_type(file.filename)[0]
    try:
        upload_fileobj(file.stream, key, content_type)
    except S3StorageError:
        raise ServiceError(502, "storage_error") from None

    setattr(course, key_col, key)
    setattr(course, name_col, file.filename)
    db.session.commit()
    return file.filename


def read_template(course, kind):
    """Return (bytes, content_type, download_name) for a template file."""
    key_col, name_col = _template_columns(kind)
    key = getattr(course, key_col)
    if not key:
        raise ServiceError(404, "not_found")
    try:
        body, content_type = download_stream(key)
        data = body.read()
    except S3StorageError:
        raise ServiceError(502, "storage_error") from None
    name = getattr(course, name_col) or os.path.basename(key)
    mimetype = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    return data, mimetype, name


def delete_template(course, kind):
    key_col, name_col = _template_columns(kind)
    key = getattr(course, key_col)
    if key:
        try:
            delete_object(key)
        except S3StorageError:
            raise ServiceError(502, "storage_error") from None
        setattr(course, key_col, None)
        setattr(course, name_col, None)
        db.session.commit()
