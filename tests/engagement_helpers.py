"""Shared fixtures and helpers for the attendance and notification tests."""
from datetime import date, datetime, timezone

import pytest

from app.models import CourseTopic, Enrollment
from app.timeutil import LOCAL_TZ

DAY = date(2026, 10, 1)  # a Thursday, the default cohort start


def _fresh(db, model, pk):
    db.session.expire_all()
    return db.session.get(model, pk)


def enroll(db, cohort, student_account, status="active"):
    e = Enrollment(cohort_id=cohort.id, student_id=student_account.actor_id,
                   course_id=cohort.course_id, status=status)
    db.session.add(e)
    db.session.commit()
    return e


def make_topic(db, course, name="Module"):
    topic = CourseTopic(course_id=course.id, name_mn=name)
    db.session.add(topic)
    db.session.commit()
    return topic


def new_session(client, headers, cohort_id, **fields):
    data = {"session_date": DAY.isoformat(), "start_time": "09:00", "end_time": "11:00"}
    data.update(fields)
    return client.post(f"/teacher/cohorts/{cohort_id}/sessions", headers=headers, json=data)


@pytest.fixture
def clock(monkeypatch):
    """``clock(datetime(2026, 10, 1, 9, 5))`` freezes the attendance clock at that
    Ulaanbaatar wall-clock time."""

    def _set(local_dt):
        utc = local_dt.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        monkeypatch.setattr("app.services.attendance.clock.now", lambda: utc)
        return utc

    _set(datetime(2026, 10, 1, 9, 0))
    return _set


@pytest.fixture
def klass(db, make_teacher, make_student, make_course, make_cohort):
    """A course, a cohort taught by a teacher, one enrolled student and a topic."""
    teacher, t_headers = make_teacher()
    student, s_headers = make_student(first_name="Anu", phone="99112233")
    course = make_course(slug="corp-leaders")
    cohort = make_cohort(course=course, teacher_id=teacher.actor_id,
                         meeting_days=["tue", "thu"], start_time="09:00", end_time="11:00")
    enroll(db, cohort, student)
    return {
        "teacher": teacher, "t_headers": t_headers,
        "student": student, "s_headers": s_headers,
        "course": course, "cohort": cohort, "topic": make_topic(db, course),
    }
