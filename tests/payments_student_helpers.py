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


def _rows(db, model, **filters):
    db.session.expire_all()
    return model.query.filter_by(**filters).all()
