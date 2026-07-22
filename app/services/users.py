"""Admin management of student & teacher records (profile + auth account)."""
from datetime import date

from app.auth import revoke_all_for_account
from app.auth.service import AccountError, provision_account
from app.extensions import db
from app.models import ACTOR_STUDENT, ACTOR_TEACHER, AuthAccount, Student, Teacher

from .errors import ServiceError

# actor segment -> config. `fields` = profile columns a client may set.
ACTORS = {
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


# ---------------------------------------------------------------- serialization
def account_dict(account):
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


def serialize(profile, account):
    return {"id": profile.id, "profile": profile.to_dict(), "account": account_dict(account)}


# ---------------------------------------------------------------- helpers
def _account_for(cfg, profile_id):
    return AuthAccount.query.filter_by(
        actor_type=cfg["actor_type"], actor_id=profile_id
    ).first()


def _extract_profile(cfg, data):
    out = {}
    for field in cfg["fields"]:
        if field not in data:
            continue
        value = data[field]
        if field in cfg["date_fields"] and value not in (None, ""):
            try:
                value = date.fromisoformat(value)
            except (ValueError, TypeError):
                raise ServiceError(400, "invalid_date", field=field) from None
        out[field] = value
    return out


def _get_profile_or_404(cfg, profile_id):
    profile = db.session.get(cfg["model"], profile_id)
    if profile is None:
        raise ServiceError(404, "not_found")
    return profile


# ---------------------------------------------------------------- operations
def list_users(cfg, *, search=None, limit=50, offset=0):
    model = cfg["model"]
    q = model.query
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(model.first_name.ilike(like), model.last_name.ilike(like)))
    total = q.count()
    try:
        limit = min(max(int(limit), 0), 200)
        offset = max(int(offset), 0)
    except (ValueError, TypeError):
        raise ServiceError(400, "invalid_pagination") from None
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
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [serialize(p, accounts.get(p.id)) for p in rows],
    }


def get_user(cfg, profile_id):
    profile = _get_profile_or_404(cfg, profile_id)
    return serialize(profile, _account_for(cfg, profile_id))


def create_user(cfg, data):
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        raise ServiceError(400, "email_and_password_required")
    profile_kwargs = _extract_profile(cfg, data)
    if not profile_kwargs.get("first_name"):
        raise ServiceError(400, "first_name_required")
    profile = cfg["model"](**profile_kwargs)
    try:
        account, _ = provision_account(
            profile, email=email, password=password,
            actor_type=cfg["actor_type"], role=cfg["role"], must_change_password=True,
        )
    except AccountError as exc:
        code = str(exc)
        raise ServiceError(409 if code == "email_taken" else 400, code) from exc
    return serialize(profile, account)


def update_user(cfg, profile_id, data):
    profile = _get_profile_or_404(cfg, profile_id)
    account = _account_for(cfg, profile_id)
    for field, value in _extract_profile(cfg, data).items():
        setattr(profile, field, value)
    if account is not None:
        if "email" in data:
            new_email = AuthAccount.normalize_email(data["email"])
            if not new_email:
                raise ServiceError(400, "email_required")
            clash = AuthAccount.get_by_email(new_email)
            if clash is not None and clash.id != account.id:
                raise ServiceError(409, "email_taken")
            account.email = new_email
        if "is_active" in data:
            account.is_active = bool(data["is_active"])
            if not account.is_active:
                revoke_all_for_account(account.id)  # deactivating -> kill sessions
    db.session.commit()
    return serialize(profile, account)


def delete_user(cfg, profile_id):
    profile = _get_profile_or_404(cfg, profile_id)
    account = _account_for(cfg, profile_id)
    if account is not None:
        db.session.delete(account)  # refresh_tokens cascade at DB level
    db.session.delete(profile)
    db.session.commit()


def reset_password(cfg, profile_id, new_password, *, min_len):
    _get_profile_or_404(cfg, profile_id)
    account = _account_for(cfg, profile_id)
    if account is None:
        raise ServiceError(404, "account_not_found")
    if len(new_password or "") < min_len:
        raise ServiceError(400, "weak_password", min_length=min_len)
    account.set_password(new_password)
    account.must_change_password = True
    revoke_all_for_account(account.id)
    db.session.commit()
