"""Shared fixtures and builders for the learning (modules / lessons / materials) tests."""
import io
import sys
import types
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.models import (
    ClassSession,
    CourseLesson,
    CourseTopic,
    Enrollment,
    LessonMaterial,
    LessonProgress,
)
from app.storage import S3StorageError

PAST = date(2026, 1, 5)
FUTURE = date.today() + timedelta(days=30)


def add(db, row):
    db.session.add(row)
    db.session.commit()
    return row


def module(db, course, name="Модуль", sort_order=0, **kw):
    return add(db, CourseTopic(course_id=course.id, name_mn=name, sort_order=sort_order, **kw))


def lesson(db, topic, name="Хичээл", sort_order=0, **kw):
    return add(db, CourseLesson(topic_id=topic.id, name_mn=name, sort_order=sort_order, **kw))


def material(db, lesson_row, title="Slides", cohort=None, sort_order=0, **kw):
    values = {"type": "file", "file_key": f"k/{title}", "file_name": f"{title}.pdf",
              "content_type": "application/pdf", "size_bytes": 1234}
    values.update(kw)
    return add(db, LessonMaterial(lesson_id=lesson_row.id, title=title, sort_order=sort_order,
                                  cohort_id=cohort.id if cohort else None, **values))


def session(db, cohort, topic, day, start="09:00"):
    return add(db, ClassSession(cohort_id=cohort.id, topic_id=topic.id, session_date=day,
                                start_time=start))


def complete(db, enrollment, lesson_row):
    return add(db, LessonProgress(enrollment_id=enrollment.id, lesson_id=lesson_row.id,
                                  completed=True))


def enroll(db, cohort, account, status="active"):
    return add(db, Enrollment(cohort_id=cohort.id, student_id=account.actor_id,
                              course_id=cohort.course_id, status=status))


@pytest.fixture
def world(db, make_course, make_cohort, make_student):
    """A published course, a cohort and an actively enrolled student ("Болд Батаа")."""
    course = make_course(slug="ai-leaders", title_mn="AI удирдагч", title_en="AI Leaders",
                         description_mn="Тайлбар", banner_image_url="https://img/x.png")
    cohort = make_cohort(course)
    account, headers = make_student(first_name="Болд", last_name="Батаа")
    return SimpleNamespace(course=course, cohort=cohort, account=account, headers=headers,
                           enrollment=enroll(db, cohort, account))


@pytest.fixture
def editor(make_staff):
    return make_staff("content_marketing")[1]


def stub_service(monkeypatch, module_name, **functions):
    """Stand in for another area's service module (``app.services.<module_name>``)."""
    fake = types.ModuleType(f"app.services.{module_name}")
    for name, fn in functions.items():
        setattr(fake, name, fn)
    monkeypatch.setitem(sys.modules, f"app.services.{module_name}", fake)
    return fake


class FakeS3:
    """In-memory replacement for the storage names the materials service imports."""

    def __init__(self):
        self.objects = {}
        self.fail = set()
        self.deleted = []

    def _check(self, op):
        if op in self.fail:
            raise S3StorageError(f"{op} failed")

    def upload_fileobj(self, fileobj, key, content_type=None):
        self._check("upload")
        self.objects[key] = (fileobj.read(), content_type)

    def presigned_url(self, key, expires=300):
        self._check("presign")
        return f"https://s3.test/{key}?expires={expires}"

    def delete_object(self, key):
        self.deleted.append(key)
        self._check("delete")
        self.objects.pop(key, None)


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    for name in ("upload_fileobj", "presigned_url", "delete_object"):
        monkeypatch.setattr(f"app.services.learning.materials.{name}", getattr(fake, name))
    return fake


def upload(client, headers, lesson_id, data=b"%PDF-1.4", filename="slides.pdf", **form):
    form["file"] = (io.BytesIO(data), filename)
    return client.post(f"/admin/lessons/{lesson_id}/materials", headers=headers, data=form,
                       content_type="multipart/form-data")
