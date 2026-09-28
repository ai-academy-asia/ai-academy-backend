"""Shared helpers for the refund tests (``test_refund*.py``).

A stubbed PosAPI, the ``posapi`` / ``finance`` / ``sale`` fixtures and
``_fresh``. Each test module binds the fixtures it uses by name
(``sale = refund_helpers.sale``).
"""
import itertools
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.ebarimt import PosAPIClient
from app.models import (
    ClassroomRequest,
    EBarimtReceipt,
    Enrollment,
    Invoice,
    Payment,
    SeatBooking,
)

_seq = itertools.count(1)
DDTD_LEN = 33


# ----------------------------------------------------------------- helpers
class FakePosAPI:
    def __init__(self):
        self.created, self.returned = [], []
        self.fail = None

    def create_receipt(self, payload):
        if self.fail:
            raise self.fail
        self.created.append(payload)
        n = len(self.created)
        return {"id": str(n).rjust(DDTD_LEN, "8"), "lottery": f"ZZ {55500000 + n}",
                "qrData": f"REPL-{n}", "date": "2026-09-28 12:00:00"}

    def return_receipt(self, ebarimt_id, date=None):
        if self.fail:
            raise self.fail
        self.returned.append((ebarimt_id, date))
        return {}


@pytest.fixture
def posapi(app, monkeypatch):
    """Live mode against a stubbed PosAPI."""
    fake = FakePosAPI()
    monkeypatch.setitem(app.config, "EBARIMT_TEMP_MODE", False)
    monkeypatch.setattr(PosAPIClient, "create_receipt", lambda self, p: fake.create_receipt(p))
    monkeypatch.setattr(PosAPIClient, "return_receipt",
                        lambda self, i, date=None: fake.return_receipt(i, date=date))
    return fake


@pytest.fixture
def finance(make_staff):
    return make_staff("finance")[1]


@pytest.fixture
def sale(db, make_cohort):
    """``sale(receipt="issued"|"temp"|"failed"|"returned"|None, student_id=None)``.

    A settled public checkout (lead + paid seat) by default; with ``student_id``
    an enrolled student's invoice instead.
    """

    def _make(receipt="issued", amount=1_000_000, student_id=None):
        n = next(_seq)
        cohort = make_cohort()
        enrollment = None
        if student_id:
            enrollment = Enrollment(cohort_id=cohort.id, student_id=student_id,
                                    course_id=cohort.course_id, status="active")
            db.session.add(enrollment)
            db.session.flush()
        invoice = Invoice(provider="qpay", sender_invoice_no=f"AIAA-QP-R{n}", amount=amount,
                          status="paid", description="Corporate Leaders tuition",
                          student_id=student_id,
                          enrollment_id=enrollment.id if enrollment else None)
        payment = Payment(invoice=invoice, provider="qpay", provider_payment_id=f"TXN-R{n}",
                          amount=amount, status="paid", method="qr",
                          paid_at=datetime.utcnow())
        db.session.add_all([invoice, payment])
        db.session.flush()

        booking = request = None
        if not student_id:
            request = ClassroomRequest(course_id=cohort.course_id, name="Бат Дорж",
                                       email=f"buyer{n}@corp.test", phone_num="99112233",
                                       status="paid")
            booking = SeatBooking(request=request, cohort_id=cohort.id, number_of_seat=n,
                                  payment_token=f"pt_token{n}", status="paid",
                                  amount=amount, invoice_id=invoice.id,
                                  paid_at=datetime.utcnow())
            db.session.add_all([request, booking])

        rec = None
        if receipt:
            live = receipt != "temp"
            rec = EBarimtReceipt(
                payment_id=payment.id, invoice_id=invoice.id, type="B2C_RECEIPT",
                total_amount=amount, vat_amount=amount / 11, status=receipt,
                is_temp_mode=not live, district_code="3501", pos_no="TEST_POS",
                ebarimt_id=str(n).rjust(DDTD_LEN, "1") if live else None,
                lottery=f"HQ {92232000 + n}" if live else None,
                qr_data="QR" if live else None, issued_at=datetime(2026, 9, 1, 10, 30),
                raw={"request": {"receipts": [{"items": [{"name": "Tuition"}]}]},
                     "response": {"date": "2026-09-01 18:30:00"}},
            )
            db.session.add(rec)
        db.session.commit()
        return SimpleNamespace(
            payment_id=payment.id, invoice_id=invoice.id,
            receipt_id=rec.id if rec else None,
            ddtd=rec.ebarimt_id if rec else None, lottery=rec.lottery if rec else None,
            booking_id=booking.id if booking else None,
            request_id=request.id if request else None,
            token=booking.payment_token if booking else None,
            enrollment_id=enrollment.id if enrollment else None,
        )

    return _make


def _fresh(db, model, id_):
    db.session.expire_all()
    return db.session.get(model, id_)
