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
    def on_lesson(**fields):
        return make_quiz(course=course, lesson=add_lesson(db, course), **fields)

    a = on_lesson()
    b = on_lesson()
    on_lesson(is_required=False)
    on_lesson(is_active=False)
    on_lesson(questions=0)
    make_quiz()   # another course
    assert required_quizzes_passed(account.actor_id, course.id) == {"passed": 0, "required": 2}

    run_attempt(client, db, headers, a.id, 0)       # failed
    run_attempt(client, db, headers, a.id, 3)       # passed
    run_attempt(client, db, headers, a.id, 3)       # passed again: still one quiz
    run_attempt(client, db, headers, b.id, 1)       # failed
    assert required_quizzes_passed(account.actor_id, course.id) == {"passed": 1, "required": 2}
    other, _ = make_student()
    assert required_quizzes_passed(other.actor_id, course.id) == {"passed": 0, "required": 2}


def test_unreachable_quizzes_never_block_a_certificate(db, make_student, make_course,
                                                       make_quiz, enroll, client, admin_headers):
    """A quiz with no lesson (its lesson deleted) or behind the lesson's first quiz
    cannot be opened from the app, so it is not required."""
    account, _, course, lesson = _setup(db, make_student, make_course, enroll)
    make_quiz(course=course, lesson=lesson)
    make_quiz(course=course, lesson=lesson)        # second on the same lesson (old data)
    doomed = add_lesson(db, course, name="Doomed")
    make_quiz(course=course, lesson=doomed)
    assert required_quizzes_passed(account.actor_id, course.id)["required"] == 2
    assert client.delete(f"/admin/lessons/{doomed.id}", headers=admin_headers).status_code == 200
    counts = required_quizzes_passed(account.actor_id, course.id)
    assert counts == {"passed": 0, "required": 1}


def test_second_active_quiz_on_a_lesson_is_refused(client, db, make_course, make_quiz,
                                                   admin_headers):
    course = make_course()
    lesson = add_lesson(db, course)
    first = make_quiz(course=course, lesson=lesson)
    resp = client.post(f"/admin/courses/{course.id}/quizzes", headers=admin_headers,
                       json={"name_mn": "Дахиад", "lesson_id": lesson.id})
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "lesson_has_quiz", "quiz_id": first.id}
    other = make_quiz(course=course, lesson=add_lesson(db, course))
    resp = client.patch(f"/admin/quizzes/{other.id}", headers=admin_headers,
                        json={"lesson_id": lesson.id})
    assert resp.status_code == 409
    # An inactive quiz may sit on the lesson; reactivating it is what clashes.
    resp = client.patch(f"/admin/quizzes/{other.id}", headers=admin_headers,
                        json={"lesson_id": lesson.id, "is_active": False})
    assert resp.status_code == 200
    resp = client.patch(f"/admin/quizzes/{other.id}", headers=admin_headers,
                        json={"is_active": True})
    assert resp.status_code == 409
