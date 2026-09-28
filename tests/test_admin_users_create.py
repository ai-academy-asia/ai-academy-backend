"""Admin student/teacher records: create and get."""
import admin_user_helpers
import pytest
from admin_user_helpers import MODELS, SEGMENTS

from app.models import AuthAccount, Student, Teacher

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
make_actor = admin_user_helpers.make_actor


# ---------------------------------------------------------------- create
@pytest.mark.parametrize("segment", SEGMENTS)
def test_create_provisions_profile_and_account(client, admin_headers, db, segment):
    resp = client.post(f"/admin/{segment}", headers=admin_headers, json={
        "email": "  New@Example.COM ", "password": "Secret123!",
        "first_name": "Saraa", "last_name": "Bat", "phone": "99112233",
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["profile"]["first_name"] == "Saraa"
    assert body["profile"]["phone"] == "99112233"
    account = body["account"]
    assert account["email"] == "new@example.com"
    assert account["role"] == segment[:-1]
    assert account["must_change_password"] is True
    assert account["is_active"] is True

    row = AuthAccount.query.filter_by(email="new@example.com").one()
    assert row.actor_id == body["id"]
    assert row.check_password("Secret123!")
    assert db.session.get(MODELS[segment], body["id"]) is not None


def test_create_student_sets_student_only_fields(client, admin_headers, db):
    resp = client.post("/admin/students", headers=admin_headers, json={
        "email": "kid@example.com", "password": "Secret123!", "first_name": "Temuulen",
        "birth_date": "2014-05-01", "ui_mode": "kids",
        "parent_name": "Oyun", "parent_phone": "88001122", "bio": "ignored",
    })
    assert resp.status_code == 201
    student = db.session.get(Student, resp.get_json()["id"])
    assert student.birth_date.isoformat() == "2014-05-01"
    assert student.ui_mode == "kids"
    assert student.parent_name == "Oyun"


def test_create_teacher_sets_bio(client, admin_headers, db):
    resp = client.post("/admin/teachers", headers=admin_headers, json={
        "email": "t@example.com", "password": "Secret123!", "first_name": "Dorj",
        "bio": "ML engineer",
    })
    assert resp.status_code == 201
    assert db.session.get(Teacher, resp.get_json()["id"]).bio == "ML engineer"


@pytest.mark.parametrize("segment", SEGMENTS)
@pytest.mark.parametrize("payload,error", [
    ({}, "email_and_password_required"),
    ({"email": "a@b.c", "first_name": "A"}, "email_and_password_required"),
    ({"password": "Secret123!", "first_name": "A"}, "email_and_password_required"),
    ({"email": "a@b.c", "password": "Secret123!"}, "first_name_required"),
    ({"email": "   ", "password": "Secret123!", "first_name": "A"}, "email_required"),
])
def test_create_validates_required_fields(client, admin_headers, segment, payload, error):
    resp = client.post(f"/admin/{segment}", headers=admin_headers, json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == error
    assert AuthAccount.query.count() == 1  # only the admin


def test_create_student_rejects_bad_birth_date(client, admin_headers):
    resp = client.post("/admin/students", headers=admin_headers, json={
        "email": "a@b.c", "password": "Secret123!", "first_name": "A",
        "birth_date": "01/05/2014",
    })
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "invalid_date", "field": "birth_date"}


@pytest.mark.parametrize("segment", SEGMENTS)
def test_create_rejects_taken_email_across_actor_types(
        client, admin_headers, make_student, db, segment):
    make_student(email="taken@example.com")
    resp = client.post(f"/admin/{segment}", headers=admin_headers, json={
        "email": "TAKEN@example.com", "password": "Secret123!", "first_name": "A",
    })
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "email_taken"
    assert MODELS[segment].query.count() == (1 if segment == "students" else 0)


# ---------------------------------------------------------------- get
@pytest.mark.parametrize("segment", SEGMENTS)
def test_get_returns_profile_and_account(client, admin_headers, make_actor, segment):
    account, _ = make_actor(segment, first_name="Anu")
    resp = client.get(f"/admin/{segment}/{account.actor_id}", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == account.actor_id
    assert body["profile"]["first_name"] == "Anu"
    assert body["account"]["id"] == account.id


@pytest.mark.parametrize("segment", SEGMENTS)
def test_get_unknown_is_404(client, admin_headers, segment):
    resp = client.get(f"/admin/{segment}/9999", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_segments_do_not_leak_into_each_other(client, admin_headers, make_student):
    account, _ = make_student()
    # student id 1 has no teacher counterpart
    assert client.get(f"/admin/teachers/{account.actor_id}",
                      headers=admin_headers).status_code == 404


def test_get_profile_without_account_has_null_account(client, admin_headers, db):
    student = Student(first_name="Orphan")
    db.session.add(student)
    db.session.commit()
    body = client.get(f"/admin/students/{student.id}", headers=admin_headers).get_json()
    assert body["account"] is None
    assert body["profile"]["first_name"] == "Orphan"
