"""Staff quiz authoring: access, CRUD, field validation, placement, delete."""
import pytest
import quiz_helpers
from quiz_helpers import add_lesson, run_attempt

from app.models import Exam, StudentExam

make_quiz = quiz_helpers.make_quiz
enroll = quiz_helpers.enroll
learner = quiz_helpers.learner


@pytest.fixture
def editor(make_staff):
    return make_staff("content_marketing")[1]


ENDPOINTS = [
    ("get", "/admin/courses/1/quizzes"),
    ("post", "/admin/courses/1/quizzes"),
    ("get", "/admin/quizzes/1"),
    ("patch", "/admin/quizzes/1"),
    ("delete", "/admin/quizzes/1"),
    ("put", "/admin/quizzes/1/questions"),
    ("get", "/admin/quizzes/1/attempts"),
]


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_requires_course_edit(client, make_staff, make_student, method, path):
    assert getattr(client, method)(path).status_code == 401
    for headers in (make_staff("finance")[1], make_student()[1]):
        resp = getattr(client, method)(path, headers=headers, json={})
        assert resp.status_code == 403 and resp.get_json()["error"] == "forbidden"


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_unknown_ids_are_404(client, editor, method, path):
    resp = getattr(client, method)(path.replace("/1", "/999999"), headers=editor, json={})
    assert resp.status_code == 404
    expected = "course_not_found" if "/courses/" in path else "quiz_not_found"
    assert resp.get_json()["error"] == expected


# ----------------------------------------------------------------- create / read
def test_create_defaults_and_list(client, db, editor, make_course):
    course = make_course()
    resp = client.post(f"/admin/courses/{course.id}/quizzes", headers=editor,
                       json={"name_mn": "  Эхний шалгалт ", "name_en": "First"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["name_mn"] == "Эхний шалгалт" and data["title"]["en"] == "First"
    assert (data["pass_percent"], data["max_attempts"]) == (70, None)
    assert (data["is_required"], data["is_active"]) == (True, True)
    assert data["questions"] == [] and data["attempt_count"] == 0

    listed = client.get(f"/admin/courses/{course.id}/quizzes", headers=editor).get_json()
    assert [q["id"] for q in listed["quizzes"]] == [data["id"]]
    assert "questions" not in listed["quizzes"][0]


def test_staff_get_includes_answer_key(client, editor, make_quiz):
    quiz = make_quiz(questions=2)
    data = client.get(f"/admin/quizzes/{quiz.id}", headers=editor).get_json()
    assert data["question_count"] == 2
    first = data["questions"][0]
    assert first["explanation"] == "because 1"
    assert [o["is_correct"] for o in first["options"]] == [False, True, False]
    assert [o["order"] for o in first["options"]] == [1, 2, 3]


def test_super_admin_may_author(client, admin_headers, make_course):
    course = make_course()
    resp = client.post(f"/admin/courses/{course.id}/quizzes", headers=admin_headers,
                       json={"name_mn": "Q"})
    assert resp.status_code == 201


@pytest.mark.parametrize("payload,code", [
    ({}, "name_mn_required"),
    ({"name_mn": "   "}, "name_mn_required"),
    ({"name_mn": 5}, "invalid_name_mn"),
    ({"name_mn": "x" * 201}, "invalid_name_mn"),
    ({"name_mn": "Q", "name_en": ["x"]}, "invalid_name_en"),
    ({"name_mn": "Q", "pass_percent": 101}, "invalid_pass_percent"),
    ({"name_mn": "Q", "pass_percent": -1}, "invalid_pass_percent"),
    ({"name_mn": "Q", "pass_percent": "70"}, "invalid_pass_percent"),
    ({"name_mn": "Q", "pass_percent": None}, "invalid_pass_percent"),
    ({"name_mn": "Q", "max_attempts": 0}, "invalid_max_attempts"),
    ({"name_mn": "Q", "max_attempts": True}, "invalid_max_attempts"),
    ({"name_mn": "Q", "is_required": "yes"}, "invalid_is_required"),
    ({"name_mn": "Q", "is_active": None}, "invalid_is_active"),
    ({"name_mn": "Q", "lesson_id": 999999}, "invalid_lesson_id"),
    ({"name_mn": "Q", "lesson_id": "abc"}, "invalid_lesson_id"),
    ({"name_mn": "Q", "topic_id": 999999}, "invalid_topic_id"),
])
def test_create_validation(client, editor, make_course, payload, code):
    course = make_course()
    resp = client.post(f"/admin/courses/{course.id}/quizzes", headers=editor, json=payload)
    assert resp.status_code == 400 and resp.get_json() == {"error": code}
    assert Exam.query.count() == 0


def test_placement_must_be_in_the_quiz_course(client, db, editor, make_course):
    course, other = make_course(), make_course()
    lesson = add_lesson(db, course)
    foreign = add_lesson(db, other)
    url = f"/admin/courses/{course.id}/quizzes"
    resp = client.post(url, headers=editor, json={"name_mn": "Q", "lesson_id": foreign.id})
    assert resp.get_json()["error"] == "invalid_lesson_id"
    resp = client.post(url, headers=editor,
                       json={"name_mn": "Q", "topic_id": foreign.topic_id})
    assert resp.get_json()["error"] == "invalid_topic_id"

    resp = client.post(url, headers=editor, json={"name_mn": "Q", "lesson_id": lesson.id})
    assert resp.status_code == 201
    assert (resp.get_json()["lesson_id"], resp.get_json()["topic_id"]) == (
        lesson.id, lesson.topic_id)


# ----------------------------------------------------------------- update
def test_patch_updates_and_clears(client, db, editor, make_course, make_quiz):
    course = make_course()
    lesson = add_lesson(db, course)
    quiz = make_quiz(course=course, lesson=lesson, max_attempts=2)
    resp = client.patch(f"/admin/quizzes/{quiz.id}", headers=editor, json={
        "name_en": None, "pass_percent": 0, "max_attempts": None, "is_active": False,
        "lesson_id": None,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert (data["name_en"], data["pass_percent"], data["max_attempts"]) == (None, 0, None)
    assert data["is_active"] is False and data["lesson_id"] is None
    assert data["name_mn"] == "Шалгалт"      # untouched fields stay


def test_patch_validation(client, editor, make_quiz):
    quiz = make_quiz()
    for payload, code in [({"name_mn": ""}, "name_mn_required"),
                          ({"pass_percent": 150}, "invalid_pass_percent"),
                          ({"topic_id": 999999}, "invalid_topic_id")]:
        resp = client.patch(f"/admin/quizzes/{quiz.id}", headers=editor, json=payload)
        assert resp.status_code == 400 and resp.get_json()["error"] == code


# ----------------------------------------------------------------- delete
def test_delete_without_attempts(client, editor, make_quiz):
    quiz = make_quiz()
    resp = client.delete(f"/admin/quizzes/{quiz.id}", headers=editor)
    assert resp.status_code == 200 and resp.get_json() == {"status": "deleted"}
    assert Exam.query.count() == 0


def test_delete_with_attempts_needs_force(client, db, editor, learner):
    headers, quiz, _ = learner
    run_attempt(client, db, headers, quiz.id, 1)
    resp = client.delete(f"/admin/quizzes/{quiz.id}", headers=editor)
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "quiz_has_attempts", "attempt_count": 1}
    resp = client.delete(f"/admin/quizzes/{quiz.id}?force=true", headers=editor)
    assert resp.status_code == 200
    assert Exam.query.count() == 0 and StudentExam.query.count() == 0
