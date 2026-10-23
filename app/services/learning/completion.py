"""When a lesson counts as done, and the order lessons open in.

A lesson is completed by ``POST /complete``, by saving a note on it, or by
attending (present/late) the class session it is taught at. Completion is sticky:
a later correction of the attendance does not undo it.

Lessons open in course order: one behind an uncompleted earlier lesson answers
``409 lesson_out_of_order`` — unless its own class day has come, so a student
sitting in the class is never shut out of it.
"""
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Enrollment, LessonProgress
from app.timeutil import utcnow

from ..errors import ServiceError
from . import path

ATTENDED = ("present", "late")


def mark_completed(enrollment, lesson_id) -> None:
    """Record the lesson as completed and refresh the enrollment's progress. No commit."""
    row = LessonProgress.query.filter_by(enrollment_id=enrollment.id, lesson_id=lesson_id).first()
    if row is None:
        row = LessonProgress(enrollment_id=enrollment.id, lesson_id=lesson_id)
        try:
            with db.session.begin_nested():
                db.session.add(row)
        except IntegrityError:
            # A parallel request inserted it first.
            row = LessonProgress.query.filter_by(
                enrollment_id=enrollment.id, lesson_id=lesson_id).one()
    if not row.completed:
        now = utcnow()
        row.completed = True
        row.completed_at = now
        row.watched_at = row.watched_at or now
    db.session.flush()
    enrollment.progress_pct = path.course_progress(enrollment)["percent"]


def on_attended(session, student_id, status) -> None:
    """Attending the class a lesson is taught at completes that lesson. No commit."""
    if session.lesson_id is None or status not in ATTENDED:
        return
    enrollment = Enrollment.query.filter_by(
        cohort_id=session.cohort_id, student_id=student_id, status="active").first()
    if enrollment is not None:
        mark_completed(enrollment, session.lesson_id)


def gated_ids(content, done, classes) -> set:
    """Lessons behind an uncompleted earlier one, bar those whose own class day has come."""
    gated, behind = set(), False
    for _, lessons in content:
        for lesson in lessons:
            session = classes.get(lesson.id)
            if behind and (session is None or path.is_locked(session)):
                gated.add(lesson.id)
            behind = behind or lesson.id not in done
    return gated


def course_gates(course_id, enrollment) -> set:
    content = path.ordered_content(course_id)
    ids = [lesson.id for _, lessons in content for lesson in lessons]
    classes = path.lesson_sessions(enrollment.cohort_id, ids)
    return gated_ids(content, path.completed_ids(enrollment.id), classes)


def ensure_in_order(lesson, enrollment) -> None:
    if lesson.id in course_gates(lesson.topic.course_id, enrollment):
        raise ServiceError(409, "lesson_out_of_order")
