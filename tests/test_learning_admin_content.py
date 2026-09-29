"""Staff authoring of modules and lessons (/admin/courses/<id>/modules, /admin/modules, …)."""
import learning_helpers as h
import pytest

from app.models import CourseLesson, CourseTopic, LessonNote

editor = h.editor
s3 = h.s3

SECTIONS = [{"title": {"mn": "Гарчиг"}, "body": None,
             "bullets": [{"mn": "a", "en": "b"}]}]


# ---------------------------------------------------------------- modules
def test_module_crud(client, db, editor, make_course):
    course = make_course(status="draft")
    base = f"/admin/courses/{course.id}/modules"
    resp = client.post(base, headers=editor, json={"name_mn": " Эхлэл ", "name_en": "Intro"})
    assert resp.status_code == 201
    first = resp.get_json()
    assert first["name_mn"] == "Эхлэл" and first["name_en"] == "Intro"
    assert first["sort_order"] == 0 and first["lesson_count"] == 0
    second = client.post(base, headers=editor, json={"name_mn": "Хоёр"}).get_json()
    assert second["sort_order"] == 1

    resp = client.patch(f"/admin/modules/{first['id']}", headers=editor,
                        json={"sort_order": 5, "name_en": None})
    assert resp.status_code == 200
    assert resp.get_json()["name_en"] is None
    listed = client.get(base, headers=editor).get_json()["modules"]
    assert [m["id"] for m in listed] == [second["id"], first["id"]]

    assert client.delete(f"/admin/modules/{first['id']}", headers=editor).status_code == 200
    assert db.session.get(CourseTopic, first["id"]) is None


@pytest.mark.parametrize("payload,code", [
    ({}, "name_mn_required"), ({"name_mn": "  "}, "name_mn_required"),
    ({"name_mn": "x" * 201}, "name_mn_too_long"), ({"name_mn": 3}, "invalid_name_mn"),
    ({"name_mn": "a", "sort_order": "z"}, "invalid_sort_order"),
    ({"name_mn": "a", "sort_order": -2}, "invalid_sort_order"),
])
def test_module_validation(client, editor, make_course, payload, code):
    resp = client.post(f"/admin/courses/{make_course().id}/modules", headers=editor, json=payload)
    assert (resp.status_code, resp.get_json()["error"]) == (400, code)


def test_module_not_found(client, editor):
    resp = client.get("/admin/courses/999/modules", headers=editor)
    assert (resp.status_code, resp.get_json()["error"]) == (404, "course_not_found")
    resp = client.post("/admin/courses/abc/modules", headers=editor, json={"name_mn": "a"})
    assert resp.status_code == 404
    for method in ("patch", "delete"):
        resp = getattr(client, method)("/admin/modules/999", headers=editor, json={})
        assert (resp.status_code, resp.get_json()["error"]) == (404, "module_not_found")


def test_module_delete_cascades_and_cleans_files(client, db, editor, make_course, s3):
    course = make_course()
    topic = h.module(db, course)
    lesson = h.lesson(db, topic)
    h.material(db, lesson, "A")
    h.material(db, lesson, "Link", type="link", url="https://x", file_key=None)
    db.session.add(LessonNote(student_id=_student(db), lesson_id=lesson.id,
                              content="n"))
    db.session.commit()
    s3.fail.add("delete")  # best-effort: a failing delete does not fail the request
    assert client.delete(f"/admin/modules/{topic.id}", headers=editor).status_code == 200
    db.session.expire_all()
    assert CourseLesson.query.count() == 0 and LessonNote.query.count() == 0
    assert s3.deleted == ["k/A"]


def _student(db):
    from app.models import Student

    row = Student(first_name="S")
    db.session.add(row)
    db.session.flush()
    return row.id


def test_permissions(client, make_course, make_staff, make_student):
    url = f"/admin/courses/{make_course().id}/modules"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=make_staff("finance")[1]).status_code == 403
    assert client.get(url, headers=make_student()[1]).status_code == 403
    assert client.get(url, headers=make_staff("super_admin")[1]).status_code == 200
    assert client.patch("/admin/lessons/1", headers=make_staff("finance")[1],
                        json={}).status_code == 403


