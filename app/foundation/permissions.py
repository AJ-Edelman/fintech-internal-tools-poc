"""The one place where roles map to permissions. Routes check permissions, never role names."""

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "refund_agent": frozenset({"customer:read", "refund:read", "refund:create"}),
    "refund_approver": frozenset({"customer:read", "refund:read", "refund:approve"}),
    "kyc_reviewer": frozenset({"customer:read", "pii:read", "kyc:review"}),
    "admin": frozenset({"access_review:read", "audit:read", "settings:write"}),
}

ALL_PERMISSIONS: frozenset[str] = frozenset().union(*ROLE_PERMISSIONS.values())


def permissions_for(roles) -> frozenset[str]:
    out: set[str] = set()
    for role in roles:
        out |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(out)
