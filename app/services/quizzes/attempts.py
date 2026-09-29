"""Student quiz attempts (contract §2.7): start/resume, answer one, finish, read.

Grading is server-side and per answer: the key for a question is revealed only in
the response to answering it, and the answer is final. Attempts belong to the
caller — another student's attempt id answers ``404 attempt_not_found``.
"""
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Exam, ExamOption, ExamQuestion, StudentExam, StudentExamAnswer
from app.timeutil import utcnow

from ..access import enrollment_for_course
from ..errors import ServiceError
from ..params import get_by_id, parse_id
from . import payloads


# ---------------------------------------------------------------- lookups
def live_quiz(quiz_id) -> Exam:
    """An active quiz with at least one question — anything else does not exist for students."""
    quiz = get_by_id(Exam, quiz_id)
    if quiz is None or not quiz.is_active or not quiz.questions:
        raise ServiceError(404, "quiz_not_found")
    return quiz


def open_attempt_for(student_id, quiz_id):
    return StudentExam.query.filter_by(
        exam_id=quiz_id, student_id=student_id, completed_at=None
    ).first()


def finished_count(student_id, quiz_id) -> int:
    return StudentExam.query.filter(
        StudentExam.exam_id == quiz_id, StudentExam.student_id == student_id,
        StudentExam.completed_at.isnot(None),
    ).count()


def _own_attempt(student_id, attempt_id, *, lock=False) -> StudentExam:
    pk = parse_id(attempt_id)
    attempt = None
    if pk is not None:
        q = StudentExam.query.filter_by(id=pk, student_id=student_id)
        attempt = (q.with_for_update() if lock else q).first()
    if attempt is None:
        raise ServiceError(404, "attempt_not_found")
    return attempt


def _answers(attempt) -> dict:
    rows = StudentExamAnswer.query.filter_by(student_exam_id=attempt.id).all()
    return {a.question_id: a for a in rows}


def _quiz_of(attempt) -> Exam:
    return db.session.get(Exam, attempt.exam_id)


# ---------------------------------------------------------------- start / resume
def start_attempt(student_id, quiz_id) -> tuple:
    """(payload, created). Resumes the open attempt instead of opening a second one."""
    quiz = live_quiz(quiz_id)
    enrollment_for_course(student_id, quiz.course_id)

    attempt = open_attempt_for(student_id, quiz.id)
    if attempt is not None:
        return payloads.open_attempt(attempt, quiz, _answers(attempt)), False

    used = finished_count(student_id, quiz.id)
    if quiz.max_attempts is not None and used >= quiz.max_attempts:
        raise ServiceError(409, "no_attempts_left",
                           attempts_used=used, max_attempts=quiz.max_attempts)

    attempt = StudentExam(exam_id=quiz.id, student_id=student_id, started_at=utcnow())
    db.session.add(attempt)
    try:
        db.session.commit()
    except IntegrityError:
        # A concurrent start won the partial unique index — resume theirs.
        db.session.rollback()
        attempt = open_attempt_for(student_id, quiz.id)
        if attempt is None:
            raise
        return payloads.open_attempt(attempt, quiz, _answers(attempt)), False
    return payloads.open_attempt(attempt, quiz, {}), True


# ---------------------------------------------------------------- answer
def answer_question(student_id, attempt_id, data) -> dict:
    attempt = _own_attempt(student_id, attempt_id, lock=True)
    if attempt.completed_at is not None:
        raise ServiceError(409, "attempt_finished")
    quiz = _quiz_of(attempt)
    enrollment_for_course(student_id, quiz.course_id)

    question = get_by_id(ExamQuestion, data.get("question_id"))
    if question is None or question.exam_id != quiz.id:
        raise ServiceError(400, "invalid_question")
    option = get_by_id(ExamOption, data.get("option_id"))
    if option is None or option.question_id != question.id:
        raise ServiceError(400, "invalid_option")
    if StudentExamAnswer.query.filter_by(
        student_exam_id=attempt.id, question_id=question.id
    ).first() is not None:
        raise ServiceError(409, "already_answered")

    answer = StudentExamAnswer(
        student_exam_id=attempt.id, question_id=question.id, option_id=option.id,
        is_correct=bool(option.is_correct), answered_at=utcnow(),
    )
    db.session.add(answer)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ServiceError(409, "already_answered") from None
    return payloads.answer_reveal(question, answer)


# ---------------------------------------------------------------- finish / read
def grade(attempt, quiz, answers) -> None:
    """Score an attempt in place. Each question counts 1; unanswered = wrong."""
    total = len(quiz.questions)
    correct = sum(1 for q in quiz.questions if q.id in answers and answers[q.id].is_correct)
    attempt.total = total
    attempt.correct_count = correct
    attempt.percent = (correct * 100) // total if total else 0
    attempt.is_passed = attempt.percent >= quiz.pass_percent
    attempt.completed_at = utcnow()


def finish_attempt(student_id, attempt_id) -> dict:
    """Idempotent: finishing a finished attempt returns its stored result."""
    attempt = _own_attempt(student_id, attempt_id, lock=True)
    quiz = _quiz_of(attempt)
    answers = _answers(attempt)
    if attempt.completed_at is None:
        grade(attempt, quiz, answers)
        db.session.commit()
    return payloads.result(attempt, quiz, answers)


def get_attempt(student_id, attempt_id) -> dict:
    attempt = _own_attempt(student_id, attempt_id)
    quiz = _quiz_of(attempt)
    answers = _answers(attempt)
    if attempt.completed_at is None:
        return payloads.open_attempt(attempt, quiz, answers)
    return payloads.result(attempt, quiz, answers)
