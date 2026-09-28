"""Finance eBarimt receipt admin: list, issue, email, sync, QR, reissue and void."""
import itertools
from datetime import datetime
from decimal import Decimal

import pytest

from app.ebarimt import EBarimtError, PosAPIClient
from app.models import EBarimtReceipt, Invoice, Payment

_seq = itertools.count(1)
DDTD_LEN = 33


# ----------------------------------------------------------------- helpers
class FakePosAPI:
    """Records every PosAPI call; ``fail`` makes the next call raise it."""

    def __init__(self):
        self.created, self.returned = [], []
        self.sent = 0
        self.fail = None
        self.info_fail = None
        self.no_ddtd = False

    def create_receipt(self, payload):
        if self.fail:
            raise self.fail
        self.created.append(payload)
        if self.no_ddtd:
            return {"lottery": "HQ 00000000"}
        n = len(self.created)
        return {
            "id": str(n).rjust(DDTD_LEN, "7"), "lottery": f"HQ {92232000 + n}",
            "qrData": f"QRDATA-{n}" * 10, "date": "2026-09-01 18:30:00",
        }

    def return_receipt(self, ebarimt_id, date=None):
        if self.fail:
            raise self.fail
        self.returned.append((ebarimt_id, date))
        return {}

    def send_data(self):
        if self.fail:
            raise self.fail
        self.sent += 1
        return {}

    def info(self):
        if self.info_fail:
            raise self.info_fail
        return {"lastSentDate": "2026-09-28 10:00:00", "leftLotteries": 9000,
                "merchants": [{"tin": "TEST_TIN"}]}


@pytest.fixture
def posapi(app, monkeypatch):
    """Live mode against a stubbed PosAPI."""
    fake = FakePosAPI()
    monkeypatch.setitem(app.config, "EBARIMT_TEMP_MODE", False)
    monkeypatch.setattr(PosAPIClient, "create_receipt", lambda self, p: fake.create_receipt(p))
    monkeypatch.setattr(PosAPIClient, "return_receipt",
                        lambda self, i, date=None: fake.return_receipt(i, date=date))
    monkeypatch.setattr(PosAPIClient, "send_data", lambda self: fake.send_data())
    monkeypatch.setattr(PosAPIClient, "info", lambda self: fake.info())
    return fake


@pytest.fixture
def mailbox(app, monkeypatch):
    sent = []
    monkeypatch.setitem(app.config, "MAIL_HOST", "smtp.test")
    monkeypatch.setattr("app.mail.send_message", sent.append)
    return sent


@pytest.fixture
def finance(make_staff):
    return make_staff("finance")[1]


@pytest.fixture
def sales(make_staff):
    return make_staff("sales_enrollment")[1]


def _payment(db, amount=1_000_000, student_id=None, method="qr"):
    n = next(_seq)
    invoice = Invoice(provider="qpay", sender_invoice_no=f"AIAA-QP-E{n}", amount=amount,
                      status="paid", description="Corporate Leaders tuition",
                      student_id=student_id)
    payment = Payment(invoice=invoice, provider="qpay", provider_payment_id=f"TXN-E{n}",
                      amount=amount, status="paid", method=method, paid_at=datetime.utcnow())
    db.session.add_all([invoice, payment])
    db.session.commit()
    return payment.id


def _receipt(db, payment_id=None, status="temp", amount=1_000_000, **fields):
    """A receipt row: ``status`` temp (no DDTD) or issued (DDTD/lottery/QR)."""
    n = next(_seq)
    invoice_id = db.session.get(Payment, payment_id).invoice_id if payment_id else None
    values = {
        "payment_id": payment_id, "invoice_id": invoice_id, "type": "B2C_RECEIPT",
        "total_amount": amount, "vat_amount": Decimal(amount) / 11, "status": status,
        "is_temp_mode": status == "temp", "district_code": "3501", "pos_no": "TEST_POS",
        "raw": {"receipts": [{"items": [{"name": "Stored description"}]}]},
    }
    if status != "temp":
        values.update(
            ebarimt_id=str(n).rjust(DDTD_LEN, "1"), lottery=f"HQ {10000000 + n}",
            qr_data=f"QR-{n}" * 20, issued_at=datetime(2026, 9, 1, 10, 30),
            raw={"request": {"receipts": [{"items": [{"name": "Tuition"}]}]},
                 "response": {"date": "2026-09-01 18:30:00"}},
        )
    values.update(fields)
    receipt = EBarimtReceipt(**values)
    db.session.add(receipt)
    db.session.commit()
    return receipt.id


def _fresh(db, model, id_):
    db.session.expire_all()
    return db.session.get(model, id_)


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


# ----------------------------------------------------------------- email
def test_email_refuses_temp_receipts(client, db, finance, mailbox):
    rid = _receipt(db, _payment(db))
    resp = client.post(f"/admin/ebarimt/{rid}/email", json={}, headers=finance)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "receipt_not_issued"
    assert mailbox == []


def test_email_needs_mail_configured(client, db, finance):
    rid = _receipt(db, _payment(db), status="issued")
    resp = client.post(f"/admin/ebarimt/{rid}/email", json={}, headers=finance)
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "mail_not_configured"


