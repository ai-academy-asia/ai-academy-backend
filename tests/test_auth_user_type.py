"""`user_type` on login / refresh / me: adult, child, teacher or staff."""
from datetime import date

import pytest
from auth_helpers import _bearer, _login

from app.auth.user_type import user_type
from app.models import Enrollment, Student


def _set_student(db, account, **fields):
    student = db.session.get(Student, account.actor_id)
    for key, value in fields.items():
        setattr(student, key, value)
    db.session.commit()


def _type_on_login(client, account):
    resp = _login(client, account.email)
    assert resp.status_code == 200
    return resp.get_json()["user_type"]


# ---------------------------------------------------------------- per actor
def test_teacher_and_staff(client, make_teacher, make_staff):
    teacher, _ = make_teacher()
    staff, _ = make_staff("finance")
    assert _type_on_login(client, teacher) == "teacher"
    assert _type_on_login(client, staff) == "staff"


def test_student_defaults_to_adult(client, make_student):
    account, _ = make_student()
    assert _type_on_login(client, account) == "adult"


@pytest.mark.parametrize("ui_mode,expected", [("kids", "child"), ("adult", "adult")])
def test_admin_ui_mode_wins_over_birth_date(client, db, make_student, ui_mode, expected):
    account, _ = make_student()
    # Birth date says the opposite; the explicit setting decides.
    born = date(1990, 1, 1) if ui_mode == "kids" else date(2016, 1, 1)
    _set_student(db, account, ui_mode=ui_mode, birth_date=born)
    assert _type_on_login(client, account) == expected


def test_birth_date_decides_without_ui_mode(client, db, make_student):
    kid, _ = make_student()
    grown, _ = make_student()
    _set_student(db, kid, birth_date=date(2014, 5, 1))
    _set_student(db, grown, birth_date=date(1995, 5, 1))
    assert _type_on_login(client, kid) == "child"
    assert _type_on_login(client, grown) == "adult"


def test_eighteenth_birthday_is_the_boundary(db, make_student):
    account, _ = make_student()
    _set_student(db, account, birth_date=date(2008, 10, 15))
    assert user_type(account, today=date(2026, 10, 14)) == "child"
    assert user_type(account, today=date(2026, 10, 15)) == "adult"


def test_junior_course_enrollment_means_child(client, db, make_student, make_course,
                                             make_cohort):
    account, _ = make_student()
    cohort = make_cohort(course=make_course(level="junior"))
    db.session.add(Enrollment(cohort_id=cohort.id, student_id=account.actor_id,
                              course_id=cohort.course_id, status="active"))
    db.session.commit()
    assert _type_on_login(client, account) == "child"


def test_cancelled_junior_enrollment_does_not_count(client, db, make_student, make_course,
                                                   make_cohort):
    account, _ = make_student()
    cohort = make_cohort(course=make_course(level="junior"))
    db.session.add(Enrollment(cohort_id=cohort.id, student_id=account.actor_id,
                              course_id=cohort.course_id, status="cancelled"))
    db.session.commit()
    assert _type_on_login(client, account) == "adult"


# ---------------------------------------------------------------- every auth response
def test_present_on_refresh_me_and_profile_update(client, db, make_student):
    account, _ = make_student()
    _set_student(db, account, ui_mode="kids")
    tokens = _login(client, account.email).get_json()

    refreshed = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.get_json()["user_type"] == "child"
    me = client.get("/auth/me", headers=_bearer(tokens["access_token"]))
    assert me.get_json()["user_type"] == "child"
    assert me.get_json()["actor_type"] == "student"
    profile = client.patch("/me/profile", headers=_bearer(tokens["access_token"]),
                           json={"first_name": "Бат"})
    assert profile.get_json()["user_type"] == "child"


# ---------------------------------------------------------------- admin override
def test_admin_can_set_and_clear_ui_mode(client, db, admin_headers, make_student):
    account, _ = make_student()
    _set_student(db, account, birth_date=date(2014, 1, 1))
    path = f"/admin/students/{account.actor_id}"

    assert client.patch(path, headers=admin_headers, json={"ui_mode": "adult"}).status_code == 200
    assert _type_on_login(client, account) == "adult"
    assert client.patch(path, headers=admin_headers, json={"ui_mode": ""}).status_code == 200
    assert _type_on_login(client, account) == "child"      # birth date decides again


def test_admin_rejects_unknown_ui_mode(client, admin_headers, make_student):
    account, _ = make_student()
    resp = client.patch(f"/admin/students/{account.actor_id}", headers=admin_headers,
                        json={"ui_mode": "teen"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_ui_mode"
