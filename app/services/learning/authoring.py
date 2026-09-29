"""Staff authoring of modules (course_topics) and lessons (course_lessons)."""
from sqlalchemy import func

from app.extensions import db
from app.models import LESSON_TYPES, Course, CourseLesson, CourseTopic, LessonMaterial

from ..errors import ServiceError
from ..params import get_by_id
from . import fields
from .materials import delete_files
from .path import ordered_lessons, ordered_topics

NAME_MAX = 200


def get_course(course_id) -> Course:
    course = get_by_id(Course, course_id)
    if course is None:
        raise ServiceError(404, "course_not_found")
    return course


def get_module(module_id) -> CourseTopic:
    topic = get_by_id(CourseTopic, module_id)
    if topic is None:
        raise ServiceError(404, "module_not_found")
    return topic


def get_lesson(lesson_id) -> CourseLesson:
    lesson = get_by_id(CourseLesson, lesson_id)
    if lesson is None:
        raise ServiceError(404, "lesson_not_found")
    return lesson


def _next_sort_order(column, *criteria) -> int:
    current = db.session.query(func.max(column)).filter(*criteria).scalar()
    return 0 if current is None else current + 1


def _material_keys(*criteria) -> list:
    rows = db.session.query(LessonMaterial.file_key).filter(
        LessonMaterial.file_key.isnot(None), *criteria).all()
    return [row[0] for row in rows]


# ---------------------------------------------------------------- modules
def list_modules(course) -> list:
    return ordered_topics(course.id)


def _apply_module(topic, data, *, creating):
    if creating or "name_mn" in data:
        topic.name_mn = fields.text(data, "name_mn", max_len=NAME_MAX, required=True)
    if "name_en" in data:
        topic.name_en = fields.text(data, "name_en", max_len=NAME_MAX)
    if "sort_order" in data:
        topic.sort_order = fields.integer(data, "sort_order")


def create_module(course, data) -> CourseTopic:
    topic = CourseTopic(course_id=course.id)
    _apply_module(topic, data, creating=True)
    if "sort_order" not in data:
        topic.sort_order = _next_sort_order(CourseTopic.sort_order,
                                            CourseTopic.course_id == course.id)
    db.session.add(topic)
    db.session.commit()
    return topic


def update_module(topic, data) -> CourseTopic:
    _apply_module(topic, data, creating=False)
    db.session.commit()
    return topic


def delete_module(topic):
    """Lessons, materials, progress and notes go with it (FK CASCADE); files best-effort."""
    lesson_ids = db.select(CourseLesson.id).where(CourseLesson.topic_id == topic.id)
    keys = _material_keys(LessonMaterial.lesson_id.in_(lesson_ids))
    db.session.delete(topic)
    db.session.commit()
    delete_files(keys)


# ---------------------------------------------------------------- lessons
def list_lessons(topic) -> list:
    return ordered_lessons(topic.id)


def _apply_lesson(lesson, data, *, creating):
    if creating or "name_mn" in data:
        lesson.name_mn = fields.text(data, "name_mn", max_len=NAME_MAX, required=True)
    if "name_en" in data:
        lesson.name_en = fields.text(data, "name_en", max_len=NAME_MAX)
    if "type" in data or creating:
        kind = data.get("type", "recording")
        if kind not in LESSON_TYPES:
            raise ServiceError(400, "invalid_type", allowed=list(LESSON_TYPES))
        lesson.type = kind
    if "classroom_embed_url" in data:
        url = data["classroom_embed_url"]
        lesson.classroom_embed_url = (
            None if url in (None, "") else fields.http_url(url, "invalid_classroom_embed_url"))
    if "duration_seconds" in data:
        lesson.duration_seconds = fields.integer(data, "duration_seconds", nullable=True)
    for key in ("summary_mn", "summary_en"):
        if key in data:
            setattr(lesson, key, fields.text(data, key, max_len=None))
    if "sections" in data:
        lesson.sections = fields.sections(data["sections"])
    if "is_preview" in data:
        lesson.is_preview = fields.boolean(data, "is_preview")
    if "sort_order" in data:
        lesson.sort_order = fields.integer(data, "sort_order")


def create_lesson(topic, data) -> CourseLesson:
    lesson = CourseLesson(topic_id=topic.id, sections=[], is_preview=False)
    _apply_lesson(lesson, data, creating=True)
    if "sort_order" not in data:
        lesson.sort_order = _next_sort_order(CourseLesson.sort_order,
                                             CourseLesson.topic_id == topic.id)
    db.session.add(lesson)
    db.session.commit()
    return lesson


def update_lesson(lesson, data) -> CourseLesson:
    _apply_lesson(lesson, data, creating=False)
    db.session.commit()
    return lesson


def delete_lesson(lesson):
    keys = _material_keys(LessonMaterial.lesson_id == lesson.id)
    db.session.delete(lesson)
    db.session.commit()
    delete_files(keys)
