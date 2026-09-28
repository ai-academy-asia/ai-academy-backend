"""Finance refunds: resolve a typed-in reference, then void receipt, return money, free seat."""
import itertools
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.ebarimt import EBarimtError, PosAPIClient
from app.models import (
    ClassroomRequest,
    EBarimtReceipt,
    Enrollment,
    Invoice,
    Payment,
    SeatBooking,
)

_seq = itertools.count(1)
DDTD_LEN = 33


# ----------------------------------------------------------------- helpers
class FakePosAPI:
    def __init__(self):
        self.created, self.returned = [], []
        self.fail = None

    def create_receipt(self, payload):
        if self.fail:
            raise self.fail
        self.created.append(payload)
        n = len(self.created)
        return {"id": str(n).rjust(DDTD_LEN, "8"), "lottery": f"ZZ {55500000 + n}",
                "qrData": f"REPL-{n}", "date": "2026-09-28 12:00:00"}

    def return_receipt(self, ebarimt_id, date=None):
        if self.fail:
            raise self.fail
        self.returned.append((ebarimt_id, date))
        return {}


@pytest.fixture
def posapi(app, monkeypatch):
    """Live mode against a stubbed PosAPI."""
    fake = FakePosAPI()
    monkeypatch.setitem(app.config, "EBARIMT_TEMP_MODE", False)
    monkeypatch.setattr(PosAPIClient, "create_receipt", lambda self, p: fake.create_receipt(p))
    monkeypatch.setattr(PosAPIClient, "return_receipt",
                        lambda self, i, date=None: fake.return_receipt(i, date=date))
    return fake


@pytest.fixture
def finance(make_staff):
    return make_staff("finance")[1]


@pytest.fixture
def sale(db, make_cohort):
    """``sale(receipt="issued"|"temp"|"failed"|"returned"|None, student_id=None)``.

    A settled public checkout (lead + paid seat) by default; with ``student_id``
    an enrolled student's invoice instead.
    """

    def _make(receipt="issued", amount=1_000_000, student_id=None):
        n = next(_seq)
        cohort = make_cohort()
        enrollment = None
        if student_id:
            enrollment = Enrollment(cohort_id=cohort.id, student_id=student_id,
                                    course_id=cohort.course_id, status="active")
            db.session.add(enrollment)
            db.session.flush()
        invoice = Invoice(provider="qpay", sender_invoice_no=f"AIAA-QP-R{n}", amount=amount,
                          status="paid", description="Corporate Leaders tuition",
                          student_id=student_id,
                          enrollment_id=enrollment.id if enrollment else None)
        payment = Payment(invoice=invoice, provider="qpay", provider_payment_id=f"TXN-R{n}",
                          amount=amount, status="paid", method="qr",
                          paid_at=datetime.utcnow())
        db.session.add_all([invoice, payment])
        db.session.flush()

        booking = request = None
        if not student_id:
            request = ClassroomRequest(course_id=cohort.course_id, name="Бат Дорж",
                                       email=f"buyer{n}@corp.test", phone_num="99112233",
                                       status="paid")
            booking = SeatBooking(request=request, cohort_id=cohort.id, number_of_seat=n,
                                  payment_token=f"pt_token{n}", status="paid",
                                  amount=amount, invoice_id=invoice.id,
                                  paid_at=datetime.utcnow())
            db.session.add_all([request, booking])

        rec = None
        if receipt:
            live = receipt != "temp"
            rec = EBarimtReceipt(
                payment_id=payment.id, invoice_id=invoice.id, type="B2C_RECEIPT",
                total_amount=amount, vat_amount=amount / 11, status=receipt,
                is_temp_mode=not live, district_code="3501", pos_no="TEST_POS",
                ebarimt_id=str(n).rjust(DDTD_LEN, "1") if live else None,
                lottery=f"HQ {92232000 + n}" if live else None,
                qr_data="QR" if live else None, issued_at=datetime(2026, 9, 1, 10, 30),
                raw={"request": {"receipts": [{"items": [{"name": "Tuition"}]}]},
                     "response": {"date": "2026-09-01 18:30:00"}},
            )
            db.session.add(rec)
        db.session.commit()
        return SimpleNamespace(
            payment_id=payment.id, invoice_id=invoice.id,
            receipt_id=rec.id if rec else None,
            ddtd=rec.ebarimt_id if rec else None, lottery=rec.lottery if rec else None,
            booking_id=booking.id if booking else None,
            request_id=request.id if request else None,
            token=booking.payment_token if booking else None,
            enrollment_id=enrollment.id if enrollment else None,
        )

    return _make


