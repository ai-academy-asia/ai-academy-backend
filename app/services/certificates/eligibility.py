"""Whether a student has earned a course certificate (contract §2.9).

Three requirements, each reported so the app can render the checklist:
- ``lessons_completed`` — every lesson of the course completed (a course with no
  lessons does not qualify);
- ``quizzes_passed``    — every required, active quiz (with questions) passed once;
- ``payment_cleared``   — the enrollment's ledger balance is ≤ 0 (no ledger row
  counts only when the course is free).

Lesson progress and quiz results belong to the learning / quiz services and are
read from them (lazily — those services embed the certificate status in turn).
"""
from __future__ import annotations

from app.models import (
    Certificate,
    StudentLedger,
)


# ------------------------------------------------------------------- lessons
def lessons_requirement(course_id, enrollment) -> dict:
    """Progress comes from the learning service, so both screens show one number."""
    from app.services.learning import course_progress

    if enrollment is None:
        return {"done": False, "percent": 0}
    progress = course_progress(enrollment)
    total = progress["total_lessons"]
    return {"done": bool(total) and progress["completed_lessons"] >= total,
            "percent": progress["percent"]}


# ------------------------------------------------------------------- quizzes
def quizzes_requirement(student_id, course_id) -> dict:
    from app.services.quizzes import required_quizzes_passed

    counts = required_quizzes_passed(student_id, course_id)
    passed, required = counts["passed"], counts["required"]
    return {"done": passed >= required, "passed": min(passed, required),
            "required": required}


# ------------------------------------------------------------------- payment
def payment_cleared(course, enrollment) -> bool:
    ledger = (StudentLedger.query.filter_by(enrollment_id=enrollment.id).first()
              if enrollment is not None else None)
    if ledger is not None:
        return (ledger.balance or 0) <= 0
    return not course.final_price_amount


# ------------------------------------------------------------------- status
def requirements(student_id, course, enrollment) -> dict:
    return {
        "lessons_completed": lessons_requirement(course.id, enrollment),
        "quizzes_passed": quizzes_requirement(student_id, course.id),
        "payment_cleared": {"done": payment_cleared(course, enrollment)},
    }


def is_eligible(reqs: dict) -> bool:
    return all(item["done"] for item in reqs.values())


def live_certificate(student_id, course_id):
    """The student's non-archived certificate for the course, or ``None``."""
    return Certificate.query.filter_by(
        student_id=student_id, course_id=course_id, is_archived=False).first()


def certificate_status(student_id, course, enrollment) -> dict:
    """The full §2.9 body: status, requirement checklist and the certificate if issued."""
    reqs = requirements(student_id, course, enrollment)
    cert = live_certificate(student_id, course.id)
    status = ("issued" if cert is not None
              else "eligible" if is_eligible(reqs) else "not_eligible")
    return {
        "status": status,
        "requirements": reqs,
        "certificate": cert.to_student_dict() if cert is not None else None,
    }
