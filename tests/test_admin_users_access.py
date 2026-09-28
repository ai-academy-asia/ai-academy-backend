"""Admin student/teacher records: auth guard and list (/admin/students, /admin/teachers)."""
import admin_user_helpers
import pytest
from admin_user_helpers import SEGMENTS

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
make_actor = admin_user_helpers.make_actor
sales_headers = admin_user_helpers.sales_headers


# ---------------------------------------------------------------- auth
@pytest.mark.parametrize("segment", SEGMENTS)
@pytest.mark.parametrize("method,suffix", [
    ("get", ""), ("post", ""), ("get", "/1"), ("patch", "/1"), ("delete", "/1"),
    ("post", "/1/reset-password"),
])
def test_requires_token(client, segment, method, suffix):
    resp = getattr(client, method)(f"/admin/{segment}{suffix}", json={})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


@pytest.mark.parametrize("segment", SEGMENTS)
def test_rejects_invalid_token(client, segment):
    resp = client.get(f"/admin/{segment}", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "invalid_token"


@pytest.mark.parametrize("segment", SEGMENTS)
@pytest.mark.parametrize("role", ["finance", "content_marketing"])
def test_forbidden_without_manage_permission(client, make_staff, segment, role):
    _, headers = make_staff(role)
    assert client.get(f"/admin/{segment}", headers=headers).status_code == 403
    resp = client.post(f"/admin/{segment}", json={}, headers=headers)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


@pytest.mark.parametrize("segment", SEGMENTS)
def test_forbidden_for_students_and_teachers(client, make_student, make_teacher, segment):
    for _, headers in (make_student(), make_teacher()):
        assert client.get(f"/admin/{segment}", headers=headers).status_code == 403


@pytest.mark.parametrize("segment", SEGMENTS)
def test_sales_enrollment_may_manage(client, sales_headers, make_actor, segment):
    make_actor(segment)
    resp = client.get(f"/admin/{segment}", headers=sales_headers)
    assert resp.status_code == 200
    assert resp.get_json()["total"] == 1


# ---------------------------------------------------------------- list
@pytest.mark.parametrize("segment", SEGMENTS)
def test_list_newest_first_with_accounts(client, admin_headers, make_actor, segment):
    first, _ = make_actor(segment, first_name="Anu")
    second, _ = make_actor(segment, first_name="Bold")
    body = client.get(f"/admin/{segment}", headers=admin_headers).get_json()
    assert body["total"] == 2
    assert body["limit"] == 50 and body["offset"] == 0
    assert [i["id"] for i in body["items"]] == [second.actor_id, first.actor_id]
    item = body["items"][0]
    assert item["profile"]["first_name"] == "Bold"
    assert item["account"]["email"] == second.email
    assert item["account"]["actor_type"] == segment[:-1]


@pytest.mark.parametrize("segment", SEGMENTS)
def test_list_search_matches_first_or_last_name(client, admin_headers, make_actor, segment):
    make_actor(segment, first_name="Anu", last_name="Bat")
    make_actor(segment, first_name="Bold", last_name="Dorj")
    make_actor(segment, first_name="Tsetseg", last_name="Khan")

    body = client.get(f"/admin/{segment}?q=an", headers=admin_headers).get_json()
    assert body["total"] == 2
    assert {i["profile"]["first_name"] for i in body["items"]} == {"Anu", "Tsetseg"}

    body = client.get(f"/admin/{segment}?q=DORJ", headers=admin_headers).get_json()
    assert [i["profile"]["first_name"] for i in body["items"]] == ["Bold"]


@pytest.mark.parametrize("segment", SEGMENTS)
def test_list_paginates_and_clamps(client, admin_headers, make_actor, segment):
    ids = [make_actor(segment)[0].actor_id for _ in range(3)]
    body = client.get(f"/admin/{segment}?limit=1&offset=1", headers=admin_headers).get_json()
    assert body["total"] == 3
    assert [i["id"] for i in body["items"]] == [ids[1]]

    body = client.get(f"/admin/{segment}?limit=999&offset=-5",
                      headers=admin_headers).get_json()
    assert body["limit"] == 200 and body["offset"] == 0
    assert len(body["items"]) == 3


@pytest.mark.parametrize("segment", SEGMENTS)
@pytest.mark.parametrize("query", ["limit=abc", "offset=x"])
def test_list_rejects_non_numeric_pagination(client, admin_headers, segment, query):
    resp = client.get(f"/admin/{segment}?{query}", headers=admin_headers)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_pagination"
