"""The one place where roles map to permissions. Routes check permissions, never role names."""

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "refund_agent": frozenset({"customer:read", "refund:read", "refund:create"}),
    "refund_approver": frozenset({"customer:read", "refund:read", "refund:approve"}),
    "kyc_reviewer": frozenset({"customer:read", "pii:read", "kyc:review"}),
    "admin": frozenset({"access_review:read", "audit:read", "settings:write", "user:manage"}),
}

ALL_PERMISSIONS: frozenset[str] = frozenset().union(*ROLE_PERMISSIONS.values())


def permissions_for(roles) -> frozenset[str]:
    out: set[str] = set()
    for role in roles:
        out |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(out)


ROLE_LABELS = {
    "refund_agent": "Refund agent",
    "refund_approver": "Refund approver",
    "kyc_reviewer": "KYC reviewer",
    "admin": "Admin",
}

PERMISSION_LABELS = {
    "customer:read": "See customers and charges (SSN and account masked)",
    "refund:read": "See refunds",
    "refund:create": "Request refunds",
    "refund:approve": "Approve or reject refunds",
    "pii:read": "See full SSN and bank account (each view is audited)",
    "kyc:review": "Approve or reject KYC",
    "access_review:read": "See who has access",
    "audit:read": "Read the audit log",
    "settings:write": "Change settings",
    "user:manage": "Add users and change their access",
}


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def roles_granting(permission: str) -> list[str]:
    return [role for role, perms in ROLE_PERMISSIONS.items() if permission in perms]
