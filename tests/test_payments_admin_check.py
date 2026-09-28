"""Finance back office: invoice checks, settlement and payment listings."""
from decimal import Decimal

import payments_helpers
from payments_helpers import _create

from app.payments import PaymentGatewayError

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
enroll = payments_helpers.enroll
finance = payments_helpers.finance
installment = payments_helpers.installment


# ================================================ POST /admin/invoices/<id>/check
def test_check_unpaid_invoice(client, db, gateways, finance):
    from app.models import Payment

    inv = _create(client, finance).get_json()
    resp = client.post(f"/admin/invoices/{inv['id']}/check", headers=finance)
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "pending"
    assert Payment.query.count() == 0


def test_check_settles_and_is_idempotent(client, db, gateways, finance, enroll, installment):
    from app.models import EBarimtReceipt, Payment, PaymentInstallment, StudentLedger

    enr = enroll()
    inst = installment(enr, amount=300_000)
    inv = _create(client, finance, installment_id=inst.id).get_json()
    gateways["qpay"].paid = True

    for _ in range(2):
        resp = client.post(f"/admin/invoices/{inv['id']}/check", headers=finance)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "paid"
        assert "qr_text" not in resp.get_json()["invoice"]

    db.session.expire_all()
    payment = Payment.query.one()
    assert payment.invoice_id == inv["id"] and payment.status == "paid"
    assert payment.method == "qr"
    assert db.session.get(PaymentInstallment, inst.id).status == "paid"
    ledger = StudentLedger.query.filter_by(enrollment_id=enr.id).one()
    assert (ledger.total_due, ledger.total_paid, ledger.balance) == (
        Decimal("300000.00"), Decimal("300000.00"), Decimal("0.00"))
    receipt = EBarimtReceipt.query.one()
    assert receipt.payment_id == payment.id and receipt.status == "temp"


def test_check_records_gateway_reported_amount(client, db, gateways, finance, enroll):
    from app.models import Payment, StudentLedger

    enr = enroll()
    inv = _create(client, finance, enrollment_id=enr.id).get_json()
    gateways["qpay"].paid = True
    gateways["qpay"].amount = 120_000
    client.post(f"/admin/invoices/{inv['id']}/check", headers=finance)
    db.session.expire_all()
    assert Payment.query.one().amount == Decimal("120000.00")
    assert StudentLedger.query.filter_by(enrollment_id=enr.id).one().total_paid == Decimal(
        "120000.00")


def test_check_underpayment_does_not_mark_installment_paid(client, db, gateways, finance,
                                                            enroll, installment):
    from app.models import PaymentInstallment

    inst = installment(enroll(), amount=300_000)
    inv = _create(client, finance, installment_id=inst.id).get_json()
    gateways["qpay"].paid = True
    gateways["qpay"].amount = 1
    client.post(f"/admin/invoices/{inv['id']}/check", headers=finance)
    db.session.expire_all()
    assert db.session.get(PaymentInstallment, inst.id).status != "paid"


def test_underpayment_is_recorded_but_leaves_the_invoice_open(client, db, gateways, finance,
                                                               enroll):
    from app.models import EBarimtReceipt, Payment

    enr = enroll()
    inv = _create(client, finance, enrollment_id=enr.id).get_json()
    gateways["qpay"].paid = True
    gateways["qpay"].amount = 100_000
    resp = client.post(f"/admin/invoices/{inv['id']}/check", headers=finance)
    assert resp.get_json()["status"] == "pending"
    payment = Payment.query.filter_by(invoice_id=inv["id"]).one()
    assert payment.amount == 100_000
    assert EBarimtReceipt.query.count() == 0
    ledger = client.get(f"/admin/ledger/{enr.id}", headers=finance).get_json()
    assert ledger["total_paid"] == 100_000

    # Polling again neither duplicates the payment nor settles the invoice.
    client.post(f"/admin/invoices/{inv['id']}/check", headers=finance)
    assert Payment.query.filter_by(invoice_id=inv["id"]).count() == 1


def test_create_rejects_installment_of_another_enrollment(client, gateways, finance, enroll,
                                                          installment):
    inst = installment(enroll())
    resp = _create(client, finance, enrollment_id=enroll().id, installment_id=inst.id)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "installment_not_in_enrollment"


def test_check_not_found(client, finance):
    resp = client.post("/admin/invoices/9999/check", headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "invoice_not_found"


def test_check_gateway_failure(client, gateways, finance):
    inv = _create(client, finance).get_json()
    gateways["qpay"].fail = PaymentGatewayError("qpay", "gateway_timeout", retriable=True)
    resp = client.post(f"/admin/invoices/{inv['id']}/check", headers=finance)
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "gateway_gateway_timeout"


# ============================================================= GET /admin/payments
def test_list_payments_with_filters(client, gateways, finance):
    a = _create(client, finance).get_json()
    b = _create(client, finance, provider="storepay").get_json()
    _create(client, finance)  # stays unpaid
    gateways["qpay"].paid = gateways["storepay"].paid = True
    client.post(f"/admin/invoices/{a['id']}/check", headers=finance)
    client.post(f"/admin/invoices/{b['id']}/check", headers=finance)

    def rows(query=""):
        resp = client.get(f"/admin/payments{query}", headers=finance)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == len(data["payments"])
        return data["payments"]

    assert [p["invoice_id"] for p in rows()] == [b["id"], a["id"]]
    assert [p["provider"] for p in rows("?provider=qpay")] == ["qpay"]
    assert [p["invoice_id"] for p in rows(f"?invoice_id={b['id']}")] == [b["id"]]
    assert len(rows("?status=paid")) == 2
    assert rows("?status=refunded") == []
    assert len(rows("?limit=1")) == 1
    first = rows()[0]
    assert first["amount"] == 300000.0 and first["refunded_amount"] == 0.0


def test_list_payments_empty(client, finance):
    resp = client.get("/admin/payments", headers=finance)
    assert resp.get_json() == {"count": 0, "payments": []}
