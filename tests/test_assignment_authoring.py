"""Assignment authoring: /teacher/cohorts/<id>/assignments and /teacher/assignments/<id>."""
import assignment_helpers
import pytest
from assignment_helpers import add_lesson

from app.models import Assignment, LessonMaterial

hw = assignment_helpers.hw
make_assignment = assignment_helpers.make_assignment
make_submission = assignment_helpers.make_submission


def _create(client, hw, headers=None, **fields):
    payload = {"title_mn": "Гэрийн даалгавар", **fields}
    return client.post(f"/teacher/cohorts/{hw.cohort.id}/assignments",
                       headers=headers or hw.teacher_headers, json=payload)


# ----------------------------------------------------------------- create / list / get
def test_teacher_creates_assignment(client, hw):
    resp = _create(client, hw, title_en="Homework", instructions_mn="Хий",
                   due_date="2026-12-01", max_score=100, lesson_id=hw.lesson.id,
                   attachment_material_id=hw.material.id)
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["title"] == {"mn": "Гэрийн даалгавар", "en": "Homework"}
    assert body["cohort_id"] == hw.cohort.id and body["lesson_id"] == hw.lesson.id
    assert body["teacher_id"] == hw.teacher.actor_id
    assert body["due_date"] == "2026-12-01" and body["max_score"] == 100
    assert body["attachment"]["id"] == hw.material.id
    assert body["is_active"] is True and body["submitted_students"] == 0


def test_manager_creates_with_cohort_teacher(client, hw, make_staff):
    resp = _create(client, hw, headers=make_staff("sales_enrollment")[1])
    assert resp.status_code == 201
    assert resp.get_json()["teacher_id"] == hw.teacher.actor_id


def test_list_includes_inactive_and_counts(client, hw, make_assignment, make_submission,
                                          make_cohort):
    a = make_assignment(hw.cohort)
    b = make_assignment(hw.cohort, is_active=False)
    make_assignment(make_cohort(course=hw.course))
    make_submission(a, hw.sid, version=1)
    make_submission(a, hw.sid, version=2)
    resp = client.get(f"/teacher/cohorts/{hw.cohort.id}/assignments",
                      headers=hw.teacher_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert [x["id"] for x in data["assignments"]] == [a.id, b.id]
    assert data["assignments"][0]["submitted_students"] == 1


def test_get_assignment(client, hw, make_assignment):
    a = make_assignment(hw.cohort)
    resp = client.get(f"/teacher/assignments/{a.id}", headers=hw.teacher_headers)
    assert resp.status_code == 200 and resp.get_json()["id"] == a.id


# ----------------------------------------------------------------- validation
@pytest.mark.parametrize("fields, code", [
    ({"title_mn": ""}, "title_mn_required"),
    ({"title_mn": None}, "title_mn_required"),
    ({"title_mn": "x" * 201}, "field_too_long"),
    ({"title_mn": 5}, "invalid_field"),
    ({"due_date": "01/12/2026"}, "invalid_date"),
    ({"max_score": -1}, "invalid_max_score"),
    ({"max_score": 0}, "invalid_max_score"),
    ({"max_score": "abc"}, "invalid_max_score"),
    ({"max_score": 100000}, "invalid_max_score"),
    ({"max_score": True}, "invalid_max_score"),
    ({"lesson_id": 999999}, "invalid_lesson"),
    ({"attachment_material_id": 999999}, "invalid_attachment"),
    ({"is_active": "yes"}, "invalid_field"),
])
def test_create_validation(client, hw, fields, code):
    resp = _create(client, hw, **fields)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == code


def test_lesson_and_material_must_belong_to_cohort_course(client, db, hw, make_course,
                                                          make_cohort):
    other_lesson = add_lesson(db, make_course())
    resp = _create(client, hw, lesson_id=other_lesson.id)
    assert resp.get_json()["error"] == "invalid_lesson"

    foreign_material = LessonMaterial(lesson_id=other_lesson.id, title="x", type="link",
                                      url="https://x.io")
    other_cohort_material = LessonMaterial(lesson_id=hw.lesson.id, title="y", type="link",
                                           url="https://y.io",
                                           cohort_id=make_cohort(course=hw.course).id)
    db.session.add_all([foreign_material, other_cohort_material])
    db.session.commit()
    for mid in (foreign_material.id, other_cohort_material.id):
        resp = _create(client, hw, attachment_material_id=mid)
        assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_attachment"


# ----------------------------------------------------------------- update / delete
def test_patch_updates_and_clears_fields(client, hw, make_assignment):
    a = make_assignment(hw.cohort, lesson_id=hw.lesson.id, title_en="Old")
    resp = client.patch(f"/teacher/assignments/{a.id}", headers=hw.teacher_headers,
                        json={"title_en": None, "max_score": 50.5, "due_date": None,
                              "lesson_id": None, "is_active": False})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["title"]["en"] is None and body["max_score"] == 50.5
    assert body["lesson_id"] is None and body["is_active"] is False


def test_patch_invalid_leaves_row_untouched(client, db, hw, make_assignment):
    a = make_assignment(hw.cohort, title_en="Keep")
    resp = client.patch(f"/teacher/assignments/{a.id}", headers=hw.teacher_headers,
                        json={"title_en": "Changed", "max_score": -3})
    assert resp.status_code == 400
    db.session.expire_all()
    assert db.session.get(Assignment, a.id).title_en == "Keep"


def test_delete_without_submissions_removes(client, db, hw, make_assignment):
    a = make_assignment(hw.cohort)
    resp = client.delete(f"/teacher/assignments/{a.id}", headers=hw.teacher_headers)
    assert resp.status_code == 200 and resp.get_json()["status"] == "deleted"
    assert db.session.get(Assignment, a.id) is None


def test_delete_with_submissions_deactivates(client, db, hw, make_assignment,
                                             make_submission):
    a = make_assignment(hw.cohort)
    make_submission(a, hw.sid)
    resp = client.delete(f"/teacher/assignments/{a.id}", headers=hw.teacher_headers)
    assert resp.get_json()["status"] == "deactivated"
    db.session.expire_all()
    assert db.session.get(Assignment, a.id).is_active is False


# ----------------------------------------------------------------- access
def test_other_teacher_gets_404(client, hw, make_teacher, make_assignment):
    _, other = make_teacher()
    a = make_assignment(hw.cohort)
    resp = client.get(f"/teacher/cohorts/{hw.cohort.id}/assignments", headers=other)
    assert resp.status_code == 404 and resp.get_json()["error"] == "cohort_not_found"
    assert _create(client, hw, headers=other).status_code == 404
    for method in ("get", "patch", "delete"):
        resp = getattr(client, method)(f"/teacher/assignments/{a.id}", headers=other, json={})
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "assignment_not_found"


def test_unknown_ids_are_404(client, hw):
    assert client.get("/teacher/cohorts/999999/assignments",
                      headers=hw.teacher_headers).status_code == 404
    resp = client.get("/teacher/assignments/999999", headers=hw.teacher_headers)
    assert resp.get_json()["error"] == "assignment_not_found"


def test_students_and_unrelated_staff_are_403(client, hw, make_staff):
    for headers in (hw.student_headers, make_staff("finance")[1],
                    make_staff("content_marketing")[1]):
        resp = client.get(f"/teacher/cohorts/{hw.cohort.id}/assignments", headers=headers)
        assert resp.status_code == 403 and resp.get_json()["error"] == "forbidden"


def test_anonymous_is_401(client, hw):
    resp = client.get(f"/teacher/cohorts/{hw.cohort.id}/assignments")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"
