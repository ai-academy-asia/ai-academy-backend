"""Push tokens, the notify() service and an account's inbox."""
import pytest

from app.models import FirebaseToken, Notification
from app.services import notifications as notif_svc


def _push(client, headers, token="device-1", platform="android"):
    return client.post("/me/push-tokens", headers=headers,
                       json={"token": token, "platform": platform})


# ----------------------------------------------------------------- push tokens
def test_register_then_refresh_push_token(client, db, make_student):
    account, headers = make_student()
    resp = _push(client, headers)
    assert resp.status_code == 201
    first = resp.get_json()
    assert first["platform"] == "android"
    assert first["last_seen_at"].endswith("+00:00")
    again = _push(client, headers, platform="ios")
    assert again.status_code == 200
    assert again.get_json()["id"] == first["id"]
    row = FirebaseToken.query.one()
    assert (row.account_id, row.platform) == (account.id, "ios")


def test_push_token_moves_between_accounts(client, db, make_student, make_teacher):
    _, s_headers = make_student()
    teacher, t_headers = make_teacher()
    _push(client, s_headers)
    assert _push(client, t_headers).status_code == 200
    assert FirebaseToken.query.one().account_id == teacher.id


@pytest.mark.parametrize("data,code", [
    ({"platform": "ios"}, "token_required"),
    ({"token": "  ", "platform": "ios"}, "token_required"),
    ({"token": "x" * 513, "platform": "ios"}, "invalid_token"),
    ({"token": "abc", "platform": "symbian"}, "invalid_platform"),
])
def test_push_token_validation(client, make_student, data, code):
    resp = client.post("/me/push-tokens", headers=make_student()[1], json=data)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == code


def test_delete_push_token_only_own_and_idempotent(client, db, make_student, make_staff):
    _, mine = make_student()
    _, theirs = make_staff("finance")
    _push(client, theirs, token="their-device")
    resp = client.delete("/me/push-tokens", headers=mine, json={"token": "their-device"})
    assert resp.status_code == 200
    assert resp.get_json()["removed"] == 0
    assert FirebaseToken.query.count() == 1
    _push(client, mine, token="my-device")
    assert client.delete("/me/push-tokens", headers=mine,
                         json={"token": "my-device"}).get_json()["removed"] == 1
    assert client.delete("/me/push-tokens", headers=mine,
                         json={"token": "my-device"}).status_code == 200
    resp = client.delete("/me/push-tokens", headers=mine, json={})
    assert resp.get_json()["error"] == "token_required"


def test_push_tokens_need_login(client):
    assert client.post("/me/push-tokens", json={"token": "a", "platform": "ios"}).status_code \
        == 401
    assert client.delete("/me/push-tokens", json={"token": "a"}).status_code == 401


# ----------------------------------------------------------------- notify()
def test_notify_creates_rows_and_calls_push_hook(app, db, make_student, monkeypatch):
    a, _ = make_student()
    b, _ = make_student()
    calls = []
    monkeypatch.setattr("app.services.notifications.push.send_push",
                        lambda ids, **kw: calls.append((ids, kw)) or 0)
    with app.test_request_context():
        n = notif_svc.notify([a.id, b.id, a.id], kind="grade", title="Graded",
                             body="9/10", data={"lesson_id": 3})
    assert n == 2
    assert Notification.query.count() == 2
    assert calls[0][0] == sorted([a.id, b.id])
    assert calls[0][1]["kind"] == "grade"


def test_notify_survives_a_failing_push(app, make_student, monkeypatch):
    a, _ = make_student()

    def _boom(*args, **kwargs):
        raise RuntimeError("fcm down")

    monkeypatch.setattr("app.services.notifications.push.send_push", _boom)
    with app.test_request_context():
        assert notif_svc.notify([a.id], kind="general", title="Hi") == 1
        assert notif_svc.notify([], kind="general", title="Hi") == 0
    assert Notification.query.count() == 1


def test_send_push_is_a_no_op_without_fcm(app, make_student):
    a, _ = make_student()
    with app.test_request_context():
        assert notif_svc.send_push([a.id], kind="general", title="Hi") == 0


# ----------------------------------------------------------------- inbox
def _seed(app, account_id, count):
    with app.test_request_context():
        for i in range(count):
            notif_svc.notify([account_id], kind="general", title=f"N{i}")


def test_inbox_newest_first_with_paging_and_unread(client, app, make_student):
    account, headers = make_student()
    other, _ = make_student()
    _seed(app, account.id, 3)
    _seed(app, other.id, 1)
    data = client.get("/me/notifications", headers=headers).get_json()
    assert data["unread_count"] == 3
    assert [n["title"] for n in data["notifications"]] == ["N2", "N1", "N0"]
    first = data["notifications"][0]
    assert set(first) == {"id", "kind", "title", "body", "data", "read_at", "created_at"}
    page = client.get(f"/me/notifications?limit=1&before_id={first['id']}",
                      headers=headers).get_json()
    assert [n["title"] for n in page["notifications"]] == ["N1"]


def test_inbox_bad_params(client, make_student):
    headers = make_student()[1]
    assert client.get("/me/notifications?limit=x", headers=headers).get_json()["error"] \
        == "invalid_limit"
    assert client.get("/me/notifications?before_id=x", headers=headers).get_json()["error"] \
        == "invalid_before_id"
    assert client.get("/me/notifications").status_code == 401


def test_mark_read_and_read_all(client, app, make_student):
    account, headers = make_student()
    _seed(app, account.id, 3)
    ids = [n["id"] for n in client.get("/me/notifications", headers=headers)
           .get_json()["notifications"]]
    resp = client.post(f"/me/notifications/{ids[0]}/read", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["read_at"] is not None
    assert resp.get_json()["unread_count"] == 2
    read_at = resp.get_json()["read_at"]
    assert client.post(f"/me/notifications/{ids[0]}/read",
                       headers=headers).get_json()["read_at"] == read_at
    resp = client.post("/me/notifications/read-all", headers=headers)
    assert resp.get_json() == {"updated": 2, "unread_count": 0}
    assert client.get("/me/notifications", headers=headers).get_json()["unread_count"] == 0


def test_others_notification_is_404(client, app, make_student, make_teacher):
    owner, _ = make_student()
    _, intruder = make_teacher()
    _seed(app, owner.id, 1)
    nid = Notification.query.one().id
    resp = client.post(f"/me/notifications/{nid}/read", headers=intruder)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "notification_not_found"
    assert client.post("/me/notifications/read-all", headers=intruder).get_json()["updated"] \
        == 0
    assert Notification.query.one().read_at is None
