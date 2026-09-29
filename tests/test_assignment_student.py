"""Student assignments: read, submit, resubmit (contract §2.6)."""
from datetime import datetime

import assignment_helpers
import pytest
from assignment_helpers import days, enroll

from app.models import AssignmentSubmission
from app.services.assignments import assignment_for_lesson

hw = assignment_helpers.hw
make_assignment = assignment_helpers.make_assignment
make_file = assignment_helpers.make_file
make_submission = assignment_helpers.make_submission


# ----------------------------------------------------------------- GET
def test_get_assignment_without_submission(client, hw, make_assignment):
    a = make_assignment(hw.cohort, title_en="Homework", instructions_mn="Хий",
                        due_date=days(3), attachment_material_id=hw.material.id)
    resp = client.get(f"/me/assignments/{a.id}", headers=hw.student_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["title"] == {"mn": "Даалгавар", "en": "Homework"}
    assert data["instructions"] == {"mn": "Хий", "en": None}
    assert data["due_date"] == days(3).isoformat()
    assert data["max_score"] == 100
    assert data["attachment"]["id"] == hw.material.id
    assert data["attachment"]["file_name"] == "slides.pdf"
    assert data["attachment"]["size_bytes"] == 1234
    assert data["submission"] is None


def test_get_shows_latest_version_with_feedback(client, db, hw, make_assignment,
                                                make_submission):
    a = make_assignment(hw.cohort)
    make_submission(a, hw.sid, version=1, status="reviewed", score=50, feedback="old",
                    graded_by_teacher_id=hw.teacher.actor_id, graded_at=datetime.utcnow())
    make_submission(a, hw.sid, version=2, status="reviewed", score=85.5, feedback="Сайн",
                    graded_by_teacher_id=hw.teacher.actor_id,
                    graded_at=datetime(2026, 8, 20, 3, 0))
    sub = client.get(f"/me/assignments/{a.id}",
                     headers=hw.student_headers).get_json()["submission"]
    assert sub["version"] == 2
    assert sub["status"] == "reviewed"
    assert sub["score"] == 85.5
    assert sub["feedback"]["message"] == "Сайн"
    assert sub["feedback"]["created_at"] == "2026-08-20T03:00:00+00:00"
    assert sub["feedback"]["mentor"] == {"id": hw.teacher.actor_id, "name": "Дорж Бат",
                                         "initials": "ДБ", "role": "teacher"}


def test_feedback_null_until_reviewed(client, hw, make_assignment, make_submission):
    a = make_assignment(hw.cohort)
    make_submission(a, hw.sid)
    sub = client.get(f"/me/assignments/{a.id}",
                     headers=hw.student_headers).get_json()["submission"]
    assert sub["status"] == "submitted" and sub["feedback"] is None and sub["score"] is None


def test_other_cohort_inactive_and_unknown_are_404(client, db, hw, make_assignment,
                                                  make_cohort):
    other = make_assignment(make_cohort(course=hw.course))
    inactive = make_assignment(hw.cohort, is_active=False)
    for aid in (other.id, inactive.id, 999999):
        resp = client.get(f"/me/assignments/{aid}", headers=hw.student_headers)
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "assignment_not_found"


def test_cancelled_enrollment_is_404(client, db, hw, make_assignment, make_student,
                                     make_cohort):
    cohort = make_cohort(course=hw.course)
    account, headers = make_student()
    enroll(db, cohort, account.actor_id, status="cancelled")
    a = make_assignment(cohort)
    assert client.get(f"/me/assignments/{a.id}", headers=headers).status_code == 404


def test_auth_required_and_student_only(client, hw, make_assignment):
    a = make_assignment(hw.cohort)
    assert client.get(f"/me/assignments/{a.id}").status_code == 401
    resp = client.get(f"/me/assignments/{a.id}", headers=hw.teacher_headers)
    assert resp.status_code == 403 and resp.get_json()["error"] == "forbidden"
    resp = client.post(f"/me/assignments/{a.id}/submissions", json={"link": "https://x.io"})
    assert resp.status_code == 401


# ----------------------------------------------------------------- submit
def test_submit_creates_versions_and_keeps_history(client, db, hw, make_assignment):
    a = make_assignment(hw.cohort, due_date=days(0))
    url = f"/me/assignments/{a.id}/submissions"
    first = client.post(url, headers=hw.student_headers,
                        json={"link": " https://github.com/me/hw ", "description": " v1 "})
    assert first.status_code == 201
    body = first.get_json()
    assert body["version"] == 1 and body["status"] == "submitted"
    assert body["link"] == "https://github.com/me/hw" and body["description"] == "v1"
    assert body["file"] is None and body["feedback"] is None and body["submitted_at"]

    second = client.post(url, headers=hw.student_headers, json={"link": "http://b.mn/2"})
    assert second.status_code == 201 and second.get_json()["version"] == 2
    assert AssignmentSubmission.query.filter_by(assignment_id=a.id).count() == 2
    latest = client.get(f"/me/assignments/{a.id}", headers=hw.student_headers).get_json()
    assert latest["submission"]["id"] == second.get_json()["id"]


def test_submit_with_own_file(client, hw, make_assignment, make_file):
    a = make_assignment(hw.cohort)
    f = make_file(hw.sid)
    resp = client.post(f"/me/assignments/{a.id}/submissions", headers=hw.student_headers,
                       json={"file_id": f.id})
    assert resp.status_code == 201
    assert resp.get_json()["file"] == {"id": f.id, "file_name": "report.pdf",
                                       "content_type": "application/pdf", "size_bytes": 10}
    assert resp.get_json()["link"] is None


def test_submit_with_someone_elses_file_is_404(client, hw, make_assignment, make_file,
                                               make_student):
    a = make_assignment(hw.cohort)
    foreign = make_file(make_student()[0].actor_id)
    for file_id in (foreign.id, 999999, "abc"):
        resp = client.post(f"/me/assignments/{a.id}/submissions",
                           headers=hw.student_headers, json={"file_id": file_id})
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "file_not_found"


@pytest.mark.parametrize("payload, code", [
    ({}, "submission_empty"),
    ({"link": "   ", "description": "only text"}, "submission_empty"),
    ({"link": "ftp://example.com/x"}, "invalid_link"),
    ({"link": "javascript:alert(1)"}, "invalid_link"),
    ({"link": "https://"}, "invalid_link"),
    ({"link": "https://x.io/" + "a" * 1000}, "invalid_link"),
    ({"link": "https://x.io", "description": "d" * 5001}, "description_too_long"),
    ({"link": 123}, "invalid_field"),
])
def test_submit_validation(client, hw, make_assignment, payload, code):
    a = make_assignment(hw.cohort)
    resp = client.post(f"/me/assignments/{a.id}/submissions", headers=hw.student_headers,
                       json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == code


def test_description_at_limit_is_accepted(client, hw, make_assignment):
    a = make_assignment(hw.cohort)
    resp = client.post(f"/me/assignments/{a.id}/submissions", headers=hw.student_headers,
                       json={"link": "https://x.io", "description": "d" * 5000})
    assert resp.status_code == 201


def test_past_due_is_409_but_no_due_date_always_allowed(client, hw, make_assignment):
    late = make_assignment(hw.cohort, due_date=days(-1))
    resp = client.post(f"/me/assignments/{late.id}/submissions", headers=hw.student_headers,
                       json={"link": "https://x.io"})
    assert resp.status_code == 409 and resp.get_json()["error"] == "past_due"
    open_ended = make_assignment(hw.cohort, due_date=None)
    resp = client.post(f"/me/assignments/{open_ended.id}/submissions",
                       headers=hw.student_headers, json={"link": "https://x.io"})
    assert resp.status_code == 201


def test_submit_to_foreign_or_inactive_assignment_is_404(client, hw, make_assignment,
                                                         make_cohort):
    for a in (make_assignment(make_cohort(course=hw.course)),
              make_assignment(hw.cohort, is_active=False)):
        resp = client.post(f"/me/assignments/{a.id}/submissions",
                           headers=hw.student_headers, json={"link": "https://x.io"})
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "assignment_not_found"


# ----------------------------------------------------------------- lesson embed
def test_assignment_for_lesson(app, db, hw, make_assignment, make_submission):
    from app.models import Enrollment

    enrollment = Enrollment.query.filter_by(student_id=hw.sid).one()
    assert assignment_for_lesson(hw.sid, enrollment, hw.lesson) is None
    make_assignment(hw.cohort, lesson_id=hw.lesson.id, is_active=False)
    first = make_assignment(hw.cohort, lesson_id=hw.lesson.id, title_mn="A")
    make_assignment(hw.cohort, lesson_id=hw.lesson.id, title_mn="B")
    make_submission(first, hw.sid)
    data = assignment_for_lesson(hw.sid, enrollment, hw.lesson)
    assert data["id"] == first.id
    assert data["submission"]["version"] == 1
