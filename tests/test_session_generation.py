"""Generating a cohort's sessions from the admin side (BE-03), re-laying them after a
schedule change (BE-04) and giving each session its lesson (BE-18)."""
from datetime import date, datetime

import engagement_helpers
import pytest
from engagement_helpers import new_session

from app.models import Attendance, ClassSession, CourseLesson, CourseTopic

clock = engagement_helpers.clock
klass = engagement_helpers.klass


@pytest.fixture
def cohort(db, klass):
    """Tue/Thu 09:00–11:00 from Thu 1 Oct to Thu 15 Oct: 1, 6, 8, 13, 15."""
    c = klass["cohort"]
    c.end_date = date(2026, 10, 15)
    db.session.commit()
    return c


def _generate(client, headers, cohort_id, url="/admin/cohorts/{}/sessions/generate", **body):
    return client.post(url.format(cohort_id), headers=headers, json=body)


def _slots(db, cohort):
    db.session.expire_all()
    return [(s.session_date.isoformat(), s.start_time) for s in
            ClassSession.query.filter_by(cohort_id=cohort.id)
            .order_by(ClassSession.session_date, ClassSession.start_time)]


# ------------------------------------------------------------------- BE-03
def test_admin_generates_the_schedule(client, db, cohort, admin_headers, clock):
    resp = _generate(client, admin_headers, cohort.id)
    assert resp.status_code == 200
    assert resp.get_json()["created"] == 5
    assert _slots(db, cohort) == [(d, "09:00") for d in (
        "2026-10-01", "2026-10-06", "2026-10-08", "2026-10-13", "2026-10-15")]


def test_admin_generate_is_permission_gated(client, cohort, make_staff, klass):
    assert _generate(client, make_staff("finance")[1], cohort.id).status_code == 403
    assert _generate(client, klass["t_headers"], cohort.id).status_code == 403
    assert _generate(client, make_staff("sales_enrollment")[1], 9999).status_code == 404


def test_enrolled_student_sees_generated_sessions(client, cohort, admin_headers, klass, clock):
    _generate(client, admin_headers, cohort.id)
    data = client.get("/me/attendance?course=corp-leaders", headers=klass["s_headers"]).get_json()
    assert len(data["sessions"]) == 5


# ------------------------------------------------------------------- BE-04
def test_time_change_never_doubles_a_day(client, db, cohort, admin_headers, clock):
    _generate(client, admin_headers, cohort.id)
    cohort.start_time, cohort.end_time = "14:00", "16:00"
    db.session.commit()
    plain = _generate(client, admin_headers, cohort.id).get_json()
    assert (plain["created"], plain["moved"]) == (0, 0)
    assert len(_slots(db, cohort)) == 5


def test_regenerate_moves_the_future_and_keeps_history(client, db, cohort, admin_headers,
                                                       klass, clock, make_teacher):
    from app.models import ScheduleChangeRequest

    _generate(client, admin_headers, cohort.id)
    clock(datetime(2026, 10, 7, 12, 0))
    by_date = {s.session_date.isoformat(): s for s in
               ClassSession.query.filter_by(cohort_id=cohort.id)}
    db.session.add(Attendance(class_session_id=by_date["2026-10-13"].id,
                              student_id=klass["student"].actor_id, status="excused",
                              method="manual"))
    other, _ = make_teacher()
    db.session.add(ScheduleChangeRequest(
        class_session_id=by_date["2026-10-15"].id, sender_teacher_id=klass["teacher"].actor_id,
        recipient_teacher_id=other.actor_id, status="pending"))
    cohort.start_time, cohort.end_time = "14:00", "16:00"
    db.session.commit()

    data = _generate(client, admin_headers, cohort.id, regenerate=True).get_json()
    assert (data["created"], data["moved"], data["removed"]) == (0, 1, 0)
    assert _slots(db, cohort) == [
        ("2026-10-01", "09:00"), ("2026-10-06", "09:00"),  # past
        ("2026-10-08", "14:00"),                           # moved
        ("2026-10-13", "09:00"),                           # has attendance
        ("2026-10-15", "09:00"),                           # has a handover request
    ]
    moved = ClassSession.query.filter_by(session_date=date(2026, 10, 8)).one()
    assert moved.end_time == "16:00"


