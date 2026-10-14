"""Device push tokens, and the push hook every notification goes through.

:func:`send_push` delivers through FCM (:mod:`.fcm`) when ``FCM_CREDENTIALS``
holds a Firebase service account; without it, it is a logged no-op and the
notification stays in-app only (issue #2).
"""
import logging

import requests
from flask import current_app

from app.extensions import db
from app.models import PUSH_PLATFORMS, FirebaseToken
from app.services.errors import ServiceError
from app.timeutil import iso, utcnow

from . import fcm

log = logging.getLogger(__name__)
MAX_TOKEN_LENGTH = 512


def send_push(account_ids, *, kind, title, body=None, data=None,
              notification_ids=None) -> int:
    """Push to every device of these accounts. Returns the devices reached.

    Each message carries ``data``, ``kind`` and — from ``notification_ids``
    (``{account_id: id}``) — the recipient's own in-app ``notification_id``,
    all as strings. A token FCM reports ``UNREGISTERED`` is deleted. Never
    raises for a delivery problem: the in-app rows are already stored.
    """
    raw = current_app.config.get("FCM_CREDENTIALS")
    if not raw:
        log.info("push skipped (no FCM config): kind=%s accounts=%d", kind, len(account_ids))
        return 0
    try:
        creds = fcm.load_credentials(raw)
    except (OSError, fcm.FcmError) as exc:
        log.error("push skipped: FCM_CREDENTIALS unusable (%s)", type(exc).__name__)
        return 0
    rows = FirebaseToken.query.filter(FirebaseToken.account_id.in_(list(account_ids))).all()
    timeout = current_app.config.get("FCM_HTTP_TIMEOUT", 10)
    reached, dead = 0, []
    for row in rows:
        payload = {**(data or {}), "kind": kind or "general"}
        notification_id = (notification_ids or {}).get(row.account_id)
        if notification_id is not None:
            payload["notification_id"] = notification_id
        try:
            outcome = fcm.send(creds, fcm.message(row.token, title=title, body=body,
                                                  data=payload), timeout=timeout)
        except fcm.FcmError as exc:
            # No access token: every other device would fail the same way.
            log.error("push stopped: %s", exc)
            break
        except requests.RequestException as exc:
            log.warning("push to one device failed (%s)", type(exc).__name__)
            continue
        if outcome == fcm.SENT:
            reached += 1
        elif outcome == fcm.UNREGISTERED:
            dead.append(row.id)
    if dead:
        FirebaseToken.query.filter(FirebaseToken.id.in_(dead)).delete(synchronize_session=False)
        db.session.commit()
    log.info("push: kind=%s devices=%d reached=%d removed=%d",
             kind, len(rows), reached, len(dead))
    return reached


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
