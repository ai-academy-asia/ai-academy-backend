"""Shared helpers for the eBarimt admin tests (``test_ebarimt_*.py``).

A stubbed PosAPI, the ``posapi`` / ``mailbox`` / ``finance`` / ``sales``
fixtures, and payment / receipt row builders. Each test module binds the fixtures
it uses by name (``posapi = ebarimt_helpers.posapi``).
"""
import itertools
from datetime import datetime
from decimal import Decimal

import pytest

from app.ebarimt import PosAPIClient
from app.models import EBarimtReceipt, Invoice, Payment

_seq = itertools.count(1)
DDTD_LEN = 33


# ----------------------------------------------------------------- helpers
class FakePosAPI:
    """Records every PosAPI call; ``fail`` makes the next call raise it."""

    def __init__(self):
        self.created, self.returned = [], []
        self.sent = 0
        self.fail = None
        self.info_fail = None
        self.no_ddtd = False

    def create_receipt(self, payload):
        if self.fail:
            raise self.fail
        self.created.append(payload)
        if self.no_ddtd:
            return {"lottery": "HQ 00000000"}
        n = len(self.created)
        return {
            "id": str(n).rjust(DDTD_LEN, "7"), "lottery": f"HQ {92232000 + n}",
            "qrData": f"QRDATA-{n}" * 10, "date": "2026-09-01 18:30:00",
        }

    def return_receipt(self, ebarimt_id, date=None):
        if self.fail:
            raise self.fail
        self.returned.append((ebarimt_id, date))
        return {}

    def send_data(self):
        if self.fail:
            raise self.fail
        self.sent += 1
        return {}

    def info(self):
        if self.info_fail:
            raise self.info_fail
        return {"lastSentDate": "2026-09-28 10:00:00", "leftLotteries": 9000,
                "merchants": [{"tin": "TEST_TIN"}]}


@pytest.fixture
def posapi(app, monkeypatch):
    """Live mode against a stubbed PosAPI."""
    fake = FakePosAPI()
    monkeypatch.setitem(app.config, "EBARIMT_TEMP_MODE", False)
    monkeypatch.setattr(PosAPIClient, "create_receipt", lambda self, p: fake.create_receipt(p))
    monkeypatch.setattr(PosAPIClient, "return_receipt",
                        lambda self, i, date=None: fake.return_receipt(i, date=date))
    monkeypatch.setattr(PosAPIClient, "send_data", lambda self: fake.send_data())
    monkeypatch.setattr(PosAPIClient, "info", lambda self: fake.info())
    return fake


@pytest.fixture
def mailbox(app, monkeypatch):
    sent = []
    monkeypatch.setitem(app.config, "MAIL_HOST", "smtp.test")
    monkeypatch.setattr("app.mail.send_message", sent.append)
    return sent


@pytest.fixture
def finance(make_staff):
    return make_staff("finance")[1]


@pytest.fixture
def sales(make_staff):
    return make_staff("sales_enrollment")[1]


def _payment(db, amount=1_000_000, student_id=None, method="qr"):
    n = next(_seq)
    invoice = Invoice(provider="qpay", sender_invoice_no=f"AIAA-QP-E{n}", amount=amount,
                      status="paid", description="Corporate Leaders tuition",
                      student_id=student_id)
    payment = Payment(invoice=invoice, provider="qpay", provider_payment_id=f"TXN-E{n}",
                      amount=amount, status="paid", method=method, paid_at=datetime.utcnow())
    db.session.add_all([invoice, payment])
    db.session.commit()
    return payment.id


def _receipt(db, payment_id=None, status="temp", amount=1_000_000, **fields):
    """A receipt row: ``status`` temp (no DDTD) or issued (DDTD/lottery/QR)."""
    n = next(_seq)
    invoice_id = db.session.get(Payment, payment_id).invoice_id if payment_id else None
    values = {
        "payment_id": payment_id, "invoice_id": invoice_id, "type": "B2C_RECEIPT",
        "total_amount": amount, "vat_amount": Decimal(amount) / 11, "status": status,
        "is_temp_mode": status == "temp", "district_code": "3501", "pos_no": "TEST_POS",
        "raw": {"receipts": [{"items": [{"name": "Stored description"}]}]},
    }
    if status != "temp":
        values.update(
            ebarimt_id=str(n).rjust(DDTD_LEN, "1"), lottery=f"HQ {10000000 + n}",
            qr_data=f"QR-{n}" * 20, issued_at=datetime(2026, 9, 1, 10, 30),
            raw={"request": {"receipts": [{"items": [{"name": "Tuition"}]}]},
                 "response": {"date": "2026-09-01 18:30:00"}},
        )
    values.update(fields)
    receipt = EBarimtReceipt(**values)
    db.session.add(receipt)
    db.session.commit()
    return receipt.id


def _fresh(db, model, id_):
    db.session.expire_all()
    return db.session.get(model, id_)
