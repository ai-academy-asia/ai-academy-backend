"""Shared fixtures and helpers for the student self-pay / callback payment tests.

Test modules bind the fixtures by name (pytest finds them in the module namespace).
"""
from datetime import date

import pytest


@pytest.fixture
def enroll(db, make_cohort):
    """``enroll(student_id)`` -> Enrollment in a fresh cohort."""
    from app.models import Enrollment

    def _make(student_id, cohort=None):
        cohort = cohort or make_cohort()
        enr = Enrollment(cohort_id=cohort.id, student_id=student_id,
                         course_id=cohort.course_id, status="active")
        db.session.add(enr)
        db.session.commit()
        return enr

    return _make


@pytest.fixture
def installment(db):
    from app.models import PaymentInstallment

    def _make(enrollment, seq=1, amount=500_000, due=date(2026, 10, 1)):
        inst = PaymentInstallment(enrollment_id=enrollment.id, student_id=enrollment.student_id,
                                  seq=seq, amount=amount, due_date=due)
        db.session.add(inst)
        db.session.commit()
        return inst

    return _make


@pytest.fixture
def student(make_student):
    return make_student()


def _create(client, headers, **fields):
    payload = {"provider": "qpay", "amount": 250_000}
    payload.update(fields)
    return client.post("/payments/invoices", json=payload, headers=headers)


def _mine(client, student, **fields):
    """A student invoice against that student's own enrollment (made if missing) —
    a student can only pay for an enrollment, so every invoice names one."""
    from app.extensions import db
    from app.models import Cohort, Course, Enrollment

    account, headers = student
    enr = Enrollment.query.filter_by(student_id=account.actor_id).first()
    if enr is None:
        course = Course(slug=f"pay-{account.actor_id}", title_mn="Төлбөр", status="open",
                        price_amount=1_000_000, currency="MNT")
        db.session.add(course)
        db.session.flush()
        cohort = Cohort(course_id=course.id, name="Pay cohort", status="open",
                        start_date=date(2026, 10, 1), capacity=10)
        db.session.add(cohort)
        db.session.flush()
        enr = Enrollment(cohort_id=cohort.id, student_id=account.actor_id,
                         course_id=course.id, status="active")
        db.session.add(enr)
        db.session.commit()
    return _create(client, headers, enrollment_id=enr.id, **fields)


def _rows(db, model, **filters):
    db.session.expire_all()
    return model.query.filter_by(**filters).all()
