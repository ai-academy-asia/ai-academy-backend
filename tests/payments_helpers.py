"""Shared fixtures and helpers for the finance back-office payment tests.

Test modules bind the fixtures by name (pytest finds them in the module namespace).
"""
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.payments.golomt import GolomtCorporateProvider, StatementTxn


@pytest.fixture
def finance(make_staff):
    return make_staff("finance")[1]


@pytest.fixture
def enroll(db, make_cohort, make_student):
    """``enroll()`` -> Enrollment of a new student in a fresh cohort."""
    from app.models import Enrollment

    def _make(student_id=None):
        student_id = student_id or make_student()[0].actor_id
        cohort = make_cohort()
        enr = Enrollment(cohort_id=cohort.id, student_id=student_id,
                         course_id=cohort.course_id, status="active")
        db.session.add(enr)
        db.session.commit()
        return enr

    return _make


@pytest.fixture
def installment(db):
    from app.models import PaymentInstallment

    def _make(enrollment, seq=1, amount=500_000, due=date(2026, 10, 1), status="pending"):
        inst = PaymentInstallment(enrollment_id=enrollment.id, student_id=enrollment.student_id,
                                  seq=seq, amount=amount, due_date=due, status=status)
        db.session.add(inst)
        db.session.commit()
        return inst

    return _make


@pytest.fixture
def statement(gateways):
    """Give the fake Golomt a statement; returns the list of (from, to) it was asked for."""
    golomt = gateways["golomt"]
    calls = []

    def _fetch(from_date, to_date):
        calls.append((from_date, to_date))
        return golomt.statement

    golomt.fetch_all_statements = _fetch
    golomt.matches = GolomtCorporateProvider.matches
    return calls


def _create(client, headers, **fields):
    payload = {"provider": "qpay", "amount": 300_000}
    payload.update(fields)
    return client.post("/admin/invoices", json=payload, headers=headers)


def _txn(txn_id, amount, description, **kw):
    return StatementTxn(txn_id=txn_id, amount=Decimal(str(amount)), description=description,
                        account="MN0001", posted_at=datetime(2026, 9, 20, 10, 0),
                        raw={"id": txn_id}, **kw)
