"""FCM delivery (issue #2): notify() → one HTTP v1 message per device token.

Every outbound call is stubbed at ``fcm.http_post``; the service account is a
throwaway RSA key made here, so the real RS256 grant is exercised and checked.
"""
import json
import logging

import jwt
import pytest
import requests
import schedule_change_helpers
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.models import FirebaseToken, Notification
from app.services import notifications as notif_svc
from app.services.notifications import fcm

handover = schedule_change_helpers.handover     # the schedule-change fixtures (issue #3)
clock = schedule_change_helpers.clock

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CREDS = {
    "type": "service_account",
    "project_id": "aiaa-test",
    "client_email": "push@aiaa-test.iam.gserviceaccount.com",
    "private_key": _KEY.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode(),
}
SEND = "https://fcm.googleapis.com/v1/projects/aiaa-test/messages:send"


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


def _fcm_error(status, code):
    return _Resp(status, {"error": {"code": status, "status": "NOT_FOUND", "details": [
        {"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError", "errorCode": code},
    ]}})


@pytest.fixture
def fcm_http(app, monkeypatch):
    """Configured credentials and a recording stub for FCM's two endpoints."""
    fcm.reset_cache()
    monkeypatch.setitem(app.config, "FCM_CREDENTIALS", json.dumps(CREDS))
    calls, answers = [], {}

    def _post(url, **kwargs):
        calls.append((url, kwargs))
        if url == fcm.TOKEN_URL:
            return answers.get("token") or _Resp(200, {"access_token": "at-1",
                                                       "expires_in": 3600})
        token = kwargs["json"]["message"]["token"]
        answer = answers.get(token, _Resp(200, {"name": "projects/aiaa-test/messages/1"}))
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(fcm, "http_post", _post)
    yield calls, answers
    fcm.reset_cache()


def _device(db, account, token, platform="android"):
    db.session.add(FirebaseToken(account_id=account.id, token=token, platform=platform))
    db.session.commit()


def _sends(calls):
    return [kw for url, kw in calls if url == SEND]


def test_without_credentials_nothing_is_sent(app, db, make_student, monkeypatch):
    monkeypatch.setitem(app.config, "FCM_CREDENTIALS", None)
    monkeypatch.setattr(fcm, "http_post", lambda *a, **k: pytest.fail("no HTTP expected"))
    student, _ = make_student()
    _device(db, student, "dev-1")
    assert notif_svc.notify([student.id], kind="general", title="Hi") == 1
    assert Notification.query.count() == 1


def test_one_message_per_device_with_the_recipients_own_notification_id(
        db, make_student, make_teacher, fcm_http):
    calls, _ = fcm_http
    student, _ = make_student()
    teacher, _ = make_teacher()
    nobody, _ = make_student()                 # no device: in-app only
    _device(db, student, "dev-s1")
    _device(db, student, "dev-s2", platform="ios")
    _device(db, teacher, "dev-t")

    sent = notif_svc.notify([student.id, teacher.id, nobody.id], kind="announcement",
                            title="Class moved", body="Room 2",
                            data={"cohort_id": 7, "urgent": True})
    assert sent == 3                           # inbox rows, one per account
    rows = {n.account_id: n.id for n in Notification.query.all()}
    sends = _sends(calls)
    assert len(sends) == 3
    by_token = {s["json"]["message"]["token"]: s["json"]["message"] for s in sends}
    assert set(by_token) == {"dev-s1", "dev-s2", "dev-t"}
    student_msg = by_token["dev-s1"]
    assert student_msg["notification"] == {"title": "Class moved", "body": "Room 2"}
    assert student_msg["data"] == {"cohort_id": "7", "urgent": "true",
                                   "kind": "announcement",
                                   "notification_id": str(rows[student.id])}
    assert by_token["dev-t"]["data"]["notification_id"] == str(rows[teacher.id])
    assert student_msg["android"] == {"priority": "HIGH"}
    assert student_msg["apns"] == {"payload": {"aps": {"sound": "default"}}}
    assert all(s["headers"]["Authorization"] == "Bearer at-1" for s in sends)


def test_the_access_token_is_a_signed_grant_fetched_once(db, make_student, fcm_http):
    calls, _ = fcm_http
    student, _ = make_student()
    _device(db, student, "dev-1")
    _device(db, student, "dev-2")
    notif_svc.notify([student.id], kind="general", title="One")
    notif_svc.notify([student.id], kind="general", title="Two")
    grants = [kw for url, kw in calls if url == fcm.TOKEN_URL]
    assert len(grants) == 1                    # cached across both notifications
    assert grants[0]["data"]["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    claims = jwt.decode(grants[0]["data"]["assertion"], _KEY.public_key(),
                        algorithms=["RS256"], audience=fcm.TOKEN_URL)
    assert claims["iss"] == CREDS["client_email"]
    assert claims["scope"] == fcm.SCOPE
    assert claims["exp"] - claims["iat"] == 3600
    assert len(_sends(calls)) == 4


def test_the_cached_token_is_renewed_when_due():
    fcm.reset_cache()
    seen = []

    def _post(url, **kwargs):
        seen.append(url)
        return _Resp(200, {"access_token": f"at-{len(seen)}", "expires_in": 3600})

    original, fcm.http_post = fcm.http_post, _post
    try:
        assert fcm.access_token(CREDS, timeout=5, now=1000) == "at-1"
        assert fcm.access_token(CREDS, timeout=5, now=1000 + 3000) == "at-1"
        assert fcm.access_token(CREDS, timeout=5, now=1000 + 3550) == "at-2"
    finally:
        fcm.http_post = original
        fcm.reset_cache()


