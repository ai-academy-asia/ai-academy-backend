"""Student router: public course/cohort browse and student self-service
enrolment (enroll, cancel, my cohorts)."""
from datetime import date

import pytest

from app.models import Enrollment


def _ids(items):
    return sorted(i["id"] for i in items)


# ----------------------------------------------------------------- GET /courses
def test_courses_anonymous_sees_only_open_and_closed(client, make_course):
    a = make_course(status="open")
    b = make_course(status="closed")
    make_course(status="draft")
    resp = client.get("/courses")
    assert resp.status_code == 200
    assert _ids(resp.get_json()["courses"]) == sorted([a.id, b.id])


def test_courses_anonymous_status_filter_is_ignored(client, make_course):
    make_course(status="draft")
    opened = make_course(status="open")
    resp = client.get("/courses?status=draft")
    assert _ids(resp.get_json()["courses"]) == [opened.id]


def test_courses_editor_sees_drafts_and_can_filter_by_status(client, make_course, make_staff):
    draft = make_course(status="draft")
    opened = make_course(status="open")
    _, headers = make_staff("content_marketing")

    all_rows = client.get("/courses", headers=headers).get_json()["courses"]
    assert _ids(all_rows) == sorted([draft.id, opened.id])
    drafts = client.get("/courses?status=draft", headers=headers).get_json()["courses"]
    assert _ids(drafts) == [draft.id]


def test_courses_staff_without_course_edit_does_not_see_drafts(client, make_course, make_staff):
    make_course(status="draft")
    _, headers = make_staff("finance")
    assert client.get("/courses", headers=headers).get_json()["courses"] == []


def test_courses_filter_by_level_and_category(client, make_course):
    junior = make_course(level="junior", category="ai")
    make_course(level="adult", category="ai")
    make_course(level="junior", category="robotics")

    rows = client.get("/courses?level=junior&category=ai").get_json()["courses"]
    assert _ids(rows) == [junior.id]
    assert len(client.get("/courses?level=adult").get_json()["courses"]) == 1


def test_courses_are_ordered_by_start_date_undated_last(client, make_course):
    undated = make_course()
    late = make_course(start_date=date(2026, 12, 1))
    early = make_course(start_date=date(2026, 10, 1))
    rows = client.get("/courses").get_json()["courses"]
    assert [r["id"] for r in rows] == [early.id, late.id, undated.id]


# ----------------------------------------------------------------- GET /courses/<id_or_slug>
def test_course_detail_by_id_and_slug(client, make_course):
    course = make_course(slug="corporate-leaders", title_mn="Удирдагчид")
    by_id = client.get(f"/courses/{course.id}")
    by_slug = client.get("/courses/corporate-leaders")
    assert by_id.status_code == by_slug.status_code == 200
    assert by_id.get_json() == by_slug.get_json()
    data = by_id.get_json()
    assert data["slug"] == "corporate-leaders"
    assert data["title"]["mn"] == "Удирдагчид"
    assert "description" in data


@pytest.mark.parametrize("ref", ["999", "no-such-course"])
def test_course_detail_unknown_is_404(client, ref):
    resp = client.get(f"/courses/{ref}")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_course_detail_draft_hidden_unless_course_edit(client, make_course, make_staff,
                                                        make_student):
    draft = make_course(status="draft", slug="secret")
    _, student_h = make_student()
    _, finance_h = make_staff("finance")
    _, editor_h = make_staff("content_marketing")

    assert client.get("/courses/secret").status_code == 404
    assert client.get("/courses/secret", headers=student_h).status_code == 404
    assert client.get(f"/courses/{draft.id}", headers=finance_h).status_code == 404
    resp = client.get("/courses/secret", headers=editor_h)
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "draft"


# ----------------------------------------------------------------- GET /cohorts
def test_cohorts_lists_public_only(client, make_cohort):
    opened = make_cohort(status="open")
    closed = make_cohort(status="closed")
    make_cohort(status="draft")
    resp = client.get("/cohorts")
    assert resp.status_code == 200
    assert _ids(resp.get_json()["cohorts"]) == sorted([opened.id, closed.id])


