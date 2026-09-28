"""Gateway callbacks and student self-pay invoices (/payments/*)."""
from datetime import date
from decimal import Decimal

import pytest

from app.payments import PaymentGatewayError


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


# ============================================================ POST /payments/invoices
def test_student_creates_invoice_for_own_enrollment(client, db, gateways, student, enroll):
    account, headers = student
    enr = enroll(account.actor_id)
    resp = _create(client, headers, enrollment_id=enr.id, description="Tuition")
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "pending"
    assert data["provider"] == "qpay"
    assert data["amount"] == 250000.0
    assert data["enrollment_id"] == enr.id
    assert data["student_id"] == account.actor_id
    assert data["sender_invoice_no"].startswith("AIAA-QP-")
    assert data["provider_invoice_id"] == f"QPAY-{data['sender_invoice_no']}"
    assert data["qr_text"] and data["qr_image"]

    req = gateways["qpay"].created[0]
    assert req.amount == Decimal("250000.00")
    assert req.description == "Tuition"
    assert req.callback_url == (
        f"http://testserver/payments/qpay/callback?ref={data['sender_invoice_no']}"
    )
    assert req.customer["name"] == "Bat"


def test_student_invoice_without_enrollment_is_tied_to_self(client, gateways, student):
    account, headers = student
    resp = _create(client, headers)
    assert resp.status_code == 201
    assert resp.get_json()["student_id"] == account.actor_id
    assert resp.get_json()["enrollment_id"] is None


def test_student_invoice_for_installment(client, gateways, student, enroll, installment):
    account, headers = student
    enr = enroll(account.actor_id)
    inst = installment(enr)
    resp = _create(client, headers, enrollment_id=enr.id, installment_id=inst.id)
    assert resp.status_code == 201
    assert resp.get_json()["installment_id"] == inst.id


def test_create_invoice_requires_auth(client, gateways):
    resp = _create(client, {})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


@pytest.mark.parametrize("actor", ["staff", "teacher"])
def test_create_invoice_is_student_only(client, gateways, make_staff, make_teacher, actor):
    headers = (make_staff("finance") if actor == "staff" else make_teacher())[1]
    resp = _create(client, headers)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


@pytest.mark.parametrize("provider", [None, "paypal", "sandbox"])
def test_create_invoice_rejects_unsupported_provider(client, db, gateways, student, provider):
    from app.models import Invoice

    resp = _create(client, student[1], provider=provider)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "unsupported_provider"
    assert set(data["supported"]) == {"qpay", "storepay", "golomt"}
    assert _rows(db, Invoice) == []


def test_create_invoice_rejects_someone_elses_enrollment(
    client, db, gateways, make_student, enroll
):
    other, _ = make_student()
    _, headers = make_student()
    enr = enroll(other.actor_id)
    resp = _create(client, headers, enrollment_id=enr.id)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "not_your_enrollment"
    assert gateways["qpay"].created == []


def test_create_invoice_rejects_unknown_enrollment(client, gateways, student):
    resp = _create(client, student[1], enrollment_id=9999)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "not_your_enrollment"


def test_create_invoice_rejects_someone_elses_installment(
    client, gateways, make_student, enroll, installment
):
    other, _ = make_student()
    _, headers = make_student()
    inst = installment(enroll(other.actor_id))
    resp = _create(client, headers, installment_id=inst.id)
    assert resp.status_code == 403


def test_create_invoice_unknown_installment(client, gateways, student):
    resp = _create(client, student[1], installment_id=9999)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "installment_not_found"


@pytest.mark.parametrize("amount, code", [
    (None, "invalid_amount"),
    ("abc", "invalid_amount"),
    (0, "amount_must_be_positive"),
    (-100, "amount_must_be_positive"),
])
def test_create_invoice_validates_amount(client, db, gateways, student, amount, code):
    from app.models import Invoice

    resp = _create(client, student[1], amount=amount)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == code
    assert _rows(db, Invoice) == []


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_create_invoice_rejects_non_finite_amount(client, gateways, student, amount):
    resp = _create(client, student[1], amount=amount)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_amount"


def test_create_invoice_rounds_amount_to_cents(client, gateways, student):
    resp = _create(client, student[1], amount="1000.456")
    assert resp.status_code == 201
    assert resp.get_json()["amount"] == 1000.46


@pytest.mark.parametrize("retriable, status", [(False, 502), (True, 503)])
def test_create_invoice_gateway_failure(client, db, gateways, student, retriable, status):
    from app.models import Invoice

    gateways["qpay"].fail = PaymentGatewayError("qpay", "gateway_http_500", retriable=retriable)
    resp = _create(client, student[1])
    assert resp.status_code == status
    assert resp.get_json()["error"] == "gateway_gateway_http_500"
    assert resp.get_json()["provider"] == "qpay"
    assert _rows(db, Invoice) == []


def test_create_invoice_gateway_not_configured(client, gateways, student):
    gateways["storepay"].fail = PaymentGatewayError("storepay", "not_configured")
    resp = _create(client, student[1], provider="storepay")
    assert resp.status_code == 501
    assert resp.get_json()["error"] == "gateway_not_configured"


# ======================================================= GET /payments/invoices/<id>
def test_student_reads_own_invoice(client, gateways, student):
    headers = student[1]
    inv = _create(client, headers).get_json()
    resp = client.get(f"/payments/invoices/{inv['id']}", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["id"] == inv["id"]
    assert resp.get_json()["qr_text"] == inv["qr_text"]


def test_student_cannot_read_other_students_invoice(client, gateways, make_student):
    inv = _create(client, make_student()[1]).get_json()
    resp = client.get(f"/payments/invoices/{inv['id']}", headers=make_student()[1])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


def test_read_invoice_not_found(client, student):
    resp = client.get("/payments/invoices/9999", headers=student[1])
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "invoice_not_found"


def test_read_invoice_requires_student(client, gateways, student, admin_headers):
    inv = _create(client, student[1]).get_json()
    assert client.get(f"/payments/invoices/{inv['id']}").status_code == 401
    assert client.get(f"/payments/invoices/{inv['id']}", headers=admin_headers).status_code == 403


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
