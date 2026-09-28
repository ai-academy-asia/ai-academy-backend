"""Public checkout, step 6: и-баримт status and customer, plus the taxpayer lookup."""
from decimal import Decimal

import public_helpers
import pytest
from public_helpers import CHECKOUT_LEAD as LEAD
from public_helpers import COMPANY, _booking, _status

from app.ebarimt import EBarimtError
from app.models import (
    EBarimtReceipt,
)

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
checkout = public_helpers.checkout
live_ebarimt = public_helpers.live_ebarimt
paid = public_helpers.paid
taxpayer = public_helpers.taxpayer


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
