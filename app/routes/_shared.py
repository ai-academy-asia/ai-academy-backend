"""Small helpers shared by the actor routers (permission checks on g.current_user)."""
from flask import g

from app.auth import has_permission


def current_user():
    return getattr(g, "current_user", None)


def can(permission: str) -> bool:
    user = current_user()
    return user is not None and has_permission(user.role, permission)


def can_any(*permissions) -> bool:
    user = current_user()
    return user is not None and any(has_permission(user.role, p) for p in permissions)
