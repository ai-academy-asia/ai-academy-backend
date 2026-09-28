"""Public checkout, step 8: StorePay invoice and status, and promotion use counting."""
from decimal import Decimal

import public_helpers
import pytest
from public_helpers import CHECKOUT_LEAD as LEAD
from public_helpers import _booking, _status

from app.models import (
    Invoice,
    Payment,
)
from app.payments import PaymentGatewayError

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
checkout = public_helpers.checkout


# ------------------------------------------------------------------ 8. StorePay
def test_storepay_invoice_created_from_token(client, gateways, checkout):
    token = checkout(price=600_000)
    resp = client.post("/payments/storepay/invoice",
                       json={"payment_token": token, "phone": "88001122", "amount": 1})
    assert resp.status_code == 201
    invoice = _booking(token).invoice
    assert invoice.provider == "storepay"
    assert invoice.amount == Decimal("600000.00")
    assert resp.get_json() == {"requestId": token, "invoiceId": invoice.provider_invoice_id,
                               "qrData": invoice.qr_text, "sandbox": False}
    assert gateways["storepay"].created[0].customer["phone"] == "88001122"


def test_storepay_invoice_accepts_pt_key_and_reuses_invoice(client, gateways, checkout):
    token = checkout()
    first = client.post("/payments/storepay/invoice", json={"pt": token}).get_json()
    second = client.post("/payments/storepay/invoice", json={"pt": token}).get_json()
    assert first["invoiceId"] == second["invoiceId"]
    assert len(gateways["storepay"].created) == 1


@pytest.mark.parametrize("payload", [{}, {"payment_token": "pt_nope"},
                                     {"classroomRequestId": 1}])
def test_storepay_invoice_404s_without_valid_token(client, gateways, checkout, payload):
    checkout()
    resp = client.post("/payments/storepay/invoice", json=payload)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "payment_token_not_found"
    assert gateways["storepay"].created == []


def test_storepay_after_qpay_raises_a_storepay_invoice(client, gateways, checkout):
    token = checkout()
    client.get(f"/payments/qpay/invoice?pt={token}")
    client.post("/payments/storepay/invoice", json={"payment_token": token})
    assert len(gateways["storepay"].created) == 1
    assert _booking(token).invoice.provider == "storepay"


def test_switching_gateway_retires_the_unpaid_qpay_invoice(client, gateways, checkout):
    token = checkout()
    client.get(f"/payments/qpay/invoice?pt={token}")
    qpay_invoice = _booking(token).invoice
    client.post("/payments/storepay/invoice", json={"payment_token": token})
    assert Invoice.query.filter_by(id=qpay_invoice.id).one().status == "cancelled"


def test_switching_gateway_keeps_an_invoice_paid_in_the_meantime(client, gateways, checkout):
    token = checkout()
    client.get(f"/payments/qpay/invoice?pt={token}")
    gateways["qpay"].paid = True
    client.post("/payments/storepay/invoice", json={"payment_token": token})
    assert gateways["storepay"].created == []
    assert _booking(token).invoice.provider == "qpay"
    assert _booking(token).invoice.status == "paid"


def test_storepay_invoice_in_sandbox(client, app, checkout, monkeypatch):
    monkeypatch.setitem(app.config, "PAYMENTS_SANDBOX", True)
    token = checkout()
    data = client.post("/payments/storepay/invoice", json={"payment_token": token}).get_json()
    assert data["sandbox"] is True
    assert _booking(token).invoice.provider == "sandbox"


def test_storepay_status_404s_before_invoice_or_unknown_token(client, gateways, checkout):
    token = checkout()
    for request_id in (token, "pt_nope"):
        resp = client.get(f"/payments/storepay/invoice/{request_id}")
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "payment_token_not_found"


def test_storepay_status_unpaid_then_confirmed(client, gateways, checkout):
    token = checkout()
    client.post("/payments/storepay/invoice", json={"payment_token": token})
    resp = client.get(f"/payments/storepay/invoice/{token}")
    assert resp.status_code == 200
    assert resp.get_json() == {"isConfirmed": False, "isCancelled": False}
    assert _booking(token).status == "held"

    gateways["storepay"].paid = True
    assert client.get(f"/payments/storepay/invoice/{token}").get_json() == {
        "isConfirmed": True, "isCancelled": False}
    booking = _booking(token)
    assert booking.status == "paid"
    assert Payment.query.one().provider == "storepay"


@pytest.mark.parametrize("status", ["cancelled", "expired", "failed"])
def test_storepay_status_reports_cancelled(client, gateways, checkout, db, status):
    token = checkout()
    client.post("/payments/storepay/invoice", json={"payment_token": token})
    _booking(token).invoice.status = status
    db.session.commit()
    assert client.get(f"/payments/storepay/invoice/{token}").get_json() == {
        "isConfirmed": False, "isCancelled": True}


def test_storepay_status_maps_gateway_failure(client, gateways, checkout):
    token = checkout()
    client.post("/payments/storepay/invoice", json={"payment_token": token})
    gateways["storepay"].fail = PaymentGatewayError("storepay", "bad_response")
    resp = client.get(f"/payments/storepay/invoice/{token}")
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "gateway_bad_response"


def test_paid_promotion_counts_toward_max_uses(client, gateways, make_course, make_cohort, db):
    from app.models import Promotion

    db.session.add(Promotion(code="ONCE", name="Once", discount_type="percent",
                             discount_value=10, max_uses=1))
    db.session.commit()
    cohort = make_cohort(course=make_course(status="published"))
    request_id = client.post("/classroom-requests", json=LEAD).get_json()["_id"]
    token = client.post(f"/classroom-courses/{cohort.course_id}/bookings", json={
        "classroom_request_id": request_id, "classroom_course_schedule_id": cohort.id,
        "promotion_code": "ONCE",
    }).get_json()["payment_token"]
    client.get(f"/payments/qpay/invoice?pt={token}")
    gateways["qpay"].paid = True
    _status(client, token)

    resp = client.post(f"/classroom-requests/{request_id}/coupon", json={"promotion_code": "ONCE"})
    assert resp.status_code == 404
