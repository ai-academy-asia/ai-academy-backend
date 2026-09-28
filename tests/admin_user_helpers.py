"""Shared fixtures and helpers for /admin/students and /admin/teachers tests."""
import pytest

from app.models import Student, Teacher

SEGMENTS = ["students", "teachers"]
MODELS = {"students": Student, "teachers": Teacher}


def _fresh(db, model, pk):
    db.session.expire_all()
    return db.session.get(model, pk)


@pytest.fixture
def make_actor(make_student, make_teacher):
    def _make(segment, **kwargs):
        maker = make_student if segment == "students" else make_teacher
        return maker(**kwargs)

    return _make


@pytest.fixture
def sales_headers(make_staff):
    return make_staff("sales_enrollment")[1]
