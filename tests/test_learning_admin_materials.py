"""Staff lesson materials: upload to S3, links, cohort narrowing, delete."""
import learning_helpers as h
import pytest

from app.models import Course, LessonMaterial

editor = h.editor
s3 = h.s3


@pytest.fixture
def lesson(db, make_course):
    return h.lesson(db, h.module(db, make_course()))


def _course(db, lesson_row):
    return db.session.get(Course, lesson_row.topic.course_id)


def test_upload_file(client, db, editor, lesson, s3):
    course_id = lesson.topic.course_id
    resp = h.upload(client, editor, lesson.id, b"%PDF-1.4 deck", "7 хоног slides.pdf",
                    sort_order="2")
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["type"] == "file"
    assert data["title"] == "7 хоног slides.pdf"
    assert data["file_name"] == "7 хоног slides.pdf"
    assert data["content_type"] == "application/pdf"
    assert data["size_bytes"] == len(b"%PDF-1.4 deck")
    assert data["cohort_id"] is None and data["sort_order"] == 2
    [key] = s3.objects
    assert key.startswith(f"courses/{course_id}/lessons/{lesson.id}/")
    assert key.endswith("_7_slides.pdf")
    assert s3.objects[key] == (b"%PDF-1.4 deck", "application/pdf")
    assert db.session.get(LessonMaterial, data["id"]).file_key == key


def test_upload_with_title_and_cohort(client, db, editor, lesson, s3, make_cohort):
    cohort = make_cohort(_course(db, lesson))
    resp = h.upload(client, editor, lesson.id, title="Week 2", cohort_id=str(cohort.id))
    assert resp.status_code == 201
    assert resp.get_json()["title"] == "Week 2"
    assert resp.get_json()["cohort_id"] == cohort.id


@pytest.mark.parametrize("cohort_ref", ["other", "9999", "abc"])
def test_upload_cohort_must_belong_to_course(client, editor, lesson, s3, make_cohort, cohort_ref):
    ref = str(make_cohort().id) if cohort_ref == "other" else cohort_ref
    resp = h.upload(client, editor, lesson.id, cohort_id=ref)
    assert (resp.status_code, resp.get_json()["error"]) == (400, "invalid_cohort")
    assert s3.objects == {}


def test_upload_too_large(client, editor, lesson, s3, monkeypatch):
    monkeypatch.setattr("app.services.learning.materials.MAX_MATERIAL_BYTES", 10)
    resp = h.upload(client, editor, lesson.id, b"x" * 11)
    assert (resp.status_code, resp.get_json()["error"]) == (413, "file_too_large")
    assert s3.objects == {}


def test_upload_requires_file(client, editor, lesson, s3):
    resp = client.post(f"/admin/lessons/{lesson.id}/materials", headers=editor,
                       data={"title": "x"}, content_type="multipart/form-data")
    assert (resp.status_code, resp.get_json()["error"]) == (400, "file_required")


def test_upload_storage_error(client, editor, lesson, s3):
    s3.fail.add("upload")
    resp = h.upload(client, editor, lesson.id)
    assert (resp.status_code, resp.get_json()["error"]) == (502, "storage_error")
    assert LessonMaterial.query.count() == 0


def test_create_link(client, editor, lesson, s3):
    resp = client.post(f"/admin/lessons/{lesson.id}/materials", headers=editor,
                       json={"type": "link", "url": "https://docs.test/a", "title": "Doc"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["type"] == "link" and data["url"] == "https://docs.test/a"
    assert data["file_name"] is None and s3.objects == {}


@pytest.mark.parametrize("payload,code", [
    ({"type": "link", "url": "https://x.test"}, "title_required"),
    ({"type": "link", "title": "a", "url": "ftp://x"}, "invalid_url"),
    ({"type": "link", "title": "a"}, "invalid_url"),
    ({"type": "video", "title": "a"}, "invalid_type"),
    ({"title": "a"}, "file_required"),
])
def test_link_validation(client, editor, lesson, s3, payload, code):
    resp = client.post(f"/admin/lessons/{lesson.id}/materials", headers=editor, json=payload)
    assert (resp.status_code, resp.get_json()["error"]) == (400, code)


def test_list_patch_and_delete(client, db, editor, lesson, s3, make_cohort):
    cohort = make_cohort(_course(db, lesson))
    h.upload(client, editor, lesson.id, filename="b.pdf", sort_order="1")
    first = h.upload(client, editor, lesson.id, filename="a.pdf").get_json()
    listed = client.get(f"/admin/lessons/{lesson.id}/materials", headers=editor).get_json()
    assert [m["file_name"] for m in listed["materials"]] == ["a.pdf", "b.pdf"]

    resp = client.patch(f"/admin/materials/{first['id']}", headers=editor,
                        json={"title": "Renamed", "cohort_id": cohort.id, "sort_order": 3})
    assert resp.status_code == 200
    assert resp.get_json()["cohort_id"] == cohort.id and resp.get_json()["title"] == "Renamed"
    resp = client.patch(f"/admin/materials/{first['id']}", headers=editor, json={"title": ""})
    assert resp.get_json()["error"] == "title_required"

    key = db.session.get(LessonMaterial, first["id"]).file_key
    assert client.delete(f"/admin/materials/{first['id']}", headers=editor).status_code == 200
    assert key not in s3.objects and s3.deleted == [key]
    assert db.session.get(LessonMaterial, first["id"]) is None


def test_delete_survives_storage_failure(client, db, editor, lesson, s3):
    material = h.material(db, lesson)
    s3.fail.add("delete")
    assert client.delete(f"/admin/materials/{material.id}", headers=editor).status_code == 200
    assert LessonMaterial.query.count() == 0


def test_not_found_and_permissions(client, editor, lesson, make_staff, make_teacher):
    for method, url in [("get", "/admin/lessons/9/materials"),
                        ("post", "/admin/lessons/9/materials")]:
        resp = getattr(client, method)(url, headers=editor, json={})
        assert (resp.status_code, resp.get_json()["error"]) == (404, "lesson_not_found")
    for method in ("patch", "delete"):
        resp = getattr(client, method)("/admin/materials/9", headers=editor, json={})
        assert (resp.status_code, resp.get_json()["error"]) == (404, "material_not_found")
    url = f"/admin/lessons/{lesson.id}/materials"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=make_teacher()[1]).status_code == 403
    assert client.post(url, headers=make_staff("finance")[1], json={}).status_code == 403
