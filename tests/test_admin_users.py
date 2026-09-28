"""Admin management of student and teacher records (/admin/students, /admin/teachers)."""
import pytest

from app.models import AuthAccount, RefreshToken, Student, Teacher

SEGMENTS = ["students", "teachers"]
MODELS = {"students": Student, "teachers": Teacher}


def _fresh(db, model, pk):
    db.session.expire_all()
    return db.session.get(model, pk)


@pytest.fixture
def make_actor(make_student, make_teacher):
    def _make(segment, **kwargs):
        maker = make_student if segment == "students" else make_teacher
        return maker(**kwargs)

    return _make


@pytest.fixture
def sales_headers(make_staff):
    return make_staff("sales_enrollment")[1]


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
