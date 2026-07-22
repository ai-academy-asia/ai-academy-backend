"""Auth service: JWT issuing, request middleware, and route guards.

Public surface:
    from app.auth import login_required, roles_required, actor_required
    from app.auth import register_auth_middleware, current_user
"""
from .decorators import (
    actor_required,
    login_required,
    require_permission,
    roles_required,
)
from .middleware import current_user, register_auth_middleware
from .permissions import PERMISSIONS_BY_ROLE, has_permission, permissions_for
from .refresh import (
    RefreshError,
    issue_refresh_token,
    refresh_ttl_for,
    revoke_all_for_account,
    revoke_refresh_token,
    rotate_refresh_token,
)
from .tokens import create_access_token, decode_token

__all__ = [
    "actor_required",
    "login_required",
    "roles_required",
    "require_permission",
    "has_permission",
    "permissions_for",
    "PERMISSIONS_BY_ROLE",
    "register_auth_middleware",
    "current_user",
    "create_access_token",
    "decode_token",
    "RefreshError",
    "issue_refresh_token",
    "refresh_ttl_for",
    "revoke_refresh_token",
    "revoke_all_for_account",
    "rotate_refresh_token",
]
