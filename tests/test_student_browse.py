"""Student router: public course and cohort browse."""
from datetime import date

import pytest
from student_helpers import _ids


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
