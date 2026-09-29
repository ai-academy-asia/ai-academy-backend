"""Student quiz attempts: start / resume, access rules, attempt limit, key secrecy."""
import pytest
import quiz_helpers
from quiz_helpers import answer, assert_no_key, key, run_attempt, start
from sqlalchemy.exc import IntegrityError

from app.models import StudentExam

make_quiz = quiz_helpers.make_quiz
enroll = quiz_helpers.enroll
learner = quiz_helpers.learner


# ----------------------------------------------------------------- auth
@pytest.mark.parametrize("method,path", [
    ("post", "/me/quizzes/1/attempts"),
    ("post", "/me/quiz-attempts/1/answers"),
    ("post", "/me/quiz-attempts/1/finish"),
    ("get", "/me/quiz-attempts/1"),
])
def test_requires_student_token(client, admin_headers, make_teacher, method, path):
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers=admin_headers).status_code == 403
    _, teacher = make_teacher()
    resp = getattr(client, method)(path, headers=teacher)
    assert resp.status_code == 403 and resp.get_json()["error"] == "forbidden"


# ----------------------------------------------------------------- start
def test_start_creates_attempt_with_ordered_questions(client, learner):
    headers, quiz, _ = learner
    resp = start(client, headers, quiz.id)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "open" and data["attempt_id"]
    assert data["started_at"].endswith("+00:00")
    assert [q["order"] for q in data["questions"]] == [1, 2, 3]
    assert [q["prompt"] for q in data["questions"]] == ["Q1?", "Q2?", "Q3?"]
    assert [o["text"] for o in data["questions"][0]["options"]] == [
        "opt 1.0", "opt 1.1", "opt 1.2"]


def test_start_payload_never_carries_the_answer_key(client, learner):
    headers, quiz, _ = learner
    data = start(client, headers, quiz.id).get_json()
    for question in data["questions"]:
        assert_no_key(question)
    raw = start(client, headers, quiz.id).get_data(as_text=True)
    assert "is_correct" not in raw and "because" not in raw
    assert "correct_option_id" not in raw


def test_resume_returns_same_attempt_and_reveals_only_answered(client, db, learner):
    headers, quiz, _ = learner
    first = start(client, headers, quiz.id).get_json()
    q1 = first["questions"][0]["id"]
    right, _ = key(db, q1)
    answer(client, headers, first["attempt_id"], q1, right)

    resp = start(client, headers, quiz.id)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["attempt_id"] == first["attempt_id"]
    assert data["questions"][0]["answer"] == {
        "question_id": q1, "option_id": right, "correct": True,
        "correct_option_id": right, "explanation": "because 1",
    }
    for question in data["questions"][1:]:
        assert_no_key(question)
    assert "because 2" not in resp.get_data(as_text=True)
    assert StudentExam.query.count() == 1


def test_get_open_attempt_hides_key_of_unanswered(client, learner):
    headers, quiz, _ = learner
    attempt_id = start(client, headers, quiz.id).get_json()["attempt_id"]
    resp = client.get(f"/me/quiz-attempts/{attempt_id}", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "open"
    for question in data["questions"]:
        assert_no_key(question)


def test_start_unknown_inactive_or_empty_quiz_is_404(client, make_student, make_course,
                                                     make_quiz, enroll):
    account, headers = make_student()
    course = make_course()
    enroll(account, course)
    inactive = make_quiz(course=course, is_active=False)
    empty = make_quiz(course=course, questions=0)
    for quiz_id in (999999, inactive.id, empty.id):
        resp = start(client, headers, quiz_id)
        assert resp.status_code == 404 and resp.get_json()["error"] == "quiz_not_found"


def test_start_requires_active_enrollment(client, make_student, make_course, make_quiz, enroll):
    account, headers = make_student()
    course = make_course()
    quiz = make_quiz(course=course)
    resp = start(client, headers, quiz.id)
    assert resp.status_code == 403 and resp.get_json()["error"] == "not_enrolled"

    enroll(account, course, status="cancelled")
    assert start(client, headers, quiz.id).get_json()["error"] == "not_enrolled"
    enroll(account, make_course())  # another course does not count
    assert start(client, headers, quiz.id).status_code == 403


# ----------------------------------------------------------------- attempt limit
def test_attempt_limit_counts_finished_attempts(client, db, make_student, make_course,
                                                make_quiz, enroll):
    account, headers = make_student()
    course = make_course()
    quiz = make_quiz(course=course, max_attempts=2)
    enroll(account, course)
    run_attempt(client, db, headers, quiz.id, 0)
    # An open attempt is resumable; it does not use up the limit.
    opened = start(client, headers, quiz.id)
    assert opened.status_code == 201
    assert start(client, headers, quiz.id).status_code == 200
    client.post(f"/me/quiz-attempts/{opened.get_json()['attempt_id']}/finish", headers=headers)

    resp = start(client, headers, quiz.id)
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "no_attempts_left", "attempts_used": 2,
                               "max_attempts": 2}


def test_unlimited_attempts(client, db, learner):
    headers, quiz, _ = learner
    for _ in range(4):
        run_attempt(client, db, headers, quiz.id, 1)
    assert start(client, headers, quiz.id).status_code == 201


# ----------------------------------------------------------------- race
def test_concurrent_start_resumes_the_winner(client, db, learner, monkeypatch):
    """The partial unique index rejects a second open attempt; the loser resumes."""
    headers, quiz, account = learner
    from app.services.quizzes import attempts as svc

    winner = StudentExam(exam_id=quiz.id, student_id=account.actor_id)
    won = {}
    real = svc.open_attempt_for
    calls = {"n": 0}

    def racing(student_id, quiz_id):
        calls["n"] += 1
        if calls["n"] == 1:   # the pre-check sees nothing; then another request commits
            db.session.add(winner)
            db.session.commit()
            won["id"] = winner.id
            return None
        return real(student_id, quiz_id)

    monkeypatch.setattr(svc, "open_attempt_for", racing)
    resp = start(client, headers, quiz.id)
    assert resp.status_code == 200
    assert resp.get_json()["attempt_id"] == won["id"]
    assert StudentExam.query.count() == 1


def test_partial_index_blocks_two_open_attempts(db, learner):
    _, quiz, account = learner
    db.session.add(StudentExam(exam_id=quiz.id, student_id=account.actor_id))
    db.session.commit()
    db.session.add(StudentExam(exam_id=quiz.id, student_id=account.actor_id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
