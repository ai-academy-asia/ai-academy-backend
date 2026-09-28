"""Public checkout, steps 4–8: QPay invoice, payment status, и-баримт, taxpayer, StorePay."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.ebarimt import EBarimtError
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

LEAD = {"name": "Бат Дорж", "email": "bat@example.mn", "phone_num": "99112233",
        "register_num": "УБ12345678"}
COMPANY = {"tin": "12345678901", "name": "Жишээ ХХК", "found": True}


@pytest.fixture
def checkout(client, make_course, make_cohort):
    """``checkout(price=..., capacity=...)`` -> payment token of a fresh held seat."""

    def _make(price=1_000_000, capacity=10, cohort=None):
        if cohort is None:
            course = make_course(status="published", price_amount=price)
            cohort = make_cohort(course=course, capacity=capacity, name="Corporate Leaders")
        request_id = client.post("/classroom-requests", json=LEAD).get_json()["_id"]
        resp = client.post(f"/classroom-courses/{cohort.course_id}/bookings", json={
            "classroom_request_id": request_id, "classroom_course_schedule_id": cohort.id,
        })
        assert resp.status_code == 201, resp.get_json()
        return resp.get_json()["payment_token"]

    return _make


@pytest.fixture
def paid(client, gateways, checkout):
    """A settled QPay checkout's token."""

    def _make(**kwargs):
        token = checkout(**kwargs)
        client.get(f"/payments/qpay/invoice?pt={token}")
        gateways["qpay"].paid = True
        assert client.get(f"/payments/invoice/status?pt={token}").get_json()[
            "status_id"]["_id"] == 2
        gateways["qpay"].paid = False
        return token

    return _make


@pytest.fixture
def live_ebarimt(app, monkeypatch):
    """Leave temp mode and stand in for PosAPI. Returns the payloads it received."""
    monkeypatch.setitem(app.config, "EBARIMT_TEMP_MODE", False)
    sent = []

    def _create(self, payload):
        sent.append(payload)
        return {"id": f"DDTD{len(sent):04d}", "lottery": "AB123", "qrData": "qr",
                "date": "2026-09-28 12:00:00"}

    monkeypatch.setattr("app.ebarimt.posapi.PosAPIClient.create_receipt", _create)
    return sent


@pytest.fixture
def taxpayer(monkeypatch):
    """Stub the tax directory; ``taxpayer.found`` is what resolve() returns."""

    class Stub:
        found = dict(COMPANY)
        fail = None
        asked = []

    def _resolve(self, value):
        Stub.asked.append(value)
        if Stub.fail:
            raise Stub.fail
        return Stub.found

    monkeypatch.setattr("app.ebarimt.lookup.TaxpayerLookup.resolve", _resolve)
    return Stub


def _booking(token):
    return SeatBooking.query.filter_by(payment_token=token).one()


def _status(client, token):
    resp = client.get(f"/payments/invoice/status?pt={token}")
    return resp.status_code, resp.get_json()


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
    assert ClassroomRequest.query.get(booking.classroom_request_id).status == "paid"
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
    cohort = make_cohort(course=make_course(status="published"), capacity=1)
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


# ------------------------------------------------------------------ 6. receipt (GET)
def test_receipt_status_404s_in_temp_mode(client, gateways, paid):
    resp = client.get(f"/payments/receipt?pt={paid()}")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "receipts_not_issued"


def test_receipt_status_404s_unknown_token(client, live_ebarimt):
    resp = client.get("/payments/receipt?pt=pt_nope")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "payment_token_not_found"


def test_receipt_status_before_and_after_payment(client, gateways, checkout, live_ebarimt):
    token = checkout()
    unpaid = client.get(f"/payments/receipt?pt={token}").get_json()
    assert unpaid == {"status": "pending", "email": LEAD["email"], "ebarimt_id": None,
                      "error": None, "requires_customer_type": False}

    client.get(f"/payments/qpay/invoice?pt={token}")
    gateways["qpay"].paid = True
    _status(client, token)
    settled = client.get(f"/payments/receipt?pt={token}").get_json()
    assert settled["status"] == "pending"
    assert settled["requires_customer_type"] is True


# ------------------------------------------------------------------ 6. receipt (POST)
def test_set_receipt_409s_before_payment(client, gateways, checkout):
    token = checkout()
    client.get(f"/payments/qpay/invoice?pt={token}")
    resp = client.post(f"/payments/receipt?pt={token}", json={"customer_type": "individual"})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "payment_not_settled"


def test_set_receipt_404s_unknown_token(client):
    resp = client.post("/payments/receipt?pt=pt_nope", json={"customer_type": "individual"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "payment_token_not_found"


@pytest.mark.parametrize("payload", [{}, {"customer_type": "government"}])
def test_set_receipt_rejects_unknown_customer_type(client, paid, payload):
    resp = client.post(f"/payments/receipt?pt={paid()}", json=payload)
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "invalid_customer_type",
                               "allowed": ["individual", "organization"]}
    assert EBarimtReceipt.query.count() == 0


def test_set_receipt_individual_in_temp_mode_files_placeholder(client, paid):
    token = paid()
    resp = client.post(f"/payments/receipt?pt={token}", json={"customer_type": "Individual"})
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "pending", "email": LEAD["email"],
                               "ebarimt_id": None, "error": None}
    receipt = EBarimtReceipt.query.one()
    assert receipt.type == "B2C_RECEIPT"
    assert receipt.customer_register is None  # the lead's register stays off the receipt
    assert receipt.is_temp_mode and receipt.status == "temp"
    assert receipt.invoice_id == _booking(token).invoice_id
    assert receipt.total_amount == Decimal("1000000.00")


