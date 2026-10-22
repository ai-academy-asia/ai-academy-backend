"""The teacher's attendance sheet, manual marking and the student's own summary."""
from datetime import datetime

import engagement_helpers
from engagement_helpers import _fresh, enroll, new_session

from app.models import Attendance
from app.services.attendance import attendance_percent

clock = engagement_helpers.clock
klass = engagement_helpers.klass


def _sheet(client, klass, sid, headers=None):
    return client.get(f"/teacher/sessions/{sid}/attendance",
                      headers=headers or klass["t_headers"])


def _mark(client, klass, sid, student_id, status, headers=None):
    return client.put(f"/teacher/sessions/{sid}/attendance/{student_id}",
                      headers=headers or klass["t_headers"], json={"status": status})


def _sid(client, klass, **fields):
    return new_session(client, klass["t_headers"], klass["cohort"].id, **fields).get_json()["id"]


# ----------------------------------------------------------------- sheet
def test_sheet_defaults_to_absent_and_reflects_marks(client, db, klass, clock, make_student):
    other, _ = make_student(first_name="Bold")
    enroll(db, klass["cohort"], other)
    sid = _sid(client, klass)
    data = _sheet(client, klass, sid).get_json()
    assert data["session"]["id"] == sid
    assert [(s["name"], s["status"], s["method"]) for s in data["students"]] == [
        ("Anu", "absent", None), ("Bold", "absent", None)]

    resp = _mark(client, klass, sid, other.actor_id, "excused")
    assert resp.status_code == 200
    assert resp.get_json()["method"] == "manual"
    data = _sheet(client, klass, sid).get_json()
    assert data["students"][1]["status"] == "excused"
    assert data["counts"]["excused"] == 1 and data["counts"]["absent"] == 1


def test_manual_mark_overrides_qr_and_records_teacher(client, db, klass, clock):
    sid = _sid(client, klass)
    token = client.post(f"/teacher/sessions/{sid}/qr",
                        headers=klass["t_headers"]).get_json()["token"]
    client.post("/me/attendance/check-in", headers=klass["s_headers"], json={"token": token})
    sid_student = klass["student"].actor_id
    assert _mark(client, klass, sid, sid_student, "late").status_code == 200
    row = Attendance.query.filter_by(class_session_id=sid).one()
    row = _fresh(db, Attendance, row.id)
    assert (row.status, row.method) == ("late", "manual")
    assert row.marked_by_teacher_id == klass["teacher"].actor_id


def test_staff_mark_has_no_teacher_id(client, db, klass, make_staff):
    sid = _sid(client, klass)
    _, staff = make_staff("sales_enrollment")
    assert _mark(client, klass, sid, klass["student"].actor_id, "present",
                 headers=staff).status_code == 200
    assert Attendance.query.one().marked_by_teacher_id is None


def test_mark_validation(client, db, klass, make_student):
    sid = _sid(client, klass)
    resp = _mark(client, klass, sid, klass["student"].actor_id, "sleeping")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_status"
    outsider, _ = make_student()
    resp = _mark(client, klass, sid, outsider.actor_id, "present")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "student_not_found"


def test_sheet_access(client, klass, make_teacher):
    sid = _sid(client, klass)
    _, other = make_teacher()
    assert _sheet(client, klass, sid, other).status_code == 404
    assert _mark(client, klass, sid, klass["student"].actor_id, "present",
                 headers=other).status_code == 404
    assert _sheet(client, klass, sid, klass["s_headers"]).status_code == 403
    assert client.get(f"/teacher/sessions/{sid}/attendance").status_code == 401


