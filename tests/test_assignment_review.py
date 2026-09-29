"""Teacher review: submission lists, version history, grading, student-file access."""
import assignment_helpers
import pytest

hw = assignment_helpers.hw
s3 = assignment_helpers.s3
make_assignment = assignment_helpers.make_assignment
make_file = assignment_helpers.make_file
make_submission = assignment_helpers.make_submission


@pytest.fixture
def graded(hw, make_assignment, make_submission, make_student, db):
    """An assignment with two versions from hw's student and one from another."""
    from assignment_helpers import enroll

    a = make_assignment(hw.cohort, max_score=10)
    other, _ = make_student(first_name="Сараа")
    enroll(db, hw.cohort, other.actor_id)
    v1 = make_submission(a, hw.sid, version=1)
    v2 = make_submission(a, hw.sid, version=2, submission_url="https://example.com/v2")
    solo = make_submission(a, other.actor_id, version=1)
    return a, v1, v2, solo


# ----------------------------------------------------------------- listing / detail
def test_list_shows_latest_version_per_student(client, hw, graded):
    a, _, v2, solo = graded
    resp = client.get(f"/teacher/assignments/{a.id}/submissions", headers=hw.teacher_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 2 and data["max_score"] == 10
    by_id = {s["id"]: s for s in data["submissions"]}
    assert set(by_id) == {v2.id, solo.id}
    assert by_id[v2.id]["version_count"] == 2 and by_id[solo.id]["version_count"] == 1
    assert by_id[v2.id]["student"] == {"id": hw.sid, "name": "Болд Батаа", "initials": "ББ"}


def test_detail_includes_history(client, hw, graded):
    _, v1, v2, _ = graded
    resp = client.get(f"/teacher/submissions/{v1.id}", headers=hw.teacher_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == v1.id and data["version_count"] == 2
    assert [h["id"] for h in data["history"]] == [v2.id, v1.id]


# ----------------------------------------------------------------- review
def test_teacher_review_sets_score_feedback_and_mentor(client, hw, graded):
    _, _, v2, _ = graded
    resp = client.post(f"/teacher/submissions/{v2.id}/review", headers=hw.teacher_headers,
                       json={"score": 8.5, "feedback": " Сайн ажил "})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "reviewed" and data["score"] == 8.5
    assert data["feedback"]["message"] == "Сайн ажил"
    assert data["feedback"]["mentor"]["initials"] == "ДБ"
    assert data["graded_at"] == data["feedback"]["created_at"] is not None

    student_view = client.get(f"/me/assignments/{v2.assignment_id}",
                              headers=hw.student_headers).get_json()["submission"]
    assert student_view["feedback"]["mentor"] == {
        "id": hw.teacher.actor_id, "name": "Дорж Бат", "initials": "ДБ", "role": "teacher"}


def test_staff_review_has_no_mentor(client, db, hw, graded, make_staff):
    from app.models import AssignmentSubmission

    _, _, v2, _ = graded
    resp = client.post(f"/teacher/submissions/{v2.id}/review",
                       headers=make_staff("sales_enrollment")[1],
                       json={"score": 10, "feedback": "OK"})
    assert resp.status_code == 200
    assert resp.get_json()["feedback"]["mentor"] is None
    db.session.expire_all()
    assert db.session.get(AssignmentSubmission, v2.id).graded_by_teacher_id is None


@pytest.mark.parametrize("payload, code", [
    ({"score": 5}, "feedback_required"),
    ({"score": 5, "feedback": "   "}, "feedback_required"),
    ({"score": 5, "feedback": "x" * 5001}, "feedback_too_long"),
    ({"feedback": "ok"}, "invalid_score"),
    ({"score": -1, "feedback": "ok"}, "invalid_score"),
    ({"score": 11, "feedback": "ok"}, "invalid_score"),
    ({"score": "ten", "feedback": "ok"}, "invalid_score"),
    ({"score": True, "feedback": "ok"}, "invalid_score"),
    ({"score": 1.234, "feedback": "ok"}, "invalid_score"),
])
def test_review_validation(client, hw, graded, payload, code):
    _, _, v2, _ = graded
    resp = client.post(f"/teacher/submissions/{v2.id}/review", headers=hw.teacher_headers,
                       json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == code


def test_review_without_max_score_accepts_any_non_negative(client, hw, make_assignment,
                                                           make_submission):
    sub = make_submission(make_assignment(hw.cohort, max_score=None), hw.sid)
    resp = client.post(f"/teacher/submissions/{sub.id}/review", headers=hw.teacher_headers,
                       json={"score": 250, "feedback": "ok"})
    assert resp.status_code == 200 and resp.get_json()["score"] == 250


# ----------------------------------------------------------------- student file
def test_submission_file_presigned(client, hw, s3, make_assignment, make_submission,
                                   make_file):
    f = make_file(hw.sid)
    sub = make_submission(make_assignment(hw.cohort), hw.sid, file_id=f.id)
    resp = client.get(f"/teacher/submissions/{sub.id}/file", headers=hw.teacher_headers)
    assert resp.status_code == 200
    assert resp.get_json()["url"] == f"https://s3.test/{f.file_key}?sig=1"


def test_submission_without_file_is_404(client, hw, s3, graded):
    _, v1, _, _ = graded
    resp = client.get(f"/teacher/submissions/{v1.id}/file", headers=hw.teacher_headers)
    assert resp.status_code == 404 and resp.get_json()["error"] == "file_not_found"


# ----------------------------------------------------------------- access
def test_other_teacher_sees_nothing(client, hw, graded, make_teacher):
    a, v1, _, _ = graded
    _, other = make_teacher()
    resp = client.get(f"/teacher/assignments/{a.id}/submissions", headers=other)
    assert resp.status_code == 404 and resp.get_json()["error"] == "assignment_not_found"
    for method, url in (("get", f"/teacher/submissions/{v1.id}"),
                        ("post", f"/teacher/submissions/{v1.id}/review"),
                        ("get", f"/teacher/submissions/{v1.id}/file")):
        resp = getattr(client, method)(url, headers=other, json={"score": 1, "feedback": "x"})
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "submission_not_found"


def test_review_forbidden_for_students_and_unrelated_staff(client, hw, graded, make_staff):
    _, v1, _, _ = graded
    for headers in (hw.student_headers, make_staff("finance")[1]):
        resp = client.post(f"/teacher/submissions/{v1.id}/review", headers=headers,
                           json={"score": 1, "feedback": "x"})
        assert resp.status_code == 403
    resp = client.post(f"/teacher/submissions/{v1.id}/review",
                       json={"score": 1, "feedback": "x"})
    assert resp.status_code == 401


def test_unknown_submission_is_404(client, hw):
    resp = client.get("/teacher/submissions/999999", headers=hw.teacher_headers)
    assert resp.status_code == 404 and resp.get_json()["error"] == "submission_not_found"
