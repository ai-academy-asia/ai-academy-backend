"""Admin student/teacher records: update and deactivate."""
import admin_user_helpers
import pytest
from admin_user_helpers import MODELS, SEGMENTS, _fresh

from app.models import AuthAccount, RefreshToken, Student

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
make_actor = admin_user_helpers.make_actor


# ---------------------------------------------------------------- update
@pytest.mark.parametrize("segment", SEGMENTS)
def test_update_profile_and_email(client, admin_headers, make_actor, db, segment):
    account, _ = make_actor(segment)
    pid, aid = account.actor_id, account.id
    resp = client.patch(f"/admin/{segment}/{pid}", headers=admin_headers, json={
        "first_name": "Renamed", "phone": "95000000", "email": " Moved@Example.com",
        "role": "super_admin",  # not writable
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["profile"]["first_name"] == "Renamed"
    assert body["account"]["email"] == "moved@example.com"
    assert body["account"]["role"] == segment[:-1]
    assert _fresh(db, MODELS[segment], pid).phone == "95000000"
    assert _fresh(db, AuthAccount, aid).email == "moved@example.com"


@pytest.mark.parametrize("segment", SEGMENTS)
def test_update_email_clash_is_409(client, admin_headers, make_actor, make_staff, db, segment):
    account, _ = make_actor(segment)
    make_staff("finance", email="finance@example.com")
    resp = client.patch(f"/admin/{segment}/{account.actor_id}", headers=admin_headers,
                        json={"email": "finance@example.com", "first_name": "Changed"})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "email_taken"
    db.session.rollback()  # requests share the fixture's app context; mimic teardown
    assert _fresh(db, MODELS[segment], account.actor_id).first_name != "Changed"


@pytest.mark.parametrize("segment", SEGMENTS)
def test_update_keeping_own_email_is_ok(client, admin_headers, make_actor, segment):
    account, _ = make_actor(segment)
    resp = client.patch(f"/admin/{segment}/{account.actor_id}", headers=admin_headers,
                        json={"email": account.email.upper()})
    assert resp.status_code == 200


@pytest.mark.parametrize("segment", SEGMENTS)
def test_update_blank_email_is_400(client, admin_headers, make_actor, segment):
    account, _ = make_actor(segment)
    resp = client.patch(f"/admin/{segment}/{account.actor_id}", headers=admin_headers,
                        json={"email": "  "})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "email_required"


def test_update_student_bad_birth_date(client, admin_headers, make_student):
    account, _ = make_student()
    resp = client.patch(f"/admin/students/{account.actor_id}", headers=admin_headers,
                        json={"birth_date": "not-a-date"})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "invalid_date", "field": "birth_date"}


def test_update_student_can_clear_birth_date(client, admin_headers, make_student, db):
    account, _ = make_student()
    pid = account.actor_id
    client.patch(f"/admin/students/{pid}", headers=admin_headers,
                 json={"birth_date": "2010-01-01"})
    assert _fresh(db, Student, pid).birth_date is not None
    resp = client.patch(f"/admin/students/{pid}", headers=admin_headers,
                        json={"birth_date": None})
    assert resp.status_code == 200
    assert _fresh(db, Student, pid).birth_date is None


@pytest.mark.parametrize("segment", SEGMENTS)
def test_deactivate_revokes_sessions_and_blocks_token(
        client, admin_headers, make_actor, db, segment):
    account, headers = make_actor(segment)
    login = client.post("/auth/login", json={"email": account.email, "password": "Passw0rd!"})
    assert login.status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 200

    resp = client.patch(f"/admin/{segment}/{account.actor_id}", headers=admin_headers,
                        json={"is_active": False})
    assert resp.status_code == 200
    assert resp.get_json()["account"]["is_active"] is False
    db.session.expire_all()
    tokens = RefreshToken.query.filter_by(account_id=account.id).all()
    assert tokens and all(t.revoked_at is not None for t in tokens)

    resp = client.get("/auth/me", headers=headers)
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "account_inactive"

    resp = client.patch(f"/admin/{segment}/{account.actor_id}", headers=admin_headers,
                        json={"is_active": True})
    assert resp.get_json()["account"]["is_active"] is True
    assert client.get("/auth/me", headers=headers).status_code == 200


@pytest.mark.parametrize("segment", SEGMENTS)
def test_update_unknown_is_404(client, admin_headers, segment):
    resp = client.patch(f"/admin/{segment}/9999", headers=admin_headers, json={"phone": "1"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"
