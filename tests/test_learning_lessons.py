"""Module lessons, lesson detail and completion (contract §2.2, §2.3)."""
import learning_helpers as h
import pytest

from app.models import Enrollment, LessonProgress

world = h.world

SECTIONS = [{"title": {"mn": "Гарчиг", "en": "Title"}, "body": {"mn": "Текст", "en": None},
             "bullets": [{"mn": "нэг", "en": "one"}]}]


@pytest.fixture
def content(db, world):
    m0 = h.module(db, world.course, "Эхний", sort_order=0)
    m1 = h.module(db, world.course, "Хоёр", sort_order=1, name_en="Two")
    first = h.lesson(db, m1, "Nesting", sort_order=0, type="recording", duration_seconds=1455,
                     classroom_embed_url="https://www.youtube.com/embed/x",
                     summary_mn="Товч", sections=SECTIONS)
    second = h.lesson(db, m1, "Reading", sort_order=1, type="reading")
    return m0, m1, first, second


# ---------------------------------------------------------------- §2.2
def test_module_lessons(client, db, world, content):
    _, m1, first, second = content
    h.complete(db, world.enrollment, first)
    resp = client.get(f"/me/modules/{m1.id}/lessons", headers=world.headers)
    assert resp.status_code == 200
    assert resp.get_json() == {
        "module": {"id": m1.id, "order": 2, "title": {"mn": "Хоёр", "en": "Two"}},
        "lessons": [
            {"id": first.id, "order": 1, "title": {"mn": "Nesting", "en": None},
             "type": "recording", "duration_seconds": 1455, "completed": True, "locked": False},
            {"id": second.id, "order": 2, "title": {"mn": "Reading", "en": None},
             "type": "reading", "duration_seconds": None, "completed": False, "locked": False},
        ],
    }


def test_module_lessons_follow_module_lock(client, db, world, content):
    _, m1, _, _ = content
    h.session(db, world.cohort, m1, h.FUTURE)
    lessons = client.get(f"/me/modules/{m1.id}/lessons", headers=world.headers).get_json()
    assert all(item["locked"] for item in lessons["lessons"])


@pytest.mark.parametrize("ref", ["999999", "abc"])
def test_module_unknown(client, world, ref):
    resp = client.get(f"/me/modules/{ref}/lessons", headers=world.headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "module_not_found"


def test_module_of_other_course_not_enrolled(client, db, world, make_course):
    other = h.module(db, make_course())
    resp = client.get(f"/me/modules/{other.id}/lessons", headers=world.headers)
    assert (resp.status_code, resp.get_json()["error"]) == (403, "not_enrolled")


def test_module_lessons_auth(client, world, content, make_teacher):
    url = f"/me/modules/{content[1].id}/lessons"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=make_teacher()[1]).status_code == 403