def test_email_goes_to_the_paying_student(client, db, finance, mailbox, make_student):
    account, _ = make_student(email="payer@student.test")
    rid = _receipt(db, _payment(db, student_id=account.actor_id), status="issued")

    resp = client.post(f"/admin/ebarimt/{rid}/email", json={}, headers=finance)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["sent"] is True and body["to"] == "payer@student.test"
    assert len(mailbox) == 1 and mailbox[0]["To"] == "payer@student.test"
    receipt = _fresh(db, EBarimtReceipt, rid)
    assert receipt.emailed_to == "payer@student.test" and receipt.emailed_at is not None


def test_email_to_an_explicit_address(client, db, finance, mailbox):
    rid = _receipt(db, _payment(db), status="issued")
    resp = client.post(f"/admin/ebarimt/{rid}/email", json={"to": "copy@corp.test"},
                       headers=finance)
    assert resp.status_code == 200
    assert resp.get_json()["to"] == "copy@corp.test"
    assert mailbox[0]["To"] == "copy@corp.test"


def test_email_without_a_recipient_is_422(client, db, finance, mailbox):
    rid = _receipt(db, _payment(db), status="issued")
    resp = client.post(f"/admin/ebarimt/{rid}/email", json={}, headers=finance)
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "no_recipient_email"


def test_email_transport_failure_is_recorded(client, db, finance, app, monkeypatch):
    from app.mail import MailError

    def _fail(msg):
        raise MailError("SMTPServerDisconnected: gone")

    monkeypatch.setitem(app.config, "MAIL_HOST", "smtp.test")
    monkeypatch.setattr("app.mail.send_message", _fail)
    rid = _receipt(db, _payment(db), status="issued")

    resp = client.post(f"/admin/ebarimt/{rid}/email", json={"to": "x@y.test"}, headers=finance)
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "mail_send_failed"
    receipt = _fresh(db, EBarimtReceipt, rid)
    assert "SMTPServerDisconnected" in receipt.email_error and receipt.emailed_at is None


def test_email_unknown_receipt_is_404(client, finance):
    resp = client.post("/admin/ebarimt/999/email", json={}, headers=finance)
    assert resp.status_code == 404


# ----------------------------------------------------------------- send-data
def test_send_data_flushes_and_reports_last_sent(client, finance, posapi):
    resp = client.post("/admin/ebarimt/send-data", headers=finance)
    assert resp.status_code == 200
    assert resp.get_json() == {
        "sent": True, "last_sent_date": "2026-09-28 10:00:00",
        "left_lotteries": 9000, "merchants": ["TEST_TIN"],
    }
    assert posapi.sent == 1


def test_send_data_survives_a_failed_info_read_back(client, finance, posapi):
    posapi.info_fail = EBarimtError("posapi_unreachable", retriable=True)
    body = client.post("/admin/ebarimt/send-data", headers=finance).get_json()
    assert body == {"sent": True, "last_sent_date": None, "left_lotteries": None,
                    "merchants": []}


def test_send_data_failure_is_503(client, finance, posapi):
    posapi.fail = EBarimtError("posapi_unreachable", retriable=True)
    resp = client.post("/admin/ebarimt/send-data", headers=finance)
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "ebarimt_posapi_unreachable"


# ----------------------------------------------------------------- QR
def test_qr_is_404_for_a_temp_receipt(client, db, finance):
    rid = _receipt(db, _payment(db))
    resp = client.get(f"/admin/ebarimt/{rid}/qr", headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "receipt_has_no_qr"


def test_qr_renders_png_by_default(client, db, finance):
    rid = _receipt(db, _payment(db), status="issued")
    resp = client.get(f"/admin/ebarimt/{rid}/qr", headers=finance)
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
    assert resp.data.startswith(b"\x89PNG")
    ddtd = _fresh(db, EBarimtReceipt, rid).ebarimt_id
    assert f'filename="ebarimt-{ddtd}.png"' in resp.headers["Content-Disposition"]


def test_qr_renders_svg(client, db, finance):
    rid = _receipt(db, _payment(db), status="issued")
    resp = client.get(f"/admin/ebarimt/{rid}/qr?format=SVG", headers=finance)
    assert resp.status_code == 200
    assert resp.mimetype == "image/svg+xml"
    assert b"<svg" in resp.data


def test_qr_rejects_unknown_format(client, db, finance):
    rid = _receipt(db, _payment(db), status="issued")
    resp = client.get(f"/admin/ebarimt/{rid}/qr?format=gif", headers=finance)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_format"


def test_qr_rejects_non_numeric_scale(client, db, finance):
    rid = _receipt(db, _payment(db), status="issued")
    resp = client.get(f"/admin/ebarimt/{rid}/qr?scale=big", headers=finance)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_scale"


def test_qr_scale_is_clamped(client, db, finance):
    rid = _receipt(db, _payment(db), status="issued")

    def png(scale):
        return client.get(f"/admin/ebarimt/{rid}/qr?scale={scale}", headers=finance).data

    assert png(500) == png(20)
    assert png(0) == png(1)
    assert png(1) != png(20)


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


@pytest.mark.xfail(strict=True, reason=(
    "get_payment passes the raw value to db.session.get, so a non-numeric id hits "
    "Postgres and 500s with DataError (app/services/payments.py:467)"))
def test_issue_with_a_non_numeric_payment_id_is_404(client, finance):
    resp = client.post("/admin/ebarimt/issue", json={"payment_id": "abc"}, headers=finance)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "payment_not_found"