def test_cohorts_filter_by_course(client, make_course, make_cohort):
    course = make_course()
    mine = make_cohort(course=course)
    make_cohort()
    rows = client.get(f"/cohorts?course_id={course.id}").get_json()["cohorts"]
    assert _ids(rows) == [mine.id]
    assert rows[0]["course"]["id"] == course.id
    # A non-numeric course_id is ignored rather than erroring.
    assert len(client.get("/cohorts?course_id=abc").get_json()["cohorts"]) == 2


# ----------------------------------------------------------------- GET /cohorts/<id>
def test_cohort_detail(client, make_cohort):
    cohort = make_cohort(capacity=5)
    resp = client.get(f"/cohorts/{cohort.id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == cohort.id
    assert data["seats_available"] == 5
    assert "created_at" in data


def test_cohort_detail_unknown_is_404(client):
    resp = client.get("/cohorts/999")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_cohort_detail_draft_hidden_unless_cohort_manage(client, make_cohort, make_staff):
    draft = make_cohort(status="draft")
    _, finance_h = make_staff("finance")
    _, sales_h = make_staff("sales_enrollment")
    assert client.get(f"/cohorts/{draft.id}").status_code == 404
    assert client.get(f"/cohorts/{draft.id}", headers=finance_h).status_code == 404
    resp = client.get(f"/cohorts/{draft.id}", headers=sales_h)
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "draft"


# ----------------------------------------------------------------- POST /cohorts/<id>/enroll
def test_enroll_creates_active_enrollment(client, make_cohort, make_student):
    cohort = make_cohort(capacity=2)
    account, headers = make_student()
    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["cohort_id"] == cohort.id
    assert data["student_id"] == account.actor_id
    assert data["course_id"] == cohort.course_id
    assert data["status"] == "active"
    assert data["created_via"] == "web"
    assert "student" not in data

    row = Enrollment.query.one()
    assert (row.student_id, row.status) == (account.actor_id, "active")
    assert client.get(f"/cohorts/{cohort.id}").get_json()["seats_available"] == 1


def test_enroll_requires_auth(client, make_cohort):
    cohort = make_cohort()
    resp = client.post(f"/cohorts/{cohort.id}/enroll")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


@pytest.mark.parametrize("actor", ["teacher", "staff"])
def test_enroll_forbidden_for_non_students(client, make_cohort, make_teacher, make_staff, actor):
    cohort = make_cohort()
    headers = make_teacher()[1] if actor == "teacher" else make_staff("super_admin")[1]
    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"
    assert Enrollment.query.count() == 0


def test_enroll_unknown_cohort_is_404(client, make_student):
    resp = client.post("/cohorts/999/enroll", headers=make_student()[1])
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


@pytest.mark.parametrize("status", ["closed", "draft"])
def test_enroll_rejects_cohort_not_open(client, make_cohort, make_student, status):
    cohort = make_cohort(status=status)
    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=make_student()[1])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "cohort_not_open"
    assert Enrollment.query.count() == 0


def test_enroll_twice_is_conflict(client, make_cohort, make_student):
    cohort = make_cohort()
    headers = make_student()[1]
    assert client.post(f"/cohorts/{cohort.id}/enroll", headers=headers).status_code == 201
    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "already_enrolled"
    assert Enrollment.query.count() == 1


def test_enroll_full_cohort_is_conflict(client, make_cohort, make_student):
    cohort = make_cohort(capacity=1)
    assert client.post(f"/cohorts/{cohort.id}/enroll",
                       headers=make_student()[1]).status_code == 201
    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=make_student()[1])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "cohort_full"
    assert Enrollment.query.count() == 1


def test_enroll_without_capacity_is_unlimited(client, make_cohort, make_student):
    cohort = make_cohort(capacity=None)
    for _ in range(3):
        assert client.post(f"/cohorts/{cohort.id}/enroll",
                           headers=make_student()[1]).status_code == 201
    assert client.get(f"/cohorts/{cohort.id}").get_json()["seats_available"] is None


