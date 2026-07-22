"""Staff-facing management of student & teacher records (profile + auth account).

Gated by ``student:manage`` / ``teacher:manage`` (sales_enrollment + super_admin).
Students and teachers share the same shape, so one set of view builders is
registered for both under /admin/students and /admin/teachers.
"""
from datetime import date

from flask import Blueprint, current_app, jsonify, request

from app.auth import require_permission, revoke_all_for_account
from app.auth.service import AccountError, provision_account
from app.extensions import db
from app.models import (
    ACTOR_STUDENT,
    ACTOR_TEACHER,
    AuthAccount,
    Student,
    Teacher,
)
from app.routes.common import json_fail

bp = Blueprint("admin_users", __name__, url_prefix="/admin")

# Per-actor configuration. `fields` = profile columns a client may set.
_ACTORS = {
    "students": {
        "actor_type": ACTOR_STUDENT,
        "model": Student,
        "role": ACTOR_STUDENT,
        "permission": "student:manage",
        "fields": {"first_name", "last_name", "phone", "birth_date",
                   "ui_mode", "parent_name", "parent_phone"},
        "date_fields": {"birth_date"},
    },
    "teachers": {
        "actor_type": ACTOR_TEACHER,
        "model": Teacher,
        "role": ACTOR_TEACHER,
        "permission": "teacher:manage",
        "fields": {"first_name", "last_name", "phone", "bio"},
        "date_fields": set(),
    },
}


# ---------------------------------------------------------------- helpers
def _account_dict(account: AuthAccount) -> dict:
    if account is None:
        return None
    return {
        "id": account.id,
        "email": account.email,
        "role": account.role,
        "actor_type": account.actor_type,
        "is_active": account.is_active,
        "must_change_password": account.must_change_password,
        "last_login_at": account.last_login_at.isoformat() if account.last_login_at else None,
    }


def _serialize(profile, account) -> dict:
    return {"id": profile.id, "profile": profile.to_dict(), "account": _account_dict(account)}


def _account_for(cfg, profile_id):
    return AuthAccount.query.filter_by(
        actor_type=cfg["actor_type"], actor_id=profile_id
    ).first()


def _extract_profile(cfg, data) -> dict:
    """Whitelist + type-coerce profile fields from the request body."""
    out = {}
    for field in cfg["fields"]:
        if field not in data:
            continue
        value = data[field]
        if field in cfg["date_fields"] and value not in (None, ""):
            try:
                value = date.fromisoformat(value)
            except (ValueError, TypeError):
                json_fail(400, "invalid_date", field=field)
        out[field] = value
    return out


def _get_profile_or_404(cfg, profile_id):
    profile = db.session.get(cfg["model"], profile_id)
    if profile is None:
        json_fail(404, "not_found")
    return profile


# ---------------------------------------------------------------- views
def _make_views(cfg):
    def list_users():
        model = cfg["model"]
        q = model.query
        search = request.args.get("q")
        if search:
            like = f"%{search}%"
            q = q.filter(db.or_(model.first_name.ilike(like), model.last_name.ilike(like)))
        total = q.count()

        try:
            limit = min(int(request.args.get("limit", 50)), 200)
            offset = max(int(request.args.get("offset", 0)), 0)
        except (ValueError, TypeError):
            json_fail(400, "invalid_pagination")

        rows = q.order_by(model.id.desc()).limit(limit).offset(offset).all()
        ids = [p.id for p in rows]
        accounts = {}
        if ids:
            accounts = {
                a.actor_id: a
                for a in AuthAccount.query.filter_by(actor_type=cfg["actor_type"])
                .filter(AuthAccount.actor_id.in_(ids))
                .all()
            }
        return jsonify(
            total=total,
            limit=limit,
            offset=offset,
            items=[_serialize(p, accounts.get(p.id)) for p in rows],
        )

    def get_user(profile_id):
        profile = _get_profile_or_404(cfg, profile_id)
        return jsonify(_serialize(profile, _account_for(cfg, profile_id)))

    def create_user():
        data = request.get_json(silent=True) or {}
        email = data.get("email")
        password = data.get("password")
        if not email or not password:
            json_fail(400, "email_and_password_required")

        profile_kwargs = _extract_profile(cfg, data)
        if not profile_kwargs.get("first_name"):
            json_fail(400, "first_name_required")

        profile = cfg["model"](**profile_kwargs)
        try:
            account, _ = provision_account(
                profile,
                email=email,
                password=password,
                actor_type=cfg["actor_type"],
                role=cfg["role"],
                must_change_password=True,
            )
        except AccountError as exc:
            code = str(exc)
            json_fail(409 if code == "email_taken" else 400, code)
        return jsonify(_serialize(profile, account)), 201

    def update_user(profile_id):
        profile = _get_profile_or_404(cfg, profile_id)
        account = _account_for(cfg, profile_id)
        data = request.get_json(silent=True) or {}

        # profile fields
        for field, value in _extract_profile(cfg, data).items():
            setattr(profile, field, value)

        # account fields (email / is_active)
        if account is not None:
            if "email" in data:
                new_email = AuthAccount.normalize_email(data["email"])
                if not new_email:
                    json_fail(400, "email_required")
                clash = AuthAccount.get_by_email(new_email)
                if clash is not None and clash.id != account.id:
                    json_fail(409, "email_taken")
                account.email = new_email
            if "is_active" in data:
                account.is_active = bool(data["is_active"])
                if not account.is_active:
                    # deactivating -> kill existing sessions immediately
                    revoke_all_for_account(account.id)

        db.session.commit()
        return jsonify(_serialize(profile, account))

    def delete_user(profile_id):
        profile = _get_profile_or_404(cfg, profile_id)
        account = _account_for(cfg, profile_id)
        if account is not None:
            db.session.delete(account)  # refresh_tokens cascade at DB level
        db.session.delete(profile)
        db.session.commit()
        return jsonify(status="deleted")

    def reset_password(profile_id):
        _get_profile_or_404(cfg, profile_id)
        account = _account_for(cfg, profile_id)
        if account is None:
            json_fail(404, "account_not_found")

        data = request.get_json(silent=True) or {}
        new_password = data.get("new_password") or ""
        min_len = current_app.config["PASSWORD_MIN_LENGTH"]
        if len(new_password) < min_len:
            json_fail(400, "weak_password", min_length=min_len)

        account.set_password(new_password)
        account.must_change_password = True  # force change on next login
        revoke_all_for_account(account.id)   # invalidate all sessions
        db.session.commit()
        return jsonify(status="ok")

    return {
        "list": list_users,
        "get": get_user,
        "create": create_user,
        "update": update_user,
        "delete": delete_user,
        "reset_password": reset_password,
    }


def _register(segment, cfg):
    views = _make_views(cfg)
    guard = require_permission(cfg["permission"])
    base = f"/{segment}"
    item = f"/{segment}/<int:profile_id>"

    routes = [
        ("list", base, ["GET"], views["list"]),
        ("create", base, ["POST"], views["create"]),
        ("get", item, ["GET"], views["get"]),
        ("update", item, ["PATCH"], views["update"]),
        ("delete", item, ["DELETE"], views["delete"]),
        ("reset_password", f"{item}/reset-password", ["POST"], views["reset_password"]),
    ]
    for name, rule, methods, view in routes:
        bp.add_url_rule(
            rule, endpoint=f"{segment}_{name}", view_func=guard(view), methods=methods
        )


for _segment, _cfg in _ACTORS.items():
    _register(_segment, _cfg)