def _fresh(db, model, id_):
    db.session.expire_all()
    return db.session.get(model, id_)


# ----------------------------------------------------------------- auth
ENDPOINTS = [
    ("get", "/admin/refunds/lookup?ref=1"),
    ("post", "/admin/refunds"),
    ("post", "/admin/payments/1/refund"),
]


@pytest.mark.parametrize("method,url", ENDPOINTS)
def test_refund_endpoints_require_login(client, method, url):
    assert getattr(client, method)(url).status_code == 401


@pytest.mark.parametrize("method,url", ENDPOINTS)
def test_refund_endpoints_forbid_roles_without_payment_refund(client, make_staff, method, url):
    _, headers = make_staff("sales_enrollment")
    resp = getattr(client, method)(url, json={"payment_id": 1, "amount": 1}, headers=headers)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


def test_super_admin_may_refund(client, admin_headers, sale):
    s = sale(receipt=None)
    resp = client.post("/admin/refunds", json={"payment_id": s.payment_id, "amount": 1000},
                       headers=admin_headers)
    assert resp.status_code == 200


# ----------------------------------------------------------------- lookup
def test_lookup_by_lottery_shows_the_sale_and_changes_nothing(client, db, finance, sale):
    s = sale()
    resp = client.get("/admin/refunds/lookup", query_string={"ref": s.lottery}, headers=finance)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["payment"]["id"] == s.payment_id
    assert body["receipt"]["id"] == s.receipt_id
    assert body["invoice"] == {"id": s.invoice_id, "description": "Corporate Leaders tuition",
                               "status": "paid"}
    assert body["buyer"]["name"] == "Бат Дорж" and body["buyer"]["phone"] == "99112233"
    assert body["course"]["booking_status"] == "paid"
    assert body["refundable"] == 1_000_000 and body["refunded"] == 0

    assert _fresh(db, Payment, s.payment_id).status == "paid"
    assert _fresh(db, EBarimtReceipt, s.receipt_id).status == "issued"


@pytest.mark.parametrize("shape", ["digits", "no_space", "lowercase"])
def test_lookup_matches_lottery_however_typed(client, finance, sale, shape):
    s = sale()
    typed = {"digits": s.lottery.split()[1], "no_space": s.lottery.replace(" ", ""),
             "lowercase": s.lottery.lower()}[shape]
    resp = client.get("/admin/refunds/lookup", query_string={"ref": typed}, headers=finance)
    assert resp.status_code == 200
    assert resp.get_json()["payment"]["id"] == s.payment_id


def test_lookup_detects_ddtd(client, finance, sale):
    s = sale()
    resp = client.get("/admin/refunds/lookup", query_string={"ref": s.ddtd}, headers=finance)
    assert resp.get_json()["receipt"]["ebarimt_id"] == s.ddtd


def test_lookup_detects_payment_token(client, finance, sale):
    s = sale()
    resp = client.get("/admin/refunds/lookup", query_string={"ref": s.token}, headers=finance)
    assert resp.status_code == 200
    assert resp.get_json()["payment"]["id"] == s.payment_id


def test_lookup_reads_a_short_number_as_payment_id(client, finance, sale):
    sale()
    s = sale()
    resp = client.get("/admin/refunds/lookup", query_string={"ref": str(s.payment_id)},
                      headers=finance)
    assert resp.get_json()["payment"]["id"] == s.payment_id


