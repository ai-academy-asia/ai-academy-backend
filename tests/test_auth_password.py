"""Auth endpoints: change-password."""


import auth_helpers
from auth_helpers import PASSWORD, _login

from app.models import AuthAccount, RefreshToken

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
student = auth_helpers.student


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
