"""Staff: replace a quiz's whole question set, and review attempts."""
from app.extensions import db
from app.models import ExamOption, ExamQuestion, Student, StudentExam

from ..errors import ServiceError
from ..params import parse_limit
from . import payloads
from .authoring import attempt_count, get_quiz_or_404


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _invalid(index, reason, **extra):
    return ServiceError(400, "invalid_questions", index=index, reason=reason, **extra)


def _validate(items) -> list:
    """Normalise the payload or raise ``invalid_questions`` naming the first bad index."""
    if not isinstance(items, list) or not items:
        raise _invalid(None, "at_least_one_question")
    clean = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise _invalid(i, "not_an_object")
        text = _text(item.get("question"))
        if text is None:
            raise _invalid(i, "question_required")
        for key in ("explanation", "image"):
            if item.get(key) is not None and not isinstance(item[key], str):
                raise _invalid(i, f"invalid_{key}")
        if item.get("image") and len(item["image"]) > 500:
            raise _invalid(i, "invalid_image")
        point = item.get("point", 1)
        if isinstance(point, bool) or not isinstance(point, int) or point < 1:
            raise _invalid(i, "invalid_point")
        options = item.get("options")
        if not isinstance(options, list) or len(options) < 2:
            raise _invalid(i, "at_least_two_options")
        clean_options = []
        for j, option in enumerate(options):
            answer = _text(option.get("answer")) if isinstance(option, dict) else None
            if answer is None:
                raise _invalid(i, "option_answer_required", option_index=j)
            if not isinstance(option.get("is_correct", False), bool):
                raise _invalid(i, "invalid_is_correct", option_index=j)
            clean_options.append((answer, option.get("is_correct", False)))
        if sum(1 for _, correct in clean_options if correct) != 1:
            raise _invalid(i, "exactly_one_correct")
        clean.append({
            "question": text, "explanation": _text(item.get("explanation")),
            "image": _text(item.get("image")), "point": point, "options": clean_options,
        })
    return clean


def replace_questions(quiz_id, items, *, force=False) -> dict:
    """Swap the whole question set. Existing attempts block it unless ``force``,
    which deletes them — an old attempt's answers point at questions that are gone."""
    quiz = get_quiz_or_404(quiz_id)
    clean = _validate(items)
    count = attempt_count(quiz)
    if count and not force:
        raise ServiceError(409, "quiz_has_attempts", attempt_count=count)

    StudentExam.query.filter_by(exam_id=quiz.id).delete(synchronize_session=False)
    # Options and any stray answers go with their question (ON DELETE CASCADE).
    ExamQuestion.query.filter_by(exam_id=quiz.id).delete(synchronize_session=False)
    for order, item in enumerate(clean):
        question = ExamQuestion(
            exam_id=quiz.id, question=item["question"], explanation=item["explanation"],
            image=item["image"], point=item["point"], sort_order=order,
        )
        db.session.add(question)
        db.session.flush()
        for j, (answer, correct) in enumerate(item["options"]):
            db.session.add(ExamOption(
                question_id=question.id, answer=answer, is_correct=correct, sort_order=j,
            ))
    db.session.commit()
    db.session.expire(quiz)
    return payloads.staff_quiz(quiz, attempt_count=0, with_questions=True)


def list_attempts(quiz_id, *, limit=None, student_id=None) -> list:
    quiz = get_quiz_or_404(quiz_id)
    q = (
        db.session.query(StudentExam, Student)
        .outerjoin(Student, Student.id == StudentExam.student_id)
        .filter(StudentExam.exam_id == quiz.id)
    )
    if student_id is not None:
        q = q.filter(StudentExam.student_id == student_id)
    rows = q.order_by(StudentExam.id.desc()).limit(parse_limit(limit)).all()
    return [payloads.staff_attempt(attempt, student) for attempt, student in rows]
