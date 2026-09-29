"""Forgotten-password reset by a 6-digit emailed code.

- ``request_reset`` never says whether the email exists: the caller always
  answers ``200 ok``. Codes are stored only as a keyed SHA-256 (HMAC) hash —
  with just a million possible codes a bare hash is reversible by brute force.
- A new code kills the account's earlier unused ones; at most
  ``MAX_CODES_PER_HOUR`` are sent per account per hour (extra requests are
  silently dropped, so the mailbox cannot be flooded). The mail is sent on a
  background thread so response time does not reveal the account either.
- A code dies after ``MAX_ATTEMPTS`` wrong guesses, on expiry, or on use. Every
  failure is the same ``invalid_code`` so the endpoint is no oracle either.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from datetime import timedelta
from email.message import EmailMessage

from flask import current_app

from app import mail
from app.auth import revoke_all_for_account
from app.extensions import db
from app.models import AuthAccount, OtpVerification
from app.timeutil import utcnow

from ..errors import ServiceError

PURPOSE = "password_reset"
CODE_TTL = timedelta(minutes=15)
MAX_ATTEMPTS = 5
MAX_CODES_PER_HOUR = 3


def _hash(account_id: int, code: str) -> str:
    key = str(current_app.config.get("SECRET_KEY") or "").encode()
    msg = f"{PURPOSE}:{account_id}:{code}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _open_codes(account_id: int, now):
    return OtpVerification.query.filter(
        OtpVerification.account_id == account_id,
        OtpVerification.purpose == PURPOSE,
        OtpVerification.used_at.is_(None),
        OtpVerification.expires_at > now,
    )


def _build_email(to: str, code: str) -> EmailMessage:
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = "Нууц үг сэргээх код / Password reset code"
    minutes = int(CODE_TTL.total_seconds() // 60)
    msg.set_content(
        f"Таны нууц үг сэргээх код: {code}\n"
        f"Код {minutes} минутын дараа хүчингүй болно. Та хүсэлт илгээгээгүй бол "
        "энэ имэйлийг үл тоомсорлоно уу.\n\n"
        f"Your password reset code: {code}\n"
        f"It expires in {minutes} minutes. If you did not ask for it, ignore this email.\n\n"
        "AI Academy Asia\n"
    )
    return msg


def request_reset(email) -> None:
    """Issue and email a code if an active account has this email. Returns nothing."""
    account = AuthAccount.get_by_email(email) if isinstance(email, str) else None
    if account is None or not account.is_active:
        return
    now = utcnow()
    recent = OtpVerification.query.filter(
        OtpVerification.account_id == account.id,
        OtpVerification.purpose == PURPOSE,
        OtpVerification.created_at > now - timedelta(hours=1),
    ).count()
    if recent >= MAX_CODES_PER_HOUR:
        current_app.logger.info("password reset rate-limited for account %s", account.id)
        return

    _open_codes(account.id, now).update({"used_at": now}, synchronize_session=False)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    db.session.add(OtpVerification(
        account_id=account.id, purpose=PURPOSE, code_hash=_hash(account.id, code),
        expires_at=now + CODE_TTL, created_at=now,
    ))
    db.session.commit()

    if not mail.is_configured():
        current_app.logger.warning(
            "password reset code for account %s not sent: mail is not configured", account.id)
        return
    _deliver(_build_email(account.email, code), account.id)


def _deliver(message: EmailMessage, account_id: int) -> threading.Thread:
    """Send off the request thread.

    An SMTP round trip only happens for a real account, so sending inline would
    make "this email exists" measurable from the response time alone.
    """
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            try:
                mail.send_message(message)
            except mail.MailError as exc:
                app.logger.warning("password reset mail to account %s failed: %s",
                                   account_id, exc)

    thread = threading.Thread(target=run, name="password-reset-mail", daemon=True)
    thread.start()
    return thread


def reset_password(email, code, new_password) -> None:
    """Swap the password when ``code`` is the account's live code. Raises on failure."""
    min_len = current_app.config["PASSWORD_MIN_LENGTH"]
    if not isinstance(new_password, str) or len(new_password) < min_len:
        raise ServiceError(400, "weak_password", min_length=min_len)
    if not isinstance(email, str) or not isinstance(code, str) or not code.strip():
        raise ServiceError(400, "invalid_code")

    account = AuthAccount.get_by_email(email)
    if account is None or not account.is_active:
        raise ServiceError(400, "invalid_code")
    now = utcnow()
    otp = (_open_codes(account.id, now)
           .filter(OtpVerification.attempts < MAX_ATTEMPTS)
           .order_by(OtpVerification.created_at.desc(), OtpVerification.id.desc())
           .with_for_update()
           .first())
    if otp is None:
        raise ServiceError(400, "invalid_code")
    if not hmac.compare_digest(otp.code_hash, _hash(account.id, code.strip())):
        otp.attempts += 1
        db.session.commit()
        raise ServiceError(400, "invalid_code")

    otp.used_at = now
    account.set_password(new_password)
    account.must_change_password = False
    revoke_all_for_account(account.id)
    db.session.commit()
