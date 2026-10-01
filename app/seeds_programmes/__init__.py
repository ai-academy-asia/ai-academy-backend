"""Test data for running programmes: ``flask seed programme <key>``.

Each programme (see :data:`PROGRAMMES`) becomes one course with its modules,
lessons and quizzes, one cohort in progress, its teachers and students (one
dropped out) with attendance, lesson progress, quiz attempts, homework,
installments, payments and notifications. Dates are laid out relative to the
day it runs, so the "currently running" picture holds whenever it is seeded.

Not idempotent by matching rows: it refuses to run twice unless ``reset`` is
set, which first removes everything a previous run of that programme created.
"""
from __future__ import annotations

from datetime import timedelta

from app.extensions import db
from app.models import AuthAccount, Cohort, Course, Invoice, Student, Teacher

from . import activity, content, homework_money, people
from .applied_ai_runs import CORPORATE, ONLINE
from .business_ai_runs import AGENTIC, BUSINESS
from .engineering import ENGINEERING
from .spec import PASSWORD

PROGRAMMES = {p.key: p for p in (ENGINEERING, CORPORATE, ONLINE, AGENTIC, BUSINESS)}


class SeedExists(Exception):
    pass


def run(key: str, *, today, reset: bool = False) -> dict:
    spec = PROGRAMMES[key]
    slug = spec.course["slug"]
    if reset:
        remove(key)
    elif Course.query.filter_by(slug=slug).first() or _accounts(spec).first():
        raise SeedExists(f"'{slug}' or {spec.login_prefix}.*@ accounts already exist")

    teachers = people.create_teachers(spec)
    students = people.create_students(spec)

    dates = activity.calendar(spec, today)
    course = content.create_course(spec, dates[0], dates[-1])
    lessons = content.create_modules(spec, course)
    content.add_materials(spec, lessons)
    exams = content.add_quizzes(spec, course, lessons)
    dates_by_lesson = {lesson.id: day for lesson, day in zip(lessons, dates)}

    cohort = people.create_cohort(spec, course, teachers[0], people.classroom(spec),
                                  dates[0], dates[-1])
    enrolled_at = activity.utc_at(dates[0] - timedelta(days=14), "10:00")
    enrolled = people.enroll(cohort, students, enrolled_at)

    sessions = activity.create_sessions(spec, cohort, lessons, dates)
    activity.record_attendance(spec, sessions, enrolled, teachers[0], today)
    activity.record_progress(lessons, dates, enrolled, today)
    activity.record_quiz_attempts(spec, exams, dates_by_lesson, enrolled, today)

    assignments = homework_money.create_assignments(spec, cohort, lessons, dates_by_lesson)
    homework_money.record_submissions(spec, assignments, dates_by_lesson, enrolled, today)
    homework_money.record_money(spec, enrolled, dates[0], today)
    homework_money.notify(spec, enrolled, assignments, today)
    db.session.commit()

    logins = [*spec.students, *([spec.dropped] if spec.dropped else [])]
    return {
        "slug": slug, "course_id": course.id, "cohort_id": cohort.id,
        "lessons": len(lessons), "start": dates[0], "end": dates[-1],
        "teachers": [spec.email(t[0]) for t in spec.teachers],
        "students": [spec.email(s[0]) for s in logins],
        "dropped": spec.email(spec.dropped[0]) if spec.dropped else None,
        "password": PASSWORD,
    }


def remove(key: str) -> None:
    """Delete one programme's course, cohorts and its seeded people."""
    spec = PROGRAMMES[key]
    course = Course.query.filter_by(slug=spec.course["slug"]).first()
    accounts = _accounts(spec).all()
    student_ids = [a.actor_id for a in accounts if a.actor_type == "student"]
    teacher_ids = [a.actor_id for a in accounts if a.actor_type == "teacher"]
    if student_ids:
        # Invoices only SET NULL on enrollment delete — remove them (payments cascade).
        Invoice.query.filter(Invoice.student_id.in_(student_ids)).delete(
            synchronize_session=False)
    if course is not None:
        Cohort.query.filter_by(course_id=course.id).delete(synchronize_session=False)
        db.session.delete(course)
    for account in accounts:
        db.session.delete(account)
    if student_ids:
        Student.query.filter(Student.id.in_(student_ids)).delete(synchronize_session=False)
    if teacher_ids:
        Teacher.query.filter(Teacher.id.in_(teacher_ids)).delete(synchronize_session=False)
    db.session.commit()


def _accounts(spec):
    return AuthAccount.query.filter(AuthAccount.email.like(spec.email_pattern))
