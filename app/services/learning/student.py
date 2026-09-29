"""Student side of the learning surface: path, lessons, lesson detail, completion, notes."""

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import LessonMaterial, LessonNote, LessonProgress, Student
from app.timeutil import utcnow

from ..access import (
    course_by_slug,
    enrollment_for_course,
    ensure_module_open,
    lesson_for_student,
    topic_for_student,
)
from ..errors import ServiceError
from . import path
from .shapes import loc, material_dict, module_ref, note_dict

NOTE_MAX_LENGTH = 5000


def _certificate_summary(student_id, course, enrollment) -> dict:
    from app.services.certificates import certificate_status

    return {"status": certificate_status(student_id, course, enrollment)["status"]}


# ---------------------------------------------------------------- §2.1
def learning_path(student_id, slug) -> dict:
    course = course_by_slug(slug)
    enrollment = enrollment_for_course(student_id, course.id)
    content = path.ordered_content(course.id)
    done = path.completed_ids(enrollment.id)
    sessions = path.first_sessions(enrollment.cohort_id, [t.id for t, _ in content])

    modules, locked_topics, total, finished = [], set(), 0, 0
    for order, (topic, lessons) in enumerate(content, 1):
        session = sessions.get(topic.id)
        locked = path.is_locked(session)
        if locked:
            locked_topics.add(topic.id)
        n_done = sum(1 for lesson in lessons if lesson.id in done)
        total += len(lessons)
        finished += n_done
        modules.append({
            **module_ref(topic, order),
            "schedule": path.schedule_dict(session),
            "lesson_count": len(lessons),
            "completed_lessons": n_done,
            # An empty module has nothing to complete; showing it done would mislead.
            "completed": bool(lessons) and n_done == len(lessons),
            "locked": locked,
        })

    return {
        "course": {
            "id": course.id,
            "slug": course.slug,
            "title": loc(course.title_mn, course.title_en),
            "description": loc(course.description_mn, course.description_en),
            "banner_image_url": course.banner_image_url,
        },
        "enrollment_id": enrollment.id,
        "cohort_id": enrollment.cohort_id,
        "progress": path.progress_dict(total, finished),
        "continue": path.continue_target(content, locked_topics, done),
        "certificate": _certificate_summary(student_id, course, enrollment),
        "modules": modules,
    }


# ---------------------------------------------------------------- §2.2
def module_lessons(student_id, module_id) -> dict:
    topic, enrollment = topic_for_student(student_id, module_id)
    locked = path.is_locked(path.topic_session(topic, enrollment))
    done = path.completed_ids(enrollment.id)
    lessons = path.ordered_lessons(topic.id)
    order = path.position(path.ordered_topics(topic.course_id), topic.id)
    return {
        "module": module_ref(topic, order),
        "lessons": [{
            "id": lesson.id,
            "order": index,
            "title": loc(lesson.name_mn, lesson.name_en),
            "type": lesson.type,
            "duration_seconds": lesson.duration_seconds,
            "completed": lesson.id in done,
            "locked": locked,
        } for index, lesson in enumerate(lessons, 1)],
    }


# ---------------------------------------------------------------- §2.3
def _open_lesson(student_id, lesson_id):
    """(lesson, enrollment) for a lesson whose module has opened, else 409."""
    lesson, enrollment = lesson_for_student(student_id, lesson_id)
    ensure_module_open(lesson.topic_id, enrollment.cohort_id)
    return lesson, enrollment


def lesson_materials(lesson, enrollment) -> list:
    """Course-wide materials plus the ones narrowed to the student's cohort."""
    return (LessonMaterial.query
            .filter(LessonMaterial.lesson_id == lesson.id,
                    or_(LessonMaterial.cohort_id.is_(None),
                        LessonMaterial.cohort_id == enrollment.cohort_id))
            .order_by(LessonMaterial.sort_order, LessonMaterial.id).all())


def _note(student_id, lesson_id):
    return LessonNote.query.filter_by(student_id=student_id, lesson_id=lesson_id).first()


def lesson_detail(student_id, lesson_id) -> dict:
    # Lazy: those services import the learning package themselves.
    from app.services.assignments import assignment_for_lesson
    from app.services.quizzes import quiz_summary_for_lesson

    lesson, enrollment = _open_lesson(student_id, lesson_id)
    topic = lesson.topic
    note = _note(student_id, lesson.id)
    has_summary = lesson.summary_mn is not None or lesson.summary_en is not None
    progress = LessonProgress.query.filter_by(
        enrollment_id=enrollment.id, lesson_id=lesson.id).first()
    return {
        "id": lesson.id,
        "module": module_ref(topic, path.position(path.ordered_topics(topic.course_id), topic.id)),
        "order": path.position(path.ordered_lessons(topic.id), lesson.id),
        "title": loc(lesson.name_mn, lesson.name_en),
        "type": lesson.type,
        "duration_seconds": lesson.duration_seconds,
        "video": {"embed_url": lesson.classroom_embed_url} if lesson.classroom_embed_url else None,
        "summary": loc(lesson.summary_mn, lesson.summary_en) if has_summary else None,
        "sections": lesson.sections or [],
        "completed": bool(progress and progress.completed),
        "materials": [material_dict(m) for m in lesson_materials(lesson, enrollment)],
        "note": note_dict(note, db.session.get(Student, student_id)) if note else None,
        "assignment": assignment_for_lesson(student_id, enrollment, lesson),
        "quiz": quiz_summary_for_lesson(student_id, lesson),
    }


def complete_lesson(student_id, lesson_id) -> dict:
    """Idempotent: completing a completed lesson changes nothing."""
    lesson, enrollment = _open_lesson(student_id, lesson_id)
    row = LessonProgress.query.filter_by(enrollment_id=enrollment.id, lesson_id=lesson.id).first()
    if row is None:
        row = LessonProgress(enrollment_id=enrollment.id, lesson_id=lesson.id)
        db.session.add(row)
    if not row.completed:
        now = utcnow()
        row.completed = True
        row.completed_at = now
        row.watched_at = row.watched_at or now
    try:
        db.session.flush()
    except IntegrityError:
        # A parallel request inserted it first — it is complete either way.
        db.session.rollback()
    progress = path.course_progress(enrollment)
    enrollment.progress_pct = progress["percent"]
    db.session.commit()
    return {"completed": True, "progress": progress}


# ---------------------------------------------------------------- §2.5
def put_note(student_id, lesson_id, data) -> tuple:
    """Upsert the student's note. Returns ``(note dict, created)``."""
    lesson, _ = lesson_for_student(student_id, lesson_id)
    content = data.get("content")
    content = content.strip() if isinstance(content, str) else ""
    if not content:
        raise ServiceError(400, "content_required")
    if len(content) > NOTE_MAX_LENGTH:
        raise ServiceError(400, "content_too_long", max_length=NOTE_MAX_LENGTH)

    note = _note(student_id, lesson.id)
    created = note is None
    if created:
        note = LessonNote(student_id=student_id, lesson_id=lesson.id, content=content)
        db.session.add(note)
    else:
        note.content = content
    try:
        db.session.commit()
    except IntegrityError:
        # Two first saves raced; the loser becomes an update of the winner's row.
        db.session.rollback()
        note = _note(student_id, lesson.id)
        note.content = content
        db.session.commit()
        created = False
    return note_dict(note, db.session.get(Student, student_id)), created
