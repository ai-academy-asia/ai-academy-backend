"""Auth endpoints: login, refresh rotation, logout, /me, change-password, and
the bearer-token middleware (exercised through /auth/me)."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.models import AuthAccount, RefreshToken

PASSWORD = "Passw0rd!"


def _login(client, email, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def student(make_student):
    account, headers = make_student(email="bat@student.test")
    return account, headers


# ----------------------------------------------------------------- login
def test_login_returns_token_pair_and_actor(client, db, student):
    resp = _login(client, "  BAT@Student.test ")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["token_type"] == "Bearer"
    assert data["access_token"] and data["refresh_token"]
    assert data["expires_in"] == 3600
    assert data["refresh_expires_in"] == 30 * 24 * 60 * 60
    assert data["must_change_password"] is False
    assert data["actor"]["email"] == "bat@student.test"
    assert data["actor"]["actor_type"] == "student"
    assert data["actor"]["profile"]["first_name"] == "Bat"

    account = db.session.get(AuthAccount, student[0].id)
    assert account.last_login_at is not None
    assert RefreshToken.query.filter_by(account_id=account.id).count() == 1

    me = client.get("/auth/me", headers=_bearer(data["access_token"]))
    assert me.status_code == 200


def test_login_staff_gets_short_refresh_ttl(client, make_staff):
    make_staff("finance", email="fin@staff.test")
    resp = _login(client, "fin@staff.test")
    assert resp.status_code == 200
    assert resp.get_json()["refresh_expires_in"] == 12 * 60 * 60


@pytest.mark.parametrize("payload", [
    {}, {"email": "bat@student.test"}, {"password": PASSWORD}, {"email": " ", "password": "x"},
])
def test_login_requires_email_and_password(client, student, payload):
    resp = client.post("/auth/login", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "email_and_password_required"


def test_login_without_json_body_is_400(client):
    resp = client.post("/auth/login", data="not json")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "email_and_password_required"


def test_login_wrong_password_and_unknown_email_look_the_same(client, student):
    wrong = _login(client, "bat@student.test", "nope-nope")
    unknown = _login(client, "ghost@student.test")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_json() == unknown.get_json() == {"error": "invalid_credentials"}


def test_login_inactive_account_is_403(client, db, student):
    student[0].is_active = False
    db.session.commit()
    resp = _login(client, "bat@student.test")
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "account_inactive"
    assert RefreshToken.query.count() == 0


# ----------------------------------------------------------------- refresh
def test_refresh_rotates_token(client, db, student):
    first = _login(client, "bat@student.test").get_json()["refresh_token"]
    resp = client.post("/auth/refresh", json={"refresh_token": first})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["refresh_token"] != first
    assert data["access_token"]
    assert data["actor"]["id"] == student[0].id

    rows = RefreshToken.query.order_by(RefreshToken.id).all()
    assert len(rows) == 2
    assert rows[0].revoked_at is not None and rows[0].replaced_by_id == rows[1].id
    assert rows[1].revoked_at is None

    again = client.post("/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert again.status_code == 200


def test_refresh_requires_token(client):
    resp = client.post("/auth/refresh", json={})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "refresh_token_required"


def test_refresh_unknown_token(client):
    resp = client.post("/auth/refresh", json={"refresh_token": "garbage"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "invalid_refresh_token"


def test_refresh_reuse_revokes_whole_family(client, db, student):
    old = _login(client, "bat@student.test").get_json()["refresh_token"]
    other_device = _login(client, "bat@student.test").get_json()["refresh_token"]
    new = client.post("/auth/refresh", json={"refresh_token": old}).get_json()["refresh_token"]

    resp = client.post("/auth/refresh", json={"refresh_token": old})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "refresh_token_reused"

    assert RefreshToken.query.filter_by(revoked_at=None).count() == 0
    for token in (new, other_device):
        r = client.post("/auth/refresh", json={"refresh_token": token})
        assert r.status_code == 401
        assert r.get_json()["error"] == "refresh_token_revoked"


def test_refresh_logged_out_token_is_revoked_not_reused(client, student):
    a = _login(client, "bat@student.test").get_json()["refresh_token"]
    b = _login(client, "bat@student.test").get_json()["refresh_token"]
    client.post("/auth/logout", json={"refresh_token": a})

    resp = client.post("/auth/refresh", json={"refresh_token": a})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "refresh_token_revoked"
    # The other session survives a plain revoked-token rejection.
    assert client.post("/auth/refresh", json={"refresh_token": b}).status_code == 200


def test_refresh_expired_token(client, db, student):
    raw = _login(client, "bat@student.test").get_json()["refresh_token"]
    row = RefreshToken.query.one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    resp = client.post("/auth/refresh", json={"refresh_token": raw})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "refresh_token_expired"


def test_refresh_inactive_account(client, db, student):
    raw = _login(client, "bat@student.test").get_json()["refresh_token"]
    student[0].is_active = False
    db.session.commit()
    resp = client.post("/auth/refresh", json={"refresh_token": raw})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "account_inactive"


# ----------------------------------------------------------------- logout
def test_logout_revokes_only_that_token_and_is_idempotent(client, db, student):
    a = _login(client, "bat@student.test").get_json()["refresh_token"]
    _login(client, "bat@student.test")

    for _ in range(2):
        resp = client.post("/auth/logout", json={"refresh_token": a})
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok"}
    assert RefreshToken.query.filter(RefreshToken.revoked_at.isnot(None)).count() == 1


def test_logout_without_token_or_unknown_token_is_ok(client):
    assert client.post("/auth/logout", json={}).status_code == 200
    assert client.post("/auth/logout", json={"refresh_token": "nope"}).status_code == 200


def test_logout_all_revokes_every_session(client, db, student, make_student):
    _login(client, "bat@student.test")
    _login(client, "bat@student.test")
    make_student(email="other@student.test")
    _login(client, "other@student.test")

    resp = client.post("/auth/logout-all", headers=student[1])
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "revoked": 2}
    assert RefreshToken.query.filter_by(
        account_id=student[0].id, revoked_at=None).count() == 0
    assert RefreshToken.query.filter_by(revoked_at=None).count() == 1


def test_logout_all_requires_auth(client):
    resp = client.post("/auth/logout-all")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


# ----------------------------------------------------------------- /me + middleware
def test_me_returns_current_account(client, make_teacher):
    account, headers = make_teacher(first_name="Dorj")
    resp = client.get("/auth/me", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == account.id
    assert data["actor_type"] == "teacher"
    assert data["actor_id"] == account.actor_id
    assert data["profile"]["first_name"] == "Dorj"


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": "Bearer "}, {"Authorization": "Basic abc"},
])
def test_me_without_token_is_401(client, headers):
    resp = client.get("/auth/me", headers=headers)
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


def _jwt(app, **overrides):
    now = datetime.now(timezone.utc)
    payload = {"sub": "1", "type": "access", "iat": now, "exp": now + timedelta(hours=1)}
    payload.update(overrides)
    return jwt.encode(payload, app.config["JWT_SECRET"], algorithm="HS256")


def test_me_with_garbage_token_is_invalid(client):
    resp = client.get("/auth/me", headers=_bearer("not-a-jwt"))
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "invalid_token"


def test_me_with_wrong_signature_is_invalid(client, student):
    token = jwt.encode({"sub": str(student[0].id), "type": "access"}, "other-secret",
                       algorithm="HS256")
    resp = client.get("/auth/me", headers=_bearer(token))
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "invalid_token"


def test_me_with_expired_token(app, client, student):
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    token = _jwt(app, sub=str(student[0].id), iat=past, exp=past + timedelta(minutes=1))
    resp = client.get("/auth/me", headers=_bearer(token))
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "token_expired"


def test_me_rejects_non_access_token_type(app, client, student):
    token = _jwt(app, sub=str(student[0].id), type="refresh")
    resp = client.get("/auth/me", headers=_bearer(token))
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "invalid_token"


@pytest.mark.parametrize("sub", [None, "abc"])
def test_me_rejects_token_with_bad_subject(app, client, sub):
    now = datetime.now(timezone.utc)
    payload = {"type": "access", "exp": now + timedelta(hours=1)}
    if sub is not None:
        payload["sub"] = sub
    token = jwt.encode(payload, app.config["JWT_SECRET"], algorithm="HS256")
    resp = client.get("/auth/me", headers=_bearer(token))
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "invalid_token"


def test_me_rejects_inactive_account_with_valid_token(client, db, student):
    student[0].is_active = False
    db.session.commit()
    resp = client.get("/auth/me", headers=student[1])
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "account_inactive"


def test_me_rejects_token_for_deleted_account(app, client):
    resp = client.get("/auth/me", headers=_bearer(_jwt(app, sub="9999")))
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "account_inactive"


# ----------------------------------------------------------------- change-password
def test_change_password_updates_hash_and_revokes_sessions(client, db, make_student):
    account, headers = make_student(email="new@student.test")
    account.must_change_password = True
    db.session.commit()
    _login(client, "new@student.test")

    resp = client.post("/auth/change-password", headers=headers,
                       json={"current_password": PASSWORD, "new_password": "BrandNew123"})
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}

    db.session.expire_all()
    fresh = db.session.get(AuthAccount, account.id)
    assert fresh.must_change_password is False
    assert fresh.check_password("BrandNew123")
    assert RefreshToken.query.filter_by(revoked_at=None).count() == 0
    assert _login(client, "new@student.test").status_code == 401
    assert _login(client, "new@student.test", "BrandNew123").status_code == 200


def test_change_password_wrong_current(client, student):
    resp = client.post("/auth/change-password", headers=student[1],
                       json={"current_password": "wrong", "new_password": "BrandNew123"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "invalid_credentials"


def test_change_password_too_short(client, student):
    resp = client.post("/auth/change-password", headers=student[1],
                       json={"current_password": PASSWORD, "new_password": "short"})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "weak_password", "min_length": 8}


def test_change_password_must_differ(client, student):
    resp = client.post("/auth/change-password", headers=student[1],
                       json={"current_password": PASSWORD, "new_password": PASSWORD})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "password_unchanged"


def test_change_password_requires_auth(client):
    resp = client.post("/auth/change-password",
                       json={"current_password": PASSWORD, "new_password": "BrandNew123"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"
