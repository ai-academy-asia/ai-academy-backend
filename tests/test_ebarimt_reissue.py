"""Finance eBarimt receipt admin: reissuing temp receipts and voiding receipts."""
import ebarimt_helpers
from ebarimt_helpers import DDTD_LEN, _fresh, _payment, _receipt

from app.ebarimt import EBarimtError, PosAPIClient
from app.models import EBarimtReceipt

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
finance = ebarimt_helpers.finance
posapi = ebarimt_helpers.posapi


# ----------------------------------------------------------------- reissue
def test_reissue_refused_while_still_in_temp_mode(client, db, finance):
    rid = _receipt(db, _payment(db))
    resp = client.post(f"/admin/ebarimt/{rid}/reissue", headers=finance)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "still_in_temp_mode"


def test_reissue_refused_for_an_issued_receipt(client, db, finance, posapi):
    rid = _receipt(db, _payment(db), status="issued")
    resp = client.post(f"/admin/ebarimt/{rid}/reissue", headers=finance)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "already_issued"
    assert posapi.created == []


def test_reissue_replays_a_temp_receipt_to_posapi(client, db, finance, posapi):
    rid = _receipt(db, _payment(db))
    resp = client.post(f"/admin/ebarimt/{rid}/reissue", headers=finance)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == rid and body["status"] == "issued"
    assert body["is_temp_mode"] is False and len(body["ebarimt_id"]) == DDTD_LEN
    sent = posapi.created[0]
    assert sent["receipts"][0]["items"][0]["barCodeType"] == "UNDEFINED"
    assert sent["receipts"][0]["items"][0]["name"] == "Stored description"


def test_reissue_failure_leaves_the_receipt_temp(client, db, finance, posapi):
    posapi.fail = EBarimtError("posapi_http_500")
    rid = _receipt(db, _payment(db))
    resp = client.post(f"/admin/ebarimt/{rid}/reissue", headers=finance)
    assert resp.status_code == 502
    assert _fresh(db, EBarimtReceipt, rid).status == "temp"


def test_reissue_unknown_receipt_is_404(client, finance, posapi):
    assert client.post("/admin/ebarimt/999/reissue", headers=finance).status_code == 404


def test_reissue_all_refused_in_temp_mode(client, finance):
    resp = client.post("/admin/ebarimt/reissue-all", json={}, headers=finance)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "still_in_temp_mode"


def test_reissue_all_replays_temp_receipts_and_reports_failures(
    client, db, finance, posapi, monkeypatch
):
    ok_id = _receipt(db, _payment(db))
    bad_id = _receipt(db, _payment(db), total_amount=2_000_000)
    _receipt(db, _payment(db), status="issued")

    def _create(self, payload):
        if payload["totalAmount"] == 2_000_000:
            raise EBarimtError("posapi_http_400")
        return posapi.create_receipt(payload)

    monkeypatch.setattr(PosAPIClient, "create_receipt", _create)
    resp = client.post("/admin/ebarimt/reissue-all", json={}, headers=finance)
    assert resp.status_code == 200
    assert resp.get_json() == {
        "candidates": 2, "issued": 1,
        "failed": [{"receipt_id": bad_id, "error": "ebarimt_posapi_http_400"}],
    }
    assert _fresh(db, EBarimtReceipt, ok_id).status == "issued"
    assert _fresh(db, EBarimtReceipt, bad_id).status == "temp"


def test_reissue_all_honours_limit(client, db, finance, posapi):
    for _ in range(3):
        _receipt(db, _payment(db))
    body = client.post("/admin/ebarimt/reissue-all", json={"limit": 2},
                       headers=finance).get_json()
    assert body["candidates"] == 2 and body["issued"] == 2
    assert EBarimtReceipt.query.filter_by(status="temp").count() == 1


# ----------------------------------------------------------------- return
def test_return_voids_a_temp_receipt_locally(client, db, finance, posapi):
    rid = _receipt(db, _payment(db))
    resp = client.post(f"/admin/ebarimt/{rid}/return", headers=finance)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "returned" and body["returned_at"]
    assert posapi.returned == []


def test_return_voids_an_issued_receipt_at_posapi(client, db, finance, posapi):
    rid = _receipt(db, _payment(db), status="issued")
    resp = client.post(f"/admin/ebarimt/{rid}/return", headers=finance)
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "returned"
    ddtd = _fresh(db, EBarimtReceipt, rid).ebarimt_id
    # Dated by PosAPI's own stamp, not our UTC clock.
    assert posapi.returned == [(ddtd, "2026-09-01 18:30:00")]


def test_return_falls_back_to_local_time_of_issue(client, db, finance, posapi):
    rid = _receipt(db, _payment(db), status="issued", raw={})
    client.post(f"/admin/ebarimt/{rid}/return", headers=finance)
    # issued_at is 10:30 UTC -> 18:30 in Ulaanbaatar.
    assert posapi.returned[0][1] == "2026-09-01 18:30:00"


def test_return_twice_is_409(client, db, finance, posapi):
    rid = _receipt(db, _payment(db), status="returned")
    resp = client.post(f"/admin/ebarimt/{rid}/return", headers=finance)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "already_returned"
    assert posapi.returned == []


def test_return_posapi_failure_keeps_the_receipt_issued(client, db, finance, posapi):
    posapi.fail = EBarimtError("posapi_http_500", detail={"message": "UNIQUE constraint failed"})
    rid = _receipt(db, _payment(db), status="issued")
    resp = client.post(f"/admin/ebarimt/{rid}/return", headers=finance)
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "ebarimt_posapi_http_500"
    assert _fresh(db, EBarimtReceipt, rid).status == "issued"


def test_return_unknown_receipt_is_404(client, finance):
    assert client.post("/admin/ebarimt/999/return", headers=finance).status_code == 404


def test_issue_with_a_non_numeric_payment_id_is_404(client, finance):
    resp = client.post("/admin/ebarimt/issue", json={"payment_id": "abc"}, headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "payment_not_found"
