"""Cohort auth guard, list/get and create (/admin/cohorts)."""
from datetime import date

import admin_cohort_helpers
import pytest

from app.models import Cohort, Enrollment

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
payload = admin_cohort_helpers.payload
sales = admin_cohort_helpers.sales


# ---------------------------------------------------------------- auth
@pytest.mark.parametrize("method,path", [
    ("get", "/admin/cohorts"), ("post", "/admin/cohorts"), ("get", "/admin/cohorts/1"),
    ("patch", "/admin/cohorts/1"), ("delete", "/admin/cohorts/1"),
    ("post", "/admin/cohorts/1/enroll"), ("get", "/admin/cohorts/1/students"),
    ("delete", "/admin/cohorts/1/students/1"),
])
def test_requires_token(client, method, path):
    resp = getattr(client, method)(path, json={})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


@pytest.mark.parametrize("role", ["finance", "content_marketing"])
def test_forbidden_without_cohort_permissions(client, make_staff, make_cohort, make_student,
                                              role):
    cohort = make_cohort()
    student, _ = make_student()
    _, headers = make_staff(role)
    for method, path in [
        ("get", "/admin/cohorts"), ("post", "/admin/cohorts"),
        ("get", f"/admin/cohorts/{cohort.id}"), ("patch", f"/admin/cohorts/{cohort.id}"),
        ("delete", f"/admin/cohorts/{cohort.id}"),
        ("post", f"/admin/cohorts/{cohort.id}/enroll"),
        ("get", f"/admin/cohorts/{cohort.id}/students"),
        ("delete", f"/admin/cohorts/{cohort.id}/students/{student.actor_id}"),
    ]:
        resp = getattr(client, method)(path, json={"student_id": student.actor_id},
                                       headers=headers)
        assert resp.status_code == 403, (method, path)
        assert resp.get_json()["error"] == "forbidden"
    assert Enrollment.query.count() == 0


def test_students_and_teachers_are_forbidden(client, make_student, make_teacher):
    for _, headers in (make_student(), make_teacher()):
        assert client.get("/admin/cohorts", headers=headers).status_code == 403


# ---------------------------------------------------------------- list / get
def test_list_orders_by_start_date_undated_last(client, sales, make_cohort):
    _, headers = sales
    undated = make_cohort(start_date=None, end_date=None)
    later = make_cohort(start_date=date(2027, 1, 1), end_date=date(2027, 2, 1))
    sooner = make_cohort(start_date=date(2026, 9, 1), end_date=date(2026, 10, 1))
    body = client.get("/admin/cohorts", headers=headers).get_json()
    assert [c["id"] for c in body["cohorts"]] == [sooner.id, later.id, undated.id]


def test_list_filters(client, admin_headers, make_cohort, make_course, make_teacher,
                      make_classroom):
    course = make_course()
    teacher, _ = make_teacher()
    room = make_classroom()
    target = make_cohort(course=course, status="draft", teacher_id=teacher.actor_id,
                         classroom_id=room.id)
    make_cohort(status="open")

    def ids(query):
        body = client.get(f"/admin/cohorts?{query}", headers=admin_headers).get_json()
        return [c["id"] for c in body["cohorts"]]

    assert ids("status=draft") == [target.id]
    assert ids(f"course_id={course.id}") == [target.id]
    assert ids(f"teacher_id={teacher.actor_id}") == [target.id]
    assert ids(f"classroom_id={room.id}") == [target.id]
    assert len(ids("course_id=abc")) == 2  # non-numeric filters are ignored


def test_get_returns_detail(client, admin_headers, make_cohort, make_teacher, make_classroom):
    teacher, _ = make_teacher(first_name="Dorj", last_name="Bat")
    room = make_classroom(name="Lab", center_name="Central")
    cohort = make_cohort(teacher_id=teacher.actor_id, classroom_id=room.id, capacity=5)
    resp = client.get(f"/admin/cohorts/{cohort.id}", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == cohort.id
    assert body["teacher"] == {"id": teacher.actor_id, "name": "Dorj Bat"}
    assert body["classroom"]["name"] == "Lab"
    assert body["course"]["id"] == cohort.course_id
    assert body["seats_available"] == 5
    assert "created_at" in body and "updated_at" in body


def test_get_unknown_is_404(client, admin_headers):
    resp = client.get("/admin/cohorts/9999", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


# ---------------------------------------------------------------- create
def test_create_defaults_to_draft(client, sales, payload, make_teacher, make_classroom, db):
    _, headers = sales
    teacher, _ = make_teacher()
    room = make_classroom()
    resp = client.post("/admin/cohorts", headers=headers, json=payload(
        teacher_id=teacher.actor_id, classroom_id=room.id, capacity=12,
        meeting_days=["mon", "wed"], start_time="18:00", end_time="20:00",
        graduation_date="2026-12-05", schedule_note="Evening",
    ))
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "draft"
    assert body["meeting_days"] == ["mon", "wed"]
    assert body["graduation_date"] == "2026-12-05"
    assert body["teacher"]["id"] == teacher.actor_id
    cohort = db.session.get(Cohort, body["id"])
    assert cohort.classroom_id == room.id
    assert cohort.start_date == date(2026, 10, 1)
    assert cohort.capacity == 12


@pytest.mark.parametrize("fields,error", [
    ({"name": ""}, "name_required"),
    ({"course_id": None}, "invalid_course_id"),
    ({"course_id": 9999}, "invalid_course_id"),
    ({"status": "archived"}, "invalid_status"),
    ({"teacher_id": 9999}, "invalid_teacher_id"),
    ({"classroom_id": 9999}, "invalid_classroom_id"),
    ({"start_date": "2026-12-01", "end_date": "2026-10-01"}, "end_before_start"),
    ({"meeting_days": "mon"}, "invalid_meeting_days"),
    ({"meeting_days": ["mon", "funday"]}, "invalid_meeting_days"),
    ({"start_time": "9:00"}, "invalid_time"),
    ({"end_time": "24:00"}, "invalid_time"),
    ({"start_time": "18:00", "end_time": "18:00"}, "end_time_before_start"),
    ({"start_time": "18:00", "end_time": "09:00"}, "end_time_before_start"),
])
def test_create_validation(client, admin_headers, payload, fields, error):
    resp = client.post("/admin/cohorts", headers=admin_headers, json=payload(**fields))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == error
    assert Cohort.query.count() == 0


def test_create_invalid_date_names_field(client, admin_headers, payload):
    resp = client.post("/admin/cohorts", headers=admin_headers,
                       json=payload(end_date="December"))
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "invalid_date", "field": "end_date"}


def test_create_invalid_time_names_field(client, admin_headers, payload):
    resp = client.post("/admin/cohorts", headers=admin_headers,
                       json=payload(start_time="10:00", end_time="25:00"))
    assert resp.get_json() == {"error": "invalid_time", "field": "end_time"}


def test_create_invalid_meeting_days_lists_valid(client, admin_headers, payload):
    body = client.post("/admin/cohorts", headers=admin_headers,
                       json=payload(meeting_days=["x"])).get_json()
    assert body["valid"] == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def test_create_rejects_unknown_parent_cohort(client, admin_headers, payload):
    resp = client.post("/admin/cohorts", headers=admin_headers,
                       json=payload(parent_cohort_id=9999))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_parent_cohort_id"
