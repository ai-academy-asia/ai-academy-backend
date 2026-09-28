"""Finance refunds: full and partial refunds — void receipt, return money, free seat."""
import refund_helpers
from refund_helpers import _fresh

from app.ebarimt import EBarimtError
from app.models import ClassroomRequest, EBarimtReceipt, Enrollment, Payment, SeatBooking

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
finance = refund_helpers.finance
posapi = refund_helpers.posapi
sale = refund_helpers.sale


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
