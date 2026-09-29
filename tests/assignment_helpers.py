"""Shared fixtures for the assignment tests.

``hw`` builds a course with one lesson, a cohort taught by a teacher and one
enrolled student; ``make_assignment`` / ``make_submission`` / ``make_file`` add
rows; ``s3`` stubs storage where the assignment services import it. Each test
module binds the fixtures it uses by name (``hw = assignment_helpers.hw``).
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.models import (
    Assignment,
    AssignmentSubmission,
    CourseLesson,
    CourseTopic,
    Enrollment,
    LessonMaterial,
    StudentFile,
)
from app.services.assignments.student import local_today


def today():
    return local_today()


def days(n):
    return today() + timedelta(days=n)


@pytest.fixture
def s3(monkeypatch):
    calls = SimpleNamespace(uploaded=[], deleted=[], signed=[], fail=None)

    def _upload(fileobj, key, content_type=None):
        if calls.fail == "upload":
            from app.storage import S3StorageError
            raise S3StorageError("boom")
        calls.uploaded.append((key, content_type, fileobj.read()))

    def _presign(key, expires=300):
        if calls.fail == "presign":
            from app.storage import S3StorageError
            raise S3StorageError("boom")
        calls.signed.append(key)
        return f"https://s3.test/{key}?sig=1"

    def _delete(key):
        if calls.fail == "delete":
            from app.storage import S3StorageError
            raise S3StorageError("boom")
        calls.deleted.append(key)

    monkeypatch.setattr("app.services.assignments.files.upload_fileobj", _upload)
    monkeypatch.setattr("app.services.assignments.files.presigned_url", _presign)
    monkeypatch.setattr("app.services.assignments.cleanup.delete_object", _delete)
    return calls


def enroll(db, cohort, student_id, status="active"):
    row = Enrollment(cohort_id=cohort.id, student_id=student_id,
                     course_id=cohort.course_id, status=status)
    db.session.add(row)
    db.session.commit()
    return row


def add_lesson(db, course):
    topic = CourseTopic(course_id=course.id, name_mn="Модуль")
    db.session.add(topic)
    db.session.flush()
    lesson = CourseLesson(topic_id=topic.id, name_mn="Хичээл")
    db.session.add(lesson)
    db.session.commit()
    return lesson


@pytest.fixture
def hw(db, make_course, make_cohort, make_student, make_teacher):
    course = make_course()
    teacher, teacher_headers = make_teacher(first_name="Дорж", last_name="Бат")
    cohort = make_cohort(course=course, teacher_id=teacher.actor_id)
    student, student_headers = make_student(first_name="Болд", last_name="Батаа")
    enroll(db, cohort, student.actor_id)
    lesson = add_lesson(db, course)
    material = LessonMaterial(lesson_id=lesson.id, title="Slides", type="file",
                              file_key="k/slides.pdf", file_name="slides.pdf",
                              content_type="application/pdf", size_bytes=1234)
    db.session.add(material)
    db.session.commit()
    return SimpleNamespace(
        course=course, cohort=cohort, lesson=lesson, material=material,
        teacher=teacher, teacher_headers=teacher_headers,
        student=student, student_headers=student_headers, sid=student.actor_id,
    )


@pytest.fixture
def make_assignment(db):
    def _make(cohort, **fields):
        values = {"cohort_id": cohort.id, "title_mn": "Даалгавар", "max_score": 100,
                  "is_active": True}
        values.update(fields)
        row = Assignment(**values)
        db.session.add(row)
        db.session.commit()
        return row

    return _make


@pytest.fixture
def make_file(db):
    def _make(student_id, name="report.pdf", **fields):
        values = {"student_id": student_id, "file_key": f"students/{student_id}/x_{name}",
                  "file_name": name, "content_type": "application/pdf", "size_bytes": 10}
        values.update(fields)
        row = StudentFile(**values)
        db.session.add(row)
        db.session.commit()
        return row

    return _make


@pytest.fixture
def make_submission(db):
    def _make(assignment, student_id, version=1, **fields):
        values = {"assignment_id": assignment.id, "student_id": student_id,
                  "version": version, "submission_url": "https://example.com/work",
                  "status": "submitted"}
        values.update(fields)
        row = AssignmentSubmission(**values)
        db.session.add(row)
        db.session.commit()
        return row

    return _make
