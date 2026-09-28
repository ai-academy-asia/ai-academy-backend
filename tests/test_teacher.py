"""Derived schedules: a teacher's own cohorts and a classroom's cohorts."""
from datetime import date

import pytest


# ----------------------------------------------------------------- GET /teachers/<id>/schedule
def test_teacher_sees_own_schedule_in_date_order(client, make_teacher, make_cohort):
    account, headers = make_teacher()
    tid = account.actor_id
    later = make_cohort(teacher_id=tid, start_date=date(2027, 1, 1), end_date=date(2027, 2, 1))
    sooner = make_cohort(teacher_id=tid, status="draft")
    make_cohort()  # someone else's

    resp = client.get(f"/teachers/{tid}/schedule", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["teacher_id"] == tid
    assert [c["id"] for c in data["cohorts"]] == [sooner.id, later.id]
    assert data["cohorts"][0]["teacher"]["id"] == tid


def test_teacher_schedule_empty(client, make_teacher):
    account, headers = make_teacher()
    resp = client.get(f"/teachers/{account.actor_id}/schedule", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["cohorts"] == []


@pytest.mark.parametrize("role", ["super_admin", "sales_enrollment"])
def test_scheduling_staff_can_view_any_teacher(client, make_teacher, make_staff,
                                               make_cohort, role):
    account, _ = make_teacher()
    cohort = make_cohort(teacher_id=account.actor_id)
    resp = client.get(f"/teachers/{account.actor_id}/schedule", headers=make_staff(role)[1])
    assert resp.status_code == 200
    assert [c["id"] for c in resp.get_json()["cohorts"]] == [cohort.id]


def test_teacher_schedule_anonymous_is_401(client, make_teacher):
    account, _ = make_teacher()
    resp = client.get(f"/teachers/{account.actor_id}/schedule")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


def test_other_teacher_is_forbidden(client, make_teacher):
    target, _ = make_teacher()
    _, other_headers = make_teacher()
    resp = client.get(f"/teachers/{target.actor_id}/schedule", headers=other_headers)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


def test_student_and_unrelated_staff_are_forbidden(client, make_teacher, make_student,
                                                   make_staff):
    target, _ = make_teacher()
    for headers in (make_student()[1], make_staff("finance")[1],
                    make_staff("content_marketing")[1]):
        resp = client.get(f"/teachers/{target.actor_id}/schedule", headers=headers)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "forbidden"


def test_student_whose_id_matches_teacher_id_is_still_forbidden(client, make_teacher,
                                                                make_student):
    teacher, _ = make_teacher()
    student, headers = make_student()
    assert student.actor_id == teacher.actor_id
    resp = client.get(f"/teachers/{teacher.actor_id}/schedule", headers=headers)
    assert resp.status_code == 403


def test_unknown_teacher_is_404_for_staff(client, admin_headers):
    resp = client.get("/teachers/999/schedule", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


# ----------------------------------------------------------------- GET /classrooms/<id>/schedule
@pytest.mark.parametrize("role", ["super_admin", "sales_enrollment"])
def test_classroom_schedule_for_scheduling_staff(client, make_classroom, make_cohort,
                                                 make_staff, role):
    room = make_classroom()
    later = make_cohort(classroom_id=room.id, start_date=date(2027, 3, 1),
                        end_date=date(2027, 4, 1))
    sooner = make_cohort(classroom_id=room.id)
    make_cohort()

    resp = client.get(f"/classrooms/{room.id}/schedule", headers=make_staff(role)[1])
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["classroom_id"] == room.id
    assert [c["id"] for c in data["cohorts"]] == [sooner.id, later.id]
    assert data["cohorts"][0]["classroom"]["id"] == room.id


def test_classroom_schedule_anonymous_is_401(client, make_classroom):
    room = make_classroom()
    resp = client.get(f"/classrooms/{room.id}/schedule")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


def test_classroom_schedule_forbidden_without_permission(client, make_classroom, make_staff,
                                                         make_teacher, make_student):
    room = make_classroom()
    for headers in (make_staff("finance")[1], make_teacher()[1], make_student()[1]):
        resp = client.get(f"/classrooms/{room.id}/schedule", headers=headers)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "forbidden"


def test_classroom_schedule_unknown_is_404(client, admin_headers):
    resp = client.get("/classrooms/999/schedule", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"
