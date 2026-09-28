"""Finance eBarimt receipt admin: access control, reads and issuing."""
import ebarimt_helpers
import pytest
from ebarimt_helpers import DDTD_LEN, _fresh, _payment, _receipt

from app.ebarimt import EBarimtError
from app.models import EBarimtReceipt

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
finance = ebarimt_helpers.finance
posapi = ebarimt_helpers.posapi
sales = ebarimt_helpers.sales


# ----------------------------------------------------------------- auth
ENDPOINTS = [
    ("get", "/admin/ebarimt"),
    ("get", "/admin/ebarimt/summary"),
    ("get", "/admin/ebarimt/1"),
    ("post", "/admin/ebarimt/issue"),
    ("post", "/admin/ebarimt/1/email"),
    ("post", "/admin/ebarimt/send-data"),
    ("get", "/admin/ebarimt/1/qr"),
    ("post", "/admin/ebarimt/1/reissue"),
    ("post", "/admin/ebarimt/reissue-all"),
    ("post", "/admin/ebarimt/1/return"),
]


@pytest.mark.parametrize("method,url", ENDPOINTS)
def test_ebarimt_endpoints_require_login(client, method, url):
    resp = getattr(client, method)(url)
    assert resp.status_code == 401


@pytest.mark.parametrize("method,url", ENDPOINTS)
def test_ebarimt_endpoints_forbid_roles_without_ebarimt_manage(client, sales, method, url):
    resp = getattr(client, method)(url, headers=sales)
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


def test_students_cannot_manage_receipts(client, make_student):
    _, headers = make_student()
    assert client.get("/admin/ebarimt", headers=headers).status_code == 403


# ----------------------------------------------------------------- reads
def test_list_filters_by_status_temp_and_payment(client, db, finance):
    pid = _payment(db)
    temp_id = _receipt(db, pid)
    issued_id = _receipt(db, _payment(db), status="issued")
    returned_id = _receipt(db, _payment(db), status="returned")

    body = client.get("/admin/ebarimt", headers=finance).get_json()
    assert body["count"] == 3
    assert [r["id"] for r in body["receipts"]] == [returned_id, issued_id, temp_id]

    by_status = client.get("/admin/ebarimt?status=issued", headers=finance).get_json()
    assert [r["id"] for r in by_status["receipts"]] == [issued_id]
    temp = client.get("/admin/ebarimt?temp=true", headers=finance).get_json()
    assert [r["id"] for r in temp["receipts"]] == [temp_id]
    live = client.get("/admin/ebarimt?temp=false", headers=finance).get_json()
    assert {r["id"] for r in live["receipts"]} == {issued_id, returned_id}
    by_payment = client.get(f"/admin/ebarimt?payment_id={pid}", headers=finance).get_json()
    assert [r["id"] for r in by_payment["receipts"]] == [temp_id]
    limited = client.get("/admin/ebarimt?limit=1", headers=finance).get_json()
    assert limited["count"] == 1


def test_list_ignores_a_non_numeric_payment_id(client, db, finance):
    _receipt(db, _payment(db))
    body = client.get("/admin/ebarimt?payment_id=abc", headers=finance).get_json()
    assert body["count"] == 1


def test_summary_counts_by_status(client, db, finance):
    _receipt(db, _payment(db))
    _receipt(db, _payment(db))
    _receipt(db, _payment(db), status="issued")

    body = client.get("/admin/ebarimt/summary", headers=finance).get_json()
    assert body == {
        "temp_mode": True, "auto_issue": True,
        "counts": {"temp": 2, "issued": 1}, "pending_reissue": 2,
    }


def test_summary_on_an_empty_table(client, admin_headers):
    body = client.get("/admin/ebarimt/summary", headers=admin_headers).get_json()
    assert body["counts"] == {} and body["pending_reissue"] == 0


def test_get_receipt(client, db, finance):
    rid = _receipt(db, _payment(db), status="issued")
    resp = client.get(f"/admin/ebarimt/{rid}", headers=finance)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == rid and body["status"] == "issued"
    assert len(body["ebarimt_id"]) == DDTD_LEN


