"""Cohort update and delete (PATCH/DELETE /admin/cohorts/<id>)."""

import admin_cohort_helpers
import pytest
from admin_cohort_helpers import _enroll, _fresh

from app.models import Cohort, Enrollment

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
sales = admin_cohort_helpers.sales


# ---------------------------------------------------------------- update
def test_update_cohort(client, sales, make_cohort, db):
    _, headers = sales
    cid = make_cohort(status="draft").id
    resp = client.patch(f"/admin/cohorts/{cid}", headers=headers, json={
        "status": "open", "name": "Renamed", "capacity": 3, "graduation_date": "2026-12-10",
        "id": 555,
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == cid
    assert body["status"] == "open"
    assert body["name"] == "Renamed"
    assert body["graduation_date"] == "2026-12-10"
    assert _fresh(db, Cohort, cid).capacity == 3


def test_update_can_clear_dates(client, admin_headers, make_cohort, db):
    cid = make_cohort().id
    resp = client.patch(f"/admin/cohorts/{cid}", headers=admin_headers,
                        json={"start_date": None, "end_date": ""})
    assert resp.status_code == 200
    cohort = _fresh(db, Cohort, cid)
    assert cohort.start_date is None and cohort.end_date is None


@pytest.mark.parametrize("fields,error", [
    ({"status": "bogus"}, "invalid_status"),
    ({"name": None}, "name_required"),
    ({"end_date": "2020-01-01"}, "end_before_start"),
    ({"start_date": "2026-13-01"}, "invalid_date"),
])
def test_update_validation(client, admin_headers, make_cohort, db, fields, error):
    cohort = make_cohort(status="open")
    cid, name = cohort.id, cohort.name
    resp = client.patch(f"/admin/cohorts/{cid}", headers=admin_headers, json=fields)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == error
    db.session.rollback()  # requests share the fixture's app context; mimic teardown
    cohort = _fresh(db, Cohort, cid)
    assert cohort.status == "open" and cohort.name == name


@pytest.mark.parametrize("field,error", [
    ("course_id", "invalid_course_id"),
    ("teacher_id", "invalid_teacher_id"),
    ("classroom_id", "invalid_classroom_id"),
])
def test_update_rejects_unknown_references(client, admin_headers, make_cohort, field, error):
    cohort = make_cohort()
    resp = client.patch(f"/admin/cohorts/{cohort.id}", headers=admin_headers,
                        json={field: 9999})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == error


def test_update_unknown_is_404(client, admin_headers):
    resp = client.patch("/admin/cohorts/9999", headers=admin_headers, json={"name": "X"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


# ---------------------------------------------------------------- delete
def test_delete_cohort_and_its_enrollments(client, sales, make_cohort, make_student, db):
    _, headers = sales
    cid = make_cohort().id
    student, _ = make_student()
    assert _enroll(client, headers, cid, student.actor_id).status_code == 201

    resp = client.delete(f"/admin/cohorts/{cid}", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "deleted"}
    assert _fresh(db, Cohort, cid) is None
    assert Enrollment.query.count() == 0


def test_delete_unknown_is_404(client, admin_headers):
    resp = client.delete("/admin/cohorts/9999", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"
