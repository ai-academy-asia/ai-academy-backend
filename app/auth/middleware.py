"""Request-level auth middleware.

``register_auth_middleware(app)`` installs a ``before_request`` hook that, when a
valid ``Authorization: Bearer <jwt>`` header is present, loads the AuthAccount
onto ``flask.g``. It is *non-enforcing* — it never rejects a request on its own;
enforcement is done by the decorators in ``app.auth.decorators``. This keeps
public routes (e.g. /health, /auth/login) working without special-casing.
"""
import jwt
from flask import g, request

from app.extensions import db

from .tokens import decode_token


def current_user():
    """Convenience accessor for the authenticated AuthAccount (or None)."""
    return getattr(g, "current_user", None)


def _load_current_user() -> None:
    g.current_user = None
    g.auth_error = None

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return

    token = header[len("Bearer ") :].strip()
    if not token:
        return

    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        g.auth_error = "token_expired"
        return
    except jwt.InvalidTokenError:
        g.auth_error = "invalid_token"
        return

    if payload.get("type") != "access":
        g.auth_error = "invalid_token"
        return

    # Load the account to honor live revocation (is_active / deletion), rather
    # than trusting stale JWT claims — this handles money-sensitive access.
    from app.models import AuthAccount

    try:
        account_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        g.auth_error = "invalid_token"
        return

    account = db.session.get(AuthAccount, account_id)
    if account is None or not account.is_active:
        g.auth_error = "account_inactive"
        return

    g.current_user = account


def register_auth_middleware(app) -> None:
    app.before_request(_load_current_user)
