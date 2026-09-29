"""Shared fixtures and helpers for the quiz tests (``test_quiz*.py``).

Each test module binds the fixtures it uses by name (``make_quiz = quiz_helpers.make_quiz``).
"""
import pytest

from app.models import (
    CourseLesson,
    CourseTopic,
    Enrollment,
    Exam,
    ExamOption,
    ExamQuestion,
)

# Words that exist only in the answer key; they must never appear in a student
# payload for a question the student has not answered.
KEY_FIELDS = ("is_correct", "correct", "correct_option_id", "explanation")


def add_lesson(db, course, name="Lesson"):
    topic = CourseTopic(course_id=course.id, name_mn="Module")
    db.session.add(topic)
    db.session.flush()
    lesson = CourseLesson(topic_id=topic.id, name_mn=name)
    db.session.add(lesson)
    db.session.commit()
    return lesson


def add_questions(db, quiz, count, correct_index=1):
    """``count`` questions with 3 options each; option ``correct_index`` is right."""
    for n in range(count):
        question = ExamQuestion(
            exam_id=quiz.id, question=f"Q{n + 1}?", explanation=f"because {n + 1}",
            sort_order=n,
        )
        db.session.add(question)
        db.session.flush()
        for j in range(3):
            db.session.add(ExamOption(
                question_id=question.id, answer=f"opt {n + 1}.{j}",
                is_correct=(j == correct_index), sort_order=j,
            ))
    db.session.commit()
    db.session.expire(quiz)


def key(db, question_id):
    """(correct option id, a wrong option id) for a question."""
    options = ExamOption.query.filter_by(question_id=question_id).order_by(ExamOption.id).all()
    right = next(o.id for o in options if o.is_correct)
    wrong = next(o.id for o in options if not o.is_correct)
    return right, wrong


@pytest.fixture
def make_quiz(db, make_course):
    """``make_quiz(course=None, questions=3, lesson=None, **fields)`` -> Exam."""

    def _make(course=None, questions=3, lesson=None, **fields):
        course = course or make_course()
        values = {"course_id": course.id, "name_mn": "Шалгалт", "name_en": "Quiz",
                  "pass_percent": 70, "lesson_id": lesson.id if lesson else None}
        values.update(fields)
        quiz = Exam(**values)
        db.session.add(quiz)
        db.session.commit()
        if questions:
            add_questions(db, quiz, questions)
        return quiz

    return _make


@pytest.fixture
def enroll(db, make_cohort):
    """``enroll(student_account, course, status="active")`` -> Enrollment."""

    def _enroll(account, course, status="active"):
        cohort = make_cohort(course=course)
        row = Enrollment(cohort_id=cohort.id, student_id=account.actor_id,
                         course_id=course.id, status=status)
        db.session.add(row)
        db.session.commit()
        return row

    return _enroll


@pytest.fixture
def learner(make_student, make_course, make_quiz, enroll):
    """An enrolled student and a 3-question quiz: (headers, quiz, account)."""
    account, headers = make_student()
    course = make_course()
    quiz = make_quiz(course=course)
    enroll(account, course)
    return headers, quiz, account


def start(client, headers, quiz_id):
    return client.post(f"/me/quizzes/{quiz_id}/attempts", headers=headers)


def answer(client, headers, attempt_id, question_id, option_id):
    return client.post(f"/me/quiz-attempts/{attempt_id}/answers", headers=headers,
                       json={"question_id": question_id, "option_id": option_id})


def finish(client, headers, attempt_id):
    return client.post(f"/me/quiz-attempts/{attempt_id}/finish", headers=headers)


def run_attempt(client, db, headers, quiz_id, right_count):
    """Start, answer the first ``right_count`` questions right and the rest wrong, finish."""
    started = start(client, headers, quiz_id).get_json()
    for n, question in enumerate(started["questions"]):
        right, wrong = key(db, question["id"])
        answer(client, headers, started["attempt_id"], question["id"],
               right if n < right_count else wrong)
    return finish(client, headers, started["attempt_id"]).get_json()


def assert_no_key(question_payload):
    """An unanswered question as served to a student carries no part of the key."""
    assert question_payload["answer"] is None
    for option in question_payload["options"]:
        assert set(option) == {"id", "text"}
    for field in KEY_FIELDS:
        assert field not in question_payload
