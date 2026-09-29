"""Reading and grading submissions — the cohort's teacher, or ``cohort:manage`` staff."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy import func

from app.extensions import db
from app.models import AssignmentSubmission, Student, StudentFile
from app.timeutil import utcnow

from ..errors import ServiceError
from ..params import get_by_id
from .authoring import assignment_for_staff
from .files import download_payload
from .serializers import number, person_dict, submission_dict

MAX_FEEDBACK = 5000


def _student(student_id) -> dict | None:
    return person_dict(db.session.get(Student, student_id))


def _staff_submission_dict(sub, *, version_count=None) -> dict:
    data = submission_dict(sub)
    data.update(assignment_id=sub.assignment_id, student=_student(sub.student_id),
                graded_at=data["feedback"]["created_at"] if data["feedback"] else None)
    if version_count is not None:
        data["version_count"] = version_count
    return data


def list_submissions(account, assignment_id) -> dict:
    """Each student's latest version, with how many versions they have sent."""
    assignment = assignment_for_staff(account, assignment_id)
    latest = (db.session.query(AssignmentSubmission.student_id,
                               func.max(AssignmentSubmission.version).label("version"),
                               func.count(AssignmentSubmission.id).label("versions"))
              .filter(AssignmentSubmission.assignment_id == assignment.id)
              .group_by(AssignmentSubmission.student_id).subquery())
    rows = (db.session.query(AssignmentSubmission, latest.c.versions)
            .join(latest, (AssignmentSubmission.student_id == latest.c.student_id)
                  & (AssignmentSubmission.version == latest.c.version))
            .filter(AssignmentSubmission.assignment_id == assignment.id)
            .order_by(AssignmentSubmission.submitted_at.desc(), AssignmentSubmission.id.desc())
            .all())
    return {
        "assignment_id": assignment.id,
        "max_score": number(assignment.max_score),
        "count": len(rows),
        "submissions": [_staff_submission_dict(sub, version_count=n) for sub, n in rows],
    }


def submission_for_staff(account, submission_id):
    sub = get_by_id(AssignmentSubmission, submission_id)
    if sub is None:
        raise ServiceError(404, "submission_not_found")
    try:
        assignment = assignment_for_staff(account, sub.assignment_id)
    except ServiceError:
        raise ServiceError(404, "submission_not_found") from None
    return sub, assignment


def get_submission(account, submission_id) -> dict:
    """One version, plus every version that student sent (newest first)."""
    sub, _ = submission_for_staff(account, submission_id)
    history = (AssignmentSubmission.query
               .filter_by(assignment_id=sub.assignment_id, student_id=sub.student_id)
               .order_by(AssignmentSubmission.version.desc()).all())
    data = _staff_submission_dict(sub, version_count=len(history))
    data["history"] = [submission_dict(h) for h in history]
    return data


def _score(value, max_score):
    if value is None or isinstance(value, bool):
        raise ServiceError(400, "invalid_score")
    try:
        score = Decimal(str(value))
    except InvalidOperation:
        raise ServiceError(400, "invalid_score") from None
    if not score.is_finite() or score < 0 or (max_score is not None and score > max_score):
        raise ServiceError(400, "invalid_score", max_score=number(max_score))
    if score != score.quantize(Decimal("0.01")) or score > Decimal("9999.99"):
        raise ServiceError(400, "invalid_score", max_score=number(max_score))
    return score


def review(account, submission_id, data) -> dict:
    sub, assignment = submission_for_staff(account, submission_id)
    feedback = data.get("feedback")
    if not isinstance(feedback, str) or not feedback.strip():
        raise ServiceError(400, "feedback_required")
    if len(feedback.strip()) > MAX_FEEDBACK:
        raise ServiceError(400, "feedback_too_long", max_length=MAX_FEEDBACK)
    sub.score = _score(data.get("score"), assignment.max_score)
    sub.feedback = feedback.strip()
    sub.status = "reviewed"
    # A staff reviewer has no teacher profile to show as the mentor.
    sub.graded_by_teacher_id = account.actor_id if account.actor_type == "teacher" else None
    sub.graded_at = utcnow()
    db.session.commit()
    return _staff_submission_dict(sub)


def submission_file(account, submission_id) -> dict:
    sub, _ = submission_for_staff(account, submission_id)
    student_file = db.session.get(StudentFile, sub.file_id) if sub.file_id else None
    if student_file is None:
        raise ServiceError(404, "file_not_found")
    return download_payload(student_file)
