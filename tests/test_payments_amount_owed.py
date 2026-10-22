"""The server decides what is owed (BE-01): enrol through the API, invoice, settle,
then read the ledger, certificate eligibility and contract figures."""
from decimal import Decimal

import pytest

from app.models import Enrollment, Invoice, PaymentInstallment, StudentLedger


@pytest.fixture
def enrolled(client, db, make_student, make_cohort, make_course):
    """``enrolled(**course)`` -> (enrollment, student headers), enrolled via the API."""
    def _make(**course_fields):
        account, headers = make_student()
        course = make_course(**course_fields)
        cohort = make_cohort(course=course)
        resp = client.post(f"/cohorts/{cohort.id}/enroll", headers=headers)
        assert resp.status_code == 201
        return db.session.get(Enrollment, resp.get_json()["id"]), headers

    return _make


def _invoice(client, headers, enr, **fields):
    return client.post("/payments/invoices", headers=headers,
                       json={"provider": "qpay", "enrollment_id": enr.id, **fields})


def _pay(client, gateways, headers, invoice_id):
    gateways["qpay"].paid = True
    resp = client.get(f"/payments/invoices/{invoice_id}/status", headers=headers)
    assert resp.get_json()["paid"] is True
    gateways["qpay"].paid = False


def _ledger(db, enr):
    db.session.expire_all()
    return StudentLedger.query.filter_by(enrollment_id=enr.id).one()


def test_token_payment_leaves_the_rest_owed(client, db, gateways, enrolled):
    from app.services.certificates.eligibility import payment_cleared

    enr, headers = enrolled()
    inv = _invoice(client, headers, enr, amount=1).get_json()
    _pay(client, gateways, headers, inv["id"])

    ledger = _ledger(db, enr)
    assert (ledger.total_due, ledger.total_paid, ledger.balance) == (
        Decimal("1000000.00"), Decimal("1.00"), Decimal("999999.00"))
    assert payment_cleared(db.session.get(Enrollment, enr.id).cohort.course, enr) is False


def test_invoice_without_amount_bills_the_whole_balance(client, db, gateways, enrolled):
    enr, headers = enrolled()
    first = _invoice(client, headers, enr, amount=400_000).get_json()
    _pay(client, gateways, headers, first["id"])
    resp = _invoice(client, headers, enr)
    assert resp.status_code == 201
    assert resp.get_json()["amount"] == 600000.0


def test_invoice_above_balance_is_refused(client, db, gateways, enrolled):
    enr, headers = enrolled()
    resp = _invoice(client, headers, enr, amount=1_000_001)
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "amount_exceeds_balance", "balance": 1000000.0}
    assert Invoice.query.count() == 0 and gateways["qpay"].created == []


def test_nothing_due_once_paid_in_full(client, db, gateways, enrolled):
    enr, headers = enrolled()
    inv = _invoice(client, headers, enr).get_json()
    _pay(client, gateways, headers, inv["id"])
    assert _ledger(db, enr).balance == 0
    resp = _invoice(client, headers, enr, amount=1)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "nothing_due"


def test_installment_invoice_bills_exactly_the_installment(client, db, gateways, enrolled):
    enr, headers = enrolled(installment_count=2)
    first = PaymentInstallment.query.filter_by(enrollment_id=enr.id, seq=1).one()
    wrong = _invoice(client, headers, enr, installment_id=first.id, amount=1)
    assert wrong.status_code == 400
    assert wrong.get_json() == {"error": "amount_mismatch", "expected": 500000.0}

    inv = _invoice(client, headers, enr, installment_id=first.id).get_json()
    assert inv["amount"] == 500000.0
    _pay(client, gateways, headers, inv["id"])
    db.session.expire_all()
    assert db.session.get(PaymentInstallment, first.id).status == "paid"
    again = _invoice(client, headers, enr, installment_id=first.id)
    assert again.status_code == 409
    assert again.get_json() == {"error": "installment_settled", "installment_status": "paid"}
    ledger = _ledger(db, enr)
    assert ledger.balance == Decimal("500000.00")
    assert ledger.next_due_date.isoformat() == "2026-11-01"


def test_staff_invoice_on_an_enrollment_obeys_the_balance(client, db, gateways, enrolled,
                                                          make_staff):
    enr, _ = enrolled()
    resp = client.post("/admin/invoices", headers=make_staff("finance")[1], json={
        "provider": "qpay", "enrollment_id": enr.id, "amount": 2_000_000})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "amount_exceeds_balance"


def test_contract_quotes_the_full_price_after_a_partial_payment(client, db, gateways, enrolled):
    from app.models import StudentContract
    from app.services.contracts import core

    enr, headers = enrolled(contract_template_key="courses/1/contract_template.pdf")
    inv = _invoice(client, headers, enr, amount=300_000).get_json()
    _pay(client, gateways, headers, inv["id"])
    core.sync(student_id=enr.student_id)
    contract = StudentContract.query.filter_by(enrollment_id=enr.id).one()
    money = core.finance(contract)
    assert (money["total_due"], money["total_paid"], money["balance"]) == (
        1000000.0, 300000.0, 700000.0)
