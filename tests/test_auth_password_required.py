"""``must_change_password`` is enforced by the server (BE-25), not only by the app."""
import pytest
from auth_helpers import PASSWORD


@pytest.fixture
def pending(db, make_student):
    """A student who has not yet replaced the password they were given."""
    account, headers = make_student()
    account.must_change_password = True
    db.session.commit()
    return account, headers


@pytest.mark.parametrize("method, url", [
    ("get", "/me/ledger"),
    ("get", "/me/cohorts"),
    ("get", "/me/notifications"),
    ("post", "/payments/invoices"),
])
def test_everything_but_auth_is_refused(client, pending, method, url):
    resp = getattr(client, method)(url, headers=pending[1], json={})
    assert resp.status_code == 403
    assert resp.get_json() == {"error": "password_change_required"}


def test_staff_routes_are_refused_too(client, db, make_staff):
    account, headers = make_staff("finance")
    account.must_change_password = True
    db.session.commit()
    resp = client.get("/admin/invoices", headers=headers)
    assert (resp.status_code, resp.get_json()["error"]) == (403, "password_change_required")


def test_auth_routes_stay_open_and_the_change_lifts_the_block(client, pending):
    account, headers = pending
    assert client.get("/auth/me", headers=headers).status_code == 200
    resp = client.post("/auth/change-password", headers=headers,
                       json={"current_password": PASSWORD, "new_password": "BrandNew123"})
    assert resp.status_code == 200
    fresh = {"Authorization": f"Bearer {resp.get_json()['access_token']}"}
    assert client.get("/me/ledger", headers=fresh).status_code == 200
    assert client.get("/me/ledger", headers=headers).status_code == 200  # same account


def test_public_routes_ignore_the_flag(client, pending):
    assert client.get("/courses", headers=pending[1]).status_code == 200
