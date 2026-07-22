"""Refresh-token lifecycle: issue, rotate, revoke.

Opaque random tokens, stored only as SHA-256 hashes, rotated on every use with
reuse detection. TTL is per-actor: learners (student/teacher) get a long
window, staff a short one (they touch money data)."""
import hashlib
import secrets
from datetime import datetime, timedelta

from flask import current_app

from app.extensions import db
from app.models import (
    ACTOR_STAFF,
    ACTOR_STUDENT,
    ACTOR_TEACHER,
    AuthAccount,
    RefreshToken,
)


class RefreshError(Exception):
    """Raised when a refresh token cannot be exchanged. ``str(exc)`` is the
    machine-readable error code returned to the client."""


_TTL_CONFIG_KEY = {
    ACTOR_STUDENT: "REFRESH_TTL_STUDENT",
    ACTOR_TEACHER: "REFRESH_TTL_TEACHER",
    ACTOR_STAFF: "REFRESH_TTL_STAFF",
}


def refresh_ttl_for(actor_type: str) -> int:
    """Refresh-token lifetime (seconds) for an actor_type. Unknown types fall
    back to the staff (shortest) window — fail safe."""
    key = _TTL_CONFIG_KEY.get(actor_type, "REFRESH_TTL_STAFF")
    return current_app.config[key]


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_refresh_token(account: AuthAccount, replaces: RefreshToken = None):
    """Create and stage (not commit) a new refresh token for an account.

    Returns (raw_token, ttl_seconds). If ``replaces`` is given, that token is
    revoked and chained to the new one (rotation). Caller commits.
    """
    raw = secrets.token_urlsafe(48)
    ttl = refresh_ttl_for(account.actor_type)
    now = datetime.utcnow()
    row = RefreshToken(
        account_id=account.id,
        token_hash=_hash(raw),
        expires_at=now + timedelta(seconds=ttl),
    )
    db.session.add(row)

    if replaces is not None:
        db.session.flush()  # assign row.id for the chain link
        replaces.revoked_at = now
        replaces.replaced_by_id = row.id

    return raw, ttl


def rotate_refresh_token(raw: str):
    """Exchange a refresh token for a new one. Returns (account, new_raw, ttl).

    Raises RefreshError on: missing/unknown/expired token, inactive account, or
    reuse of an already-revoked token (which also revokes the whole family)."""
    if not raw:
        raise RefreshError("refresh_token_required")

    row = RefreshToken.query.filter_by(token_hash=_hash(raw)).first()
    if row is None:
        raise RefreshError("invalid_refresh_token")

    if row.revoked_at is not None:
        if row.replaced_by_id is not None:
            # This token was rotated (superseded) yet is being presented again —
            # the legit client would hold the newest token, so this signals
            # theft. Nuke every active token for the account: attacker and the
            # real holder both must re-login.
            revoke_all_for_account(row.account_id)
            db.session.commit()
            raise RefreshError("refresh_token_reused")
        # Revoked by logout / logout-all / password change — just reject it,
        # without touching the account's other (still-valid) sessions.
        raise RefreshError("refresh_token_revoked")

    if row.expires_at <= datetime.utcnow():
        raise RefreshError("refresh_token_expired")

    account = db.session.get(AuthAccount, row.account_id)
    if account is None or not account.is_active:
        raise RefreshError("account_inactive")

    new_raw, ttl = issue_refresh_token(account, replaces=row)
    db.session.commit()
    return account, new_raw, ttl


def revoke_refresh_token(raw: str) -> bool:
    """Revoke a single token (logout). No-op if unknown/already revoked."""
    if not raw:
        return False
    row = RefreshToken.query.filter_by(token_hash=_hash(raw)).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.session.commit()
    return True


def revoke_all_for_account(account_id: int) -> int:
    """Revoke every active token for an account (logout-everywhere / reuse
    response). Stages the update; caller commits (or it is committed by the
    reuse path). Returns the number of tokens revoked."""
    return (
        RefreshToken.query.filter_by(account_id=account_id, revoked_at=None)
        .update({"revoked_at": datetime.utcnow()})
    )