@pytest.mark.parametrize("key", ["payment_id", "invoice_id", "receipt_id", "ebarimt_id"])
def test_lookup_by_explicit_key(client, finance, sale, key):
    sale()
    s = sale()
    value = {"payment_id": s.payment_id, "invoice_id": s.invoice_id,
             "receipt_id": s.receipt_id, "ebarimt_id": s.ddtd}[key]
    resp = client.get("/admin/refunds/lookup", query_string={key: value, "ref": "junk"},
                      headers=finance)
    assert resp.status_code == 200
    assert resp.get_json()["payment"]["id"] == s.payment_id


def test_lookup_of_an_enrolled_students_payment_has_no_buyer(client, finance, sale,
                                                             make_student):
    account, _ = make_student()
    s = sale(student_id=account.actor_id)
    body = client.get(f"/admin/refunds/lookup?payment_id={s.payment_id}",
                      headers=finance).get_json()
    assert body["buyer"] is None and body["course"] is None


def test_lookup_without_a_reference_is_400(client, finance):
    for url in ("/admin/refunds/lookup", "/admin/refunds/lookup?ref=%20%20", ):
        resp = client.get(url, headers=finance)
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["error"] == "refund_reference_required"
        assert "lottery" in body["accepts"]


def test_lookup_of_punctuation_only_is_400(client, finance):
    resp = client.get("/admin/refunds/lookup?ref=---", headers=finance)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "refund_reference_required"


