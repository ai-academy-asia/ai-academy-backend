"""A lesson completes on a saved note or an attended class (BE-06), and lessons open
in course order (BE-19)."""
from datetime import datetime

import engagement_helpers
import learning_helpers as h
import pytest
from engagement_helpers import new_session

from app.models import CourseLesson, Enrollment, LessonProgress

world = h.world
clock = engagement_helpers.clock
klass = engagement_helpers.klass


@pytest.fixture
def three(db, world):
    topic = h.module(db, world.course)
    return [h.lesson(db, topic, f"L{i}", sort_order=i) for i in range(3)]


def _path(client, world):
    return client.get("/me/courses/ai-leaders/learning", headers=world.headers).get_json()


def _note(client, headers, lesson_id, content="Тэмдэглэл"):
    return client.put(f"/me/lessons/{lesson_id}/note", headers=headers, json={"content": content})


# ------------------------------------------------------------------- BE-06
def test_saving_a_note_completes_the_lesson(client, db, world, three):
    assert _path(client, world)["continue"]["lesson_id"] == three[0].id
    assert _note(client, world.headers, three[0].id).status_code in (200, 201)

    data = _path(client, world)
    assert data["continue"]["lesson_id"] == three[1].id
    assert data["progress"] == {"percent": 33, "completed_lessons": 1, "total_lessons": 3}
    assert db.session.get(Enrollment, world.enrollment.id).progress_pct == 33
    _note(client, world.headers, three[0].id, "Засвар")
    assert LessonProgress.query.filter_by(enrollment_id=world.enrollment.id).count() == 1


def test_notes_on_every_lesson_satisfy_lessons_completed(client, world, three):
    for lesson in three:
        _note(client, world.headers, lesson.id)
    from app.services.certificates.eligibility import lessons_requirement

    assert lessons_requirement(world.course.id, world.enrollment)["done"] is True


def _class_lesson(db, client, klass):
    lesson = CourseLesson(topic_id=klass["topic"].id, name_mn="Ангийн")
    db.session.add(lesson)
    db.session.commit()
    sid = new_session(client, klass["t_headers"], klass["cohort"].id,
                      lesson_id=lesson.id).get_json()["id"]
    return lesson, sid


def _completed(db, klass, lesson):
    enrollment = Enrollment.query.filter_by(student_id=klass["student"].actor_id).one()
    return LessonProgress.query.filter_by(enrollment_id=enrollment.id, lesson_id=lesson.id,
                                          completed=True).count() == 1


@pytest.mark.parametrize("status,done", [("present", True), ("late", True),
                                         ("excused", False), ("absent", False)])
def test_teacher_marking_attended_completes_the_lesson(client, db, klass, clock, status, done):
    lesson, sid = _class_lesson(db, client, klass)
    resp = client.put(f"/teacher/sessions/{sid}/attendance/{klass['student'].actor_id}",
                      headers=klass["t_headers"], json={"status": status})
    assert resp.status_code == 200
    assert _completed(db, klass, lesson) is done


def test_qr_check_in_completes_the_lesson_and_stays(client, db, klass, clock):
    lesson, sid = _class_lesson(db, client, klass)
    clock(datetime(2026, 10, 1, 9, 5))
    token = client.post(f"/teacher/sessions/{sid}/qr", headers=klass["t_headers"]).get_json()
    resp = client.post("/me/attendance/check-in", headers=klass["s_headers"],
                       json={"token": token["token"]})
    assert resp.status_code == 201
    assert _completed(db, klass, lesson)
    client.put(f"/teacher/sessions/{sid}/attendance/{klass['student'].actor_id}",
               headers=klass["t_headers"], json={"status": "absent"})
    assert _completed(db, klass, lesson)  # completion is sticky


# ------------------------------------------------------------------- BE-19
def test_later_lessons_wait_for_earlier_ones(client, world, three):
    first, second, third = three
    for url in (f"/me/lessons/{second.id}", f"/me/lessons/{third.id}"):
        resp = client.get(url, headers=world.headers)
        assert (resp.status_code, resp.get_json()["error"]) == (409, "lesson_out_of_order")
    assert _note(client, world.headers, third.id).status_code == 409
    assert client.post(f"/me/lessons/{third.id}/complete",
                       headers=world.headers).status_code == 409

    module = client.get(f"/me/modules/{first.topic_id}/lessons",
                        headers=world.headers).get_json()
    assert [x["locked"] for x in module["lessons"]] == [False, True, True]

    client.post(f"/me/lessons/{first.id}/complete", headers=world.headers)
    assert client.get(f"/me/lessons/{second.id}", headers=world.headers).status_code == 200
    assert client.get(f"/me/lessons/{third.id}", headers=world.headers).status_code == 409


def test_a_lesson_whose_class_day_came_opens_out_of_order(client, db, klass, clock):
    earlier = CourseLesson(topic_id=klass["topic"].id, name_mn="Өмнөх", sort_order=0)
    db.session.add(earlier)
    db.session.commit()
    lesson, _ = _class_lesson(db, client, klass)
    lesson.sort_order = 1
    db.session.commit()
    assert client.get(f"/me/lessons/{lesson.id}", headers=klass["s_headers"]).status_code == 200
