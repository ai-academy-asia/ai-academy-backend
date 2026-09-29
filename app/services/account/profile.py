"""A student or teacher editing their own profile. Staff profiles are HR's business."""
from __future__ import annotations

import re

from app.extensions import db
from app.models import ACTOR_STUDENT, ACTOR_TEACHER

from ..errors import ServiceError

_PHONE = re.compile(r"^[0-9+\- ]+$")
_EDITABLE = {
    ACTOR_STUDENT: ("first_name", "last_name", "phone"),
    ACTOR_TEACHER: ("first_name", "last_name", "phone", "bio"),
}
_MAX_LEN = {"first_name": 100, "last_name": 100, "bio": 5000}


def _text(field, value):
    """Stripped text, ``None`` for blank. Non-strings and overlong values are 400s."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ServiceError(400, f"invalid_{field}")
    value = value.strip()
    if len(value) > _MAX_LEN[field]:
        raise ServiceError(400, "field_too_long", field=field, max_length=_MAX_LEN[field])
    return value or None


def _phone(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise ServiceError(400, "invalid_phone")
    value = value.strip()
    if len(value) > 20 or not _PHONE.match(value):
        raise ServiceError(400, "invalid_phone")
    return value


def update_profile(account, data: dict) -> dict:
    """Apply the known fields in ``data``; unknown ones are ignored. Returns ``/auth/me``."""
    fields = _EDITABLE.get(account.actor_type)
    if fields is None:
        raise ServiceError(403, "forbidden")
    profile = account.profile
    if profile is None:
        raise ServiceError(404, "profile_not_found")

    changes = {}
    for field in fields:
        if field not in data:
            continue
        value = data[field]
        if field == "first_name":
            value = _text(field, value) if isinstance(value, str) else None
            if not value:
                raise ServiceError(400, "first_name_required")
        elif field == "phone":
            value = _phone(value)
        else:
            value = _text(field, value)
        changes[field] = value

    for field, value in changes.items():
        setattr(profile, field, value)
    db.session.commit()
    body = account.to_dict()
    if account.actor_type == ACTOR_TEACHER and body.get("profile") is not None:
        body["profile"]["bio"] = profile.bio
    return body
