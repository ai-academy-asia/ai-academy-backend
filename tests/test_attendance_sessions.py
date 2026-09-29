"""Class sessions: list/create/edit/delete, generate from the cohort schedule, roster."""
from datetime import date

import engagement_helpers
import pytest
from engagement_helpers import _fresh, enroll, make_topic, new_session

from app.models import ClassSession

klass = engagement_helpers.klass


# ----------------------------------------------------------------- create / list
def test_teacher_creates_and_lists_sessions(client, klass):
    c, h = klass["cohort"], klass["t_headers"]
    resp = new_session(client, h, c.id, topic_id=klass["topic"].id)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["session_date"] == "2026-10-01"
    assert (data["start_time"], data["end_time"]) == ("09:00", "11:00")
    assert data["topic_id"] == klass["topic"].id
    assert data["created_at"].endswith("+00:00")
    new_session(client, h, c.id, session_date="2026-10-06")
    new_session(client, h, c.id, session_date="2026-09-29")

    listed = client.get(f"/teacher/cohorts/{c.id}/sessions", headers=h).get_json()
    assert [s["session_date"] for s in listed["sessions"]] == [
        "2026-09-29", "2026-10-01", "2026-10-06"]
    ranged = client.get(f"/teacher/cohorts/{c.id}/sessions?from=2026-10-01&to=2026-10-05",
                        headers=h).get_json()
    assert [s["session_date"] for s in ranged["sessions"]] == ["2026-10-01"]


def test_list_bad_range_is_400(client, klass):
    resp = client.get(f"/teacher/cohorts/{klass['cohort'].id}/sessions?from=nope",
                      headers=klass["t_headers"])
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_from"


def test_duplicate_slot_is_409(client, klass):
    c, h = klass["cohort"], klass["t_headers"]
    assert new_session(client, h, c.id).status_code == 201
    resp = new_session(client, h, c.id)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "session_exists"


@pytest.mark.parametrize("fields,code", [
    ({"session_date": None}, "session_date_required"),
    ({"session_date": "2026-13-01"}, "invalid_session_date"),
    ({"start_time": None}, "start_time_required"),
    ({"start_time": "9am"}, "invalid_start_time"),
    ({"end_time": "25:00"}, "invalid_end_time"),
    ({"end_time": "08:00"}, "invalid_time_range"),
    ({"topic_id": 999999}, "invalid_topic_id"),
    ({"topic_id": "abc"}, "invalid_topic_id"),
])
def test_create_validation(client, klass, fields, code):
    resp = new_session(client, klass["t_headers"], klass["cohort"].id, **fields)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == code


def test_topic_of_another_course_is_invalid(client, db, klass, make_course):
    foreign = make_topic(db, make_course())
    resp = new_session(client, klass["t_headers"], klass["cohort"].id, topic_id=foreign.id)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_topic_id"


# ----------------------------------------------------------------- access
def test_other_teachers_cohort_is_404(client, klass, make_teacher):
    _, other = make_teacher()
    c = klass["cohort"]
    for resp in (client.get(f"/teacher/cohorts/{c.id}/sessions", headers=other),
                 new_session(client, other, c.id),
                 client.get(f"/teacher/cohorts/{c.id}/students", headers=other),
                 client.post(f"/teacher/cohorts/{c.id}/sessions/generate", headers=other)):
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "cohort_not_found"


def test_unknown_cohort_is_404(client, klass):
    resp = client.get("/teacher/cohorts/999999/sessions", headers=klass["t_headers"])
    assert resp.status_code == 404


def test_manager_staff_may_act_on_any_cohort(client, klass, make_staff):
    _, headers = make_staff("sales_enrollment")
    assert new_session(client, headers, klass["cohort"].id).status_code == 201


def test_wrong_actor_is_403_and_anonymous_401(client, klass, make_staff):
    c = klass["cohort"]
    for headers in (klass["s_headers"], make_staff("finance")[1]):
        resp = client.get(f"/teacher/cohorts/{c.id}/sessions", headers=headers)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "forbidden"
    resp = client.get(f"/teacher/cohorts/{c.id}/sessions")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


