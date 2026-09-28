"""Student router: self-service enrolment (enroll, cancel, my cohorts)."""

import pytest
from student_helpers import _ids

from app.models import Enrollment


# ----------------------------------------------------------------- POST /cohorts/<id>/enroll
def test_enroll_creates_active_enrollment(client, make_cohort, make_student):
    cohort = make_cohort(capacity=2)
    account, headers = make_student()
    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["cohort_id"] == cohort.id
    assert data["student_id"] == account.actor_id
    assert data["course_id"] == cohort.course_id
    assert data["status"] == "active"
    assert data["created_via"] == "web"
    assert "student" not in data

    row = Enrollment.query.one()
    assert (row.student_id, row.status) == (account.actor_id, "active")
    assert client.get(f"/cohorts/{cohort.id}").get_json()["seats_available"] == 1


def test_enroll_requires_auth(client, make_cohort):
    cohort = make_cohort()
    resp = client.post(f"/cohorts/{cohort.id}/enroll")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


@pytest.mark.parametrize("actor", ["teacher", "staff"])
def test_enroll_forbidden_for_non_students(client, make_cohort, make_teacher, make_staff, actor):
    cohort = make_cohort()
    headers = make_teacher()[1] if actor == "teacher" else make_staff("super_admin")[1]
    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"
    assert Enrollment.query.count() == 0


def test_enroll_unknown_cohort_is_404(client, make_student):
    resp = client.post("/cohorts/999/enroll", headers=make_student()[1])
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


@pytest.mark.parametrize("status", ["closed", "draft"])
def test_enroll_rejects_cohort_not_open(client, make_cohort, make_student, status):
    cohort = make_cohort(status=status)
    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=make_student()[1])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "cohort_not_open"
    assert Enrollment.query.count() == 0


def test_enroll_twice_is_conflict(client, make_cohort, make_student):
    cohort = make_cohort()
    headers = make_student()[1]
    assert client.post(f"/cohorts/{cohort.id}/enroll", headers=headers).status_code == 201
    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "already_enrolled"
    assert Enrollment.query.count() == 1


def test_enroll_full_cohort_is_conflict(client, make_cohort, make_student):
    cohort = make_cohort(capacity=1)
    assert client.post(f"/cohorts/{cohort.id}/enroll",
                       headers=make_student()[1]).status_code == 201
    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=make_student()[1])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "cohort_full"
    assert Enrollment.query.count() == 1


def test_enroll_without_capacity_is_unlimited(client, make_cohort, make_student):
    cohort = make_cohort(capacity=None)
    for _ in range(3):
        assert client.post(f"/cohorts/{cohort.id}/enroll",
                           headers=make_student()[1]).status_code == 201
    assert client.get(f"/cohorts/{cohort.id}").get_json()["seats_available"] is None


def test_enroll_after_cancel_reactivates_same_row(client, make_cohort, make_student):
    cohort = make_cohort()
    headers = make_student()[1]
    first = client.post(f"/cohorts/{cohort.id}/enroll", headers=headers).get_json()
    client.delete(f"/cohorts/{cohort.id}/enroll", headers=headers)
    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert resp.status_code == 201
    assert resp.get_json()["id"] == first["id"]
    assert resp.get_json()["status"] == "active"
    assert Enrollment.query.count() == 1


def test_reenroll_after_cancel_respects_capacity(client, make_cohort, make_student):
    cohort = make_cohort(capacity=1)
    returning = make_student()[1]
    client.post(f"/cohorts/{cohort.id}/enroll", headers=returning)
    client.delete(f"/cohorts/{cohort.id}/enroll", headers=returning)
    assert client.post(f"/cohorts/{cohort.id}/enroll",
                       headers=make_student()[1]).status_code == 201

    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=returning)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "cohort_full"


# ----------------------------------------------------------------- DELETE /cohorts/<id>/enroll
def test_cancel_marks_enrollment_cancelled(client, db, make_cohort, make_student):
    cohort = make_cohort(capacity=3)
    headers = make_student()[1]
    client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)

    resp = client.delete(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "cancelled"}
    db.session.expire_all()
    assert Enrollment.query.one().status == "cancelled"
    assert client.get(f"/cohorts/{cohort.id}").get_json()["seats_available"] == 3


def test_cancel_when_not_enrolled_is_404(client, make_cohort, make_student):
    cohort = make_cohort()
    headers = make_student()[1]
    resp = client.delete(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_enrolled"

    client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)
    client.delete(f"/cohorts/{cohort.id}/enroll", headers=headers)
    again = client.delete(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert again.status_code == 404
    assert again.get_json()["error"] == "not_enrolled"


def test_cancel_does_not_touchother_students(client, make_cohort, make_student):
    cohort = make_cohort()
    a, b = make_student()[1], make_student()[1]
    client.post(f"/cohorts/{cohort.id}/enroll", headers=a)
    resp = client.delete(f"/cohorts/{cohort.id}/enroll", headers=b)
    assert resp.status_code == 404
    assert Enrollment.query.one().status == "active"


def test_cancel_unknown_cohort_is_404(client, make_student):
    resp = client.delete("/cohorts/999/enroll", headers=make_student()[1])
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_cancel_auth(client, make_cohort, make_teacher):
    cohort = make_cohort()
    assert client.delete(f"/cohorts/{cohort.id}/enroll").status_code == 401
    resp = client.delete(f"/cohorts/{cohort.id}/enroll", headers=make_teacher()[1])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


# ----------------------------------------------------------------- GET /me/cohorts
def test_my_cohorts_lists_only_active_enrollments(client, make_cohort, make_student):
    kept, dropped, other = make_cohort(), make_cohort(), make_cohort()
    headers = make_student()[1]
    client.post(f"/cohorts/{kept.id}/enroll", headers=headers)
    client.post(f"/cohorts/{dropped.id}/enroll", headers=headers)
    client.delete(f"/cohorts/{dropped.id}/enroll", headers=headers)
    client.post(f"/cohorts/{other.id}/enroll", headers=make_student()[1])

    resp = client.get("/me/cohorts", headers=headers)
    assert resp.status_code == 200
    assert _ids(resp.get_json()["cohorts"]) == [kept.id]


def test_my_cohorts_empty(client, make_student):
    resp = client.get("/me/cohorts", headers=make_student()[1])
    assert resp.status_code == 200
    assert resp.get_json() == {"cohorts": []}


def test_my_cohorts_auth(client, make_staff):
    assert client.get("/me/cohorts").status_code == 401
    resp = client.get("/me/cohorts", headers=make_staff("super_admin")[1])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"
