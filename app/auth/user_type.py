"""Which app experience an account gets: ``adult``, ``child``, ``teacher`` or ``staff``.

The mobile app picks its UI (kids vs adult) from this at login, so it is decided
here, once, rather than by each client:

1. an admin-set ``Student.ui_mode`` (``kids`` / ``adult``) always wins;
2. else the birth date — under ``CHILD_MAX_AGE_EXCLUSIVE`` is a child;
3. else an active enrollment in a ``junior`` course means a child;
4. else adult.
"""
from datetime import date

from app.extensions import db
from app.models import ACTOR_STAFF, ACTOR_TEACHER, Cohort, Course, Enrollment, Student

USER_TYPES = ("adult", "child", "teacher", "staff")
CHILD_MAX_AGE_EXCLUSIVE = 18


def _age(birth_date: date, today: date) -> int:
    before_birthday = (today.month, today.day) < (birth_date.month, birth_date.day)
    return today.year - birth_date.year - before_birthday


def _in_junior_course(student_id: int) -> bool:
    return db.session.query(
        Enrollment.query.join(Cohort, Enrollment.cohort_id == Cohort.id)
        .join(Course, Cohort.course_id == Course.id)
        .filter(Enrollment.student_id == student_id, Enrollment.status == "active",
                Course.level == "junior")
        .exists()
    ).scalar()


def user_type(account, today: date = None) -> str:
    if account.actor_type == ACTOR_TEACHER:
        return "teacher"
    if account.actor_type == ACTOR_STAFF:
        return "staff"
    student = db.session.get(Student, account.actor_id)
    if student is None:
        return "adult"
    if student.ui_mode in ("kids", "adult"):
        return "child" if student.ui_mode == "kids" else "adult"
    if student.birth_date is not None:
        age = _age(student.birth_date, today or date.today())
        return "child" if age < CHILD_MAX_AGE_EXCLUSIVE else "adult"
    return "child" if _in_junior_course(student.id) else "adult"
