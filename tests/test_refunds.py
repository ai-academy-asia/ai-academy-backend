"""Finance refunds: access control and resolving a typed-in reference."""
import pytest
import refund_helpers
from refund_helpers import DDTD_LEN, _fresh

from app.models import ClassroomRequest, EBarimtReceipt, Invoice, Payment, SeatBooking

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
finance = refund_helpers.finance
sale = refund_helpers.sale


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
