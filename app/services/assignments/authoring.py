"""Assignment authoring by the cohort's teacher, or staff with ``cohort:manage``."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import func

from app.extensions import db
from app.models import (
    Assignment,
    AssignmentSubmission,
    Cohort,
    CourseLesson,
    LessonMaterial,
)

from ..access import cohort_for_teacher
from ..errors import ServiceError
from ..params import get_by_id
from .serializers import staff_assignment_dict

MAX_SCORE_LIMIT = Decimal("9999.99")   # Numeric(6, 2)
_TEXT_FIELDS = {"title_mn": 200, "title_en": 200,
                "instructions_mn": None, "instructions_en": None}


def assignment_for_staff(account, assignment_id) -> Assignment:
    """404 both for a missing assignment and for one in a cohort not the caller's."""
    assignment = get_by_id(Assignment, assignment_id)
    if assignment is None:
        raise ServiceError(404, "assignment_not_found")
    try:
        cohort_for_teacher(account, assignment.cohort_id)
    except ServiceError:
        raise ServiceError(404, "assignment_not_found") from None
    return assignment


def _submitted_counts(assignment_ids) -> dict:
    if not assignment_ids:
        return {}
    rows = (db.session.query(AssignmentSubmission.assignment_id,
                             func.count(func.distinct(AssignmentSubmission.student_id)))
            .filter(AssignmentSubmission.assignment_id.in_(assignment_ids))
            .group_by(AssignmentSubmission.assignment_id).all())
    return dict(rows)


def _to_dict(assignment) -> dict:
    counts = _submitted_counts([assignment.id])
    return staff_assignment_dict(assignment, submitted_students=counts.get(assignment.id, 0))


# ---------------------------------------------------------------- field parsing
def _text(data, field, limit):
    value = data[field]
    if value is not None and not isinstance(value, str):
        raise ServiceError(400, "invalid_field", field=field)
    value = value.strip() if value else None
    if value and limit and len(value) > limit:
        raise ServiceError(400, "field_too_long", field=field, max_length=limit)
    return value or None


def _due_date(value):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ServiceError(400, "invalid_date", field="due_date") from None


def _max_score(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ServiceError(400, "invalid_max_score")
    try:
        score = Decimal(str(value))
    except InvalidOperation:
        raise ServiceError(400, "invalid_max_score") from None
    if not score.is_finite() or score <= 0 or score > MAX_SCORE_LIMIT:
        raise ServiceError(400, "invalid_max_score")
    return score


def _lesson_id(cohort, value):
    if value is None:
        return None
    lesson = get_by_id(CourseLesson, value)
    if lesson is None or lesson.topic.course_id != cohort.course_id:
        raise ServiceError(400, "invalid_lesson")
    return lesson.id


def _material_id(cohort, value):
    if value is None:
        return None
    material = get_by_id(LessonMaterial, value)
    lesson = db.session.get(CourseLesson, material.lesson_id) if material else None
    if (lesson is None or lesson.topic.course_id != cohort.course_id
            or material.cohort_id not in (None, cohort.id)):
        raise ServiceError(400, "invalid_attachment")
    return material.id


def _apply(assignment, cohort, data):
    for field, limit in _TEXT_FIELDS.items():
        if field in data:
            setattr(assignment, field, _text(data, field, limit))
    if "due_date" in data:
        assignment.due_date = _due_date(data["due_date"])
    if "max_score" in data:
        assignment.max_score = _max_score(data["max_score"])
    if "lesson_id" in data:
        assignment.lesson_id = _lesson_id(cohort, data["lesson_id"])
    if "attachment_material_id" in data:
        assignment.attachment_material_id = _material_id(cohort, data["attachment_material_id"])
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            raise ServiceError(400, "invalid_field", field="is_active")
        assignment.is_active = data["is_active"]
    if not assignment.title_mn:
        raise ServiceError(400, "title_mn_required")


# ---------------------------------------------------------------- CRUD
def list_for_cohort(account, cohort_id) -> list:
    cohort = cohort_for_teacher(account, cohort_id)
    rows = Assignment.query.filter_by(cohort_id=cohort.id).order_by(Assignment.id).all()
    counts = _submitted_counts([a.id for a in rows])
    return [staff_assignment_dict(a, submitted_students=counts.get(a.id, 0)) for a in rows]


def create(account, cohort_id, data) -> dict:
    cohort = cohort_for_teacher(account, cohort_id)
    teacher_id = account.actor_id if account.actor_type == "teacher" else cohort.teacher_id
    assignment = Assignment(cohort_id=cohort.id, teacher_id=teacher_id, is_active=True)
    _apply(assignment, cohort, data)
    db.session.add(assignment)
    db.session.commit()
    return _to_dict(assignment)


def get(account, assignment_id) -> dict:
    return _to_dict(assignment_for_staff(account, assignment_id))


def update(account, assignment_id, data) -> dict:
    assignment = assignment_for_staff(account, assignment_id)
    try:
        _apply(assignment, db.session.get(Cohort, assignment.cohort_id), data)
    except ServiceError:
        db.session.rollback()
        raise
    db.session.commit()
    return _to_dict(assignment)


def delete(account, assignment_id) -> str:
    """Archive (deactivate) once anyone has submitted — homework is never thrown away."""
    assignment = assignment_for_staff(account, assignment_id)
    has_submissions = db.session.query(
        AssignmentSubmission.query.filter_by(assignment_id=assignment.id).exists()
    ).scalar()
    if has_submissions:
        assignment.is_active = False
        db.session.commit()
        return "deactivated"
    db.session.delete(assignment)
    db.session.commit()
    return "deleted"
