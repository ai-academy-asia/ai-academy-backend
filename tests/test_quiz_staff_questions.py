"""Staff quiz authoring: replacing the question set, and reviewing attempts."""
import pytest
import quiz_helpers
from quiz_helpers import run_attempt, start

from app.models import ExamOption, ExamQuestion, StudentExam, StudentExamAnswer

make_quiz = quiz_helpers.make_quiz
enroll = quiz_helpers.enroll
learner = quiz_helpers.learner


@pytest.fixture
def editor(make_staff):
    return make_staff("content_marketing")[1]


def _q(text="What?", correct=0, n=3, **extra):
    return {"question": text, "options": [
        {"answer": f"a{j}", "is_correct": j == correct} for j in range(n)], **extra}


def _put(client, headers, quiz_id, payload, force=False):
    url = f"/admin/quizzes/{quiz_id}/questions" + ("?force=true" if force else "")
    return client.put(url, headers=headers, json=payload)


# ----------------------------------------------------------------- replace
def test_replace_sets_questions_in_order(client, editor, make_quiz):
    quiz = make_quiz(questions=0)
    resp = _put(client, editor, quiz.id, [
        _q("First?", correct=2, explanation=" Why ", image="https://img/x.png", point=2),
        _q("Second?", n=2),
    ])
    assert resp.status_code == 200
    data = resp.get_json()
    assert [q["question"] for q in data["questions"]] == ["First?", "Second?"]
    first = data["questions"][0]
    assert (first["explanation"], first["image"], first["point"]) == (
        "Why", "https://img/x.png", 2)
    assert [o["is_correct"] for o in first["options"]] == [False, False, True]
    assert [o["answer"] for o in first["options"]] == ["a0", "a1", "a2"]
    assert data["question_count"] == 2


def test_replace_accepts_wrapped_payload_and_drops_old(client, db, editor, make_quiz):
    quiz = make_quiz(questions=3)
    resp = _put(client, editor, quiz.id, {"questions": [_q("Only?")]})
    assert resp.status_code == 200
    assert ExamQuestion.query.filter_by(exam_id=quiz.id).count() == 1
    assert ExamOption.query.count() == 3


@pytest.mark.parametrize("payload,index,reason", [
    ([], None, "at_least_one_question"),
    ({"questions": None}, None, "at_least_one_question"),
    ("nope", None, "at_least_one_question"),
    ([_q(), "x"], 1, "not_an_object"),
    ([_q(), _q(text="  ")], 1, "question_required"),
    ([_q(n=1)], 0, "at_least_two_options"),
    ([{"question": "Q?"}], 0, "at_least_two_options"),
    ([_q(correct=5)], 0, "exactly_one_correct"),
    ([{"question": "Q?", "options": [{"answer": "a", "is_correct": True},
                                     {"answer": "b", "is_correct": True}]}],
     0, "exactly_one_correct"),
    ([{"question": "Q?", "options": [{"answer": "a", "is_correct": True},
                                     {"answer": ""}]}], 0, "option_answer_required"),
    ([{"question": "Q?", "options": [{"answer": "a", "is_correct": "yes"},
                                     {"answer": "b"}]}], 0, "invalid_is_correct"),
    ([_q(point=0)], 0, "invalid_point"),
    ([_q(explanation=5)], 0, "invalid_explanation"),
    ([_q(image="x" * 501)], 0, "invalid_image"),
])
def test_replace_validation(client, editor, make_quiz, payload, index, reason):
    quiz = make_quiz(questions=1)
    resp = _put(client, editor, quiz.id, payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert (data["error"], data["index"], data["reason"]) == ("invalid_questions", index, reason)
    assert ExamQuestion.query.filter_by(exam_id=quiz.id).count() == 1   # untouched


def test_replace_blocked_by_attempts_unless_forced(client, db, editor, learner):
    headers, quiz, _ = learner
    run_attempt(client, db, headers, quiz.id, 2)
    start(client, headers, quiz.id)   # an open one too
    resp = _put(client, editor, quiz.id, [_q()])
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "quiz_has_attempts", "attempt_count": 2}
    assert ExamQuestion.query.filter_by(exam_id=quiz.id).count() == 3

    resp = _put(client, editor, quiz.id, [_q()], force=True)
    assert resp.status_code == 200 and resp.get_json()["attempt_count"] == 0
    assert StudentExam.query.count() == 0 and StudentExamAnswer.query.count() == 0
    # The student starts over on the new set.
    fresh = start(client, headers, quiz.id)
    assert fresh.status_code == 201 and len(fresh.get_json()["questions"]) == 1


def test_force_still_validates(client, db, editor, learner):
    headers, quiz, _ = learner
    run_attempt(client, db, headers, quiz.id, 2)
    resp = _put(client, editor, quiz.id, [], force=True)
    assert resp.status_code == 400
    assert StudentExam.query.count() == 1


# ----------------------------------------------------------------- attempts list
def test_attempts_list(client, db, editor, learner, make_student, enroll):
    headers, quiz, account = learner
    from app.models import Course

    other, other_headers = make_student(first_name="Saraa", last_name="Bold")
    enroll(other, db.session.get(Course, quiz.course_id))
    first = run_attempt(client, db, headers, quiz.id, 3)
    start(client, other_headers, quiz.id)

    resp = client.get(f"/admin/quizzes/{quiz.id}/attempts", headers=editor)
    assert resp.status_code == 200
    rows = resp.get_json()["attempts"]
    assert [r["student"]["name"] for r in rows] == ["Saraa Bold", "Bat"]
    assert rows[0]["status"] == "open" and rows[0]["percent"] is None
    assert rows[1] == {
        "attempt_id": first["attempt_id"], "student": {"id": account.actor_id, "name": "Bat"},
        "status": "finished", "correct": 3, "total": 3, "percent": 100, "passed": True,
        "started_at": rows[1]["started_at"], "finished_at": first["finished_at"],
    }

    limited = client.get(f"/admin/quizzes/{quiz.id}/attempts?limit=1", headers=editor)
    assert len(limited.get_json()["attempts"]) == 1
    only = client.get(f"/admin/quizzes/{quiz.id}/attempts?student_id={account.actor_id}",
                      headers=editor).get_json()["attempts"]
    assert [r["attempt_id"] for r in only] == [first["attempt_id"]]


def test_attempts_list_bad_params(client, editor, make_quiz):
    quiz = make_quiz()
    resp = client.get(f"/admin/quizzes/{quiz.id}/attempts?limit=abc", headers=editor)
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_limit"
    resp = client.get(f"/admin/quizzes/{quiz.id}/attempts?student_id=x", headers=editor)
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_student_id"
