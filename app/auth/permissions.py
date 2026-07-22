"""Central role -> permission policy (RBAC).

Routes declare the *capability* they need (``@require_permission("payment:refund")``),
never a role name. What each role can do lives here, in one auditable place.
``super_admin`` holds the wildcard and implicitly passes every check, so new
endpoints never need to remember to include it.

Permissions are ``resource:action`` strings. Non-staff roles (student/teacher)
carry no back-office permissions — their endpoints are gated by actor_type
(``@actor_required``) instead.

If admin-configurable roles are ever needed, move this dict into DB tables; the
route decorators stay unchanged.
"""

WILDCARD = "*"

# super_admin-only capabilities: granted to no role below, so only super_admin
# passes (via the wildcard). Listed here for discoverability.
#   - classroom:manage  (create/update/delete хичээлийн танхим)

PERMISSIONS_BY_ROLE = {
    "super_admin": {WILDCARD},
    "finance": {
        "payment:read",
        "payment:refund",
        "installment:manage",
        "ledger:read",
        "ebarimt:manage",
        "report:finance",
    },
    "sales_enrollment": {
        "enrollment:create",
        "enrollment:read",
        "cohort:manage",
        "student:assign",
        "student:manage",
        "teacher:manage",
        "schedule:manage",
        "swap:approve",
    },
    "content_marketing": {
        "content:edit",
        "course:edit",
        "post:manage",
        "banner:manage",
    },
    # student / teacher: no back-office permissions (use @actor_required).
    "student": set(),
    "teacher": set(),
}


def permissions_for(role: str) -> set:
    return PERMISSIONS_BY_ROLE.get(role, set())


def has_permission(role: str, permission: str) -> bool:
    perms = permissions_for(role)
    return WILDCARD in perms or permission in perms
