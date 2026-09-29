"""A module locked until its class date is locked everywhere, not just on the lesson screen."""
from datetime import timedelta

import pytest

from app.models import (
    Assignment,
    ClassSession,
    CourseLesson,
    CourseTopic,
    Enrollment,
    Exam,
    ExamOption,
    ExamQuestion,
    LessonMaterial,
)
from app.services.learning.path import today


@pytest.fixture
def locked(db, make_student, make_course, make_cohort):
    """A student enrolled in a cohort whose only module meets tomorrow, with content in it."""
    account, headers = make_student()
    course = make_course()
    cohort = make_cohort(course=course)
    db.session.add(Enrollment(cohort_id=cohort.id, student_id=account.actor_id,
                              course_id=course.id, status="active"))
    module = CourseTopic(course_id=course.id, name_mn="Модуль")
    db.session.add(module)
    db.session.flush()
    lesson = CourseLesson(topic_id=module.id, name_mn="Хичээл")
    session = ClassSession(cohort_id=cohort.id, topic_id=module.id,
                           session_date=today() + timedelta(days=1), start_time="18:00")
    db.session.add_all([lesson, session])
    db.session.flush()
    material = LessonMaterial(lesson_id=lesson.id, title="Slides", type="file",
                              file_key="courses/x.pdf", file_name="x.pdf", size_bytes=1)
    quiz = Exam(course_id=course.id, lesson_id=lesson.id, name_mn="Quiz")
    assignment = Assignment(cohort_id=cohort.id, lesson_id=lesson.id, title_mn="Даалгавар")
    db.session.add_all([material, quiz, assignment])
    db.session.flush()
    question = ExamQuestion(exam_id=quiz.id, question="?")
    db.session.add(question)
    db.session.flush()
    db.session.add_all([ExamOption(question_id=question.id, answer="A", is_correct=True),
                        ExamOption(question_id=question.id, answer="B", sort_order=1)])
    db.session.commit()
    return {"headers": headers, "session": session, "material": material.id,
            "quiz": quiz.id, "assignment": assignment.id}


def _calls(ids):
    return [
        ("get", f"/me/materials/{ids['material']}/download", None),
        ("post", f"/me/quizzes/{ids['quiz']}/attempts", None),
        ("get", f"/me/assignments/{ids['assignment']}", None),
        ("post", f"/me/assignments/{ids['assignment']}/submissions",
         {"link": "https://example.com/hw"}),
    ]


def test_every_way_in_is_locked_before_the_class_date(client, locked):
    for method, url, body in _calls(locked):
        resp = getattr(client, method)(url, headers=locked["headers"], json=body)
        assert (resp.status_code, resp.get_json()["error"]) == (409, "lesson_locked"), url


def test_it_opens_on_the_class_date(client, db, locked, monkeypatch):
    locked["session"].session_date = today()
    db.session.commit()
    monkeypatch.setattr("app.services.learning.materials.presigned_url",
                        lambda key, expires=300: "https://s3.test/x")
    for method, url, body in _calls(locked):
        resp = getattr(client, method)(url, headers=locked["headers"], json=body)
        assert resp.status_code in (200, 201), (url, resp.get_json())
