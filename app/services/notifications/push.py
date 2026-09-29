"""Device push tokens, and the push hook every notification goes through.

There are no FCM credentials yet, so :func:`send_push` is a logged no-op. When
an ``FCM_CREDENTIALS`` config appears, this is the one function to fill in —
callers already hand it every notification that should reach a phone.
"""
import logging

from flask import current_app

from app.extensions import db
from app.models import PUSH_PLATFORMS, FirebaseToken
from app.services.errors import ServiceError
from app.timeutil import iso, utcnow

log = logging.getLogger(__name__)
MAX_TOKEN_LENGTH = 512


def send_push(account_ids, *, kind, title, body=None, data=None) -> int:
    """Deliver a push to every device of these accounts. Returns devices reached."""
    if not current_app.config.get("FCM_CREDENTIALS"):
        log.info("push skipped (no FCM config): kind=%s accounts=%d", kind, len(account_ids))
        return 0
    tokens = FirebaseToken.query.filter(FirebaseToken.account_id.in_(list(account_ids))).count()
    log.warning("FCM configured but delivery is not implemented; %d device(s) skipped", tokens)
    return 0


def _token(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ServiceError(400, "token_required")
    value = value.strip()
    if len(value) > MAX_TOKEN_LENGTH:
        raise ServiceError(400, "invalid_token")
    return value


def token_dict(row: FirebaseToken) -> dict:
    return {
        "id": row.id,
        "platform": row.platform,
        "created_at": iso(row.created_at),
        "last_seen_at": iso(row.last_seen_at),
    }


def register_token(account_id, data) -> tuple:
    """Upsert a device token: ``(payload, created)``.

    A token is one device, so if another account registered it (someone logged
    out and a colleague logged in on the same phone) it moves to this account.
    """
    token = _token(data.get("token"))
    platform = data.get("platform")
    if platform not in PUSH_PLATFORMS:
        raise ServiceError(400, "invalid_platform", allowed=list(PUSH_PLATFORMS))
    now = utcnow()
    row = FirebaseToken.query.filter_by(token=token).first()
    created = row is None
    if created:
        row = FirebaseToken(token=token, created_at=now)
        db.session.add(row)
    row.account_id = account_id
    row.platform = platform
    row.last_seen_at = now
    db.session.commit()
    return token_dict(row), created


def remove_token(account_id, data) -> int:
    """Forget the caller's own device token. Unknown or foreign tokens: no-op."""
    token = _token(data.get("token"))
    removed = FirebaseToken.query.filter_by(token=token, account_id=account_id).delete()
    db.session.commit()
    return removed
