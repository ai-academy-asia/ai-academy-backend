"""Auth endpoints: login and refresh-token rotation."""
from datetime import datetime, timedelta

import auth_helpers
import pytest
from auth_helpers import PASSWORD, _bearer, _login

from app.models import AuthAccount, RefreshToken

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
student = auth_helpers.student


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