def test_regenerate_drops_days_no_longer_met(client, db, cohort, admin_headers, clock):
    _generate(client, admin_headers, cohort.id)
    cohort.meeting_days = ["thu"]
    db.session.commit()
    data = _generate(client, admin_headers, cohort.id, regenerate=True).get_json()
    assert data["removed"] == 2
    assert [d for d, _ in _slots(db, cohort)] == ["2026-10-01", "2026-10-08", "2026-10-15"]


def test_regenerate_on_the_teacher_route_too(client, db, cohort, klass, clock):
    url = "/teacher/cohorts/{}/sessions/generate"
    _generate(client, klass["t_headers"], cohort.id, url=url)
    cohort.start_time = "10:00"
    db.session.commit()
    data = _generate(client, klass["t_headers"], cohort.id, url=url, regenerate=True).get_json()
    assert data["moved"] == 4  # 1 Oct is today: history


# ------------------------------------------------------------------- BE-18
def _lessons(db, course, *names):
    topic = CourseTopic(course_id=course.id, name_mn="Модуль 2", sort_order=2)
    db.session.add(topic)
    db.session.flush()
    rows = [CourseLesson(topic_id=topic.id, name_mn=n, sort_order=i) for i, n in enumerate(names)]
    db.session.add_all(rows)
    db.session.commit()
    return topic, rows


def test_assign_lessons_in_course_order(client, db, cohort, admin_headers, klass, clock):
    first = CourseLesson(topic_id=klass["topic"].id, name_mn="Эхний")
    db.session.add(first)
    db.session.commit()
    topic2, (second, third) = _lessons(db, klass["course"], "Хоёр", "Гурав")
    data = _generate(client, admin_headers, cohort.id, assign_lessons=True).get_json()
    assert data["lessons_assigned"] == 3
    db.session.expire_all()
    rows = ClassSession.query.filter_by(cohort_id=cohort.id).order_by(
        ClassSession.session_date).all()
    assert [(r.lesson_id, r.topic_id) for r in rows] == [
        (first.id, klass["topic"].id), (second.id, topic2.id), (third.id, topic2.id),
        (None, None), (None, None)]
    again = _generate(client, admin_headers, cohort.id, assign_lessons=True).get_json()
    assert again["lessons_assigned"] == 0


def test_session_lesson_is_validated_and_sets_the_module(client, db, klass, make_course):
    lesson = CourseLesson(topic_id=klass["topic"].id, name_mn="Хичээл")
    stranger_topic = CourseTopic(course_id=make_course().id, name_mn="Өөр")
    db.session.add_all([lesson, stranger_topic])
    db.session.flush()
    stranger = CourseLesson(topic_id=stranger_topic.id, name_mn="Өөр")
    db.session.add(stranger)
    db.session.commit()
    h, cid = klass["t_headers"], klass["cohort"].id
    resp = new_session(client, h, cid, lesson_id=lesson.id)
    assert resp.status_code == 201
    assert (resp.get_json()["lesson_id"], resp.get_json()["topic_id"]) == (
        lesson.id, klass["topic"].id)
    bad = new_session(client, h, cid, session_date="2026-10-02", lesson_id=stranger.id)
    assert (bad.status_code, bad.get_json()["error"]) == (400, "invalid_lesson_id")


def test_lesson_list_shows_each_lessons_class(client, db, klass, clock):
    early = CourseLesson(topic_id=klass["topic"].id, name_mn="Нэг", sort_order=0)
    late = CourseLesson(topic_id=klass["topic"].id, name_mn="Хоёр", sort_order=1)
    db.session.add_all([early, late])
    db.session.commit()
    h, cid = klass["t_headers"], klass["cohort"].id
    new_session(client, h, cid, session_date="2026-09-29", lesson_id=early.id)
    new_session(client, h, cid, session_date="2030-01-08", lesson_id=late.id)

    resp = client.get(f"/me/modules/{klass['topic'].id}/lessons", headers=klass["s_headers"])
    assert resp.status_code == 200
    rows = [(x["locked"], x["schedule"], x["attendance"]) for x in resp.get_json()["lessons"]]
    assert rows == [
        (False, {"date": "2026-09-29", "start_time": "09:00"}, "absent"),
        (True, {"date": "2030-01-08", "start_time": "09:00"}, None),
    ]
    locked = client.get(f"/me/lessons/{late.id}", headers=klass["s_headers"])
    assert (locked.status_code, locked.get_json()["error"]) == (409, "lesson_locked")
    assert client.get(f"/me/lessons/{early.id}", headers=klass["s_headers"]).status_code == 200
