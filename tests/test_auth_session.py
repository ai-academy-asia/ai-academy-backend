"""Auth endpoints: logout, /me and the bearer-token middleware
(exercised through /auth/me)."""
from datetime import datetime, timedelta, timezone

import auth_helpers
import jwt
import pytest
from auth_helpers import _bearer, _login

from app.models import RefreshToken

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
student = auth_helpers.student


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
