"""`flask seed programme`: the test data must load and read back through the real API."""
from datetime import date

import pytest

from app.models import (
    AuthAccount,
    ClassSession,
    Course,
    CourseLesson,
    Exam,
    StudentExam,
    StudentLedger,
)
from app.seeds_programmes import SeedExists, remove, run

TODAY = date(2026, 10, 1)


def _login(client, email):
    resp = client.post("/auth/login", json={"email": email, "password": "Test1234!"})
    assert resp.status_code == 200, resp.get_json()
    return {"Authorization": f"Bearer {resp.get_json()['access_token']}"}


def _accounts(prefix):
    return AuthAccount.query.filter(AuthAccount.email.like(f"{prefix}.%")).count()


def test_engineering_is_mid_way_through_module_5(app, db):
    result = run("engineering", today=TODAY)

    assert result["lessons"] == 95 == CourseLesson.query.count()
    assert Exam.query.count() == 5
    assert ClassSession.query.filter(ClassSession.session_date < TODAY).count() == 79
    assert StudentExam.query.filter(StudentExam.completed_at.isnot(None)).count() > 0
    assert Course.query.filter_by(slug="ai-engineering").one().status == "closed"


def test_corporate_leaders_started_on_6_august(app, db):
    result = run("corporate", today=TODAY)

    assert result["lessons"] == 12
    assert result["start"] == date(2026, 8, 6)
    assert ClassSession.query.filter(ClassSession.session_date < TODAY).count() == 8


def test_online_is_its_own_course_without_a_classroom(app, db):
    run("corporate", today=TODAY)
    run("online", today=TODAY)

    online = Course.query.filter_by(slug="ai-applied-online").one()
    assert online.format == "online"
    assert Course.query.filter_by(slug="ai-corporate-leaders").one().id != online.id
    assert _accounts("online") == _accounts("corp") == 12
    # A single-payment plan: every ledger is either settled or owes the full price.
    balances = {int(row.balance) for row in StudentLedger.query.all()}
    assert balances <= {0, 1490000, 2450000, 4900000}


def test_refuses_twice_resets_and_removes_one_programme_only(app, db):
    run("engineering", today=TODAY)
    run("online", today=TODAY)
    with pytest.raises(SeedExists):
        run("engineering", today=TODAY)

    run("engineering", today=TODAY, reset=True)
    assert Course.query.filter_by(slug="ai-engineering").count() == 1
    assert _accounts("eng") == 13

    remove("engineering")
    assert Course.query.filter_by(slug="ai-engineering").count() == 0
    assert _accounts("eng") == 0
    assert _accounts("online") == 12


@pytest.mark.parametrize("key, login, locked", [
    ("engineering", "eng.s01", [False] * 5 + [True]),
    ("corporate", "corp.s01", [False, False, False, True]),
    ("online", "online.s01", [False, False, True, True]),
    ("agentic", "agentic.s01", [False, False, False, True]),
    ("business", "biz.s01", [False, False, True, True]),
    ("summer-kids", "jr10.s01", [False, False, False]),
    ("summer-teens", "jr14.s01", [False, False, False]),
])
def test_student_sees_the_path_unlocked_up_to_today(app, db, client, key, login, locked):
    result = run(key, today=date.today())
    headers = _login(client, f"{login}@test.ai-academy.asia")

    resp = client.get(f"/me/courses/{result['slug']}/learning", headers=headers)
    assert resp.status_code == 200, resp.get_json()
    assert [m["locked"] for m in resp.get_json()["modules"]] == locked
    assert client.get("/me/ledger", headers=headers).status_code == 200


def test_dropped_student_is_not_enrolled(app, db, client):
    result = run("corporate", today=date.today())
    headers = _login(client, result["dropped"])
    resp = client.get(f"/me/courses/{result['slug']}/learning", headers=headers)
    assert resp.status_code == 403


def test_agentic_and_business_are_separate_courses_on_one_syllabus(app, db):
    agentic = run("agentic", today=TODAY)
    business = run("business", today=TODAY)

    assert agentic["lessons"] == business["lessons"] == 14
    assert agentic["course_id"] != business["course_id"]
    assert _accounts("agentic") == _accounts("biz") == 12
    assert Exam.query.count() == 4


@pytest.mark.parametrize("key, first, last", [
    ("summer-kids", date(2026, 6, 16), date(2026, 7, 9)),
    ("summer-teens", date(2026, 6, 15), date(2026, 7, 8)),
])
def test_summer_camps_are_finished_on_their_real_dates(app, db, key, first, last):
    from app.models import Enrollment, Student
    from app.services.certificates.eligibility import requirements

    result = run(key, today=TODAY)
    assert (result["start"], result["end"], result["lessons"]) == (first, last, 11)

    enrollment = Enrollment.query.order_by(Enrollment.id).first()   # the most diligent
    best = db.session.get(Student, enrollment.student_id)
    assert best.parent_name == best.last_name
    course = db.session.get(Course, result["course_id"])
    reqs = requirements(best.id, course, enrollment)
    assert all(item["done"] for item in reqs.values()), reqs
