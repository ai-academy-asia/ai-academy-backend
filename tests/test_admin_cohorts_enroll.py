"""Staff enrollment, roster and removal (/admin/cohorts/<id>/enroll, /students)."""

import admin_cohort_helpers
import pytest
from admin_cohort_helpers import _enroll, _fresh

from app.models import Enrollment

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
payload = admin_cohort_helpers.payload
sales = admin_cohort_helpers.sales


# ---------------------------------------------------------------- enroll
def test_staff_enroll_records_provenance(client, sales, make_cohort, make_student, db):
    staff, headers = sales
    cohort = make_cohort(status="open")
    student, _ = make_student()
    resp = _enroll(client, headers, cohort.id, student.actor_id)
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "active"
    assert body["student_id"] == student.actor_id
    assert body["course_id"] == cohort.course_id
    assert body["created_via"] == "admin"
    assert body["created_by_admin_id"] == staff.actor_id
    assert db.session.get(Enrollment, body["id"]).cohort_id == cohort.id


def test_staff_may_enroll_into_closed_cohort(client, admin_headers, make_cohort, make_student):
    cohort = make_cohort(status="closed")
    student, _ = make_student()
    assert _enroll(client, admin_headers, cohort.id, student.actor_id).status_code == 201


def test_enroll_into_draft_is_409(client, admin_headers, make_cohort, make_student):
    cohort = make_cohort(status="draft")
    student, _ = make_student()
    resp = _enroll(client, admin_headers, cohort.id, student.actor_id)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "cohort_not_open"
    assert Enrollment.query.count() == 0


@pytest.mark.parametrize("payload", [{}, {"student_id": None}, {"student_id": 0}])
def test_enroll_requires_student_id(client, admin_headers, make_cohort, payload):
    cohort = make_cohort()
    resp = client.post(f"/admin/cohorts/{cohort.id}/enroll", headers=admin_headers,
                       json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "student_id_required"


def test_enroll_unknown_student_is_404(client, admin_headers, make_cohort):
    cohort = make_cohort()
    resp = _enroll(client, admin_headers, cohort.id, 9999)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "student_not_found"


def test_enroll_unknown_cohort_is_404(client, admin_headers, make_student):
    student, _ = make_student()
    resp = _enroll(client, admin_headers, 9999, student.actor_id)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_enroll_twice_is_409(client, admin_headers, make_cohort, make_student):
    cohort = make_cohort()
    student, _ = make_student()
    _enroll(client, admin_headers, cohort.id, student.actor_id)
    resp = _enroll(client, admin_headers, cohort.id, student.actor_id)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "already_enrolled"
    assert Enrollment.query.count() == 1


def test_enroll_into_full_cohort_is_409(client, admin_headers, make_cohort, make_student):
    cohort = make_cohort(capacity=1)
    first, _ = make_student()
    second, _ = make_student()
    assert _enroll(client, admin_headers, cohort.id, first.actor_id).status_code == 201
    resp = _enroll(client, admin_headers, cohort.id, second.actor_id)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "cohort_full"


def test_enroll_reactivates_cancelled_enrollment(client, admin_headers, make_cohort,
                                                 make_student, db):
    cohort = make_cohort()
    student, _ = make_student()
    first_id = _enroll(client, admin_headers, cohort.id, student.actor_id).get_json()["id"]
    client.delete(f"/admin/cohorts/{cohort.id}/students/{student.actor_id}",
                  headers=admin_headers)
    resp = _enroll(client, admin_headers, cohort.id, student.actor_id)
    assert resp.status_code == 201
    assert resp.get_json()["id"] == first_id
    assert resp.get_json()["status"] == "active"
    assert Enrollment.query.count() == 1


def test_reactivation_respects_capacity(client, admin_headers, make_cohort, make_student):
    cohort = make_cohort(capacity=1)
    first, _ = make_student()
    second, _ = make_student()
    _enroll(client, admin_headers, cohort.id, first.actor_id)
    client.delete(f"/admin/cohorts/{cohort.id}/students/{first.actor_id}",
                  headers=admin_headers)
    assert _enroll(client, admin_headers, cohort.id, second.actor_id).status_code == 201
    resp = _enroll(client, admin_headers, cohort.id, first.actor_id)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "cohort_full"


# ---------------------------------------------------------------- roster
def test_roster_lists_only_active(client, sales, make_cohort, make_student):
    _, headers = sales
    cohort = make_cohort()
    stay, _ = make_student(first_name="Anu", last_name="Bat")
    leave, _ = make_student()
    _enroll(client, headers, cohort.id, stay.actor_id)
    _enroll(client, headers, cohort.id, leave.actor_id)
    client.delete(f"/admin/cohorts/{cohort.id}/students/{leave.actor_id}", headers=headers)

    resp = client.get(f"/admin/cohorts/{cohort.id}/students", headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["cohort_id"] == cohort.id
    assert body["count"] == 1
    assert body["students"][0]["student_id"] == stay.actor_id
    assert body["students"][0]["student"]["name"] == "Anu Bat"


def test_roster_unknown_cohort_is_404(client, admin_headers):
    resp = client.get("/admin/cohorts/9999/students", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


# ---------------------------------------------------------------- remove
def test_remove_student_cancels_enrollment(client, sales, make_cohort, make_student, db):
    _, headers = sales
    cohort = make_cohort(capacity=1)
    student, _ = make_student()
    eid = _enroll(client, headers, cohort.id, student.actor_id).get_json()["id"]

    resp = client.delete(f"/admin/cohorts/{cohort.id}/students/{student.actor_id}",
                         headers=headers)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "removed"}
    assert _fresh(db, Enrollment, eid).status == "cancelled"  # history kept
    body = client.get(f"/admin/cohorts/{cohort.id}", headers=headers).get_json()
    assert body["enrolled_count"] == 0
    assert body["seats_available"] == 1


def test_remove_not_enrolled_is_404(client, admin_headers, make_cohort, make_student):
    cohort = make_cohort()
    student, _ = make_student()
    resp = client.delete(f"/admin/cohorts/{cohort.id}/students/{student.actor_id}",
                         headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_enrolled"
