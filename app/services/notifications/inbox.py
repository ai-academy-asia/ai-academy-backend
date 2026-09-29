"""Creating notifications, and an account's own inbox."""
import logging

from app.extensions import db
from app.models import Notification
from app.services.errors import ServiceError
from app.services.params import parse_id, parse_limit
from app.timeutil import iso, utcnow

from . import push

log = logging.getLogger(__name__)
MAX_TITLE_LENGTH = 200


def notification_dict(n: Notification) -> dict:
    return {
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "data": n.data,
        "read_at": iso(n.read_at),
        "created_at": iso(n.created_at),
    }


def notify(account_ids, *, kind, title, body=None, data=None) -> int:
    """One notification per (distinct) account, committed; then the push hook.

    Returns the number of rows created. A push failure never undoes the inbox
    rows — the notification is delivered in-app regardless.
    """
    ids = sorted({int(a) for a in account_ids or []})
    if not ids:
        return 0
    now = utcnow()
    db.session.add_all([
        Notification(account_id=a, kind=kind or "general", title=title, body=body,
                     data=data, created_at=now)
        for a in ids
    ])
    db.session.commit()
    try:
        push.send_push(ids, kind=kind, title=title, body=body, data=data)
    except Exception:  # noqa: BLE001 — push is best-effort by design
        log.exception("push hook failed for kind=%s", kind)
    return len(ids)


def unread_count(account_id) -> int:
    return Notification.query.filter_by(account_id=account_id, read_at=None).count()


def list_for(account_id, *, limit=None, before_id=None) -> dict:
    query = Notification.query.filter_by(account_id=account_id)
    if before_id not in (None, ""):
        before = parse_id(before_id)
        if before is None:
            raise ServiceError(400, "invalid_before_id")
        query = query.filter(Notification.id < before)
    rows = query.order_by(Notification.id.desc()).limit(
        parse_limit(limit, default=30, maximum=100)
    ).all()
    return {
        "unread_count": unread_count(account_id),
        "notifications": [notification_dict(n) for n in rows],
    }


def mark_read(account_id, notification_id) -> dict:
    n = Notification.query.filter_by(
        id=parse_id(notification_id), account_id=account_id
    ).first()
    if n is None:
        raise ServiceError(404, "notification_not_found")
    if n.read_at is None:
        n.read_at = utcnow()
        db.session.commit()
    return {**notification_dict(n), "unread_count": unread_count(account_id)}


def mark_all_read(account_id) -> dict:
    updated = Notification.query.filter_by(account_id=account_id, read_at=None).update(
        {"read_at": utcnow()}, synchronize_session=False
    )
    db.session.commit()
    return {"updated": updated, "unread_count": 0}
