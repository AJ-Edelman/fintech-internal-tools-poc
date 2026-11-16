"""Record-level access by region (BUILD_SPEC_2 item 3). Owner after stage 0: worker C.

Contract: a caller acts only on records whose customer is in a region they hold for the
permission in use. `User.scopes` maps permission -> frozenset of "US", "EU", "ALL".
Out of scope means 404 (never 403) and the record is not counted. The system actor is unscoped.
"""

REGIONS = ("US", "EU")
ALL = "ALL"


def regions_for(user, permission: str) -> frozenset[str] | None:
    """Regions the user holds for `permission`; None means every region."""
    return None  # stage 0 stub: worker C implements


def customer_filter(user, permission: str, customer_id_expr: str) -> tuple[str, dict]:
    """SQL condition limiting `customer_id_expr` to the user's regions, plus its params.
    Lists, counts and searches AND this into their WHERE clause."""
    return "1 = 1", {}  # stage 0 stub: worker C implements


def check_customer(conn, user, permission: str, customer_id) -> None:
    """Raise AppError(404) unless the customer is in the user's regions for `permission`."""
    return None  # stage 0 stub: worker C implements
