"""GET /me/courses/<slug>/certificate — the §2.9 requirement checklist."""
import account_helpers
import pytest

enroll = account_helpers.enroll
make_ledger = account_helpers.make_ledger
make_lessons = account_helpers.make_lessons
complete = account_helpers.complete
make_quiz = account_helpers.make_quiz
earned = account_helpers.earned


def _status(client, headers, course):
    return client.get(f"/me/courses/{course.slug}/certificate", headers=headers)


def test_all_requirements_met_is_eligible(client, earned):
    _, headers, course, _ = earned
    body = _status(client, headers, course).get_json()
    assert body == {
        "status": "eligible",
        "requirements": {
            "lessons_completed": {"done": True, "percent": 100},
            "quizzes_passed": {"done": True, "passed": 0, "required": 0},
            "payment_cleared": {"done": True},
        },
        "certificate": None,
    }


def test_partial_lessons_floor_percent(client, make_student, make_course, make_cohort, enroll,
                                       make_lessons, complete, make_ledger):
    account, headers = make_student()
    course = make_course()
    enr = enroll(account.actor_id, make_cohort(course=course))
    lessons = make_lessons(course, 3)
    complete(enr, lessons[:1])
    make_ledger(enr, paid=1_000_000)
    body = _status(client, headers, course).get_json()
    assert body["status"] == "not_eligible"
    assert body["requirements"]["lessons_completed"] == {"done": False, "percent": 33}


def test_course_without_lessons_is_not_eligible(client, make_student, make_course, make_cohort,
                                                enroll, make_ledger):
    account, headers = make_student()
    course = make_course()
    make_ledger(enroll(account.actor_id, make_cohort(course=course)), paid=1_000_000)
    body = _status(client, headers, course).get_json()
    assert body["requirements"]["lessons_completed"] == {"done": False, "percent": 0}
    assert body["status"] == "not_eligible"


def test_quizzes_requirement_counts_required_non_empty_quizzes(client, earned, make_quiz,
                                                               make_course):
    account, headers, course, _ = earned
    make_quiz(course, passed_by=account.actor_id)
    make_quiz(course)                                  # required, not passed
    make_quiz(course, required=False)                  # optional
    make_quiz(course, questions=0)                     # empty: not required yet
    make_quiz(make_course(), passed_by=account.actor_id)  # another course
    body = _status(client, headers, course).get_json()
    assert body["requirements"]["quizzes_passed"] == {"done": False, "passed": 1, "required": 2}
    assert body["status"] == "not_eligible"


@pytest.mark.parametrize("due,paid,price,done", [
    (1_000_000, 999_999, 1_000_000, False),
    (1_000_000, 1_000_000, 1_000_000, True),
    (1_000_000, 1_200_000, 1_000_000, True),
    (None, None, 1_000_000, False),   # no ledger row, paid course
    (None, None, 0, True),            # no ledger row, free course
    (None, None, None, True),
])
def test_payment_cleared(client, make_student, make_course, make_cohort, enroll, make_lessons,
                         complete, make_ledger, due, paid, price, done):
    account, headers = make_student()
    course = make_course(price_amount=price)
    enr = enroll(account.actor_id, make_cohort(course=course))
    complete(enr, make_lessons(course, 1))
    if due is not None:
        make_ledger(enr, due=due, paid=paid)
    body = _status(client, headers, course).get_json()
    assert body["requirements"]["payment_cleared"] == {"done": done}
    assert body["status"] == ("eligible" if done else "not_eligible")


def test_uses_sibling_services_when_present(client, earned, monkeypatch):
    _, headers, course, enr = earned
    seen = {}

    def _progress(enrollment):
        seen["enrollment"] = enrollment.id
        return {"percent": 50, "completed_lessons": 1, "total_lessons": 2}

    def _quizzes(student_id, course_id):
        seen["quiz"] = (student_id, course_id)
        return {"passed": 2, "required": 3}

    monkeypatch.setattr("app.services.learning.course_progress", _progress, raising=False)
    monkeypatch.setattr("app.services.quizzes.required_quizzes_passed", _quizzes, raising=False)
    body = _status(client, headers, course).get_json()
    assert body["requirements"]["lessons_completed"] == {"done": False, "percent": 50}
    assert body["requirements"]["quizzes_passed"] == {"done": False, "passed": 2, "required": 3}
    assert seen["enrollment"] == enr.id and seen["quiz"][1] == course.id


def test_certificate_status_function_signature(app, earned):
    from app.services.certificates import certificate_status

    account, _, course, enr = earned
    body = certificate_status(account.actor_id, course, enr)
    assert body["status"] == "eligible" and set(body) == {"status", "requirements", "certificate"}
    body = certificate_status(account.actor_id, course, None)
    assert body["status"] == "not_eligible"


def test_issued_certificate_is_reported(client, earned, admin_headers):
    account, headers, course, _ = earned
    client.post("/admin/certificates", headers=admin_headers,
                json={"student_id": account.actor_id, "course_id": course.id})
    body = _status(client, headers, course).get_json()
    assert body["status"] == "issued"
    cert = body["certificate"]
    assert cert["cert_number"].startswith("AIAA-") and cert["has_file"] is False
    assert cert["verify_url"].endswith(f"/certificates/verify/{cert['cert_number']}")


def test_status_access_rules(client, make_student, make_course, make_teacher, earned):
    _, headers, course, _ = earned
    stranger = make_student()[1]
    resp = _status(client, stranger, course)
    assert resp.status_code == 403 and resp.get_json()["error"] == "not_enrolled"
    resp = client.get("/me/courses/nope/certificate", headers=headers)
    assert resp.status_code == 404 and resp.get_json()["error"] == "course_not_found"
    draft = make_course(status="draft")
    assert _status(client, headers, draft).status_code == 404
    assert _status(client, make_teacher()[1], course).status_code == 403
    assert _status(client, {}, course).status_code == 401


def test_cancelled_enrollment_is_not_enrolled(client, make_student, make_course, make_cohort,
                                              enroll):
    account, headers = make_student()
    course = make_course()
    enroll(account.actor_id, make_cohort(course=course), status="cancelled")
    assert _status(client, headers, course).get_json()["error"] == "not_enrolled"
