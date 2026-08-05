"""Outbound email.

- ``sender``  : SMTP transport (stdlib smtplib, no extra dependency).
- ``receipt`` : the eBarimt receipt template students get after paying.

Transport and content are kept apart so templates stay unit-testable without a
server, and a second kind of mail doesn't have to touch connection handling.
"""
from .receipt import build_receipt_email
from .sender import MailError, is_configured, send_message

__all__ = ["MailError", "build_receipt_email", "is_configured", "send_message"]
