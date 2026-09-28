"""Student invoice status polling and gateway callbacks (/payments/*)."""
from decimal import Decimal

import payments_student_helpers
from payments_student_helpers import _create, _rows

from app.payments import PaymentGatewayError

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
enroll = payments_student_helpers.enroll
installment = payments_student_helpers.installment
student = payments_student_helpers.student


# ================================================ GET /payments/invoices/<id>/status
def test_status_poll_while_unpaid(client, db, gateways, student):
    from app.models import Payment

    inv = _create(client, student[1]).get_json()
    resp = client.get(f"/payments/invoices/{inv['id']}/status", headers=student[1])
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "pending"
    assert data["paid"] is False
    assert "qr_text" not in data["invoice"]
    assert _rows(db, Payment) == []


def test_status_poll_settles_paid_invoice(client, db, gateways, student, enroll, installment):
    from app.models import EBarimtReceipt, Payment, PaymentInstallment, StudentLedger

    account, headers = student
    enr = enroll(account.actor_id)
    inst = installment(enr, amount=250_000)
    inv = _create(client, headers, enrollment_id=enr.id, installment_id=inst.id).get_json()

    gateways["qpay"].paid = True
    resp = client.get(f"/payments/invoices/{inv['id']}/status", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "paid" and data["paid"] is True
    assert data["invoice"]["paid_at"] is not None

    payments = _rows(db, Payment)
    assert len(payments) == 1
    assert payments[0].amount == Decimal("250000.00")
    assert payments[0].provider_payment_id == f"TXN-{inv['id']}"
    assert db.session.get(PaymentInstallment, inst.id).status == "paid"
    ledger = StudentLedger.query.filter_by(enrollment_id=enr.id).one()
    assert ledger.total_paid == Decimal("250000.00")
    assert ledger.balance == 0
    receipt = EBarimtReceipt.query.filter_by(payment_id=payments[0].id).one()
    assert receipt.status == "temp" and receipt.is_temp_mode is True
    assert receipt.total_amount == Decimal("250000.00")

    # A paid invoice is not re-checked with the gateway.
    gateways["qpay"].fail = PaymentGatewayError("qpay", "boom")
    again = client.get(f"/payments/invoices/{inv['id']}/status", headers=headers)
    assert again.status_code == 200
    assert again.get_json()["paid"] is True
    assert len(_rows(db, Payment)) == 1


def test_status_poll_gateway_failure(client, gateways, student):
    inv = _create(client, student[1]).get_json()
    gateways["qpay"].fail = PaymentGatewayError("qpay", "gateway_timeout", retriable=True)
    resp = client.get(f"/payments/invoices/{inv['id']}/status", headers=student[1])
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "gateway_gateway_timeout"


def test_status_poll_other_student_forbidden(client, gateways, make_student):
    inv = _create(client, make_student()[1]).get_json()
    gateways["qpay"].paid = True
    resp = client.get(f"/payments/invoices/{inv['id']}/status", headers=make_student()[1])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


def test_status_poll_not_found_and_auth(client, student):
    assert client.get("/payments/invoices/9999/status", headers=student[1]).status_code == 404
    assert client.get("/payments/invoices/9999/status").status_code == 401


# ============================================== /payments/<provider>/callback
def test_callback_unknown_provider(client, gateways):
    resp = client.post("/payments/paypal/callback?ref=X")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "unsupported_provider"


def test_callback_sandbox_is_not_callable_by_name(client, gateways):
    resp = client.get("/payments/sandbox/callback?ref=X")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "unsupported_provider"


def test_callback_unknown_ref(client, gateways):
    resp = client.get("/payments/qpay/callback?ref=AIAA-QP-NOPE")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "invoice_not_found"


def test_callback_without_any_reference(client, gateways):
    resp = client.post("/payments/storepay/callback", json={"foo": "bar"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "invoice_not_found"


def test_callback_while_unpaid_does_not_settle(client, db, gateways, student):
    from app.models import Payment

    inv = _create(client, student[1]).get_json()
    resp = client.get(f"/payments/qpay/callback?ref={inv['sender_invoice_no']}")
    assert resp.status_code == 200
    assert resp.get_json() == {"ref": inv["sender_invoice_no"], "invoice_id": inv["id"],
                               "status": "pending", "paid": False}
    assert _rows(db, Payment) == []


def test_callback_settles_and_replay_is_idempotent(client, db, gateways, student, enroll):
    from app.models import EBarimtReceipt, Invoice, Payment, StudentLedger

    account, headers = student
    enr = enroll(account.actor_id)
    inv = _create(client, headers, enrollment_id=enr.id).get_json()
    ref = inv["sender_invoice_no"]
    gateways["qpay"].paid = True

    first = client.get(f"/payments/qpay/callback?ref={ref}")
    assert first.status_code == 200
    assert first.get_json() == {"ref": ref, "invoice_id": inv["id"], "status": "paid",
                                "paid": True}
    replay = client.post(f"/payments/qpay/callback?ref={ref}", json={"any": "thing"})
    assert replay.status_code == 200
    assert replay.get_json()["paid"] is True

    assert len(_rows(db, Payment)) == 1
    assert len(_rows(db, EBarimtReceipt)) == 1
    assert db.session.get(Invoice, inv["id"]).status == "paid"
    ledger = StudentLedger.query.filter_by(enrollment_id=enr.id).one()
    assert ledger.total_paid == Decimal("250000.00")


def test_storepay_callback_finds_invoice_by_body_reference(client, db, gateways, student):
    from app.models import Payment

    inv = _create(client, student[1], provider="storepay").get_json()
    gateways["storepay"].paid = True
    resp = client.post("/payments/storepay/callback", json={"orderId": inv["sender_invoice_no"]})
    assert resp.status_code == 200
    assert resp.get_json()["paid"] is True
    assert _rows(db, Payment)[0].provider == "storepay"


def test_callback_finds_invoice_by_provider_invoice_id(client, gateways, student):
    inv = _create(client, student[1], provider="storepay").get_json()
    gateways["storepay"].paid = True
    resp = client.post("/payments/storepay/callback",
                       json={"loanId": inv["provider_invoice_id"]})
    assert resp.status_code == 200
    assert resp.get_json()["invoice_id"] == inv["id"]


def test_callback_on_another_providers_path_is_rejected(client, db, gateways, student):
    from app.models import Payment

    inv = _create(client, student[1]).get_json()
    gateways["qpay"].paid = gateways["storepay"].paid = True
    resp = client.post(f"/payments/storepay/callback?ref={inv['sender_invoice_no']}")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "invoice_not_found"
    assert _rows(db, Payment) == []


def test_callback_gateway_failure(client, db, gateways, student):
    from app.models import Payment

    inv = _create(client, student[1]).get_json()
    gateways["qpay"].fail = PaymentGatewayError("qpay", "gateway_http_401")
    resp = client.get(f"/payments/qpay/callback?ref={inv['sender_invoice_no']}")
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "gateway_gateway_http_401"
    assert _rows(db, Payment) == []
