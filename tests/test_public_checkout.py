"""Public checkout, steps 4–5: QPay invoice and payment status."""
from datetime import datetime, timedelta
from decimal import Decimal

import public_helpers
import pytest
from public_helpers import CHECKOUT_LEAD as LEAD
from public_helpers import _booking, _status

from app.models import (
    ClassroomRequest,
    EBarimtReceipt,
    Enrollment,
    Invoice,
    Payment,
    SeatBooking,
    StudentLedger,
)
from app.payments import PaymentGatewayError

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
checkout = public_helpers.checkout


# ------------------------------------------------------------------ 4. QPay invoice
def test_qpay_invoice_charges_booking_amount(client, gateways, checkout):
    token = checkout(price=750_000)
    resp = client.get(f"/payments/qpay/invoice?pt={token}")
    assert resp.status_code == 200
    data = resp.get_json()
    booking = _booking(token)
    invoice = booking.invoice
    assert invoice.provider == "qpay" and invoice.status == "pending"
    assert invoice.amount == Decimal("750000.00")
    assert data == {
        "invoice_id": invoice.provider_invoice_id, "qr_image": "aW1n",
        "qr_text": invoice.qr_text, "qPay_shortUrl": invoice.payment_url, "urls": [],
        "sandbox": False,
    }
    req = gateways["qpay"].created[0]
    assert req.description == "Corporate Leaders"
    assert req.customer == {"name": LEAD["name"], "phone": LEAD["phone_num"],
                            "email": LEAD["email"]}  # no national register number
    assert req.callback_url.startswith("http://testserver/payments/qpay/callback?ref=")


def test_qpay_invoice_is_reused_while_pending(client, gateways, checkout):
    token = checkout()
    first = client.get(f"/payments/qpay/invoice?pt={token}").get_json()
    second = client.get(f"/payments/qpay/invoice?pt={token}").get_json()
    assert first["invoice_id"] == second["invoice_id"]
    assert len(gateways["qpay"].created) == 1
    assert Invoice.query.count() == 1


def test_qpay_invoice_is_replaced_once_expired(client, gateways, checkout, db):
    token = checkout()
    client.get(f"/payments/qpay/invoice?pt={token}")
    old = _booking(token).invoice
    old.status = "expired"
    db.session.commit()

    client.get(f"/payments/qpay/invoice?pt={token}")
    assert len(gateways["qpay"].created) == 2
    assert _booking(token).invoice_id != old.id


@pytest.mark.parametrize("query", ["", "?pt=", "?pt=pt_nope"])
def test_qpay_invoice_404s_unknown_token(client, gateways, query):
    resp = client.get(f"/payments/qpay/invoice{query}")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "payment_token_not_found"


@pytest.mark.parametrize("error, status, code", [
    (PaymentGatewayError("qpay", "http_error", retriable=True), 503, "gateway_http_error"),
    (PaymentGatewayError("qpay", "declined"), 502, "gateway_declined"),
    (PaymentGatewayError("qpay", "not_configured"), 501, "gateway_not_configured"),
])
def test_qpay_invoice_maps_gateway_failures(client, gateways, checkout, error, status, code):
    token = checkout()
    gateways["qpay"].fail = error
    resp = client.get(f"/payments/qpay/invoice?pt={token}")
    assert resp.status_code == status
    assert resp.get_json()["error"] == code
    assert _booking(token).invoice_id is None


def test_qpay_invoice_refuses_zero_amount_booking(client, gateways, checkout, db):
    token = checkout()
    _booking(token).amount = Decimal("0")
    db.session.commit()
    resp = client.get(f"/payments/qpay/invoice?pt={token}")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "amount_must_be_positive"


def test_sandbox_invoice_settles_without_a_gateway(client, app, checkout, monkeypatch):
    monkeypatch.setitem(app.config, "PAYMENTS_SANDBOX", True)
    token = checkout()
    data = client.get(f"/payments/qpay/invoice?pt={token}").get_json()
    assert data["sandbox"] is True
    assert data["qr_text"].endswith("NOT-A-REAL-PAYMENT")
    assert _booking(token).invoice.provider == "sandbox"

    assert _status(client, token)[1]["status_id"]["_id"] == 2
    assert _booking(token).status == "paid"


