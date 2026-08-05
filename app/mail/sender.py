"""SMTP transport.

Deliberately thin: callers build a fully-formed ``EmailMessage`` and this module
owns nothing but the connection. Keeping content out of here means the receipt
template can be unit-tested without a server, and a second kind of mail (a
contract, a reminder) doesn't have to touch transport code.

No third-party dependency — stdlib ``smtplib`` covers Workspace/Gmail SMTP, AWS
SES's SMTP endpoint, and anything else that speaks the protocol.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app


class MailError(Exception):
    """Transport failed. Content errors raise before we get here."""


def is_configured() -> bool:
    """False when no SMTP host is set — sending is then a no-op, not a crash."""
    return bool(current_app.config.get("MAIL_HOST"))


def send_message(msg: EmailMessage) -> None:
    cfg = current_app.config
    host = cfg.get("MAIL_HOST")
    if not host:
        raise MailError("MAIL_HOST is not configured")

    port = cfg.get("MAIL_PORT", 587)
    timeout = cfg.get("MAIL_TIMEOUT", 20)
    username = cfg.get("MAIL_USERNAME")
    password = cfg.get("MAIL_PASSWORD")

    if not msg.get("From"):
        msg["From"] = cfg.get("MAIL_FROM")
    reply_to = cfg.get("MAIL_REPLY_TO")
    if reply_to and not msg.get("Reply-To"):
        msg["Reply-To"] = reply_to

    try:
        if cfg.get("MAIL_USE_SSL"):
            client = smtplib.SMTP_SSL(
                host, port, timeout=timeout, context=ssl.create_default_context()
            )
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)
        with client:
            client.ehlo()
            if cfg.get("MAIL_USE_TLS") and not cfg.get("MAIL_USE_SSL"):
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if username:
                client.login(username, password or "")
            client.send_message(msg)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise MailError(f"{type(exc).__name__}: {exc}") from exc
