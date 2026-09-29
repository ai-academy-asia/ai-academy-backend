"""Who may see which learning data. One place, so every endpoint answers alike.

- A student sees a course's content only through an **active enrollment** in one
  of its cohorts; otherwise ``403 not_enrolled``.
- Something that exists but is not theirs answers **404**, never 403 — the API
  does not confirm other people's data exists.
- A teacher acts only on cohorts they are assigned to; staff with
  ``cohort:manage`` act on any.
"""
from app.auth import has_permission
from app.extensions import db
from app.models import Cohort, Course, CourseLesson, CourseTopic, Enrollment

from .errors import ServiceError
from .params import get_by_id


def course_by_slug(slug) -> Course:
    """A published course by slug (or id). Drafts do not exist for students."""
    course = Course.query.filter_by(slug=str(slug)).first()
    if course is None and str(slug).isdigit():
        course = db.session.get(Course, int(slug))
    if course is None or not course.is_public:
        raise ServiceError(404, "course_not_found")
    return course


def enrollment_for_course(student_id, course_id) -> Enrollment:
    """The student's active enrollment in this course — newest cohort first."""
    enrollment = (
        Enrollment.query.join(Cohort, Enrollment.cohort_id == Cohort.id)
        .filter(Enrollment.student_id == student_id, Enrollment.status == "active",
                Cohort.course_id == course_id)
        .order_by(Cohort.start_date.desc().nullslast(), Enrollment.id.desc())
        .first()
    )
    if enrollment is None:
        raise ServiceError(403, "not_enrolled")
    return enrollment


def topic_for_student(student_id, topic_id) -> tuple:
    """(topic, enrollment) — 404 for an unknown module, 403 when not enrolled."""
    topic = get_by_id(CourseTopic, topic_id)
    if topic is None:
        raise ServiceError(404, "module_not_found")
    return topic, enrollment_for_course(student_id, topic.course_id)


def lesson_for_student(student_id, lesson_id) -> tuple:
    """(lesson, enrollment) — 404 for an unknown lesson, 403 when not enrolled."""
    lesson = get_by_id(CourseLesson, lesson_id)
    if lesson is None:
        raise ServiceError(404, "lesson_not_found")
    return lesson, enrollment_for_course(student_id, lesson.topic.course_id)


def ensure_module_open(topic_id, cohort_id) -> None:
    """``409 lesson_locked`` while the module's first class session is still ahead.

    Every way into a module's content goes through this — the lesson screen, a
    material download, a quiz, an assignment — or a sequential id would open
    what the class date has not.
    """
    if topic_id is None:
        return
    from app.services.learning import path  # learning imports this module

    session = path.first_sessions(cohort_id, [topic_id]).get(topic_id)
    if path.is_locked(session):
        raise ServiceError(409, "lesson_locked")


def cohort_for_teacher(account, cohort_id) -> Cohort:
    """A cohort the caller may teach: their own, or any with ``cohort:manage``."""
    cohort = get_by_id(Cohort, cohort_id)
    if cohort is None:
        raise ServiceError(404, "cohort_not_found")
    if has_permission(account.role, "cohort:manage"):
        return cohort
    if account.actor_type == "teacher" and cohort.teacher_id == account.actor_id:
        return cohort
    raise ServiceError(404, "cohort_not_found")