def test_get_unknown_receipt_is_404(client, finance):
    resp = client.get("/admin/ebarimt/999", headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "receipt_not_found"


# ----------------------------------------------------------------- issue
def test_issue_requires_payment_id(client, finance):
    resp = client.post("/admin/ebarimt/issue", json={}, headers=finance)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "payment_id_required"


def test_issue_for_unknown_payment_is_404(client, finance):
    resp = client.post("/admin/ebarimt/issue", json={"payment_id": 999}, headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "payment_not_found"


def test_issue_in_temp_mode_stores_payload_without_calling_posapi(client, db, finance):
    pid = _payment(db, amount=1_100_000)
    resp = client.post("/admin/ebarimt/issue", json={"payment_id": pid}, headers=finance)
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "temp" and body["is_temp_mode"] is True
    assert body["type"] == "B2C_RECEIPT" and body["ebarimt_id"] is None
    assert body["total_amount"] == 1_100_000 and body["vat_amount"] == 100_000

    raw = _fresh(db, EBarimtReceipt, body["id"]).raw
    assert raw["type"] == "B2C_RECEIPT" and "customerTin" not in raw
    assert raw["receipts"][0]["items"][0]["name"] == "Corporate Leaders tuition"
    assert raw["payments"][0]["code"] == "BANK_TRANSFER_QPAY"


def test_issue_is_idempotent_per_payment(client, db, finance):
    pid = _payment(db)
    first = client.post("/admin/ebarimt/issue", json={"payment_id": pid}, headers=finance)
    again = client.post("/admin/ebarimt/issue", json={"payment_id": pid}, headers=finance)
    assert again.get_json()["id"] == first.get_json()["id"]
    assert EBarimtReceipt.query.count() == 1


def test_issue_rejects_unknown_receipt_type(client, db, finance):
    pid = _payment(db)
    resp = client.post("/admin/ebarimt/issue", json={"payment_id": pid, "type": "B2G"},
                       headers=finance)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_receipt_type"


def test_b2b_issue_requires_customer_register(client, db, finance):
    pid = _payment(db)
    resp = client.post("/admin/ebarimt/issue", json={"payment_id": pid, "type": "B2B_RECEIPT"},
                       headers=finance)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "customer_register_required"
    assert EBarimtReceipt.query.count() == 0


def test_b2b_issue_carries_customer_tin(client, db, finance):
    pid = _payment(db)
    resp = client.post("/admin/ebarimt/issue", headers=finance, json={
        "payment_id": pid, "type": "B2B_RECEIPT", "customer_register": "12345678901",
        "description": "Corporate seat x1",
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["type"] == "B2B_RECEIPT" and body["customer_register"] == "12345678901"
    raw = _fresh(db, EBarimtReceipt, body["id"]).raw
    assert raw["customerTin"] == "12345678901"
    assert raw["receipts"][0]["items"][0]["name"] == "Corporate seat x1"


def test_issue_in_live_mode_stamps_ddtd_lottery_and_qr(client, db, finance, posapi):
    pid = _payment(db)
    resp = client.post("/admin/ebarimt/issue", json={"payment_id": pid}, headers=finance)
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "issued" and body["is_temp_mode"] is False
    assert len(body["ebarimt_id"]) == DDTD_LEN
    assert body["lottery"] == "HQ 92232001" and body["qr_data"]
    # PosAPI's Ulaanbaatar clock (18:30 local) is stored as UTC.
    assert body["issued_at"].startswith("2026-09-01T10:30:00")
    assert len(posapi.created) == 1


def test_issue_in_live_mode_surfaces_posapi_failure(client, db, finance, posapi):
    posapi.fail = EBarimtError("posapi_unreachable", retriable=True)
    pid = _payment(db)
    resp = client.post("/admin/ebarimt/issue", json={"payment_id": pid}, headers=finance)
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "ebarimt_posapi_unreachable"
    assert EBarimtReceipt.query.count() == 0


def test_issue_in_live_mode_rejected_receipt_is_502(client, db, finance, posapi):
    posapi.fail = EBarimtError("posapi_http_400", detail={"message": "ТТД бүртгэлгүй"})
    pid = _payment(db)
    resp = client.post("/admin/ebarimt/issue", json={"payment_id": pid}, headers=finance)
    assert resp.status_code == 502
    body = resp.get_json()
    assert body["error"] == "ebarimt_posapi_http_400"
    assert body["detail"] == {"message": "ТТД бүртгэлгүй"}


def test_issue_in_live_mode_without_ddtd_is_502(client, db, finance, posapi):
    posapi.no_ddtd = True
    pid = _payment(db)
    resp = client.post("/admin/ebarimt/issue", json={"payment_id": pid}, headers=finance)
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "ebarimt_no_ddtd"
    assert EBarimtReceipt.query.count() == 0
