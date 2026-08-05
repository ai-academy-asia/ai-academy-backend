"""Small helpers shared by the actor routers."""
from flask import g, request

from app.auth import has_permission


def body() -> dict:
    """The JSON request body, or ``{}``.

    Silent parsing on purpose: a missing or malformed body should surface as the
    specific "field required" error the service raises, not as a generic 400
    from Flask that tells the caller nothing about which field was wrong.
    """
    return request.get_json(silent=True) or {}


def current_user():
    return getattr(g, "current_user", None)


def can(permission: str) -> bool:
    user = current_user()
    return user is not None and has_permission(user.role, permission)


def can_any(*permissions) -> bool:
    user = current_user()
    return user is not None and any(has_permission(user.role, p) for p in permissions)
