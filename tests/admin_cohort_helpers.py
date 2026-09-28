"""Shared fixtures and helpers for the /admin/cohorts tests."""
import pytest


def _fresh(db, model, pk):
    db.session.expire_all()
    return db.session.get(model, pk)


@pytest.fixture
def sales(make_staff):
    return make_staff("sales_enrollment")


@pytest.fixture
def payload(make_course):
    course_id = make_course().id

    def _payload(**fields):
        data = {"course_id": course_id, "name": "Corporate Leaders 2026-10",
                "start_date": "2026-10-01", "end_date": "2026-12-01"}
        data.update(fields)
        return data

    return _payload


def _enroll(client, headers, cohort_id, student_id):
    return client.post(f"/admin/cohorts/{cohort_id}/enroll", headers=headers,
                       json={"student_id": student_id})
