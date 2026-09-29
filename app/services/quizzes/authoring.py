"""Staff quiz authoring (``course:edit``): quiz CRUD. Questions live in :mod:`.questions`."""
from app.extensions import db
from app.models import Course, CourseLesson, CourseTopic, Exam, StudentExam

from ..errors import ServiceError
from ..params import get_by_id, parse_id
from . import payloads

_BOOL_FIELDS = ("is_required", "is_active")


def get_course_or_404(course_id) -> Course:
    course = get_by_id(Course, course_id)
    if course is None:
        raise ServiceError(404, "course_not_found")
    return course


def get_quiz_or_404(quiz_id) -> Exam:
    quiz = get_by_id(Exam, quiz_id)
    if quiz is None:
        raise ServiceError(404, "quiz_not_found")
    return quiz


def attempt_count(quiz) -> int:
    return StudentExam.query.filter_by(exam_id=quiz.id).count()


def _int_field(data, key, *, low, high=None, nullable=False):
    value = data[key]
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceError(400, f"invalid_{key}")
    if value < low or (high is not None and value > high):
        raise ServiceError(400, f"invalid_{key}")
    return value


def _name(data, key, *, required):
    value = data[key]
    if value is not None and not isinstance(value, str):
        raise ServiceError(400, f"invalid_{key}")
    value = (value or "").strip() or None
    if required and not value:
        raise ServiceError(400, f"{key}_required")
    if value and len(value) > 200:
        raise ServiceError(400, f"invalid_{key}")
    return value


def _placement(quiz, data):
    """Resolve ``lesson_id`` / ``topic_id``; both must belong to the quiz's course."""
    if "topic_id" in data:
        topic = None
        if data["topic_id"] is not None:
            topic = get_by_id(CourseTopic, data["topic_id"])
            if topic is None or topic.course_id != quiz.course_id:
                raise ServiceError(400, "invalid_topic_id")
        quiz.topic_id = topic.id if topic else None
    if "lesson_id" in data:
        lesson = None
        if data["lesson_id"] is not None:
            lesson = get_by_id(CourseLesson, data["lesson_id"])
            if lesson is None or lesson.topic.course_id != quiz.course_id:
                raise ServiceError(400, "invalid_lesson_id")
        quiz.lesson_id = lesson.id if lesson else None
        if lesson is not None and "topic_id" not in data:
            quiz.topic_id = lesson.topic_id   # a lesson quiz sits in the lesson's module


def _apply(quiz, data, *, creating):
    if "name_mn" in data or creating:
        quiz.name_mn = _name({"name_mn": data.get("name_mn")}, "name_mn", required=True)
    if "name_en" in data:
        quiz.name_en = _name(data, "name_en", required=False)
    if "pass_percent" in data:
        quiz.pass_percent = _int_field(data, "pass_percent", low=0, high=100)
    if "max_attempts" in data:
        quiz.max_attempts = _int_field(data, "max_attempts", low=1, nullable=True)
    for key in _BOOL_FIELDS:
        if key in data:
            if not isinstance(data[key], bool):
                raise ServiceError(400, f"invalid_{key}")
            setattr(quiz, key, data[key])
    _placement(quiz, data)


# ---------------------------------------------------------------- CRUD
def list_quizzes(course_id) -> list:
    course = get_course_or_404(course_id)
    quizzes = Exam.query.filter_by(course_id=course.id).order_by(Exam.id).all()
    return [payloads.staff_quiz(q, attempt_count=attempt_count(q)) for q in quizzes]


def create_quiz(course_id, data) -> dict:
    course = get_course_or_404(course_id)
    quiz = Exam(course_id=course.id, pass_percent=70, is_required=True, is_active=True)
    _apply(quiz, data, creating=True)
    db.session.add(quiz)
    db.session.commit()
    return payloads.staff_quiz(quiz, attempt_count=0, with_questions=True)


def get_quiz(quiz_id) -> dict:
    quiz = get_quiz_or_404(quiz_id)
    return payloads.staff_quiz(quiz, attempt_count=attempt_count(quiz), with_questions=True)


def update_quiz(quiz_id, data) -> dict:
    quiz = get_quiz_or_404(quiz_id)
    _apply(quiz, data, creating=False)
    db.session.commit()
    return payloads.staff_quiz(quiz, attempt_count=attempt_count(quiz), with_questions=True)


def delete_quiz(quiz_id, *, force=False) -> None:
    """Deleting a quiz deletes its attempts (students' results) — only with ``force``."""
    quiz = get_quiz_or_404(quiz_id)
    count = attempt_count(quiz)
    if count and not force:
        raise ServiceError(409, "quiz_has_attempts", attempt_count=count)
    # Bulk delete: the database cascades questions, options and attempts. An ORM
    # delete would instead try to NULL the loaded questions' exam_id.
    Exam.query.filter_by(id=quiz.id).delete(synchronize_session=False)
    db.session.commit()


def parse_force(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes")


def parse_student_filter(value):
    """Optional ``?student_id=`` on the attempts list; garbage is a 400."""
    if value in (None, ""):
        return None
    pk = parse_id(value)
    if pk is None:
        raise ServiceError(400, "invalid_student_id")
    return pk
