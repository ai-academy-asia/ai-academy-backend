"""Cohort double-booking guard for teachers and classrooms (/admin/cohorts)."""

import admin_cohort_helpers
import pytest
from admin_cohort_helpers import _fresh

from app.models import Cohort

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
payload = admin_cohort_helpers.payload


# ---------------------------------------------------------------- double booking
@pytest.fixture
def booked(client, admin_headers, payload, make_teacher, make_classroom):
    """An existing cohort: teacher + room, Mon/Wed 18:00-20:00, Oct-Dec."""
    teacher, _ = make_teacher()
    room = make_classroom()
    resp = client.post("/admin/cohorts", headers=admin_headers, json=payload(
        teacher_id=teacher.actor_id, classroom_id=room.id,
        meeting_days=["mon", "wed"], start_time="18:00", end_time="20:00",
    ))
    assert resp.status_code == 201
    return {"cohort_id": resp.get_json()["id"], "teacher_id": teacher.actor_id,
            "classroom_id": room.id}


def test_teacher_double_booking_is_blocked(client, admin_headers, payload, booked):
    resp = client.post("/admin/cohorts", headers=admin_headers, json=payload(
        name="Clash", teacher_id=booked["teacher_id"], start_date="2026-11-01",
        end_date="2027-01-01", meeting_days=["wed"], start_time="19:00", end_time="21:00",
    ))
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["error"] == "teacher_double_booked"
    assert body["conflict"]["cohort_id"] == booked["cohort_id"]
    assert body["conflict"]["meeting_days"] == ["mon", "wed"]
    assert body["conflict"]["start_time"] == "18:00"
    assert Cohort.query.count() == 1


def test_classroom_double_booking_is_blocked(client, admin_headers, payload, booked):
    resp = client.post("/admin/cohorts", headers=admin_headers, json=payload(
        name="Clash", classroom_id=booked["classroom_id"],
        meeting_days=["mon"], start_time="17:00", end_time="18:30",
    ))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "classroom_double_booked"
    assert resp.get_json()["conflict"]["cohort_id"] == booked["cohort_id"]


def test_unknown_days_or_times_assume_a_clash(client, admin_headers, payload, booked):
    resp = client.post("/admin/cohorts", headers=admin_headers,
                       json=payload(name="Vague", teacher_id=booked["teacher_id"]))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "teacher_double_booked"


@pytest.mark.parametrize("fields", [
    {"meeting_days": ["tue", "thu"], "start_time": "18:00", "end_time": "20:00"},
    {"meeting_days": ["mon"], "start_time": "20:00", "end_time": "21:00"},  # back-to-back
    {"meeting_days": ["mon"], "start_time": "09:00", "end_time": "12:00"},
    {"start_date": "2027-01-01", "end_date": "2027-03-01"},
    {"start_date": None, "end_date": None},  # undated cohorts are never checked
])
def test_non_overlapping_bookings_are_allowed(client, admin_headers, payload, booked, fields):
    data = payload(name="Other", teacher_id=booked["teacher_id"],
                   classroom_id=booked["classroom_id"])
    data.update(fields)
    resp = client.post("/admin/cohorts", headers=admin_headers, json=data)
    assert resp.status_code == 201, resp.get_json()


def test_updating_a_cohort_does_not_clash_with_itself(client, admin_headers, booked):
    resp = client.patch(f"/admin/cohorts/{booked['cohort_id']}", headers=admin_headers,
                        json={"end_time": "21:00"})
    assert resp.status_code == 200
    assert resp.get_json()["end_time"] == "21:00"


def test_update_into_a_clash_is_blocked(client, admin_headers, payload, booked, db):
    resp = client.post("/admin/cohorts", headers=admin_headers, json=payload(
        name="Other", teacher_id=booked["teacher_id"], meeting_days=["fri"],
        start_time="18:00", end_time="20:00",
    ))
    other_id = resp.get_json()["id"]
    resp = client.patch(f"/admin/cohorts/{other_id}", headers=admin_headers,
                        json={"meeting_days": ["fri", "mon"]})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "teacher_double_booked"
    db.session.rollback()  # requests share the fixture's app context; mimic teardown
    assert _fresh(db, Cohort, other_id).meeting_days == ["fri"]
