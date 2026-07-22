"""Route guards that enforce what the middleware merely resolved."""
from functools import wraps

from flask import g, jsonify

from .permissions import has_permission


def _unauthorized():
    code = getattr(g, "auth_error", None) or "authentication_required"
    return jsonify(error=code), 401


def login_required(fn):
    """Require any authenticated actor."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if getattr(g, "current_user", None) is None:
            return _unauthorized()
        return fn(*args, **kwargs)

    return wrapper


def roles_required(*roles):
    """Require the account's ``role`` to be one of ``roles`` (RBAC).

    e.g. ``@roles_required("super_admin", "finance")``.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = getattr(g, "current_user", None)
            if user is None:
                return _unauthorized()
            if user.role not in roles:
                return jsonify(error="forbidden"), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_permission(*permissions):
    """Require the account's role to grant ALL of ``permissions`` (RBAC).

    Prefer this over ``roles_required`` for back-office endpoints — the route
    states the capability it needs, not who has it. ``super_admin`` passes via
    the wildcard. e.g. ``@require_permission("payment:refund")``.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = getattr(g, "current_user", None)
            if user is None:
                return _unauthorized()
            if not all(has_permission(user.role, perm) for perm in permissions):
                return jsonify(error="forbidden"), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor_required(*actor_types):
    """Require the account's ``actor_type`` to be one of ``actor_types``.

    e.g. ``@actor_required("student")`` for student-app-only endpoints.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = getattr(g, "current_user", None)
            if user is None:
                return _unauthorized()
            if user.actor_type not in actor_types:
                return jsonify(error="forbidden"), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator
