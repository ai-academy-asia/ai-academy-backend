"""JSON shapes for quizzes (contract §2.7) — the one place the answer key is gated.

Student payloads reveal ``is_correct`` / the correct option / the explanation
only through :func:`answer_reveal`, which is called only for a question the
student has already answered in that attempt. Staff payloads (:func:`staff_quiz`)
carry the full key and must never be returned from a ``/me`` endpoint.
"""
from app.timeutil import iso


def title(quiz) -> dict:
    return {"mn": quiz.name_mn, "en": quiz.name_en}


def correct_option_id(question):
    return next((o.id for o in question.options if o.is_correct), None)


def answer_reveal(question, answer) -> dict:
    """What the student may learn about one question *after* answering it."""
    return {
        "question_id": question.id,
        "option_id": answer.option_id,
        "correct": answer.is_correct,
        "correct_option_id": correct_option_id(question),
        "explanation": question.explanation,
    }


def student_question(question, order, answer) -> dict:
    """A question as the student sees it. ``answer`` is their StudentExamAnswer or None."""
    return {
        "id": question.id,
        "order": order,
        "prompt": question.question,
        "image": question.image,
        # Text and id only — never `is_correct` here.
        "options": [{"id": o.id, "text": o.answer} for o in question.options],
        "answer": answer_reveal(question, answer) if answer is not None else None,
    }


def open_attempt(attempt, quiz, answers) -> dict:
    """Start / resume payload. ``answers`` maps question_id -> StudentExamAnswer."""
    return {
        "attempt_id": attempt.id,
        "quiz_id": quiz.id,
        "status": "open",
        "started_at": iso(attempt.started_at),
        "questions": [
            student_question(q, i, answers.get(q.id))
            for i, q in enumerate(quiz.questions, start=1)
        ],
    }


def result(attempt, quiz, answers) -> dict:
    """A finished attempt's score, with correctness per question (no key)."""
    return {
        "attempt_id": attempt.id,
        "quiz_id": quiz.id,
        "status": "finished",
        "correct": attempt.correct_count,
        "total": attempt.total,
        "percent": attempt.percent,
        "passed": attempt.is_passed,
        "started_at": iso(attempt.started_at),
        "finished_at": iso(attempt.completed_at),
        "questions": [
            {"question_id": q.id, "order": i,
             "correct": bool(answers.get(q.id) and answers[q.id].is_correct)}
            for i, q in enumerate(quiz.questions, start=1)
        ],
    }


def last_result(attempt) -> dict:
    return {
        "attempt_id": attempt.id,
        "correct": attempt.correct_count,
        "total": attempt.total,
        "percent": attempt.percent,
        "passed": attempt.is_passed,
        "finished_at": iso(attempt.completed_at),
    }


# ---------------------------------------------------------------- staff
def staff_question(question, order) -> dict:
    return {
        "id": question.id,
        "order": order,
        "question": question.question,
        "explanation": question.explanation,
        "image": question.image,
        "point": question.point,
        "options": [
            {"id": o.id, "order": i, "answer": o.answer, "is_correct": o.is_correct}
            for i, o in enumerate(question.options, start=1)
        ],
    }


def staff_quiz(quiz, *, attempt_count=None, with_questions=False) -> dict:
    data = {
        "id": quiz.id,
        "course_id": quiz.course_id,
        "topic_id": quiz.topic_id,
        "lesson_id": quiz.lesson_id,
        "name_mn": quiz.name_mn,
        "name_en": quiz.name_en,
        "title": title(quiz),
        "pass_percent": quiz.pass_percent,
        "max_attempts": quiz.max_attempts,
        "is_required": quiz.is_required,
        "is_active": quiz.is_active,
        "question_count": len(quiz.questions),
        "created_at": iso(quiz.created_at),
    }
    if attempt_count is not None:
        data["attempt_count"] = attempt_count
    if with_questions:
        data["questions"] = [
            staff_question(q, i) for i, q in enumerate(quiz.questions, start=1)
        ]
    return data


def staff_attempt(attempt, student) -> dict:
    name = " ".join(p for p in (student.first_name, student.last_name) if p) if student else None
    return {
        "attempt_id": attempt.id,
        "student": {"id": attempt.student_id, "name": name},
        "status": "finished" if attempt.completed_at else "open",
        "correct": attempt.correct_count,
        "total": attempt.total,
        "percent": attempt.percent,
        "passed": attempt.is_passed,
        "started_at": iso(attempt.started_at),
        "finished_at": iso(attempt.completed_at),
    }
