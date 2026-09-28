"""Finance back office: Golomt reconcile and the student ledger."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import payments_helpers
import pytest
from payments_helpers import _create, _txn

from app.payments import PaymentGatewayError

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
enroll = payments_helpers.enroll
finance = payments_helpers.finance
installment = payments_helpers.installment
statement = payments_helpers.statement


# ============================================== POST /admin/payments/reconcile/golomt
def test_reconcile_settles_matching_credits(client, db, gateways, statement, finance, enroll):
    from app.models import EBarimtReceipt, Invoice, Payment, StudentLedger

    enr = enroll()
    hit = _create(client, finance, provider="golomt", enrollment_id=enr.id).get_json()
    short = _create(client, finance, provider="golomt").get_json()
    untouched = _create(client, finance, provider="golomt").get_json()
    _create(client, finance)  # a pending QPay invoice is not reconciled
    gateways["golomt"].statement = [
        _txn("T1", 300_000, f"tulbur {hit['sender_invoice_no'].lower()} bat"),
        _txn("T2", 100_000, f"{short['sender_invoice_no']}"),  # amount mismatch
        _txn("T3", 300_000, "no reference here"),
    ]

    resp = client.post("/admin/payments/reconcile/golomt",
                       json={"from": "2026-09-01", "to": "2026-09-27"}, headers=finance)
    assert resp.status_code == 200
    data = resp.get_json()
    assert statement == [(date(2026, 9, 1), date(2026, 9, 27))]
    assert data["from"] == "2026-09-01" and data["to"] == "2026-09-27"
    assert data["statement_txns"] == 3
    assert data["pending_invoices"] == 3
    assert data["settled"] == 1
    assert data["matched"] == [{"invoice_id": hit["id"], "ref": hit["sender_invoice_no"],
                                "txn_id": "T1", "amount": 300000.0, "account": "MN0001"}]

    db.session.expire_all()
    payment = Payment.query.one()
    assert (payment.provider, payment.provider_payment_id, payment.method) == (
        "golomt", "T1", "transfer")
    assert payment.paid_at == datetime(2026, 9, 20, 10, 0)
    assert db.session.get(Invoice, hit["id"]).status == "paid"
    assert db.session.get(Invoice, short["id"]).status == "pending"
    assert db.session.get(Invoice, untouched["id"]).status == "pending"
    assert StudentLedger.query.filter_by(enrollment_id=enr.id).one().total_paid == Decimal(
        "300000.00")
    assert EBarimtReceipt.query.filter_by(payment_id=payment.id).count() == 1

    # Re-running over the same statement settles nothing new.
    again = client.post("/admin/payments/reconcile/golomt", json={}, headers=finance).get_json()
    assert again["settled"] == 0 and again["pending_invoices"] == 2
    assert Payment.query.count() == 1


def test_reconcile_defaults_to_last_14_days(client, gateways, statement, finance):
    resp = client.post("/admin/payments/reconcile/golomt", headers=finance)
    assert resp.status_code == 200
    today = date.today()
    assert statement == [(today - timedelta(days=14), today)]
    assert resp.get_json()["settled"] == 0


def test_reconcile_from_defaults_relative_to_to(client, gateways, statement, finance):
    client.post("/admin/payments/reconcile/golomt", json={"to": "2026-09-15"}, headers=finance)
    assert statement == [(date(2026, 9, 1), date(2026, 9, 15))]


@pytest.mark.parametrize("dates", [{"from": "2026-13-01"}, {"to": "yesterday"}, {"to": 20260901}])
def test_reconcile_invalid_date(client, gateways, statement, finance, dates):
    resp = client.post("/admin/payments/reconcile/golomt", json=dates, headers=finance)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_date"
    assert statement == []


def test_reconcile_gateway_failure(client, gateways, finance):
    def _boom(from_date, to_date):
        raise PaymentGatewayError("golomt", "not_configured")

    gateways["golomt"].fetch_all_statements = _boom
    resp = client.post("/admin/payments/reconcile/golomt", headers=finance)
    assert resp.status_code == 501
    assert resp.get_json()["error"] == "gateway_not_configured"


# ======================================================== ledger
def test_ledger_not_found_before_any_payment(client, finance, enroll):
    resp = client.get(f"/admin/ledger/{enroll().id}", headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "ledger_not_found"


def test_ledger_after_settlement(client, gateways, finance, enroll, installment):
    enr = enroll()
    first = installment(enr, seq=1, amount=300_000, due=date(2026, 10, 1))
    installment(enr, seq=2, amount=200_000, due=date(2026, 11, 1))
    inv = _create(client, finance, installment_id=first.id).get_json()
    gateways["qpay"].paid = True
    client.post(f"/admin/invoices/{inv['id']}/check", headers=finance)

    resp = client.get(f"/admin/ledger/{enr.id}", headers=finance)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["enrollment_id"] == enr.id and data["student_id"] == enr.student_id
    assert (data["total_due"], data["total_paid"], data["balance"]) == (500000.0, 300000.0,
                                                                       200000.0)
    assert data["next_due_date"] == "2026-11-01"


def test_recompute_creates_ledger_from_installments(client, finance, enroll, installment):
    enr = enroll()
    installment(enr, seq=1, amount=100_000, due=date(2026, 10, 1), status="waived")
    installment(enr, seq=2, amount=150_000, due=date(2026, 12, 1))
    installment(enr, seq=3, amount=150_000, due=date(2026, 11, 1))
    resp = client.post(f"/admin/ledger/{enr.id}/recompute", headers=finance)
    assert resp.status_code == 200
    data = resp.get_json()
    assert (data["total_due"], data["total_paid"], data["balance"]) == (400000.0, 0.0, 400000.0)
    assert data["next_due_date"] == "2026-11-01"
    assert client.get(f"/admin/ledger/{enr.id}", headers=finance).get_json() == data


def test_recompute_without_plan_nets_refunds(client, db, gateways, finance, enroll):
    from app.models import Payment

    enr = enroll()
    a = _create(client, finance, enrollment_id=enr.id).get_json()
    b = _create(client, finance, enrollment_id=enr.id, provider="storepay").get_json()
    gateways["qpay"].paid = gateways["storepay"].paid = True
    client.post(f"/admin/invoices/{a['id']}/check", headers=finance)
    client.post(f"/admin/invoices/{b['id']}/check", headers=finance)

    db.session.expire_all()
    pa = Payment.query.filter_by(invoice_id=a["id"]).one()
    pa.status, pa.refunded_amount = "partially_refunded", Decimal("100000")
    pb = Payment.query.filter_by(invoice_id=b["id"]).one()
    pb.status, pb.refunded_amount = "refunded", Decimal("300000")
    db.session.commit()

    data = client.post(f"/admin/ledger/{enr.id}/recompute", headers=finance).get_json()
    assert (data["total_due"], data["total_paid"], data["balance"]) == (200000.0, 200000.0, 0.0)
    assert data["next_due_date"] is None


def test_recompute_unknown_enrollment(client, finance):
    resp = client.post("/admin/ledger/9999/recompute", headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "enrollment_not_found"