def test_an_unregistered_token_is_deleted_and_others_are_kept(db, make_student, fcm_http):
    calls, answers = fcm_http
    student, _ = make_student()
    for token in ("dead", "flaky", "bare-404", "fine"):
        _device(db, student, token)
    answers["dead"] = _fcm_error(404, "UNREGISTERED")
    answers["flaky"] = _fcm_error(503, "UNAVAILABLE")
    answers["bare-404"] = _Resp(404, {"error": {"code": 404}})   # no FCM code
    notif_svc.notify([student.id], kind="general", title="Hi")
    assert {t.token for t in FirebaseToken.query.all()} == {"flaky", "bare-404", "fine"}
    assert len(_sends(calls)) == 4


def test_a_network_failure_skips_one_device_only(db, make_student, fcm_http):
    calls, answers = fcm_http
    student, _ = make_student()
    _device(db, student, "down")
    _device(db, student, "up")
    answers["down"] = requests.ConnectionError("boom")
    assert notif_svc.push.send_push(
        [student.id], kind="general", title="Hi") == 1
    assert FirebaseToken.query.count() == 2


def test_no_access_token_sends_nothing_and_never_raises(db, make_student, fcm_http):
    calls, answers = fcm_http
    student, _ = make_student()
    _device(db, student, "dev-1")
    _device(db, student, "dev-2")
    answers["token"] = _Resp(400, {"error": "invalid_grant"})
    assert notif_svc.notify([student.id], kind="general", title="Hi") == 1
    assert _sends(calls) == []
    assert len([c for c in calls if c[0] == fcm.TOKEN_URL]) == 1    # stopped, not retried
    assert Notification.query.count() == 1
    assert FirebaseToken.query.count() == 2


def test_unusable_credentials_are_a_logged_no_op(app, db, make_student, monkeypatch):
    monkeypatch.setitem(app.config, "FCM_CREDENTIALS", '{"project_id": "x"}')
    monkeypatch.setattr(fcm, "http_post", lambda *a, **k: pytest.fail("no HTTP expected"))
    student, _ = make_student()
    _device(db, student, "dev-1")
    assert notif_svc.push.send_push([student.id], kind="general", title="Hi") == 0


def test_credentials_can_be_a_file_path(app, db, make_student, fcm_http, tmp_path,
                                        monkeypatch):
    calls, _ = fcm_http
    path = tmp_path / "service-account.json"
    path.write_text(json.dumps(CREDS), encoding="utf-8")
    monkeypatch.setitem(app.config, "FCM_CREDENTIALS", str(path))
    student, _ = make_student()
    _device(db, student, "dev-1")
    assert notif_svc.push.send_push([student.id], kind="general", title="Hi") == 1


def test_reserved_and_empty_data_keys_are_left_out():
    body = fcm.message("t", title="T", data={"from": "x", "google.x": "y", "gone": None,
                                              "nested": {"a": 1}})
    assert body["message"]["data"] == {"nested": '{"a":1}'}
    assert "body" not in body["message"]["notification"]


def test_an_admin_announcement_reaches_the_cohorts_devices(client, db, admin_headers,
                                                         make_cohort, make_student,
                                                         fcm_http):
    from engagement_helpers import enroll

    calls, _ = fcm_http
    cohort = make_cohort()
    student, _ = make_student()
    enroll(db, cohort, student)
    _device(db, student, "dev-1")
    resp = client.post("/admin/notifications", headers=admin_headers,
                       json={"cohort_id": cohort.id, "title": "Class moved"})
    assert resp.status_code == 201
    (sent,) = _sends(calls)
    data = sent["json"]["message"]["data"]
    assert data["kind"] == "announcement" and data["cohort_id"] == str(cohort.id)
    assert data["notification_id"] == str(Notification.query.one().id)


# ------------------------------------------------- pinned behaviour (issue #3)
@pytest.mark.parametrize("status, code", [(400, "INVALID_ARGUMENT"),      # malformed token
                                          (403, "SENDER_ID_MISMATCH")])   # another project's
def test_other_fcm_errors_are_logged_and_keep_the_token(db, make_student, fcm_http,
                                                        caplog, monkeypatch, status, code):
    calls, answers = fcm_http
    student, _ = make_student()
    _device(db, student, "bad")
    _device(db, student, "good")
    answers["bad"] = _fcm_error(status, code)
    # conftest's migrations run Alembic's fileConfig, which disables loggers that
    # already exist (fcm's among them) for the rest of the session: re-enable it.
    monkeypatch.setattr(logging.getLogger(fcm.__name__), "disabled", False)
    with caplog.at_level("WARNING", logger=fcm.__name__):
        reached = notif_svc.push.send_push([student.id], kind="general", title="Hi")
    assert reached == 1                                     # "good" still sent
    assert [s["json"]["message"]["token"] for s in _sends(calls)] == ["bad", "good"]
    assert {t.token for t in FirebaseToken.query.all()} == {"bad", "good"}
    assert f"fcm send failed: HTTP {status} {code}" in caplog.text


def test_a_schedule_change_request_pushes_the_recipients_own_notification(
        client, db, handover, fcm_http):
    calls, _ = fcm_http
    h = handover
    _device(db, h["b"], "dev-b")                            # the recipient
    _device(db, h["a"], "dev-a")                            # the sender: no push
    resp = schedule_change_helpers.send(client, h["a_h"], h["session"].id, h["b"].actor_id)
    assert resp.status_code == 201
    (sent,) = _sends(calls)
    message = sent["json"]["message"]
    assert message["token"] == "dev-b"
    note = Notification.query.filter_by(account_id=h["b"].id).one()
    assert message["data"]["kind"] == "schedule_change_request"
    assert message["data"]["notification_id"] == str(note.id)
    assert message["data"]["request_id"] == str(resp.get_json()["id"])
