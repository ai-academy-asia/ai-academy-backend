"""Finance back office: invoices, payments, Golomt reconcile and the student ledger."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.payments import PaymentGatewayError
from app.payments.golomt import GolomtCorporateProvider, StatementTxn


@pytest.fixture
def finance(make_staff):
    return make_staff("finance")[1]


@pytest.fixture
def enroll(db, make_cohort, make_student):
    """``enroll()`` -> Enrollment of a new student in a fresh cohort."""
    from app.models import Enrollment

    def _make(student_id=None):
        student_id = student_id or make_student()[0].actor_id
        cohort = make_cohort()
        enr = Enrollment(cohort_id=cohort.id, student_id=student_id,
                         course_id=cohort.course_id, status="active")
        db.session.add(enr)
        db.session.commit()
        return enr

    return _make


@pytest.fixture
def installment(db):
    from app.models import PaymentInstallment

    def _make(enrollment, seq=1, amount=500_000, due=date(2026, 10, 1), status="pending"):
        inst = PaymentInstallment(enrollment_id=enrollment.id, student_id=enrollment.student_id,
                                  seq=seq, amount=amount, due_date=due, status=status)
        db.session.add(inst)
        db.session.commit()
        return inst

    return _make


@pytest.fixture
def statement(gateways):
    """Give the fake Golomt a statement; returns the list of (from, to) it was asked for."""
    golomt = gateways["golomt"]
    calls = []

    def _fetch(from_date, to_date):
        calls.append((from_date, to_date))
        return golomt.statement

    golomt.fetch_all_statements = _fetch
    golomt.matches = GolomtCorporateProvider.matches
    return calls


def _create(client, headers, **fields):
    payload = {"provider": "qpay", "amount": 300_000}
    payload.update(fields)
    return client.post("/admin/invoices", json=payload, headers=headers)


def _txn(txn_id, amount, description, **kw):
    return StatementTxn(txn_id=txn_id, amount=Decimal(str(amount)), description=description,
                        account="MN0001", posted_at=datetime(2026, 9, 20, 10, 0),
                        raw={"id": txn_id}, **kw)


# ================================================================ auth matrix
ENDPOINTS = [
    ("post", "/admin/invoices"),
    ("get", "/admin/invoices"),
    ("get", "/admin/invoices/1"),
    ("post", "/admin/invoices/1/check"),
    ("get", "/admin/payments"),
    ("post", "/admin/payments/reconcile/golomt"),
    ("get", "/admin/ledger/1"),
    ("post", "/admin/ledger/1/recompute"),
]


@pytest.mark.parametrize("method, url", ENDPOINTS)
def test_requires_token(client, method, url):
    resp = getattr(client, method)(url, json={})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "authentication_required"


@pytest.mark.parametrize("method, url", ENDPOINTS)
@pytest.mark.parametrize("role", ["sales_enrollment", "content_marketing"])
def test_non_finance_staff_forbidden(client, make_staff, method, url, role):
    resp = getattr(client, method)(url, json={}, headers=make_staff(role)[1])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


@pytest.mark.parametrize("method, url", ENDPOINTS)
def test_students_forbidden(client, make_student, method, url):
    resp = getattr(client, method)(url, json={}, headers=make_student()[1])
    assert resp.status_code == 403


# ============================================================ POST /admin/invoices
def test_finance_creates_invoice_for_enrollment(client, gateways, finance, enroll):
    enr = enroll()
    resp = _create(client, finance, enrollment_id=enr.id, description="Term 1")
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "pending"
    assert data["enrollment_id"] == enr.id
    assert data["student_id"] == enr.student_id  # derived from the enrollment
    assert data["amount"] == 300000.0
    assert gateways["qpay"].created[0].customer["name"] == "Bat"


def test_super_admin_creates_invoice(client, gateways, admin_headers):
    assert _create(client, admin_headers).status_code == 201


def test_create_invoice_derives_links_from_installment(client, gateways, finance, enroll,
                                                       installment):
    enr = enroll()
    inst = installment(enr)
    data = _create(client, finance, installment_id=inst.id).get_json()
    assert data["installment_id"] == inst.id
    assert data["enrollment_id"] == enr.id
    assert data["student_id"] == enr.student_id


def test_create_invoice_uses_explicit_customer(client, gateways, finance, enroll):
    customer = {"name": "ACME LLC", "register": "1234567"}
    resp = _create(client, finance, enrollment_id=enroll().id, customer=customer)
    assert resp.status_code == 201
    assert gateways["qpay"].created[0].customer == customer


def test_golomt_invoice_carries_course_hint(client, gateways, finance, enroll, db):
    from app.models import Course

    enr = enroll()
    course = db.session.get(Course, enr.course_id)
    resp = _create(client, finance, provider="golomt", enrollment_id=enr.id)
    assert resp.status_code == 201
    assert resp.get_json()["sender_invoice_no"].startswith("AIAA-GO-")
    assert gateways["golomt"].created[0].extra == {
        "course_slug": course.slug, "course_title": course.title_mn,
    }


@pytest.mark.parametrize("fields, status, code", [
    ({"provider": "paypal"}, 400, "unsupported_provider"),
    ({"provider": None}, 400, "unsupported_provider"),
    ({"amount": "x"}, 400, "invalid_amount"),
    ({"amount": 0}, 400, "amount_must_be_positive"),
    ({"enrollment_id": 9999}, 404, "enrollment_not_found"),
    ({"student_id": 9999}, 404, "student_not_found"),
    ({"installment_id": 9999}, 404, "installment_not_found"),
])
def test_create_invoice_validation(client, db, gateways, finance, fields, status, code):
    from app.models import Invoice

    resp = _create(client, finance, **fields)
    assert resp.status_code == status
    assert resp.get_json()["error"] == code
    assert Invoice.query.count() == 0


def test_create_invoice_sandbox_refused_when_disabled(client, db, finance):
    # Uses the real registry: the service accepts the name, get_provider refuses it.
    resp = _create(client, finance, provider="sandbox")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "gateway_unsupported_provider"


def test_create_invoice_gateway_failure(client, db, gateways, finance):
    from app.models import Invoice

    gateways["qpay"].fail = PaymentGatewayError("qpay", "gateway_http_500",
                                                detail={"message": "down"})
    resp = _create(client, finance)
    assert resp.status_code == 502
    assert resp.get_json() == {"error": "gateway_gateway_http_500", "provider": "qpay",
                               "detail": {"message": "down"}}
    assert Invoice.query.count() == 0


# ============================================================= GET /admin/invoices
def test_list_invoices_with_filters(client, gateways, finance, enroll):
    enr = enroll()
    a = _create(client, finance, enrollment_id=enr.id).get_json()
    b = _create(client, finance, provider="storepay").get_json()
    c = _create(client, finance, provider="golomt", student_id=enr.student_id).get_json()
    gateways["qpay"].paid = True
    client.post(f"/admin/invoices/{a['id']}/check", headers=finance)

    def ids(query=""):
        resp = client.get(f"/admin/invoices{query}", headers=finance)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == len(data["invoices"])
        return [i["id"] for i in data["invoices"]]

    assert ids() == [c["id"], b["id"], a["id"]]  # newest first
    assert ids("?provider=storepay") == [b["id"]]
    assert ids("?status=paid") == [a["id"]]
    assert ids("?status=pending") == [c["id"], b["id"]]
    assert ids(f"?enrollment_id={enr.id}") == [a["id"]]
    assert ids(f"?student_id={enr.student_id}") == [c["id"], a["id"]]
    assert ids("?student_id=abc") == [c["id"], b["id"], a["id"]]  # non-numeric ignored
    assert ids("?limit=1") == [c["id"]]

    listed = client.get("/admin/invoices", headers=finance).get_json()["invoices"][0]
    assert "qr_text" not in listed


@pytest.mark.xfail(strict=True, raises=Exception,
                   reason="list_invoices/list_payments call int(limit) unguarded: "
                   "?limit=abc is a 500, not a 400")
def test_list_invoices_rejects_non_numeric_limit(client, finance):
    resp = client.get("/admin/invoices?limit=abc", headers=finance)
    assert resp.status_code == 400


# ======================================================= GET /admin/invoices/<id>
def test_get_invoice(client, gateways, finance):
    inv = _create(client, finance).get_json()
    resp = client.get(f"/admin/invoices/{inv['id']}", headers=finance)
    assert resp.status_code == 200
    assert resp.get_json()["sender_invoice_no"] == inv["sender_invoice_no"]
    assert resp.get_json()["qr_text"] == inv["qr_text"]


def test_get_invoice_not_found(client, finance):
    resp = client.get("/admin/invoices/9999", headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "invoice_not_found"


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