# ----------------------------------------------------------------- edit / delete
def test_patch_session(client, db, klass):
    h = klass["t_headers"]
    sid = new_session(client, h, klass["cohort"].id).get_json()["id"]
    resp = client.patch(f"/teacher/sessions/{sid}", headers=h,
                        json={"start_time": "10:00", "topic_id": klass["topic"].id})
    assert resp.status_code == 200
    assert resp.get_json()["start_time"] == "10:00"
    assert resp.get_json()["topic_id"] == klass["topic"].id
    resp = client.patch(f"/teacher/sessions/{sid}", headers=h, json={"topic_id": None})
    assert resp.get_json()["topic_id"] is None


def test_patch_validation_leaves_row_untouched(client, db, klass):
    h = klass["t_headers"]
    sid = new_session(client, h, klass["cohort"].id).get_json()["id"]
    resp = client.patch(f"/teacher/sessions/{sid}", headers=h, json={"end_time": "07:00"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_time_range"
    assert _fresh(db, ClassSession, sid).end_time == "11:00"


def test_patch_into_taken_slot_is_409(client, klass):
    h, c = klass["t_headers"], klass["cohort"]
    new_session(client, h, c.id)
    sid = new_session(client, h, c.id, start_time="13:00", end_time="15:00").get_json()["id"]
    resp = client.patch(f"/teacher/sessions/{sid}", headers=h, json={"start_time": "09:00"})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "session_exists"


def test_delete_session_and_others_404(client, db, klass, make_teacher):
    h = klass["t_headers"]
    sid = new_session(client, h, klass["cohort"].id).get_json()["id"]
    _, other = make_teacher()
    for resp in (client.patch(f"/teacher/sessions/{sid}", headers=other, json={}),
                 client.delete(f"/teacher/sessions/{sid}", headers=other)):
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "session_not_found"
    assert client.delete(f"/teacher/sessions/{sid}", headers=h).status_code == 200
    assert _fresh(db, ClassSession, sid) is None
    assert client.delete(f"/teacher/sessions/{sid}", headers=h).status_code == 404


# ----------------------------------------------------------------- generate
def test_generate_follows_meeting_days_and_skips_existing(client, db, klass, make_cohort):
    c, h = klass["cohort"], klass["t_headers"]
    c.end_date = date(2026, 10, 15)  # Thu 1, Tue 6, Thu 8, Tue 13, Thu 15
    db.session.commit()
    new_session(client, h, c.id, session_date="2026-10-06")
    resp = client.post(f"/teacher/cohorts/{c.id}/sessions/generate", headers=h)
    assert resp.status_code == 200
    data = resp.get_json()
    assert (data["created"], data["skipped"]) == (4, 1)
    assert [s["session_date"] for s in data["sessions"]] == [
        "2026-10-01", "2026-10-08", "2026-10-13", "2026-10-15"]
    assert all(s["end_time"] == "11:00" for s in data["sessions"])
    again = client.post(f"/teacher/cohorts/{c.id}/sessions/generate", headers=h).get_json()
    assert (again["created"], again["skipped"]) == (0, 5)


@pytest.mark.parametrize("fields", [
    {"meeting_days": None}, {"meeting_days": []}, {"start_date": None}, {"end_date": None},
    {"start_time": None},
])
def test_generate_needs_a_complete_schedule(client, klass, make_cohort, fields):
    values = {"teacher_id": klass["teacher"].actor_id, "meeting_days": ["mon"],
              "start_time": "09:00"}
    values.update(fields)
    cohort = make_cohort(**values)
    resp = client.post(f"/teacher/cohorts/{cohort.id}/sessions/generate",
                       headers=klass["t_headers"])
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "cohort_schedule_incomplete"


# ----------------------------------------------------------------- roster
def test_roster_lists_active_students(client, db, klass, make_student):
    c = klass["cohort"]
    gone, _ = make_student(first_name="Zaya")
    enroll(db, c, gone, status="cancelled")
    resp = client.get(f"/teacher/cohorts/{c.id}/students", headers=klass["t_headers"])
    assert resp.status_code == 200
    assert resp.get_json()["students"] == [{
        "student_id": klass["student"].actor_id,
        "enrollment_id": resp.get_json()["students"][0]["enrollment_id"],
        "name": "Anu", "phone": "99112233",
    }]