# ----------------------------------------------------------------- student summary
def test_my_attendance_summary(client, db, klass, clock):
    clock(datetime(2026, 10, 8, 10, 0))
    s1 = _sid(client, klass, session_date="2026-10-01", topic_id=klass["topic"].id)
    s2 = _sid(client, klass, session_date="2026-10-06")
    s3 = _sid(client, klass, session_date="2026-10-08")
    _sid(client, klass, session_date="2026-10-13")
    student_id = klass["student"].actor_id
    _mark(client, klass, s1, student_id, "present")
    _mark(client, klass, s3, student_id, "late")
    _mark(client, klass, s2, student_id, "excused")

    resp = client.get("/me/attendance?course=corp-leaders", headers=klass["s_headers"])
    assert resp.status_code == 200
    data = resp.get_json()
    assert [(s["date"], s["status"]) for s in data["sessions"]] == [
        ("2026-10-01", "present"), ("2026-10-06", "excused"),
        ("2026-10-08", "late"), ("2026-10-13", None)]
    assert data["sessions"][0]["topic_id"] == klass["topic"].id
    assert data["sessions"][0]["start_time"] == "09:00"
    assert data["summary"] == {"attended": 2, "total_past": 3, "percent": 66}

    enrollment = klass["cohort"].enrollments[0]
    assert attendance_percent(enrollment) == 66


def test_my_attendance_with_no_sessions(client, klass, clock):
    data = client.get("/me/attendance?course=corp-leaders",
                      headers=klass["s_headers"]).get_json()
    assert data["sessions"] == []
    assert data["summary"] == {"attended": 0, "total_past": 0, "percent": 0}


def test_my_attendance_errors(client, klass, make_student, make_course):
    h = klass["s_headers"]
    resp = client.get("/me/attendance", headers=h)
    assert (resp.status_code, resp.get_json()["error"]) == (400, "course_required")
    resp = client.get("/me/attendance?course=nope", headers=h)
    assert (resp.status_code, resp.get_json()["error"]) == (404, "course_not_found")
    _, stranger = make_student()
    resp = client.get("/me/attendance?course=corp-leaders", headers=stranger)
    assert (resp.status_code, resp.get_json()["error"]) == (403, "not_enrolled")
    assert client.get("/me/attendance?course=corp-leaders",
                      headers=klass["t_headers"]).status_code == 403
    assert client.get("/me/attendance?course=corp-leaders").status_code == 401


# ----------------------------------------------------------------- BE-08 / BE-09
def test_todays_session_counts_only_once_it_ends(client, klass, clock):
    """09:00–11:00 today: not missed at 10:59, missed from 11:00."""
    sid = _sid(client, klass, session_date="2026-10-08")
    url, h = "/me/attendance?course=corp-leaders", klass["s_headers"]
    clock(datetime(2026, 10, 8, 10, 59))
    data = client.get(url, headers=h).get_json()
    assert data["sessions"][0]["status"] is None
    assert data["summary"] == {"attended": 0, "total_past": 0, "percent": 0}
    clock(datetime(2026, 10, 8, 11, 0))
    data = client.get(url, headers=h).get_json()
    assert data["sessions"][0]["status"] == "absent"
    assert data["summary"]["total_past"] == 1
    assert sid == data["sessions"][0]["session_id"]


def test_session_without_end_time_runs_the_default_length(client, klass, clock):
    _sid(client, klass, session_date="2026-10-08", start_time="23:00", end_time=None)
    url, h = "/me/attendance?course=corp-leaders", klass["s_headers"]
    clock(datetime(2026, 10, 9, 0, 29))
    assert client.get(url, headers=h).get_json()["summary"]["total_past"] == 0
    clock(datetime(2026, 10, 9, 0, 30))
    assert client.get(url, headers=h).get_json()["summary"]["total_past"] == 1


def test_check_in_before_the_end_counts_at_once(client, klass, clock):
    sid = _sid(client, klass)
    clock(datetime(2026, 10, 1, 9, 5))
    _mark(client, klass, sid, klass["student"].actor_id, "present")
    summary = client.get("/me/attendance?course=corp-leaders",
                         headers=klass["s_headers"]).get_json()["summary"]
    assert summary == {"attended": 1, "total_past": 1, "percent": 100}


def test_marking_a_future_session_is_refused(client, db, klass, clock):
    future = _sid(client, klass, session_date="2026-10-02")
    resp = _mark(client, klass, future, klass["student"].actor_id, "present")
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "session_in_future"
    assert Attendance.query.count() == 0
    today = _sid(client, klass, session_date="2026-10-01", start_time="20:00", end_time=None)
    assert _mark(client, klass, today, klass["student"].actor_id, "present").status_code == 200
    clock(datetime(2027, 3, 1, 12, 0))  # no limit on correcting the past
    assert _mark(client, klass, today, klass["student"].actor_id, "late").status_code == 200
