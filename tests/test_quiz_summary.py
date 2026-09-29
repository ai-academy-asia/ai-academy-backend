"""Quiz state read by other areas: lesson summary and certificate eligibility."""
import quiz_helpers
from quiz_helpers import add_lesson, run_attempt, start

from app.services.quizzes import quiz_summary_for_lesson, required_quizzes_passed

make_quiz = quiz_helpers.make_quiz
enroll = quiz_helpers.enroll


def _setup(db, make_student, make_course, enroll):
    account, headers = make_student()
    course = make_course()
    enroll(account, course)
    return account, headers, course, add_lesson(db, course)


def test_summary_none_without_a_live_quiz(db, make_student, make_course, make_quiz, enroll):
    account, _, course, lesson = _setup(db, make_student, make_course, enroll)
    assert quiz_summary_for_lesson(account.actor_id, lesson) is None
    make_quiz(course=course, lesson=lesson, is_active=False)
    make_quiz(course=course, lesson=lesson, questions=0)
    make_quiz(course=course)   # course-level quiz, not this lesson's
    assert quiz_summary_for_lesson(account.actor_id, lesson) is None


def test_summary_fresh(db, make_student, make_course, make_quiz, enroll):
    account, _, course, lesson = _setup(db, make_student, make_course, enroll)
    quiz = make_quiz(course=course, lesson=lesson, max_attempts=3)
    make_quiz(course=course, lesson=lesson)   # higher id: not chosen
    assert quiz_summary_for_lesson(account.actor_id, lesson) == {
        "id": quiz.id, "title": {"mn": "Шалгалт", "en": "Quiz"}, "question_count": 3,
        "pass_percent": 70, "is_required": True, "attempts_used": 0, "attempts_left": 3,
        "open_attempt_id": None, "last_result": None,
    }


def test_summary_tracks_attempts(client, db, make_student, make_course, make_quiz, enroll):
    account, headers, course, lesson = _setup(db, make_student, make_course, enroll)
    quiz = make_quiz(course=course, lesson=lesson, max_attempts=2)
    first = run_attempt(client, db, headers, quiz.id, 3)
    second = run_attempt(client, db, headers, quiz.id, 1)

    data = quiz_summary_for_lesson(account.actor_id, lesson)
    assert (data["attempts_used"], data["attempts_left"]) == (2, 0)
    # last_result is the most recent finished attempt, not the best one.
    assert data["last_result"] == {
        "attempt_id": second["attempt_id"], "correct": 1, "total": 3, "percent": 33,
        "passed": False, "finished_at": second["finished_at"],
    }
    assert first["passed"] is True


def test_summary_open_attempt_and_unlimited(client, db, make_student, make_course, make_quiz,
                                            enroll):
    account, headers, course, lesson = _setup(db, make_student, make_course, enroll)
    quiz = make_quiz(course=course, lesson=lesson)
    attempt_id = start(client, headers, quiz.id).get_json()["attempt_id"]
    data = quiz_summary_for_lesson(account.actor_id, lesson)
    assert data["open_attempt_id"] == attempt_id
    assert (data["attempts_used"], data["attempts_left"]) == (0, None)


def test_required_quizzes_passed(client, db, make_student, make_course, make_quiz, enroll):
    account, headers, course, _ = _setup(db, make_student, make_course, enroll)
    assert required_quizzes_passed(account.actor_id, course.id) == {"passed": 0, "required": 0}
    a = make_quiz(course=course)
    b = make_quiz(course=course)
    make_quiz(course=course, is_required=False)
    make_quiz(course=course, is_active=False)
    make_quiz(course=course, questions=0)
    make_quiz()   # another course
    assert required_quizzes_passed(account.actor_id, course.id) == {"passed": 0, "required": 2}

    run_attempt(client, db, headers, a.id, 0)       # failed
    run_attempt(client, db, headers, a.id, 3)       # passed
    run_attempt(client, db, headers, a.id, 3)       # passed again: still one quiz
    run_attempt(client, db, headers, b.id, 1)       # failed
    assert required_quizzes_passed(account.actor_id, course.id) == {"passed": 1, "required": 2}
    other, _ = make_student()
    assert required_quizzes_passed(other.actor_id, course.id) == {"passed": 0, "required": 2}
