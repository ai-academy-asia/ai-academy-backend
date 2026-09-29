"""GET /me/courses/<slug>/learning — module list, progress, continue, certificate state."""
from datetime import date

import learning_helpers as h

world = h.world


def _get(client, w, slug="ai-leaders"):
    return client.get(f"/me/courses/{slug}/learning", headers=w.headers)


def test_learning_path_shape(client, db, world):
    m1 = h.module(db, world.course, "Эхлэл", sort_order=0, name_en="Intro")
    m2 = h.module(db, world.course, "Дараа", sort_order=1)
    l1 = h.lesson(db, m1, "A", sort_order=0)
    h.lesson(db, m1, "B", sort_order=1)
    h.lesson(db, m2, "C")
    h.session(db, world.cohort, m1, h.PAST, "09:00")
    h.session(db, world.cohort, m1, date(2026, 1, 12), "10:00")
    h.complete(db, world.enrollment, l1)

    resp = _get(client, world)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["course"] == {
        "id": world.course.id, "slug": "ai-leaders",
        "title": {"mn": "AI удирдагч", "en": "AI Leaders"},
        "description": {"mn": "Тайлбар", "en": None},
        "banner_image_url": "https://img/x.png",
    }
    assert data["enrollment_id"] == world.enrollment.id
    assert data["cohort_id"] == world.cohort.id
    assert data["progress"] == {"percent": 33, "completed_lessons": 1, "total_lessons": 3}
    assert data["certificate"] == {"status": "not_eligible"}
    assert data["modules"] == [
        {"id": m1.id, "order": 1, "title": {"mn": "Эхлэл", "en": "Intro"},
         "schedule": {"date": "2026-01-05", "start_time": "09:00"},
         "lesson_count": 2, "completed_lessons": 1, "completed": False, "locked": False},
        {"id": m2.id, "order": 2, "title": {"mn": "Дараа", "en": None}, "schedule": None,
         "lesson_count": 1, "completed_lessons": 0, "completed": False, "locked": False},
    ]
    assert data["continue"]["module_id"] == m1.id


def test_by_course_id_and_ordering_by_sort_order(client, db, world):
    later = h.module(db, world.course, "Later", sort_order=5)
    first = h.module(db, world.course, "First", sort_order=1)
    data = _get(client, world, slug=str(world.course.id)).get_json()
    assert [m["id"] for m in data["modules"]] == [first.id, later.id]
    assert [m["order"] for m in data["modules"]] == [1, 2]


def test_future_module_is_locked_and_skipped_by_continue(client, db, world):
    m1 = h.module(db, world.course, sort_order=0)
    m2 = h.module(db, world.course, sort_order=1)
    a = h.lesson(db, m1)
    b = h.lesson(db, m2)
    h.session(db, world.cohort, m1, h.FUTURE)
    data = _get(client, world).get_json()
    assert [m["locked"] for m in data["modules"]] == [True, False]
    assert data["modules"][0]["schedule"]["date"] == h.FUTURE.isoformat()
    assert data["continue"] == {"module_id": m2.id, "lesson_id": b.id}
    assert a.id != b.id


def test_other_cohorts_sessions_do_not_count(client, db, world, make_cohort):
    m1 = h.module(db, world.course)
    h.lesson(db, m1)
    h.session(db, make_cohort(world.course), m1, h.FUTURE)
    mod = _get(client, world).get_json()["modules"][0]
    assert mod["schedule"] is None
    assert mod["locked"] is False


def test_continue_first_incomplete_then_last_when_all_done(client, db, world):
    m1 = h.module(db, world.course, sort_order=0)
    m2 = h.module(db, world.course, sort_order=1)
    a = h.lesson(db, m1, sort_order=0)
    b = h.lesson(db, m1, sort_order=1)
    c = h.lesson(db, m2)
    h.complete(db, world.enrollment, a)
    assert _get(client, world).get_json()["continue"] == {"module_id": m1.id, "lesson_id": b.id}

    h.complete(db, world.enrollment, b)
    h.complete(db, world.enrollment, c)
    data = _get(client, world).get_json()
    assert data["continue"] == {"module_id": m2.id, "lesson_id": c.id}
    assert data["progress"] == {"percent": 100, "completed_lessons": 3, "total_lessons": 3}
    assert [m["completed"] for m in data["modules"]] == [True, True]


def test_continue_null_when_everything_locked(client, db, world):
    m1 = h.module(db, world.course)
    h.lesson(db, m1)
    h.session(db, world.cohort, m1, h.FUTURE)
    assert _get(client, world).get_json()["continue"] is None


def test_empty_course(client, world):
    data = _get(client, world).get_json()
    assert data["modules"] == []
    assert data["continue"] is None
    assert data["progress"] == {"percent": 0, "completed_lessons": 0, "total_lessons": 0}


def test_percent_floors(client, db, world):
    m1 = h.module(db, world.course)
    lessons = [h.lesson(db, m1, sort_order=i) for i in range(3)]
    for row in lessons[:2]:
        h.complete(db, world.enrollment, row)
    assert _get(client, world).get_json()["progress"]["percent"] == 66


def test_progress_of_another_enrollment_is_ignored(client, db, world, make_student):
    m1 = h.module(db, world.course)
    row = h.lesson(db, m1)
    other, _ = make_student()
    h.complete(db, h.enroll(db, world.cohort, other), row)
    assert _get(client, world).get_json()["progress"]["completed_lessons"] == 0


def test_certificate_status_is_embedded(client, world, monkeypatch):
    seen = {}

    def certificate_status(student_id, course, enrollment):
        seen["args"] = (student_id, course.id, enrollment.id)
        return {"status": "issued", "requirements": {}, "certificate": {"cert_number": "X"}}

    h.stub_service(monkeypatch, "certificates", certificate_status=certificate_status)
    assert _get(client, world).get_json()["certificate"] == {"status": "issued"}
    assert seen["args"] == (world.account.actor_id, world.course.id, world.enrollment.id)


def test_course_progress_helper(db, world):
    from app.services.learning import course_progress

    m1 = h.module(db, world.course)
    a = h.lesson(db, m1)
    h.lesson(db, m1)
    h.complete(db, world.enrollment, a)
    assert course_progress(world.enrollment) == {
        "percent": 50, "completed_lessons": 1, "total_lessons": 2}


# ---------------------------------------------------------------- access
def test_requires_token(client, world):
    assert client.get("/me/courses/ai-leaders/learning").status_code == 401


def test_staff_token_forbidden(client, world, admin_headers):
    resp = client.get("/me/courses/ai-leaders/learning", headers=admin_headers)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


def test_not_enrolled(client, world, make_student):
    _, headers = make_student()
    resp = client.get("/me/courses/ai-leaders/learning", headers=headers)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "not_enrolled"


def test_cancelled_enrollment_is_not_enrolled(client, db, world):
    world.enrollment.status = "cancelled"
    db.session.commit()
    assert _get(client, world).get_json()["error"] == "not_enrolled"


def test_unknown_or_draft_course(client, world, make_course):
    assert _get(client, world, slug="nope").status_code == 404
    make_course(slug="draft-one", status="draft")
    resp = _get(client, world, slug="draft-one")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "course_not_found"