def test_lookup_of_unknown_lottery_is_404(client, finance, sale):
    sale()
    resp = client.get("/admin/refunds/lookup?ref=XX%2011111111", headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "receipt_not_found"


def test_lookup_of_unknown_token_is_404(client, finance):
    resp = client.get("/admin/refunds/lookup?ref=pt_nope", headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "payment_token_not_found"


def test_lookup_of_unknown_payment_is_404(client, finance):
    resp = client.get("/admin/refunds/lookup?ref=999", headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "payment_not_found"


def test_lookup_of_invoice_without_payment_is_404(client, db, finance):
    invoice = Invoice(provider="qpay", sender_invoice_no="AIAA-QP-UNPAID", amount=5,
                      status="pending")
    db.session.add(invoice)
    db.session.commit()
    resp = client.get(f"/admin/refunds/lookup?invoice_id={invoice.id}", headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "payment_not_found"


def test_lookup_of_unpaid_booking_is_409(client, db, finance, make_cohort):
    cohort = make_cohort()
    request = ClassroomRequest(name="A", email="a@b.test", phone_num="1")
    db.session.add(SeatBooking(request=request, cohort_id=cohort.id, number_of_seat=1,
                               payment_token="pt_held", amount=10))
    db.session.commit()
    resp = client.get("/admin/refunds/lookup?ref=pt_held", headers=finance)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "booking_not_paid"


def test_lookup_of_an_ambiguous_lottery_is_409(client, db, finance, sale):
    a, b = sale(), sale()
    db.session.get(EBarimtReceipt, b.receipt_id).lottery = "QQ " + a.lottery.split()[1]
    db.session.commit()
    resp = client.get("/admin/refunds/lookup", query_string={"ref": a.lottery.split()[1]},
                      headers=finance)
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["error"] == "ambiguous_reference"
    assert sorted(body["receipt_ids"]) == sorted([a.receipt_id, b.receipt_id])


def test_lookup_of_a_receipt_without_payment_is_409(client, db, finance):
    receipt = EBarimtReceipt(total_amount=10, status="issued", is_temp_mode=False,
                             ebarimt_id="9" * DDTD_LEN)
    db.session.add(receipt)
    db.session.commit()
    resp = client.get(f"/admin/refunds/lookup?receipt_id={receipt.id}", headers=finance)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "receipt_has_no_payment"


# ----------------------------------------------------------------- full refund
def test_full_refund_voids_receipt_returns_money_and_frees_the_seat(
    client, db, finance, sale, posapi
):
    s = sale()
    resp = client.post("/admin/refunds", headers=finance, json={
        "payment_id": s.payment_id, "amount": 1_000_000, "reason": "Moved abroad",
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["steps"] == {"receipt": "returned", "payment": "refunded",
                             "replacement": "not_needed", "seat": "cancelled"}
    assert body["replacement_receipt"] is None
    assert body["seat_booking"]["status"] == "cancelled"
    assert posapi.returned == [(s.ddtd, "2026-09-01 18:30:00")]

    payment = _fresh(db, Payment, s.payment_id)
    assert payment.status == "refunded" and payment.refunded_amount == 1_000_000
    assert payment.refund_reason == "Moved abroad" and payment.refunded_at is not None
    assert db.session.get(EBarimtReceipt, s.receipt_id).status == "returned"
    assert db.session.get(SeatBooking, s.booking_id).status == "cancelled"
    assert db.session.get(ClassroomRequest, s.request_id).status == "abandoned"


def test_full_refund_cancels_the_enrollment_and_updates_the_ledger(
    client, db, finance, sale, make_student
):
    account, _ = make_student()
    s = sale(receipt="temp", student_id=account.actor_id)
    resp = client.post("/admin/refunds", json={"payment_id": s.payment_id, "amount": 1_000_000},
                       headers=finance)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["steps"]["receipt"] == "returned" and body["steps"]["seat"] == "none"
    assert body["enrollment"]["status"] == "cancelled"
    assert body["ledger"]["total_paid"] == 0
    assert _fresh(db, Enrollment, s.enrollment_id).status == "cancelled"


def test_refunding_twice_is_409(client, db, finance, sale, posapi):
    s = sale()
    client.post("/admin/refunds", json={"payment_id": s.payment_id, "amount": 1_000_000},
                headers=finance)
    resp = client.post("/admin/refunds", json={"payment_id": s.payment_id, "amount": 1_000_000},
                       headers=finance)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "already_refunded"
    assert len(posapi.returned) == 1


def test_refund_without_a_receipt(client, finance, sale):
    s = sale(receipt=None)
    body = client.post("/admin/refunds", json={"payment_id": s.payment_id, "amount": 1_000_000},
                       headers=finance).get_json()
    assert body["steps"]["receipt"] == "none" and body["steps"]["replacement"] == "none"
    assert body["receipt"] is None and body["payment"]["status"] == "refunded"


def test_refund_skips_a_receipt_posapi_never_accepted(client, db, finance, sale, posapi):
    s = sale(receipt="failed")
    body = client.post("/admin/refunds", json={"payment_id": s.payment_id, "amount": 1_000_000},
                       headers=finance).get_json()
    assert body["steps"]["receipt"] == "skipped_not_issued"
    assert posapi.returned == []
    assert _fresh(db, EBarimtReceipt, s.receipt_id).status == "failed"


def test_refund_can_keep_the_receipt_on_request(client, db, finance, sale, posapi):
    s = sale()
    body = client.post("/admin/refunds", headers=finance, json={
        "payment_id": s.payment_id, "amount": 1_000_000, "void_receipt": "false",
    }).get_json()
    assert body["steps"]["receipt"] == "kept" and body["steps"]["replacement"] == "none"
    assert posapi.returned == []
    assert _fresh(db, EBarimtReceipt, s.receipt_id).status == "issued"


def test_refund_retry_after_money_failed_skips_the_returned_receipt(
    client, db, finance, sale, posapi
):
    s = sale(receipt="returned")
    body = client.post("/admin/refunds", json={"payment_id": s.payment_id, "amount": 1_000_000},
                       headers=finance).get_json()
    assert body["steps"]["receipt"] == "already_returned"
    assert body["steps"]["payment"] == "refunded"
    assert posapi.returned == []


def test_posapi_failure_leaves_money_and_seat_untouched(client, db, finance, sale, posapi):
    posapi.fail = EBarimtError("posapi_unreachable", retriable=True)
    s = sale()
    resp = client.post("/admin/refunds", json={"payment_id": s.payment_id, "amount": 1_000_000},
                       headers=finance)
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "ebarimt_posapi_unreachable"
    assert _fresh(db, Payment, s.payment_id).status == "paid"
    assert db.session.get(EBarimtReceipt, s.receipt_id).status == "issued"
    assert db.session.get(SeatBooking, s.booking_id).status == "paid"


# ----------------------------------------------------------------- partial refund
def test_partial_refund_replaces_the_receipt_for_what_was_kept(
    client, db, finance, sale, posapi
):
    s = sale()
    resp = client.post("/admin/refunds", json={"payment_id": s.payment_id, "amount": 400_000},
                       headers=finance)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["steps"] == {"receipt": "returned", "payment": "partially_refunded",
                             "replacement": "issued", "seat": "kept"}
    repl = body["replacement_receipt"]
    assert repl["replaces_receipt_id"] == s.receipt_id
    assert repl["total_amount"] == 600_000 and repl["status"] == "issued"
    assert posapi.created[0]["totalAmount"] == 600_000
    assert posapi.created[0]["receipts"][0]["items"][0]["name"] == "Tuition"

    payment = _fresh(db, Payment, s.payment_id)
    assert payment.status == "partially_refunded" and payment.refunded_amount == 400_000
    assert db.session.get(EBarimtReceipt, s.receipt_id).status == "returned"
    assert db.session.get(SeatBooking, s.booking_id).status == "paid"


def test_partial_refund_by_attendance_returns_half(client, db, finance, sale):
    s = sale(receipt="temp")
    body = client.post("/admin/refunds", json={"payment_id": s.payment_id, "pct_attended": 10},
                       headers=finance).get_json()
    assert body["payment"]["refunded_amount"] == 500_000
    assert body["payment"]["refund_pct_attended"] == 10
    repl = body["replacement_receipt"]
    assert repl["total_amount"] == 500_000 and repl["status"] == "temp"
    assert repl["replaces_receipt_id"] == s.receipt_id


def test_retrying_a_partial_refund_reuses_the_replacement(client, db, finance, sale, posapi):
    s = sale()
    payload = {"payment_id": s.payment_id, "amount": 400_000}
    first = client.post("/admin/refunds", json=payload, headers=finance).get_json()
    again = client.post("/admin/refunds", json=payload, headers=finance)
    assert again.status_code == 200
    body = again.get_json()
    assert body["steps"]["receipt"] == "already_corrected"
    assert body["steps"]["replacement"] == "reused"
    assert body["replacement_receipt"]["id"] == first["replacement_receipt"]["id"]
    assert len(posapi.created) == 1 and len(posapi.returned) == 1
    assert EBarimtReceipt.query.count() == 2


def test_attendance_over_threshold_refunds_nothing(client, db, finance, sale, posapi):
    s = sale()
    resp = client.post("/admin/refunds", json={"payment_id": s.payment_id, "pct_attended": 50},
                       headers=finance)
    assert resp.status_code == 409 and resp.get_json()["error"] == "nothing_to_refund"
    assert _fresh(db, Payment, s.payment_id).status == "paid"
    assert posapi.returned == []


def test_refunding_the_offered_full_amount_completes_a_partial_refund(client, db, finance, sale):
    s = sale(receipt="temp")
    client.post("/admin/refunds", json={"payment_id": s.payment_id, "amount": 300_000},
                headers=finance)
    lookup = client.get(f"/admin/refunds/lookup?payment_id={s.payment_id}",
                        headers=finance).get_json()
    assert lookup["refundable"] == 700_000 and lookup["full_refund_amount"] == 1_000_000
    client.post("/admin/refunds", json={"payment_id": s.payment_id,
                                        "amount": lookup["full_refund_amount"]}, headers=finance)
    payment = _fresh(db, Payment, s.payment_id)
    assert payment.status == "refunded" and payment.refunded_amount == 1_000_000


def test_refund_amount_below_what_was_already_returned_is_rejected(client, db, finance, sale):
    s = sale(receipt="temp")
    client.post("/admin/refunds", json={"payment_id": s.payment_id, "amount": 300_000},
                headers=finance)
    resp = client.post("/admin/refunds", json={"payment_id": s.payment_id, "amount": 100_000},
                       headers=finance)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "refund_below_already_refunded"
    assert _fresh(db, Payment, s.payment_id).refunded_amount == 300_000


# ----------------------------------------------------------------- validation
@pytest.mark.parametrize("extra,code", [
    ({}, "refund_basis_required"),
    ({"amount": 2_000_000}, "refund_exceeds_payment"),
    ({"amount": "lots"}, "invalid_amount"),
    ({"amount": 0}, "amount_must_be_positive"),
    ({"pct_attended": "half"}, "invalid_number"),
])
def test_bad_refund_body_is_rejected_before_the_receipt_is_voided(
    client, db, finance, sale, posapi, extra, code
):
    s = sale()
    resp = client.post("/admin/refunds", json={"payment_id": s.payment_id, **extra},
                       headers=finance)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == code
    assert posapi.returned == []
    assert _fresh(db, EBarimtReceipt, s.receipt_id).status == "issued"
    assert db.session.get(Payment, s.payment_id).status == "paid"


def test_refund_without_a_reference_is_400(client, finance):
    resp = client.post("/admin/refunds", json={"amount": 10}, headers=finance)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "refund_reference_required"


def test_refund_of_unknown_payment_is_404(client, finance):
    resp = client.post("/admin/refunds", json={"payment_id": 999, "amount": 10},
                       headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "payment_not_found"


# ----------------------------------------------------------------- reference keys
@pytest.mark.parametrize("key", [
    "payment_id", "payment_token", "invoice_id", "receipt_id", "ebarimt_id", "lottery",
    "ref_lottery", "ref_ddtd", "ref_token",
])
def test_refund_accepts_every_reference(client, db, finance, sale, key):
    sale(receipt="temp")
    s = sale()
    ref = {
        "payment_id": {"payment_id": s.payment_id},
        "payment_token": {"payment_token": s.token},
        "invoice_id": {"invoice_id": s.invoice_id},
        "receipt_id": {"receipt_id": s.receipt_id},
        "ebarimt_id": {"ebarimt_id": s.ddtd},
        "lottery": {"lottery": s.lottery},
        "ref_lottery": {"ref": s.lottery.split()[1]},
        "ref_ddtd": {"ref": s.ddtd},
        "ref_token": {"ref": s.token},
    }[key]
    resp = client.post("/admin/refunds", json={**ref, "amount": 1_000_000,
                                               "void_receipt": False}, headers=finance)
    assert resp.status_code == 200
    assert resp.get_json()["payment"]["id"] == s.payment_id
    assert _fresh(db, Payment, s.payment_id).status == "refunded"


def test_explicit_reference_beats_ref(client, db, finance, sale):
    a, b = sale(receipt=None), sale(receipt=None)
    body = client.post("/admin/refunds", headers=finance, json={
        "payment_id": b.payment_id, "ref": str(a.payment_id), "amount": 10,
    }).get_json()
    assert body["payment"]["id"] == b.payment_id
    assert _fresh(db, Payment, a.payment_id).status == "paid"


# ----------------------------------------------------------------- by payment id
def test_refund_by_payment_path(client, db, finance, sale, posapi):
    s = sale()
    resp = client.post(f"/admin/payments/{s.payment_id}/refund", json={"pct_attended": 5},
                       headers=finance)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["steps"]["payment"] == "partially_refunded"
    assert body["replacement_receipt"]["total_amount"] == 500_000
    assert _fresh(db, Payment, s.payment_id).refunded_amount == 500_000


def test_refund_by_payment_path_ignores_other_references(client, db, finance, sale):
    a, b = sale(receipt=None), sale(receipt=None)
    resp = client.post(f"/admin/payments/{a.payment_id}/refund",
                       json={"payment_id": b.payment_id, "amount": 1_000_000}, headers=finance)
    assert resp.get_json()["payment"]["id"] == a.payment_id
    assert _fresh(db, Payment, b.payment_id).status == "paid"


def test_refund_by_payment_path_unknown_is_404(client, finance):
    resp = client.post("/admin/payments/999/refund", json={"amount": 10}, headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "payment_not_found"