# ------------------------------------------------------------------ 5. status
def test_status_without_invoice_is_pending(client, gateways, checkout):
    token = checkout()
    assert _status(client, token) == (200, {"status_id": {"_id": 1, "name": "Хүлээгдэж буй"}})


def test_status_unpaid_leaves_seat_held(client, gateways, checkout):
    token = checkout()
    client.get(f"/payments/qpay/invoice?pt={token}")
    assert _status(client, token)[1]["status_id"]["_id"] == 1
    assert _booking(token).status == "held"
    assert Payment.query.count() == 0


def test_status_paid_settles_booking(client, gateways, checkout):
    token = checkout(price=800_000)
    client.get(f"/payments/qpay/invoice?pt={token}")
    gateways["qpay"].paid = True

    assert _status(client, token) == (200, {"status_id": {"_id": 2, "name": "Төлөгдсөн"}})
    booking = _booking(token)
    assert booking.status == "paid" and booking.paid_at is not None
    assert booking.invoice.status == "paid"
    assert ClassroomRequest.query.filter_by(id=booking.classroom_request_id).one().status == "paid"
    payment = Payment.query.one()
    assert payment.invoice_id == booking.invoice_id
    assert payment.amount == Decimal("800000.00")
    # Public checkouts wait for the buyer's individual/company answer before
    # filing a receipt, and an anonymous lead has no enrollment or ledger.
    assert EBarimtReceipt.query.count() == 0
    assert Enrollment.query.count() == 0 and StudentLedger.query.count() == 0


def test_status_is_idempotent_once_paid(client, gateways, checkout):
    token = checkout()
    client.get(f"/payments/qpay/invoice?pt={token}")
    gateways["qpay"].paid = True
    _status(client, token)
    gateways["qpay"].fail = PaymentGatewayError("qpay", "should_not_be_called")
    assert _status(client, token)[1]["status_id"]["_id"] == 2
    assert Payment.query.count() == 1


def test_status_404s_unknown_token(client, gateways):
    code, data = _status(client, "pt_nope")
    assert code == 404 and data["error"] == "payment_token_not_found"


def test_status_maps_gateway_failure(client, gateways, checkout):
    token = checkout()
    client.get(f"/payments/qpay/invoice?pt={token}")
    gateways["qpay"].fail = PaymentGatewayError("qpay", "timeout", retriable=True)
    code, data = _status(client, token)
    assert code == 503 and data["error"] == "gateway_timeout"
    assert _booking(token).status == "held"


def test_status_settles_lapsed_hold_whose_seat_is_still_free(client, gateways, checkout, db):
    token = checkout()
    client.get(f"/payments/qpay/invoice?pt={token}")
    _booking(token).expires_at = datetime.utcnow() - timedelta(minutes=5)
    db.session.commit()
    gateways["qpay"].paid = True
    assert _status(client, token)[1]["status_id"]["_id"] == 2
    assert _booking(token).status == "paid"


def test_status_refuses_lapsed_hold_whose_seat_was_resold(client, gateways, checkout,
                                                          make_course, make_cohort, db):
    cohort = make_cohort(course=make_course(status="open"), capacity=1)
    first = checkout(cohort=cohort)
    client.get(f"/payments/qpay/invoice?pt={first}")
    _booking(first).expires_at = datetime.utcnow() - timedelta(minutes=5)
    db.session.commit()
    second = checkout(cohort=cohort)
    assert _booking(second).number_of_seat == _booking(first).number_of_seat

    gateways["qpay"].paid = True
    code, data = _status(client, first)
    assert code == 409 and data["error"] == "seat_taken_after_hold_expired"
    assert SeatBooking.query.filter_by(cohort_id=cohort.id, status="paid").count() <= 1
