"""POST /auth/forgot-password and /auth/reset-password."""
import hashlib
from datetime import datetime, timedelta

import account_helpers
from account_helpers import PASSWORD, _code_from, _rows

outbox = account_helpers.outbox
NEW = "BrandNew123"


def _forgot(client, email):
    return client.post("/auth/forgot-password", json={"email": email})


def _reset(client, email, code, password=NEW):
    return client.post("/auth/reset-password",
                       json={"email": email, "code": code, "new_password": password})


def _login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def _otps(db, account):
    from app.models import OtpVerification
    return _rows(db, OtpVerification, account_id=account.id)


# ----------------------------------------------------------------- forgot
def test_forgot_is_ok_for_unknown_email_and_sends_nothing(client, db, outbox):
    from app.models import OtpVerification

    for payload in ({"email": "nobody@x.test"}, {}, {"email": 5}):
        resp = client.post("/auth/forgot-password", json=payload)
        assert resp.status_code == 200 and resp.get_json() == {"status": "ok"}
    assert outbox == [] and OtpVerification.query.count() == 0


def test_forgot_emails_a_hashed_code(client, db, make_student, outbox):
    account, _ = make_student()
    resp = _forgot(client, account.email.upper())
    assert resp.get_json() == {"status": "ok"}
    [msg] = outbox
    assert msg["To"] == account.email
    code = _code_from(msg)
    assert len(code) == 6 and code.isdigit()
    [otp] = _otps(db, account)
    assert otp.purpose == "password_reset" and otp.used_at is None
    assert code not in otp.code_hash and otp.code_hash != hashlib.sha256(code.encode()).hexdigest()
    assert timedelta(minutes=14) < otp.expires_at - otp.created_at <= timedelta(minutes=15)


def test_forgot_for_inactive_account_sends_nothing(client, db, make_student, outbox):
    account, _ = make_student()
    account.is_active = False
    db.session.commit()
    assert _forgot(client, account.email).get_json() == {"status": "ok"}
    assert outbox == [] and _otps(db, account) == []


def test_new_code_invalidates_the_old_one(client, db, make_student, outbox):
    account, _ = make_student()
    _forgot(client, account.email)
    _forgot(client, account.email)
    first, second = _code_from(outbox[0]), _code_from(outbox[1])
    if first != second:
        assert _reset(client, account.email, first).get_json()["error"] == "invalid_code"
    assert _reset(client, account.email, second).status_code == 200


def test_rate_limit_three_codes_per_hour(client, db, make_student, outbox):
    account, _ = make_student()
    for _ in range(5):
        assert _forgot(client, account.email).status_code == 200
    assert len(outbox) == 3 and len(_otps(db, account)) == 3


def test_rate_limit_window_slides(client, db, make_student, outbox):
    account, _ = make_student()
    for _ in range(3):
        _forgot(client, account.email)
    for otp in _otps(db, account):
        otp.created_at = datetime.utcnow() - timedelta(hours=2)
    db.session.commit()
    _forgot(client, account.email)
    assert len(outbox) == 4


def test_forgot_without_mail_configured_logs_and_still_ok(client, db, make_student, caplog):
    account, _ = make_student()
    resp = _forgot(client, account.email)
    assert resp.get_json() == {"status": "ok"}
    assert len(_otps(db, account)) == 1
    assert "mail is not configured" in caplog.text


def test_forgot_survives_mail_failure(client, app, db, make_student, monkeypatch):
    from app.mail import MailError

    def _boom(msg):
        raise MailError("smtp down")

    monkeypatch.setitem(app.config, "MAIL_HOST", "smtp.test")
    monkeypatch.setattr("app.mail.send_message", _boom)
    account, _ = make_student()
    assert _forgot(client, account.email).get_json() == {"status": "ok"}


# ----------------------------------------------------------------- reset
def test_reset_happy_path_revokes_sessions(client, db, make_student, outbox):
    account, _ = make_student()
    account.must_change_password = True
    db.session.commit()
    refresh = _login(client, account.email, PASSWORD).get_json()["refresh_token"]

    _forgot(client, account.email)
    code = _code_from(outbox[0])
    resp = _reset(client, account.email, code)
    assert resp.status_code == 200 and resp.get_json() == {"status": "ok"}

    assert _login(client, account.email, PASSWORD).status_code == 401
    login = _login(client, account.email, NEW)
    assert login.status_code == 200 and login.get_json()["must_change_password"] is False
    resp = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401 and resp.get_json()["error"] == "refresh_token_revoked"
    [otp] = _otps(db, account)
    assert otp.used_at is not None
    # single use
    assert _reset(client, account.email, code, "Another123").get_json()["error"] == "invalid_code"


def test_reset_invalid_code_is_uniform(client, db, make_student, outbox):
    account, _ = make_student()
    _forgot(client, account.email)
    code = _code_from(outbox[0])
    wrong = "000000" if code != "000000" else "111111"
    for email, c in ((account.email, wrong), ("nobody@x.test", code),
                     (account.email, ""), (None, code), (account.email, 123456)):
        resp = _reset(client, email, c)
        assert resp.status_code == 400 and resp.get_json() == {"error": "invalid_code"}


def test_reset_without_any_code_requested(client, make_student):
    account, _ = make_student()
    assert _reset(client, account.email, "123456").get_json()["error"] == "invalid_code"


def test_reset_expired_code(client, db, make_student, outbox):
    account, _ = make_student()
    _forgot(client, account.email)
    [otp] = _otps(db, account)
    otp.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    resp = _reset(client, account.email, _code_from(outbox[0]))
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_code"


def test_code_dies_after_five_wrong_attempts(client, db, make_student, outbox):
    account, _ = make_student()
    _forgot(client, account.email)
    code = _code_from(outbox[0])
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert _reset(client, account.email, wrong).status_code == 400
    [otp] = _otps(db, account)
    assert otp.attempts == 5
    resp = _reset(client, account.email, code)
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_code"
    assert _login(client, account.email, PASSWORD).status_code == 200


def test_reset_weak_password(client, app, make_student, outbox):
    account, _ = make_student()
    _forgot(client, account.email)
    code = _code_from(outbox[0])
    for pw in ("short", None, ""):
        resp = _reset(client, account.email, code, pw)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "weak_password",
                                   "min_length": app.config["PASSWORD_MIN_LENGTH"]}
    # the code was not spent on the weak attempts
    assert _reset(client, account.email, code).status_code == 200


def test_reset_for_deactivated_account(client, db, make_student, outbox):
    account, _ = make_student()
    _forgot(client, account.email)
    account.is_active = False
    db.session.commit()
    resp = _reset(client, account.email, _code_from(outbox[0]))
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_code"
