"""Record-level access by region (BUILD_SPEC_2 item 3). Owner after stage 0: worker C.

Contract: a caller acts only on records whose customer is in a region they hold for the
permission in use. `User.scopes` maps permission -> frozenset of "US", "EU", "ALL".
Out of scope means 404 (never 403) and the record is not counted. The system actor is unscoped.
"""
from sqlalchemy import text

from .errors import AppError

REGIONS = ("US", "EU")
ALL = "ALL"


def regions_for(user, permission: str) -> frozenset[str] | None:
    """Regions the user holds for `permission`; None means every region."""
    if user is None:
        return frozenset()
    if getattr(user, "is_system", False):
        return None
    scopes = getattr(user, "scopes", None) or {}
    if not scopes:
        # Users built in code (seed, scripts) carry no scopes: they act unscoped.
        # Every request-bound user gets scopes from auth.user_from_request.
        return None
    held = scopes.get(permission, frozenset())
    if ALL in held:
        return None
    return frozenset(r for r in held if r in REGIONS)


def customer_filter(user, permission: str, customer_id_expr: str) -> tuple[str, dict]:
    """SQL condition limiting `customer_id_expr` to the user's regions, plus its params.
    Lists, counts and searches AND this into their WHERE clause."""
    regions = regions_for(user, permission)
    if regions is None:
        return "1 = 1", {}
    if not regions:
        return "1 = 0", {}
    names = {f"scope_region_{i}": r for i, r in enumerate(sorted(regions))}
    marks = ", ".join(f":{k}" for k in names)
    return (f"{customer_id_expr} IN (SELECT scope_c.id FROM customer scope_c "
            f"WHERE scope_c.region IN ({marks}))", names)


def check_customer(conn, user, permission: str, customer_id) -> None:
    """Raise AppError(404) unless the customer is in the user's regions for `permission`."""
    regions = regions_for(user, permission)
    if regions is None:
        return
    region = conn.execute(text("SELECT region FROM customer WHERE id = :i"), {"i": customer_id}).scalar()
    if region is None or region not in regions:
        raise AppError(404, f"customer {customer_id} not found")
