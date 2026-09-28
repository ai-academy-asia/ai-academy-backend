"""Finance eBarimt receipt admin: email, send-data and the QR image."""
import ebarimt_helpers
from ebarimt_helpers import _fresh, _payment, _receipt

from app.ebarimt import EBarimtError
from app.models import EBarimtReceipt

# Shared fixtures, bound by name so pytest finds them in this module (an
# import would read as unused and then shadowed by the test argument).
finance = ebarimt_helpers.finance
mailbox = ebarimt_helpers.mailbox
posapi = ebarimt_helpers.posapi


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
