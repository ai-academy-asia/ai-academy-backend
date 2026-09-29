"""Student quiz attempts: per-answer grading, finish, scoring, reading results."""
import quiz_helpers
from quiz_helpers import answer, finish, key, run_attempt, start

from app.models import StudentExam

make_quiz = quiz_helpers.make_quiz
enroll = quiz_helpers.enroll
learner = quiz_helpers.learner


def _begin(client, headers, quiz):
    data = start(client, headers, quiz.id).get_json()
    return data["attempt_id"], [q["id"] for q in data["questions"]]


# ----------------------------------------------------------------- answer
def test_answer_reveals_key_for_that_question_only(client, db, learner):
    headers, quiz, _ = learner
    attempt_id, qids = _begin(client, headers, quiz)
    right, wrong = key(db, qids[0])
    resp = answer(client, headers, attempt_id, qids[0], wrong)
    assert resp.status_code == 200
    assert resp.get_json() == {"question_id": qids[0], "option_id": wrong, "correct": False,
                               "correct_option_id": right, "explanation": "because 1"}
    resp = answer(client, headers, attempt_id, qids[1], key(db, qids[1])[0])
    assert resp.get_json()["correct"] is True


def test_answer_is_final(client, db, learner):
    headers, quiz, _ = learner
    attempt_id, qids = _begin(client, headers, quiz)
    right, wrong = key(db, qids[0])
    answer(client, headers, attempt_id, qids[0], wrong)
    resp = answer(client, headers, attempt_id, qids[0], right)
    assert resp.status_code == 409 and resp.get_json()["error"] == "already_answered"


def test_answer_validation(client, db, learner, make_quiz):
    headers, quiz, _ = learner
    other = make_quiz(course_id=quiz.course_id)
    other_q = other.questions[0]
    attempt_id, qids = _begin(client, headers, quiz)
    right_other, _ = key(db, other_q.id)
    right_second, _ = key(db, qids[1])

    cases = [
        ({"question_id": other_q.id, "option_id": right_other}, "invalid_question"),
        ({"question_id": "abc", "option_id": right_second}, "invalid_question"),
        ({"option_id": right_second}, "invalid_question"),
        ({"question_id": qids[0], "option_id": right_second}, "invalid_option"),
        ({"question_id": qids[0], "option_id": 999999}, "invalid_option"),
        ({"question_id": qids[0]}, "invalid_option"),
    ]
    for payload, code in cases:
        resp = client.post(f"/me/quiz-attempts/{attempt_id}/answers", headers=headers,
                           json=payload)
        assert resp.status_code == 400, payload
        assert resp.get_json() == {"error": code}


def test_answer_after_finish_is_409(client, db, learner):
    headers, quiz, _ = learner
    attempt_id, qids = _begin(client, headers, quiz)
    finish(client, headers, attempt_id)
    resp = answer(client, headers, attempt_id, qids[0], key(db, qids[0])[0])
    assert resp.status_code == 409 and resp.get_json()["error"] == "attempt_finished"


def test_answer_needs_active_enrollment(client, db, learner):
    headers, quiz, account = learner
    attempt_id, qids = _begin(client, headers, quiz)
    from app.models import Enrollment

    Enrollment.query.update({"status": "cancelled"})
    db.session.commit()
    resp = answer(client, headers, attempt_id, qids[0], key(db, qids[0])[0])
    assert resp.status_code == 403 and resp.get_json()["error"] == "not_enrolled"


def test_other_students_attempt_is_404(client, db, learner, make_student, enroll):
    headers, quiz, _ = learner
    attempt_id, qids = _begin(client, headers, quiz)
    intruder, intruder_headers = make_student()
    from app.models import Course

    enroll(intruder, db.session.get(Course, quiz.course_id))
    right, _ = key(db, qids[0])
    for resp in (
        answer(client, intruder_headers, attempt_id, qids[0], right),
        finish(client, intruder_headers, attempt_id),
        client.get(f"/me/quiz-attempts/{attempt_id}", headers=intruder_headers),
        client.get("/me/quiz-attempts/999999", headers=headers),
    ):
        assert resp.status_code == 404 and resp.get_json()["error"] == "attempt_not_found"
    assert StudentExam.query.one().completed_at is None


# ----------------------------------------------------------------- finish / scoring
def test_finish_scores_and_persists(client, db, learner):
    headers, quiz, account = learner
    result = run_attempt(client, db, headers, quiz.id, 2)
    assert result["correct"] == 2 and result["total"] == 3
    assert result["percent"] == 66          # floor(2/3*100)
    assert result["passed"] is False        # 66 < 70
    assert result["status"] == "finished" and result["finished_at"].endswith("+00:00")
    assert result["questions"] == [
        {"question_id": q["question_id"], "order": i, "correct": i <= 2}
        for i, q in enumerate(result["questions"], start=1)
    ]
    row = db.session.get(StudentExam, result["attempt_id"])
    assert (row.correct_count, row.total, row.percent, row.is_passed) == (2, 3, 66, False)
    assert row.completed_at is not None


def test_pass_threshold_is_inclusive(client, db, make_student, make_course, make_quiz, enroll):
    account, headers = make_student()
    course = make_course()
    quiz = make_quiz(course=course, questions=4, pass_percent=75)
    enroll(account, course)
    assert run_attempt(client, db, headers, quiz.id, 3)["passed"] is True     # 75 >= 75
    assert run_attempt(client, db, headers, quiz.id, 4)["percent"] == 100


def test_points_do_not_weight_the_percent(client, db, learner):
    headers, quiz, _ = learner
    quiz.questions[0].point = 10
    db.session.commit()
    assert run_attempt(client, db, headers, quiz.id, 1)["percent"] == 33


def test_unanswered_questions_count_as_wrong(client, db, learner):
    headers, quiz, _ = learner
    attempt_id, qids = _begin(client, headers, quiz)
    answer(client, headers, attempt_id, qids[2], key(db, qids[2])[0])
    result = finish(client, headers, attempt_id).get_json()
    assert (result["correct"], result["percent"]) == (1, 33)
    assert [q["correct"] for q in result["questions"]] == [False, False, True]
    assert "correct_option_id" not in str(result) and "because" not in str(result)


def test_finish_is_idempotent_and_readable(client, db, learner):
    headers, quiz, _ = learner
    first = run_attempt(client, db, headers, quiz.id, 3)
    again = finish(client, headers, first["attempt_id"])
    assert again.status_code == 200 and again.get_json() == first
    got = client.get(f"/me/quiz-attempts/{first['attempt_id']}", headers=headers)
    assert got.status_code == 200 and got.get_json() == first
    assert first["passed"] is True and first["percent"] == 100
