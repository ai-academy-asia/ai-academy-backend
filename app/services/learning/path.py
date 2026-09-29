"""The shape of a course as a student walks it: ordering, module schedule/lock, progress.

A module is dated by its cohort's earliest class session that covers it and stays
locked until that day arrives in Ulaanbaatar (recordings open after the live
class). Progress is lesson-based and per enrollment.
"""
from app.extensions import db
from app.models import ClassSession, CourseLesson, CourseTopic, LessonProgress
from app.timeutil import iso, local, utcnow


def today():
    """The calendar day in Ulaanbaatar — what "the class date has come" is measured in."""
    return local(utcnow()).date()


def ordered_topics(course_id) -> list:
    return (CourseTopic.query.filter_by(course_id=course_id)
            .order_by(CourseTopic.sort_order, CourseTopic.id).all())


def ordered_lessons(topic_id) -> list:
    return (CourseLesson.query.filter_by(topic_id=topic_id)
            .order_by(CourseLesson.sort_order, CourseLesson.id).all())


def ordered_content(course_id) -> list:
    """``[(topic, [lessons…]), …]`` in module order, then lesson order."""
    topics = ordered_topics(course_id)
    by_topic = {t.id: [] for t in topics}
    if topics:
        lessons = (CourseLesson.query.filter(CourseLesson.topic_id.in_(by_topic))
                   .order_by(CourseLesson.sort_order, CourseLesson.id).all())
        for lesson in lessons:
            by_topic[lesson.topic_id].append(lesson)
    return [(t, by_topic[t.id]) for t in topics]


def position(items, target_id) -> int:
    """1-based position of ``target_id`` in an ordered list — the ``order`` the app shows."""
    for index, item in enumerate(items, 1):
        if item.id == target_id:
            return index
    return 0


def completed_ids(enrollment_id) -> set:
    rows = (db.session.query(LessonProgress.lesson_id)
            .filter_by(enrollment_id=enrollment_id, completed=True).all())
    return {row[0] for row in rows}


def first_sessions(cohort_id, topic_ids) -> dict:
    """``{topic_id: earliest ClassSession}`` for this cohort."""
    if not topic_ids:
        return {}
    rows = (ClassSession.query
            .filter(ClassSession.cohort_id == cohort_id, ClassSession.topic_id.in_(topic_ids))
            .order_by(ClassSession.session_date, ClassSession.start_time.nullslast(),
                      ClassSession.id)
            .all())
    first = {}
    for row in rows:
        first.setdefault(row.topic_id, row)
    return first


def schedule_dict(session):
    if session is None:
        return None
    return {"date": iso(session.session_date), "start_time": session.start_time}


def is_locked(session) -> bool:
    """No session = self-paced = never locked."""
    return session is not None and session.session_date > today()


def topic_session(topic, enrollment):
    return first_sessions(enrollment.cohort_id, [topic.id]).get(topic.id)


def progress_dict(total, done) -> dict:
    return {
        "percent": (done * 100) // total if total else 0,
        "completed_lessons": done,
        "total_lessons": total,
    }


def course_progress(enrollment) -> dict:
    """``{"percent", "completed_lessons", "total_lessons"}`` for one enrollment (§2.1)."""
    course_id = enrollment.cohort.course_id
    lesson_ids = [
        row[0] for row in db.session.query(CourseLesson.id)
        .join(CourseTopic, CourseLesson.topic_id == CourseTopic.id)
        .filter(CourseTopic.course_id == course_id).all()
    ]
    done = completed_ids(enrollment.id) & set(lesson_ids)
    return progress_dict(len(lesson_ids), len(done))


def continue_target(content, locked_topics, done):
    """First unlocked, uncompleted lesson; else the last unlocked one; ``None`` if none is open."""
    last = None
    for topic, lessons in content:
        if topic.id in locked_topics:
            continue
        for lesson in lessons:
            if lesson.id not in done:
                return {"module_id": topic.id, "lesson_id": lesson.id}
            last = {"module_id": topic.id, "lesson_id": lesson.id}
    return last
