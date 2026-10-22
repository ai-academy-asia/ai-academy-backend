"""Auth endpoints: change-password."""


import auth_helpers
from auth_helpers import PASSWORD, _login

from app.models import AuthAccount, RefreshToken

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
student = auth_helpers.student


# ----------------------------------------------------------------- change-password
def test_change_password_signs_out_others_and_keeps_this_device(client, db, make_student):
    account, headers = make_student(email="new@student.test")
    account.must_change_password = True
    db.session.commit()
    other_device = _login(client, "new@student.test").get_json()["refresh_token"]

    resp = client.post("/auth/change-password", headers=headers,
                       json={"current_password": PASSWORD, "new_password": "BrandNew123"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok" and body["must_change_password"] is False
    assert body["access_token"] and body["refresh_token"] and body["actor"]["id"] == account.id

    db.session.expire_all()
    fresh = db.session.get(AuthAccount, account.id)
    assert fresh.must_change_password is False
    assert fresh.check_password("BrandNew123")
    assert RefreshToken.query.filter_by(revoked_at=None).count() == 1  # this device only
    assert client.post("/auth/refresh",
                       json={"refresh_token": other_device}).status_code == 401
    # The new pair outlives the access token: refreshing keeps the device signed in.
    again = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert again.status_code == 200
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
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
