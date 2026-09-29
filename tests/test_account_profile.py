"""PATCH /me/profile — a student or teacher edits their own profile."""
import pytest


def test_student_updates_profile(client, db, make_student):
    account, headers = make_student()
    resp = client.patch("/me/profile", headers=headers, json={
        "first_name": "  Сараа ", "last_name": "Бат", "phone": "+976 9911-2233",
        "email": "evil@x.test", "role": "super_admin", "bio": "ignored for students",
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["email"] == account.email and body["role"] == "student"
    assert body["profile"]["first_name"] == "Сараа"
    assert body["profile"]["last_name"] == "Бат"
    assert body["profile"]["phone"] == "+976 9911-2233"
    assert body == client.get("/auth/me", headers=headers).get_json()


def test_partial_update_keeps_other_fields(client, make_student):
    _, headers = make_student(first_name="Bat", last_name="Dorj", phone="99112233")
    body = client.patch("/me/profile", headers=headers, json={"last_name": ""}).get_json()
    assert body["profile"] == {**body["profile"], "first_name": "Bat", "last_name": None,
                               "phone": "99112233"}
    body = client.patch("/me/profile", headers=headers, json={"phone": ""}).get_json()
    assert body["profile"]["phone"] is None


def test_teacher_can_set_bio(client, db, make_teacher):
    from app.models import Teacher

    account, headers = make_teacher()
    body = client.patch("/me/profile", headers=headers,
                        json={"bio": "AI багш", "first_name": "Дорж"}).get_json()
    assert body["profile"]["bio"] == "AI багш" and body["profile"]["first_name"] == "Дорж"
    db.session.expire_all()
    assert db.session.get(Teacher, account.actor_id).bio == "AI багш"


@pytest.mark.parametrize("value", ["", "   ", None, 5])
def test_first_name_required(client, make_student, value):
    _, headers = make_student()
    resp = client.patch("/me/profile", headers=headers, json={"first_name": value})
    assert resp.status_code == 400 and resp.get_json()["error"] == "first_name_required"


@pytest.mark.parametrize("value", ["abc", "9911#2233", "1" * 21, 99112233])
def test_invalid_phone(client, make_student, value):
    _, headers = make_student()
    resp = client.patch("/me/profile", headers=headers, json={"phone": value})
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_phone"


def test_overlong_name_is_400(client, make_student):
    _, headers = make_student()
    resp = client.patch("/me/profile", headers=headers, json={"last_name": "x" * 101})
    assert resp.status_code == 400 and resp.get_json()["error"] == "field_too_long"


def test_failed_validation_changes_nothing(client, db, make_student):
    from app.models import Student

    account, headers = make_student(first_name="Bat")
    client.patch("/me/profile", headers=headers, json={"first_name": "New", "phone": "bad!"})
    db.session.expire_all()
    assert db.session.get(Student, account.actor_id).first_name == "Bat"


def test_staff_and_anonymous_rejected(client, make_staff):
    assert client.patch("/me/profile", json={"first_name": "X"}).status_code == 401
    resp = client.patch("/me/profile", headers=make_staff("super_admin")[1],
                        json={"first_name": "X"})
    assert resp.status_code == 403 and resp.get_json()["error"] == "forbidden"
