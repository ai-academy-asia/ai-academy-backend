"""Teachers, students, the classroom and the running cohort they meet in.

Every seeded login shares one password and ends in ``@test.ai-academy.asia``;
the programme's login prefix (``eng.``, ``corp.``, …) is how ``--reset`` finds
the accounts that belong to one programme.
"""
from __future__ import annotations

from datetime import date

from app.auth.service import create_student_account, create_teacher_account
from app.extensions import db
from app.models import Classroom, Cohort, Enrollment

from .spec import PASSWORD


def create_teachers(spec) -> list:
    teachers = []
    for login, first, last, phone, bio in spec.teachers:
        _, teacher = create_teacher_account(
            email=spec.email(login), password=PASSWORD, first_name=first, last_name=last,
            phone=phone, must_change_password=False,
        )
        teacher.bio = bio
        teachers.append(teacher)
    return teachers


def create_students(spec) -> list[tuple]:
    """[(student, diligence, payment profile, dropped?)]"""
    rows = [*spec.students, *([spec.dropped] if spec.dropped else [])]
    out = []
    for row in rows:
        login, first, last, phone, year, diligence, pay = row
        _, student = create_student_account(
            email=spec.email(login), password=PASSWORD, first_name=first, last_name=last,
            phone=phone, must_change_password=False,
        )
        student.birth_date = date(year, 3 + len(first) % 9, 1 + len(last) % 27)
        out.append((student, diligence, pay, row is spec.dropped))
    return out


def classroom(spec) -> Classroom | None:
    if not spec.in_person:
        return None
    room = Classroom.query.filter_by(name=spec.room).first()
    if room is None:
        room = Classroom(name=spec.room, center_name="AI Academy Asia",
                         location="Улаанбаатар, Сүхбаатар дүүрэг", capacity=25,
                         floor=spec.room.split()[-1][0], equipment=["projector", "25 PCs"])
        db.session.add(room)
        db.session.flush()
    return room


def create_cohort(spec, course, teacher, room, start, end) -> Cohort:
    cohort = Cohort(
        **spec.cohort, course_id=course.id, start_date=start, end_date=end,
        graduation_date=end, teacher_id=teacher.id,
        classroom_id=room.id if room else None, status="closed",
        start_time=spec.start_time, end_time=spec.end_time,
    )
    db.session.add(cohort)
    db.session.flush()
    return cohort


def enroll(cohort, students, enrolled_at) -> list[tuple]:
    """[(enrollment, student, diligence, payment profile)] for the active ones."""
    active = []
    for student, diligence, pay, dropped in students:
        enrollment = Enrollment(
            cohort_id=cohort.id, student_id=student.id, course_id=cohort.course_id,
            status="cancelled" if dropped else "active", created_via="admin",
            created_at=enrolled_at,
        )
        db.session.add(enrollment)
        db.session.flush()
        if not dropped:
            active.append((enrollment, student, diligence, pay))
    return active
