"""Route guards that enforce what the middleware merely resolved."""
from functools import wraps

from flask import g, jsonify, request

from .permissions import has_permission


def _unauthorized():
    code = getattr(g, "auth_error", None) or "authentication_required"
    return jsonify(error=code), 401


def _password_change_pending(user) -> bool:
    """A provisioned or reset account may use /auth/* (change its password, read
    /auth/me, log out) and nothing else until the password is changed — the
    client's own gate is not a control."""
    return bool(user.must_change_password) and not request.path.startswith("/auth/")


def _guard(user):
    """The response that stops this user, or ``None`` to let the request through."""
    if user is None:
        return _unauthorized()
    if _password_change_pending(user):
        return jsonify(error="password_change_required"), 403
    return None


def login_required(fn):
    """Require any authenticated actor."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        stop = _guard(getattr(g, "current_user", None))
        if stop is not None:
            return stop
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
            stop = _guard(user)
            if stop is not None:
                return stop
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
            stop = _guard(user)
            if stop is not None:
                return stop
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
            stop = _guard(user)
            if stop is not None:
                return stop
            if user.actor_type not in actor_types:
                return jsonify(error="forbidden"), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator
