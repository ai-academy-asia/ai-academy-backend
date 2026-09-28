"""Student self-pay invoices: create and read (/payments/invoices)."""
from decimal import Decimal

import payments_student_helpers
import pytest
from payments_student_helpers import _create, _rows

from app.payments import PaymentGatewayError

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
enroll = payments_student_helpers.enroll
installment = payments_student_helpers.installment
student = payments_student_helpers.student


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
