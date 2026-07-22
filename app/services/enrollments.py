"""Enrollment domain logic: student self-enroll, staff enroll, roster, cancel."""
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Enrollment, Student

from .errors import ServiceError


def enroll(cohort, student_id, *, require_open, created_via, admin_id=None) -> Enrollment:
    if db.session.get(Student, student_id) is None:
        raise ServiceError(404, "student_not_found")
    if require_open and cohort.status != "open":
        raise ServiceError(409, "cohort_not_open")
    if cohort.status == "draft":
        raise ServiceError(409, "cohort_not_open")

    existing = Enrollment.query.filter_by(cohort_id=cohort.id, student_id=student_id).first()
    if existing is not None:
        if existing.status == "active":
            raise ServiceError(409, "already_enrolled")
        existing.status = "active"  # re-activate a cancelled enrollment
        db.session.commit()
        return existing

    if cohort.seats_available == 0:
        raise ServiceError(409, "cohort_full")
    enrollment = Enrollment(
        cohort_id=cohort.id, student_id=student_id, status="active",
        course_id=cohort.course_id, created_via=created_via, created_by_admin_id=admin_id,
    )
    db.session.add(enrollment)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ServiceError(409, "already_enrolled") from None
    return enrollment


def cancel(cohort, student_id):
    enrollment = Enrollment.query.filter_by(
        cohort_id=cohort.id, student_id=student_id, status="active"
    ).first()
    if enrollment is None:
        raise ServiceError(404, "not_enrolled")
    enrollment.status = "cancelled"
    db.session.commit()


def roster(cohort):
    return Enrollment.query.filter_by(cohort_id=cohort.id, status="active").all()


def remove(cohort_id, student_id):
    enrollment = Enrollment.query.filter_by(cohort_id=cohort_id, student_id=student_id).first()
    if enrollment is None:
        raise ServiceError(404, "not_enrolled")
    enrollment.status = "cancelled"
    db.session.commit()
