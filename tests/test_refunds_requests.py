"""Finance refunds: body validation, reference keys and the by-payment-id path."""
import pytest
import refund_helpers
from refund_helpers import _fresh

from app.models import EBarimtReceipt, Payment

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
finance = refund_helpers.finance
posapi = refund_helpers.posapi
sale = refund_helpers.sale


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
