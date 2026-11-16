"""Shared customer and charge model."""
from sqlalchemy import text

from .audit import write_audit
from .errors import AppError
from .pii import PII_FIELDS, customer_view


def list_customers(conn) -> list[dict]:
    rows = conn.execute(text("SELECT * FROM customer ORDER BY id")).mappings()
    return [customer_view(dict(r)) for r in rows]


def get_customer(conn, customer_id: int, viewer) -> dict:
    """Masked unless the viewer holds pii:read; an unmasked view is audited."""
    row = conn.execute(text("SELECT * FROM customer WHERE id = :i"), {"i": customer_id}).mappings().first()
    if row is None:
        raise AppError(404, f"customer {customer_id} not found")
    reveal = "pii:read" in viewer.permissions
    if reveal:
        write_audit(conn, actor=viewer.username, action="customer.pii_view", entity="customer",
                    entity_id=customer_id, before=None, after={"fields": list(PII_FIELDS)},
                    reason="customer detail view")
    return customer_view(dict(row), reveal=reveal)


def list_charges(conn, customer_id: int | None = None) -> list[dict]:
    sql = (
        "SELECT ch.id, ch.customer_id, cu.name AS customer_name, ch.amount_cents, ch.created_at, "
        "COALESCE((SELECT SUM(r.amount_cents) FROM refund r WHERE r.charge_id = ch.id "
        "AND r.status IN ('pending_approval', 'approved')), 0) AS committed_cents "
        "FROM charge ch JOIN customer cu ON cu.id = ch.customer_id "
    )
    params = {}
    if customer_id is not None:
        sql += "WHERE ch.customer_id = :c "
        params["c"] = customer_id
    return [dict(r) for r in conn.execute(text(sql + "ORDER BY ch.id"), params).mappings()]


def role_assignments(conn) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT u.username, ra.role FROM role_assignment ra JOIN app_user u ON u.id = ra.user_id "
            "ORDER BY u.username, ra.role"
        )
    ).mappings()
    return [dict(r) for r in rows]
