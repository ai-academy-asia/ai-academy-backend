"""Course writes: auth guard, POST/PATCH/DELETE /courses."""

import admin_course_helpers
import pytest
from admin_course_helpers import _fresh, _upload

from app.models import Course

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
editor = admin_course_helpers.editor
s3 = admin_course_helpers.s3


# ---------------------------------------------------------------- auth
@pytest.mark.parametrize("method,path", [
    ("post", "/courses"), ("patch", "/courses/1"), ("delete", "/courses/1"),
    ("put", "/courses/1/templates/cert"), ("get", "/courses/1/templates/cert"),
    ("delete", "/courses/1/templates/cert"),
])
def test_requires_token(client, method, path):
    resp = getattr(client, method)(path, json={})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


@pytest.mark.parametrize("role", ["sales_enrollment", "finance"])
def test_forbidden_without_course_edit(client, make_staff, make_course, s3, role):
    course = make_course()
    _, headers = make_staff(role)
    for method, path in [
        ("post", "/courses"), ("patch", f"/courses/{course.id}"),
        ("delete", f"/courses/{course.id}"),
        ("put", f"/courses/{course.id}/templates/cert"),
        ("get", f"/courses/{course.id}/templates/cert"),
        ("delete", f"/courses/{course.id}/templates/cert"),
    ]:
        resp = getattr(client, method)(path, json={"slug": "x", "title_mn": "x"},
                                       headers=headers)
        assert resp.status_code == 403, (method, path)
        assert resp.get_json()["error"] == "forbidden"
    assert Course.query.count() == 1


def test_students_are_forbidden(client, make_student):
    _, headers = make_student()
    resp = client.post("/courses", headers=headers, json={"slug": "x", "title_mn": "x"})
    assert resp.status_code == 403


# ---------------------------------------------------------------- create
def test_create_course_defaults_to_draft(client, editor, db):
    resp = client.post("/courses", headers=editor, json={
        "slug": "corporate-leaders", "title_mn": "Корпорат удирдагчид", "title_en": "Leaders",
        "level": "adult", "price_amount": 2500000, "discount_percent": 10,
        "start_date": "2026-08-06", "curriculum": [{"week": 1, "topic": "AI"}],
        "cert_template_key": "hijack", "id": 999,
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "draft"
    assert body["slug"] == "corporate-leaders"
    assert body["title"] == {"mn": "Корпорат удирдагчид", "en": "Leaders"}
    assert body["start_date"] == "2026-08-06"
    assert body["final_price_amount"] == 2250000.0
    assert body["has_cert_template"] is False
    assert body["id"] != 999
    course = db.session.get(Course, body["id"])
    assert course.cert_template_key is None
    assert course.curriculum == [{"week": 1, "topic": "AI"}]


@pytest.mark.parametrize("fields,error", [
    ({"slug": ""}, "slug_required"),
    ({"title_mn": None}, "title_mn_required"),
    ({"status": "archived"}, "invalid_status"),
    ({"level": "senior"}, "invalid_level"),
])
def test_create_validation(client, admin_headers, fields, error):
    data = {"slug": "c", "title_mn": "C"}
    data.update(fields)
    resp = client.post("/courses", headers=admin_headers, json=data)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == error
    assert Course.query.count() == 0


def test_create_invalid_date_names_field(client, admin_headers):
    resp = client.post("/courses", headers=admin_headers,
                       json={"slug": "c", "title_mn": "C", "end_date": "soon"})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "invalid_date", "field": "end_date"}


def test_create_duplicate_slug_is_409(client, admin_headers, make_course):
    make_course(slug="taken")
    resp = client.post("/courses", headers=admin_headers, json={"slug": "taken", "title_mn": "X"})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "slug_taken"
    assert Course.query.count() == 1


# ---------------------------------------------------------------- update
@pytest.mark.parametrize("by", ["id", "slug"])
def test_update_by_id_or_slug(client, editor, make_course, db, by):
    course = make_course(slug="ai-basics", status="draft")
    cid = course.id
    ref = cid if by == "id" else "ai-basics"
    resp = client.patch(f"/courses/{ref}", headers=editor, json={
        "status": "open", "tagline_mn": "Шинэ", "start_date": "2026-09-01",
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "open"
    assert body["tagline"]["mn"] == "Шинэ"
    assert body["start_date"] == "2026-09-01"
    assert _fresh(db, cid).status == "open"


def test_update_can_clear_date(client, editor, make_course, db):
    from datetime import date

    cid = make_course(start_date=date(2026, 9, 1)).id
    resp = client.patch(f"/courses/{cid}", headers=editor, json={"start_date": ""})
    assert resp.status_code == 200
    assert _fresh(db, cid).start_date is None


@pytest.mark.parametrize("fields,error", [
    ({"slug": ""}, "slug_required"),
    ({"title_mn": ""}, "title_mn_required"),
    ({"status": "gone"}, "invalid_status"),
    ({"level": "phd"}, "invalid_level"),
    ({"start_date": "2026-02-30"}, "invalid_date"),
])
def test_update_validation(client, editor, make_course, db, fields, error):
    cid = make_course(slug="keep", status="open").id
    resp = client.patch(f"/courses/{cid}", headers=editor, json=fields)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == error
    db.session.rollback()  # requests share the fixture's app context; mimic teardown
    course = _fresh(db, cid)
    assert course.slug == "keep" and course.status == "open"


def test_update_to_taken_slug_is_409(client, editor, make_course, db):
    make_course(slug="taken")
    cid = make_course(slug="mine").id
    resp = client.patch(f"/courses/{cid}", headers=editor, json={"slug": "taken"})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "slug_taken"
    assert _fresh(db, cid).slug == "mine"


@pytest.mark.parametrize("ref", ["9999", "no-such-course"])
def test_update_unknown_is_404(client, editor, ref):
    resp = client.patch(f"/courses/{ref}", headers=editor, json={"title_mn": "X"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


# ---------------------------------------------------------------- delete
@pytest.mark.parametrize("by", ["id", "slug"])
def test_delete_course(client, editor, make_course, db, s3, by):
    course = make_course(slug="gone")
    cid = course.id
    resp = client.delete(f"/courses/{cid if by == 'id' else 'gone'}", headers=editor)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "deleted"}
    assert _fresh(db, cid) is None


def test_delete_course_removes_its_templates(client, editor, make_course, db, s3):
    cid = make_course().id
    _upload(client, editor, cid, "cert", "cert.pdf")
    _upload(client, editor, cid, "contract", "contract.docx")
    assert len(s3.objects) == 2
    assert client.delete(f"/courses/{cid}", headers=editor).status_code == 200
    assert s3.objects == {}


def test_delete_course_survives_s3_cleanup_failure(client, editor, make_course, db, s3):
    cid = make_course().id
    _upload(client, editor, cid)
    s3.fail.add("delete")
    assert client.delete(f"/courses/{cid}", headers=editor).status_code == 200
    assert _fresh(db, cid) is None


def test_delete_course_in_use_is_409(client, editor, make_course, make_cohort, db, s3):
    course = make_course()
    cid = course.id
    make_cohort(course=course)
    _upload(client, editor, cid)
    resp = client.delete(f"/courses/{cid}", headers=editor)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "course_in_use"
    assert _fresh(db, cid) is not None
    assert len(s3.objects) == 1  # templates kept with the course


def test_delete_unknown_is_404(client, editor):
    resp = client.delete("/courses/9999", headers=editor)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"