def test_set_receipt_is_idempotent(client, paid, taxpayer):
    token = paid()
    client.post(f"/payments/receipt?pt={token}", json={"customer_type": "individual"})
    again = client.post(f"/payments/receipt?pt={token}",
                        json={"customer_type": "organization", "customer_register": "1234567"})
    assert again.status_code == 200
    assert EBarimtReceipt.query.count() == 1
    assert EBarimtReceipt.query.one().type == "B2C_RECEIPT"
    assert taxpayer.asked == []


@pytest.mark.parametrize("register", [None, "", "123", "12345678", "abcdefg", "123456789012345"])
def test_set_receipt_organization_needs_register(client, paid, taxpayer, register):
    resp = client.post(f"/payments/receipt?pt={paid()}",
                       json={"customer_type": "organization", "customer_register": register})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_organization_register"
    assert taxpayer.asked == []


def test_set_receipt_organization_404s_unknown_company(client, paid, taxpayer):
    taxpayer.found = None
    resp = client.post(f"/payments/receipt?pt={paid()}",
                       json={"customer_type": "organization", "customer_register": "1234567"})
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "organization_not_found", "register": "1234567"}
    assert EBarimtReceipt.query.count() == 0


def test_set_receipt_organization_files_against_resolved_tin(client, paid, taxpayer):
    resp = client.post(f"/payments/receipt?pt={paid()}",
                       json={"customer_type": "organization", "customer_register": " 1234567 "})
    assert resp.status_code == 200
    assert taxpayer.asked == ["1234567"]
    receipt = EBarimtReceipt.query.one()
    assert receipt.type == "B2B_RECEIPT"
    assert receipt.customer_register == COMPANY["tin"]
    assert receipt.raw["customerTin"] == COMPANY["tin"]


def test_set_receipt_live_issues_and_reports_ddtd(client, paid, live_ebarimt):
    token = paid()
    resp = client.post(f"/payments/receipt?pt={token}", json={"customer_type": "individual"})
    assert resp.status_code == 200
    # mail is not configured, so the issued receipt waits for delivery
    assert resp.get_json() == {"status": "pending", "email": LEAD["email"],
                               "ebarimt_id": "DDTD0001", "error": None}
    assert "customerTin" not in live_ebarimt[0]
    assert live_ebarimt[0]["type"] == "B2C_RECEIPT"

    after = client.get(f"/payments/receipt?pt={token}").get_json()
    assert after["ebarimt_id"] == "DDTD0001"
    assert after["requires_customer_type"] is False


def test_set_receipt_live_emails_the_buyer(client, app, paid, live_ebarimt, monkeypatch):
    monkeypatch.setitem(app.config, "MAIL_HOST", "smtp.test")
    outbox = []
    monkeypatch.setattr("app.mail.send_message", outbox.append)
    token = paid()
    data = client.post(f"/payments/receipt?pt={token}",
                       json={"customer_type": "individual"}).get_json()
    assert data["status"] == "sent" and data["email"] == LEAD["email"]
    assert outbox and outbox[0]["To"] == LEAD["email"]
    assert client.get(f"/payments/receipt?pt={token}").get_json()["status"] == "sent"


def test_set_receipt_live_reports_mail_failure(client, app, paid, live_ebarimt, monkeypatch):
    from app.mail import MailError

    def _bounce(message):
        raise MailError("mailbox unavailable")

    monkeypatch.setitem(app.config, "MAIL_HOST", "smtp.test")
    monkeypatch.setattr("app.mail.send_message", _bounce)
    data = client.post(f"/payments/receipt?pt={paid()}",
                       json={"customer_type": "individual"}).get_json()
    assert data["status"] == "failed"
    assert data["ebarimt_id"] == "DDTD0001"
    assert "mailbox unavailable" in data["error"]


# ------------------------------------------------------------------ taxpayer
def test_taxpayer_returns_company(client, taxpayer):
    resp = client.get("/payments/taxpayer?tin=1234567")
    assert resp.status_code == 200
    assert resp.get_json() == COMPANY
    assert taxpayer.asked == ["1234567"]


def test_taxpayer_404s_unknown_company(client, taxpayer):
    taxpayer.found = None
    resp = client.get("/payments/taxpayer?tin=1234567")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "organization_not_found"


@pytest.mark.parametrize("tin", ["", "abc", "123"])
def test_taxpayer_404s_malformed_number_without_lookup(client, tin):
    resp = client.get(f"/payments/taxpayer?tin={tin}")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "organization_not_found"


def test_taxpayer_maps_directory_outage(client, taxpayer):
    taxpayer.fail = EBarimtError("taxinfo_http_error", retriable=True)
    resp = client.get("/payments/taxpayer?tin=12345678901")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "ebarimt_taxinfo_http_error"


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


@pytest.mark.xfail(strict=True, reason="storepay_invoice reuses any pending invoice, so a "
                   "buyer who opened the QPay QR first gets the QPay invoice back as StorePay")
def test_storepay_after_qpay_raises_a_storepay_invoice(client, gateways, checkout):
    token = checkout()
    client.get(f"/payments/qpay/invoice?pt={token}")
    client.post("/payments/storepay/invoice", json={"payment_token": token})
    assert len(gateways["storepay"].created) == 1
    assert _booking(token).invoice.provider == "storepay"


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
