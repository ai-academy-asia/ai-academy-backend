"""Auth endpoints: login, refresh, logout, current user, change password."""
from datetime import datetime

from flask import Blueprint, current_app, g, jsonify, request

from app.auth import (
    RefreshError,
    create_access_token,
    issue_refresh_token,
    login_required,
    revoke_all_for_account,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.extensions import db
from app.models import AuthAccount

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _token_response(account, refresh_raw, refresh_ttl, *, include_actor=True):
    """Build the standard access+refresh token payload."""
    body = {
        "access_token": create_access_token(account),
        "token_type": "Bearer",
        "expires_in": current_app.config["JWT_ACCESS_TTL"],
        "refresh_token": refresh_raw,
        "refresh_expires_in": refresh_ttl,
        "must_change_password": account.must_change_password,
    }
    if include_actor:
        body["actor"] = account.to_dict()
    return body


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = AuthAccount.normalize_email(data.get("email"))
    password = data.get("password") or ""

    if not email or not password:
        return jsonify(error="email_and_password_required"), 400

    account = AuthAccount.get_by_email(email)
    # Same response whether the email is unknown or the password is wrong —
    # avoids leaking which emails exist.
    if account is None or not account.check_password(password):
        return jsonify(error="invalid_credentials"), 401
    if not account.is_active:
        return jsonify(error="account_inactive"), 403

    account.last_login_at = datetime.utcnow()
    refresh_raw, refresh_ttl = issue_refresh_token(account)
    db.session.commit()

    return jsonify(_token_response(account, refresh_raw, refresh_ttl))


@bp.post("/refresh")
def refresh():
    """Rotate a refresh token for a fresh access + refresh pair."""
    data = request.get_json(silent=True) or {}
    raw = data.get("refresh_token") or ""
    try:
        account, new_raw, ttl = rotate_refresh_token(raw)
    except RefreshError as exc:
        return jsonify(error=str(exc)), 401
    return jsonify(_token_response(account, new_raw, ttl))


@bp.post("/logout")
def logout():
    """Revoke the presented refresh token (this device). Idempotent; needs no
    access token so it works even after the access token has expired."""
    data = request.get_json(silent=True) or {}
    revoke_refresh_token(data.get("refresh_token") or "")
    return jsonify(status="ok")


@bp.post("/logout-all")
@login_required
def logout_all():
    """Revoke every refresh token for the authenticated account (log out
    everywhere)."""
    count = revoke_all_for_account(g.current_user.id)
    db.session.commit()
    return jsonify(status="ok", revoked=count)


@bp.get("/me")
@login_required
def me():
    return jsonify(g.current_user.to_dict())


@bp.post("/change-password")
@login_required
def change_password():
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    user = g.current_user
    if not user.check_password(current_password):
        return jsonify(error="invalid_credentials"), 401

    min_len = current_app.config["PASSWORD_MIN_LENGTH"]
    if len(new_password) < min_len:
        return jsonify(error="weak_password", min_length=min_len), 400
    if new_password == current_password:
        return jsonify(error="password_unchanged"), 400

    user.set_password(new_password)
    user.must_change_password = False
    # Force re-login everywhere after a password change (revoke all refresh
    # tokens). The current access token stays valid until it expires (short TTL).
    revoke_all_for_account(user.id)
    db.session.commit()
    return jsonify(status="ok")