def test_enroll_after_cancel_reactivates_same_row(client, make_cohort, make_student):
    cohort = make_cohort()
    headers = make_student()[1]
    first = client.post(f"/cohorts/{cohort.id}/enroll", headers=headers).get_json()
    client.delete(f"/cohorts/{cohort.id}/enroll", headers=headers)
    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert resp.status_code == 201
    assert resp.get_json()["id"] == first["id"]
    assert resp.get_json()["status"] == "active"
    assert Enrollment.query.count() == 1


def test_reenroll_after_cancel_respects_capacity(client, make_cohort, make_student):
    cohort = make_cohort(capacity=1)
    returning = make_student()[1]
    client.post(f"/cohorts/{cohort.id}/enroll", headers=returning)
    client.delete(f"/cohorts/{cohort.id}/enroll", headers=returning)
    assert client.post(f"/cohorts/{cohort.id}/enroll",
                       headers=make_student()[1]).status_code == 201

    resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=returning)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "cohort_full"


# ----------------------------------------------------------------- DELETE /cohorts/<id>/enroll
def test_cancel_marks_enrollment_cancelled(client, db, make_cohort, make_student):
    cohort = make_cohort(capacity=3)
    headers = make_student()[1]
    client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)

    resp = client.delete(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "cancelled"}
    db.session.expire_all()
    assert Enrollment.query.one().status == "cancelled"
    assert client.get(f"/cohorts/{cohort.id}").get_json()["seats_available"] == 3


def test_cancel_when_not_enrolled_is_404(client, make_cohort, make_student):
    cohort = make_cohort()
    headers = make_student()[1]
    resp = client.delete(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_enrolled"

    client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)
    client.delete(f"/cohorts/{cohort.id}/enroll", headers=headers)
    again = client.delete(f"/cohorts/{cohort.id}/enroll", headers=headers)
    assert again.status_code == 404
    assert again.get_json()["error"] == "not_enrolled"


def test_cancel_does_not_touchother_students(client, make_cohort, make_student):
    cohort = make_cohort()
    a, b = make_student()[1], make_student()[1]
    client.post(f"/cohorts/{cohort.id}/enroll", headers=a)
    resp = client.delete(f"/cohorts/{cohort.id}/enroll", headers=b)
    assert resp.status_code == 404
    assert Enrollment.query.one().status == "active"


def test_cancel_unknown_cohort_is_404(client, make_student):
    resp = client.delete("/cohorts/999/enroll", headers=make_student()[1])
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_cancel_auth(client, make_cohort, make_teacher):
    cohort = make_cohort()
    assert client.delete(f"/cohorts/{cohort.id}/enroll").status_code == 401
    resp = client.delete(f"/cohorts/{cohort.id}/enroll", headers=make_teacher()[1])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


# ----------------------------------------------------------------- GET /me/cohorts
def test_my_cohorts_lists_only_active_enrollments(client, make_cohort, make_student):
    kept, dropped, other = make_cohort(), make_cohort(), make_cohort()
    headers = make_student()[1]
    client.post(f"/cohorts/{kept.id}/enroll", headers=headers)
    client.post(f"/cohorts/{dropped.id}/enroll", headers=headers)
    client.delete(f"/cohorts/{dropped.id}/enroll", headers=headers)
    client.post(f"/cohorts/{other.id}/enroll", headers=make_student()[1])

    resp = client.get("/me/cohorts", headers=headers)
    assert resp.status_code == 200
    assert _ids(resp.get_json()["cohorts"]) == [kept.id]


def test_my_cohorts_empty(client, make_student):
    resp = client.get("/me/cohorts", headers=make_student()[1])
    assert resp.status_code == 200
    assert resp.get_json() == {"cohorts": []}


def test_my_cohorts_auth(client, make_staff):
    assert client.get("/me/cohorts").status_code == 401
    resp = client.get("/me/cohorts", headers=make_staff("super_admin")[1])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"