# ---------------------------------------------------------------- lessons
def test_lesson_crud(client, db, editor, make_course):
    topic = h.module(db, make_course())
    base = f"/admin/modules/{topic.id}/lessons"
    resp = client.post(base, headers=editor, json={
        "name_mn": "Хичээл", "type": "video", "duration_seconds": 600,
        "classroom_embed_url": "https://www.youtube.com/embed/x", "summary_mn": "Товч",
        "sections": SECTIONS, "is_preview": True})
    assert resp.status_code == 201
    lesson = resp.get_json()
    assert lesson["module_id"] == topic.id
    assert lesson["type"] == "video" and lesson["duration_seconds"] == 600
    assert lesson["is_preview"] is True and lesson["sort_order"] == 0
    assert lesson["sections"] == [{"title": {"mn": "Гарчиг", "en": None}, "body": None,
                                   "bullets": [{"mn": "a", "en": "b"}]}]
    default = client.post(base, headers=editor, json={"name_mn": "Дараах"}).get_json()
    assert default["type"] == "recording" and default["sort_order"] == 1
    assert default["sections"] == [] and default["is_preview"] is False

    url = f"/admin/lessons/{lesson['id']}"
    resp = client.patch(url, headers=editor, json={
        "sort_order": 5, "classroom_embed_url": "", "duration_seconds": None, "sections": None})
    assert resp.status_code == 200
    patched = resp.get_json()
    assert patched["classroom_embed_url"] is None and patched["duration_seconds"] is None
    assert patched["sections"] == []
    listed = client.get(base, headers=editor).get_json()["lessons"]
    assert [row["id"] for row in listed] == [default["id"], lesson["id"]]

    detail = client.get(url, headers=editor).get_json()
    assert detail["id"] == lesson["id"] and detail["materials"] == []
    assert client.delete(url, headers=editor).status_code == 200
    assert client.get(url, headers=editor).status_code == 404


@pytest.mark.parametrize("payload,code", [
    ({}, "name_mn_required"),
    ({"name_mn": "a", "type": "podcast"}, "invalid_type"),
    ({"name_mn": "a", "duration_seconds": -1}, "invalid_duration_seconds"),
    ({"name_mn": "a", "duration_seconds": True}, "invalid_duration_seconds"),
    ({"name_mn": "a", "is_preview": "yes"}, "invalid_is_preview"),
    ({"name_mn": "a", "classroom_embed_url": "javascript:x"}, "invalid_classroom_embed_url"),
    ({"name_mn": "a", "sections": {"title": "x"}}, "invalid_sections"),
    ({"name_mn": "a", "sections": [{"title": "plain"}]}, "invalid_sections"),
    ({"name_mn": "a", "sections": [{"title": {"en": "no mn"}}]}, "invalid_sections"),
    ({"name_mn": "a", "sections": [{"bullets": "x"}]}, "invalid_sections"),
    ({"name_mn": "a", "sections": [{"bullets": [None]}]}, "invalid_sections"),
    ({"name_mn": "a", "sections": [{"extra": 1}]}, "invalid_sections"),
    ({"name_mn": "a", "sections": ["x"]}, "invalid_sections"),
])
def test_lesson_validation(client, db, editor, make_course, payload, code):
    topic = h.module(db, make_course())
    resp = client.post(f"/admin/modules/{topic.id}/lessons", headers=editor, json=payload)
    assert (resp.status_code, resp.get_json()["error"]) == (400, code)


def test_lesson_not_found(client, editor):
    for method in ("get", "post"):
        resp = getattr(client, method)("/admin/modules/77/lessons", headers=editor,
                                       json={"name_mn": "a"})
        assert (resp.status_code, resp.get_json()["error"]) == (404, "module_not_found")
    for method in ("get", "patch", "delete"):
        resp = getattr(client, method)("/admin/lessons/77", headers=editor, json={})
        assert (resp.status_code, resp.get_json()["error"]) == (404, "lesson_not_found")


def test_lesson_delete_cleans_files(client, db, editor, make_course, s3):
    lesson = h.lesson(db, h.module(db, make_course()))
    h.material(db, lesson, "A")
    assert client.delete(f"/admin/lessons/{lesson.id}", headers=editor).status_code == 200
    assert s3.deleted == ["k/A"]