# ---------------------------------------------------------------- §2.3
def test_lesson_detail(client, db, world, content, make_cohort):
    _, m1, first, _ = content
    mine = h.material(db, first, "Mine", cohort=world.cohort, sort_order=1)
    shared = h.material(db, first, "Shared", sort_order=0)
    link = h.material(db, first, "Link", sort_order=2, type="link", url="https://x.test",
                      file_key=None, file_name=None, content_type=None, size_bytes=None)
    h.material(db, first, "Theirs", cohort=make_cohort(world.course))

    resp = client.get(f"/me/lessons/{first.id}", headers=world.headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == first.id
    assert data["module"] == {"id": m1.id, "order": 2, "title": {"mn": "Хоёр", "en": "Two"}}
    assert data["order"] == 1
    assert data["title"] == {"mn": "Nesting", "en": None}
    assert data["type"] == "recording"
    assert data["duration_seconds"] == 1455
    assert data["video"] == {"embed_url": "https://www.youtube.com/embed/x"}
    assert data["summary"] == {"mn": "Товч", "en": None}
    assert data["sections"] == SECTIONS
    assert data["completed"] is False
    assert [m["id"] for m in data["materials"]] == [shared.id, mine.id, link.id]
    assert data["materials"][0] == {
        "id": shared.id, "title": "Shared", "type": "file", "file_name": "Shared.pdf",
        "content_type": "application/pdf", "size_bytes": 1234}
    assert data["materials"][2]["url"] == "https://x.test"
    assert "url" not in data["materials"][0]
    assert data["note"] is None
    assert data["assignment"] is None or isinstance(data["assignment"], dict)
    assert data["quiz"] is None or isinstance(data["quiz"], dict)


def test_lesson_detail_nulls(client, world, content):
    data = client.get(f"/me/lessons/{content[3].id}", headers=world.headers).get_json()
    assert data["video"] is None
    assert data["summary"] is None
    assert data["sections"] == []
    assert data["materials"] == []


def test_lesson_detail_embeds_assignment_and_quiz(client, world, content, monkeypatch):
    lesson_id = content[2].id
    calls = {}

    def assignment_for_lesson(student_id, enrollment, lesson):
        calls["assignment"] = (student_id, enrollment.id, lesson.id)
        return {"id": 17}

    def quiz_summary_for_lesson(student_id, lesson):
        calls["quiz"] = (student_id, lesson.id)
        return {"id": 9}

    h.stub_service(monkeypatch, "assignments", assignment_for_lesson=assignment_for_lesson)
    h.stub_service(monkeypatch, "quizzes", quiz_summary_for_lesson=quiz_summary_for_lesson)
    data = client.get(f"/me/lessons/{lesson_id}", headers=world.headers).get_json()
    assert data["assignment"] == {"id": 17}
    assert data["quiz"] == {"id": 9}
    sid = world.account.actor_id
    assert calls == {"assignment": (sid, world.enrollment.id, lesson_id),
                     "quiz": (sid, lesson_id)}


def test_lesson_locked(client, db, world, content):
    _, m1, first, _ = content
    h.session(db, world.cohort, m1, h.FUTURE)
    resp = client.get(f"/me/lessons/{first.id}", headers=world.headers)
    assert (resp.status_code, resp.get_json()["error"]) == (409, "lesson_locked")
    resp = client.post(f"/me/lessons/{first.id}/complete", headers=world.headers)
    assert (resp.status_code, resp.get_json()["error"]) == (409, "lesson_locked")


def test_lesson_past_session_opens(client, db, world, content):
    _, m1, first, _ = content
    h.session(db, world.cohort, m1, h.PAST)
    assert client.get(f"/me/lessons/{first.id}", headers=world.headers).status_code == 200


@pytest.mark.parametrize("ref", ["424242", "x1"])
def test_lesson_unknown(client, world, ref):
    resp = client.get(f"/me/lessons/{ref}", headers=world.headers)
    assert (resp.status_code, resp.get_json()["error"]) == (404, "lesson_not_found")


def test_lesson_other_course(client, db, world, make_course):
    other = h.lesson(db, h.module(db, make_course()))
    resp = client.get(f"/me/lessons/{other.id}", headers=world.headers)
    assert (resp.status_code, resp.get_json()["error"]) == (403, "not_enrolled")


def test_lesson_auth(client, world, content, admin_headers):
    url = f"/me/lessons/{content[2].id}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=admin_headers).status_code == 403


# ---------------------------------------------------------------- complete
def test_complete_is_idempotent_and_updates_progress(client, db, world, content):
    _, _, first, _ = content
    url = f"/me/lessons/{first.id}/complete"
    for _ in range(2):
        resp = client.post(url, headers=world.headers)
        assert resp.status_code == 200
        assert resp.get_json() == {
            "completed": True,
            "progress": {"percent": 50, "completed_lessons": 1, "total_lessons": 2}}
    db.session.expire_all()
    rows = LessonProgress.query.filter_by(enrollment_id=world.enrollment.id).all()
    assert len(rows) == 1 and rows[0].completed_at and rows[0].watched_at
    assert db.session.get(Enrollment, world.enrollment.id).progress_pct == 50
    detail = client.get(f"/me/lessons/{first.id}", headers=world.headers).get_json()
    assert detail["completed"] is True


def test_complete_errors(client, db, world, content, make_student, make_course):
    url = f"/me/lessons/{content[2].id}/complete"
    assert client.post(url).status_code == 401
    resp = client.post(url, headers=make_student()[1])
    assert (resp.status_code, resp.get_json()["error"]) == (403, "not_enrolled")
    resp = client.post("/me/lessons/0/complete", headers=world.headers)
    assert (resp.status_code, resp.get_json()["error"]) == (404, "lesson_not_found")
