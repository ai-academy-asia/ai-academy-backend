"""Staff issuing, the certificate PDF on S3, student download and public verification."""
from __future__ import annotations

import os
from datetime import timedelta

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Certificate, Cohort, Course, Enrollment, Student
from app.storage import S3StorageError, build_key, presigned_url, upload_fileobj
from app.timeutil import iso, utcnow

from ..errors import ServiceError
from ..params import get_by_id, parse_id, parse_limit
from .eligibility import is_eligible, requirements

DOWNLOAD_TTL = 300  # seconds a pre-signed download link stays valid
DEFAULT_MAX_BYTES = 20 * 1024 * 1024


# ------------------------------------------------------------------- lookups
def get_certificate(cert_id) -> Certificate:
    cert = get_by_id(Certificate, cert_id)
    if cert is None:
        raise ServiceError(404, "certificate_not_found")
    return cert


def list_certificates(*, course_id=None, student_id=None, limit=None) -> list:
    q = Certificate.query
    if course_id not in (None, ""):
        q = q.filter_by(course_id=parse_id(course_id))
    if student_id not in (None, ""):
        q = q.filter_by(student_id=parse_id(student_id))
    rows = q.order_by(Certificate.issued_at.desc(), Certificate.id.desc())
    return [c.to_dict() for c in rows.limit(parse_limit(limit))]


def verify(cert_number) -> dict:
    cert = Certificate.query.filter_by(cert_number=str(cert_number), is_archived=False).first()
    if cert is None:
        raise ServiceError(404, "certificate_not_found")
    return cert.to_verify_dict()


# ------------------------------------------------------------------- issuing
def _enrollment(student_id, course_id):
    """The student's active enrollment in the course (newest cohort), or ``None``."""
    return (Enrollment.query.join(Cohort, Enrollment.cohort_id == Cohort.id)
            .filter(Enrollment.student_id == student_id, Enrollment.status == "active",
                    Cohort.course_id == course_id)
            .order_by(Cohort.start_date.desc().nullslast(), Enrollment.id.desc())
            .first())


def _next_number(year: int) -> str:
    prefix = f"AIAA-{year}-"
    last = (db.session.query(db.func.max(Certificate.cert_number))
            .filter(Certificate.cert_number.like(f"{prefix}%")).scalar())
    seq = int(last[len(prefix):]) + 1 if last and last[len(prefix):].isdigit() else 1
    return f"{prefix}{seq:05d}"


def _verify_url(cert_number: str) -> str:
    base = (current_app.config.get("PUBLIC_BASE_URL") or "").rstrip("/")
    return f"{base}/certificates/verify/{cert_number}"


def issue(student_id, course_id, *, force=False) -> Certificate:
    """Issue if the student meets the requirements (or ``force``). 409s on a duplicate."""
    for name, value in (("student_id", student_id), ("course_id", course_id)):
        if value in (None, ""):
            raise ServiceError(400, f"{name}_required")
    student = get_by_id(Student, student_id)
    if student is None:
        raise ServiceError(404, "student_not_found")
    course = get_by_id(Course, course_id)
    if course is None:
        raise ServiceError(404, "course_not_found")
    existing = Certificate.query.filter_by(student_id=student.id, course_id=course.id).first()
    if existing is not None:
        # One certificate per student per course, archived ones included (the
        # table's unique key): an archived certificate is history, not a free slot.
        raise ServiceError(409, "already_issued", certificate_id=existing.id,
                           archived=existing.is_archived)

    enrollment = _enrollment(student.id, course.id)
    reqs = requirements(student.id, course, enrollment)
    if not force and (enrollment is None or not is_eligible(reqs)):
        raise ServiceError(409, "not_eligible", requirements=reqs,
                           enrolled=enrollment is not None)

    for _ in range(5):  # a concurrent issue may take the same sequence number
        number = _next_number(utcnow().year)
        cert = Certificate(
            student_id=student.id, course_id=course.id,
            enrollment_id=enrollment.id if enrollment is not None else None,
            cert_number=number, verify_url=_verify_url(number),
            payment_cleared=reqs["payment_cleared"]["done"], issued_at=utcnow(),
        )
        db.session.add(cert)
        try:
            db.session.commit()
            return cert
        except IntegrityError:
            db.session.rollback()
            if Certificate.query.filter_by(student_id=student.id,
                                           course_id=course.id).first() is not None:
                raise ServiceError(409, "already_issued") from None
    raise ServiceError(503, "certificate_number_busy")


def archive(cert: Certificate) -> Certificate:
    cert.is_archived = True
    db.session.commit()
    return cert


# ------------------------------------------------------------------- files
def upload_file(cert: Certificate, file, *, content_length) -> Certificate:
    if file is None or not file.filename:
        raise ServiceError(400, "file_required")
    if os.path.splitext(file.filename)[1].lower() != ".pdf":
        raise ServiceError(400, "unsupported_file_type", allowed=[".pdf"])
    max_bytes = current_app.config.get("MAX_CERTIFICATE_BYTES") or DEFAULT_MAX_BYTES
    if content_length and content_length > max_bytes:
        raise ServiceError(413, "file_too_large", max_bytes=max_bytes)
    key = build_key("certificates", f"{cert.cert_number}.pdf")
    try:
        upload_fileobj(file.stream, key, "application/pdf")
    except S3StorageError:
        raise ServiceError(502, "storage_error") from None
    cert.file_key = key
    db.session.commit()
    return cert


def student_download(student_id, cert_number) -> dict:
    """A short-lived link to the student's own certificate PDF."""
    cert = Certificate.query.filter_by(
        cert_number=str(cert_number), student_id=student_id, is_archived=False).first()
    if cert is None:
        raise ServiceError(404, "certificate_not_found")
    if not cert.file_key:
        raise ServiceError(404, "certificate_file_missing")
    try:
        url = presigned_url(cert.file_key, expires=DOWNLOAD_TTL)
    except S3StorageError:
        raise ServiceError(502, "storage_error") from None
    return {"url": url, "expires_at": iso(utcnow() + timedelta(seconds=DOWNLOAD_TTL))}
