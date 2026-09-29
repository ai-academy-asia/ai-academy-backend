"""The student side of homework: read an assignment, (re)submit it (contract §2.6).

Assignments are cohort-scoped, so an assignment outside the student's active
cohorts answers 404 ``assignment_not_found`` rather than 403 — it does not exist
for them.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Assignment, AssignmentSubmission, Enrollment, StudentFile
from app.timeutil import LOCAL_TZ, utcnow

from ..errors import ServiceError
from ..params import get_by_id
from .serializers import assignment_dict, submission_dict

MAX_DESCRIPTION = 5000
MAX_LINK = 1000


def local_today():
    """Due dates are Ulaanbaatar calendar days, not UTC ones."""
    return datetime.now(LOCAL_TZ).date()


def latest_submission(assignment_id, student_id):
    return (AssignmentSubmission.query
            .filter_by(assignment_id=assignment_id, student_id=student_id)
            .order_by(AssignmentSubmission.version.desc()).first())


def _is_enrolled(student_id, cohort_id) -> bool:
    return db.session.query(
        Enrollment.query.filter_by(student_id=student_id, cohort_id=cohort_id,
                                   status="active").exists()
    ).scalar()


def visible_assignment(student_id, assignment_id) -> Assignment:
    assignment = get_by_id(Assignment, assignment_id)
    if (assignment is None or not assignment.is_active
            or not _is_enrolled(student_id, assignment.cohort_id)):
        raise ServiceError(404, "assignment_not_found")
    return assignment


def get_for_student(student_id, assignment_id) -> dict:
    assignment = visible_assignment(student_id, assignment_id)
    return assignment_dict(assignment, latest_submission(assignment.id, student_id))


def assignment_for_lesson(student_id, enrollment, lesson) -> dict | None:
    """The lesson's active assignment in the enrollment's cohort, or None."""
    assignment = (Assignment.query
                  .filter_by(cohort_id=enrollment.cohort_id, lesson_id=lesson.id,
                             is_active=True)
                  .order_by(Assignment.id).first())
    if assignment is None:
        return None
    return assignment_dict(assignment, latest_submission(assignment.id, student_id))


# ---------------------------------------------------------------- submit
def _clean_text(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ServiceError(400, "invalid_field")
    return value.strip() or None


def _valid_link(link):
    if link is None:
        return None
    parsed = urlparse(link)
    if len(link) > MAX_LINK or parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ServiceError(400, "invalid_link")
    return link


def _own_file(student_id, raw_id):
    if raw_id is None:
        return None
    student_file = get_by_id(StudentFile, raw_id)
    if student_file is None or student_file.student_id != student_id:
        raise ServiceError(404, "file_not_found")
    return student_file


def submit(student_id, assignment_id, data) -> dict:
    """A new submission version. History is kept; nothing is overwritten."""
    assignment = visible_assignment(student_id, assignment_id)
    link = _valid_link(_clean_text(data.get("link")))
    description = _clean_text(data.get("description"))
    if description and len(description) > MAX_DESCRIPTION:
        raise ServiceError(400, "description_too_long", max_length=MAX_DESCRIPTION)
    student_file = _own_file(student_id, data.get("file_id"))
    if link is None and student_file is None:
        raise ServiceError(400, "submission_empty")
    if assignment.due_date is not None and local_today() > assignment.due_date:
        raise ServiceError(409, "past_due")

    # Two taps in flight race for the same version; the unique constraint
    # decides, and the loser simply takes the next number.
    for _ in range(3):
        current = (db.session.query(func.max(AssignmentSubmission.version))
                   .filter_by(assignment_id=assignment.id, student_id=student_id)
                   .scalar()) or 0
        sub = AssignmentSubmission(
            assignment_id=assignment.id, student_id=student_id, version=current + 1,
            submission_url=link, note=description,
            file_id=student_file.id if student_file else None,
            status="submitted", submitted_at=utcnow(),
        )
        db.session.add(sub)
        try:
            db.session.commit()
            return submission_dict(sub)
        except IntegrityError:
            db.session.rollback()
    raise ServiceError(409, "submission_conflict")
