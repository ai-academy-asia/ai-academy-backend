"""Admin student/teacher records: delete and reset password."""
import admin_user_helpers
import pytest
from admin_user_helpers import MODELS, SEGMENTS, _fresh

from app.models import AuthAccount, RefreshToken, Student, Teacher

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
make_actor = admin_user_helpers.make_actor


# ---------------------------------------------------------------- delete
@pytest.mark.parametrize("segment", SEGMENTS)
def test_delete_removes_profile_account_and_tokens(
        client, admin_headers, make_actor, db, segment):
    account, headers = make_actor(segment)
    pid, aid = account.actor_id, account.id
    client.post("/auth/login", json={"email": account.email, "password": "Passw0rd!"})

    resp = client.delete(f"/admin/{segment}/{pid}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "deleted"}
    assert _fresh(db, MODELS[segment], pid) is None
    assert db.session.get(AuthAccount, aid) is None
    assert RefreshToken.query.filter_by(account_id=aid).count() == 0
    assert client.get("/auth/me", headers=headers).status_code == 401


@pytest.mark.parametrize("segment", SEGMENTS)
def test_delete_unknown_is_404(client, admin_headers, segment):
    resp = client.delete(f"/admin/{segment}/9999", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_delete_profile_without_account(client, admin_headers, db):
    teacher = Teacher(first_name="Orphan")
    db.session.add(teacher)
    db.session.commit()
    tid = teacher.id
    assert client.delete(f"/admin/teachers/{tid}", headers=admin_headers).status_code == 200
    assert _fresh(db, Teacher, tid) is None


# ---------------------------------------------------------------- reset password
@pytest.mark.parametrize("segment", SEGMENTS)
def test_reset_password_sets_new_and_forces_change(
        client, admin_headers, make_actor, db, segment):
    account, _ = make_actor(segment)
    client.post("/auth/login", json={"email": account.email, "password": "Passw0rd!"})

    resp = client.post(f"/admin/{segment}/{account.actor_id}/reset-password",
                       headers=admin_headers, json={"new_password": "BrandNew99"})
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}

    row = _fresh(db, AuthAccount, account.id)
    assert row.check_password("BrandNew99")
    assert not row.check_password("Passw0rd!")
    assert row.must_change_password is True
    assert all(t.revoked_at is not None
               for t in RefreshToken.query.filter_by(account_id=account.id))
    old = client.post("/auth/login", json={"email": account.email, "password": "Passw0rd!"})
    assert old.status_code == 401
    new = client.post("/auth/login", json={"email": account.email, "password": "BrandNew99"})
    assert new.status_code == 200


@pytest.mark.parametrize("segment", SEGMENTS)
@pytest.mark.parametrize("payload", [{}, {"new_password": "short"}])
def test_reset_password_rejects_weak(client, admin_headers, make_actor, db, segment, payload):
    account, _ = make_actor(segment)
    resp = client.post(f"/admin/{segment}/{account.actor_id}/reset-password",
                       headers=admin_headers, json=payload)
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "weak_password", "min_length": 8}
    assert _fresh(db, AuthAccount, account.id).check_password("Passw0rd!")


@pytest.mark.parametrize("segment", SEGMENTS)
def test_reset_password_unknown_profile_is_404(client, admin_headers, segment):
    resp = client.post(f"/admin/{segment}/9999/reset-password", headers=admin_headers,
                       json={"new_password": "BrandNew99"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_reset_password_without_account_is_404(client, admin_headers, db):
    student = Student(first_name="Orphan")
    db.session.add(student)
    db.session.commit()
    resp = client.post(f"/admin/students/{student.id}/reset-password", headers=admin_headers,
                       json={"new_password": "BrandNew99"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "account_not_found"
