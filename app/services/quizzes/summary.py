"""Quiz state other areas read: the lesson-detail summary and certificate eligibility."""
from sqlalchemy import func

from app.extensions import db
from app.models import Exam, ExamQuestion, StudentExam

from . import payloads
from .attempts import finished_count, open_attempt_for


def _has_questions():
    return db.session.query(ExamQuestion.id).filter(ExamQuestion.exam_id == Exam.id).exists()


def summary(student_id, quiz) -> dict:
    """The §2.7 summary of one quiz for one student."""
    used = finished_count(student_id, quiz.id)
    open_attempt = open_attempt_for(student_id, quiz.id)
    latest = (
        StudentExam.query.filter(
            StudentExam.exam_id == quiz.id, StudentExam.student_id == student_id,
            StudentExam.completed_at.isnot(None),
        )
        .order_by(StudentExam.completed_at.desc(), StudentExam.id.desc())
        .first()
    )
    return {
        "id": quiz.id,
        "title": payloads.title(quiz),
        "question_count": len(quiz.questions),
        "pass_percent": quiz.pass_percent,
        "is_required": quiz.is_required,
        "attempts_used": used,
        "attempts_left": (
            None if quiz.max_attempts is None else max(quiz.max_attempts - used, 0)
        ),
        "open_attempt_id": open_attempt.id if open_attempt else None,
        "last_result": payloads.last_result(latest) if latest else None,
    }


def quiz_summary_for_lesson(student_id, lesson):
    """The lesson's quiz summary (``quiz`` in the lesson detail), or ``None``.

    The active quiz with ``lesson_id == lesson.id`` and at least one question —
    lowest id when there are several.
    """
    quiz = (
        Exam.query.filter(Exam.lesson_id == lesson.id, Exam.is_active.is_(True),
                          _has_questions())
        .order_by(Exam.id)
        .first()
    )
    return summary(student_id, quiz) if quiz else None


def required_quizzes_passed(student_id, course_id) -> dict:
    """``{"passed", "required"}`` over the course's active, required quizzes.

    A quiz with no questions cannot be taken, so it is not required yet.
    """
    required_ids = [
        row.id for row in db.session.query(Exam.id).filter(
            Exam.course_id == course_id, Exam.is_active.is_(True),
            Exam.is_required.is_(True), _has_questions(),
        )
    ]
    if not required_ids:
        return {"passed": 0, "required": 0}
    passed = (
        db.session.query(func.count(func.distinct(StudentExam.exam_id)))
        .filter(StudentExam.student_id == student_id,
                StudentExam.exam_id.in_(required_ids),
                StudentExam.is_passed.is_(True))
        .scalar()
    )
    return {"passed": passed or 0, "required": len(required_ids)}
