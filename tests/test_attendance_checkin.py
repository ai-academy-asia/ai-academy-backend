"""QR issuing and rotation, student check-in, the late rule and idempotency."""
import hashlib
from datetime import datetime

import engagement_helpers
from engagement_helpers import _fresh, enroll, new_session

from app.models import Attendance, ClassSession

clock = engagement_helpers.clock
klass = engagement_helpers.klass


def _session(client, klass, **fields):
    return new_session(client, klass["t_headers"], klass["cohort"].id, **fields).get_json()["id"]


def _qr(client, klass, sid):
    return client.post(f"/teacher/sessions/{sid}/qr", headers=klass["t_headers"])


def _scan(client, headers, token):
    return client.post("/me/attendance/check-in", headers=headers, json={"token": token})


# ----------------------------------------------------------------- QR
def test_qr_stores_only_a_hash_and_expires_in_5_minutes(client, db, klass, clock):
    clock(datetime(2026, 10, 1, 8, 55))
    sid = _session(client, klass)
    resp = _qr(client, klass, sid)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["expires_at"] == "2026-10-01T01:00:00+00:00"  # 09:00 local
    row = _fresh(db, ClassSession, sid)
    assert row.qr_token_hash == hashlib.sha256(data["token"].encode()).hexdigest()
    assert data["token"] not in row.qr_token_hash


def test_qr_only_on_session_day(client, klass, clock):
    sid = _session(client, klass, session_date="2026-10-02")
    resp = _qr(client, klass, sid)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "session_not_today"


def test_qr_uses_local_date_not_utc(client, klass, clock):
    # 07:30 local on the 2nd is still the 1st in UTC; the 2nd's session is "today".
    clock(datetime(2026, 10, 2, 7, 30))
    sid = _session(client, klass, session_date="2026-10-02")
    assert _qr(client, klass, sid).status_code == 200


def test_qr_access(client, klass, make_teacher):
    sid = _session(client, klass)
    _, other = make_teacher()
    assert client.post(f"/teacher/sessions/{sid}/qr", headers=other).status_code == 404
    assert client.post(f"/teacher/sessions/{sid}/qr",
                       headers=klass["s_headers"]).status_code == 403
    assert client.post("/teacher/sessions/999999/qr",
                       headers=klass["t_headers"]).status_code == 404


def test_new_qr_invalidates_previous(client, klass, clock):
    sid = _session(client, klass)
    old = _qr(client, klass, sid).get_json()["token"]
    new = _qr(client, klass, sid).get_json()["token"]
    assert old != new
    resp = _scan(client, klass["s_headers"], old)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_token"
    assert _scan(client, klass["s_headers"], new).status_code == 201


def test_expired_qr_is_rejected(client, klass, clock):
    sid = _session(client, klass)
    token = _qr(client, klass, sid).get_json()["token"]
    clock(datetime(2026, 10, 1, 9, 5, 1))
    resp = _scan(client, klass["s_headers"], token)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_token"


# ----------------------------------------------------------------- check-in
def test_check_in_present_then_idempotent(client, db, klass, clock):
    sid = _session(client, klass)
    clock(datetime(2026, 10, 1, 9, 10))
    token = _qr(client, klass, sid).get_json()["token"]
    resp = _scan(client, klass["s_headers"], token)
    assert resp.status_code == 201
    data = resp.get_json()
    assert (data["session_id"], data["status"], data["method"]) == (sid, "present", "qr")
    assert data["checked_in_at"] == "2026-10-01T01:10:00+00:00"

    clock(datetime(2026, 10, 1, 9, 12))
    again = _scan(client, klass["s_headers"], token)
    assert again.status_code == 200
    assert again.get_json() == data
    assert Attendance.query.count() == 1


def test_check_in_after_15_minutes_is_late(client, klass, clock):
    sid = _session(client, klass)
    clock(datetime(2026, 10, 1, 9, 15))
    token = _qr(client, klass, sid).get_json()["token"]
    assert _scan(client, klass["s_headers"], token).get_json()["status"] == "present"

    sid2 = _session(client, klass, start_time="13:00", end_time="15:00")
    clock(datetime(2026, 10, 1, 13, 16))
    token = _qr(client, klass, sid2).get_json()["token"]
    assert _scan(client, klass["s_headers"], token).get_json()["status"] == "late"


def test_check_in_requires_active_enrollment(client, db, klass, clock, make_student):
    sid = _session(client, klass)
    token = _qr(client, klass, sid).get_json()["token"]
    stranger, s_headers = make_student()
    resp = _scan(client, s_headers, token)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "not_enrolled"
    enroll(db, klass["cohort"], stranger, status="cancelled")
    assert _scan(client, s_headers, token).status_code == 403


def test_check_in_validation_and_actor(client, klass):
    resp = client.post("/me/attendance/check-in", headers=klass["s_headers"], json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "token_required"
    resp = _scan(client, klass["s_headers"], "made-up")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_token"
    assert _scan(client, klass["t_headers"], "x").status_code == 403
    assert client.post("/me/attendance/check-in", json={"token": "x"}).status_code == 401
