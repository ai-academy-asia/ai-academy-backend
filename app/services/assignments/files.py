"""Student uploads (contract §2.8): private S3 objects handed back via pre-signed URLs."""
from __future__ import annotations

import mimetypes
import os
import uuid
from datetime import timedelta

from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import StudentFile
from app.storage import S3StorageError, build_key, presigned_url, upload_fileobj
from app.timeutil import iso, utcnow

from ..errors import ServiceError
from ..params import get_by_id
from .serializers import file_dict

ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip",
    ".png", ".jpg", ".jpeg",
}
MAX_FILE_BYTES = 20 * 1024 * 1024
URL_TTL_SECONDS = 300


def _size_of(stream) -> int:
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


def _key_name(filename, ext) -> str:
    # secure_filename drops non-ASCII (Cyrillic names vanish entirely); the
    # original name is kept on the row, the key only needs to be safe.
    stem = secure_filename(os.path.splitext(filename)[0])[:150] or "file"
    return f"{uuid.uuid4().hex}_{stem}{ext}"


def upload(student_id, file, *, content_length=None) -> dict:
    if file is None or not file.filename:
        raise ServiceError(400, "file_required")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ServiceError(400, "unsupported_file_type", allowed=sorted(ALLOWED_EXTENSIONS))
    # Content-Length covers the whole multipart body — a cheap early reject;
    # the stream's own size is the real check.
    if content_length and content_length > MAX_FILE_BYTES + 64 * 1024:
        raise ServiceError(413, "file_too_large", max_bytes=MAX_FILE_BYTES)
    size = _size_of(file.stream)
    if size > MAX_FILE_BYTES:
        raise ServiceError(413, "file_too_large", max_bytes=MAX_FILE_BYTES)
    if size == 0:
        raise ServiceError(400, "file_required")

    content_type = mimetypes.guess_type(file.filename)[0] or file.mimetype
    key = build_key("students", str(student_id), _key_name(file.filename, ext))
    try:
        upload_fileobj(file.stream, key, content_type)
    except S3StorageError:
        raise ServiceError(502, "storage_error") from None

    row = StudentFile(student_id=student_id, file_key=key, file_name=file.filename[:255],
                      content_type=content_type, size_bytes=size)
    db.session.add(row)
    db.session.commit()
    return file_dict(row)


def download_payload(student_file) -> dict:
    """``{url, expires_at, file_name, size_bytes}`` — the §2.4 download shape."""
    try:
        url = presigned_url(student_file.file_key, expires=URL_TTL_SECONDS)
    except S3StorageError:
        raise ServiceError(503, "storage_error") from None
    return {"url": url, "expires_at": iso(utcnow() + timedelta(seconds=URL_TTL_SECONDS)),
            "file_name": student_file.file_name, "size_bytes": student_file.size_bytes}


def download_own(student_id, file_id) -> dict:
    student_file = get_by_id(StudentFile, file_id)
    if student_file is None or student_file.student_id != student_id:
        raise ServiceError(404, "file_not_found")
    return download_payload(student_file)
