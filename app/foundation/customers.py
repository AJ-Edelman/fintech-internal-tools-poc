"""Shared customer and charge model."""
from sqlalchemy import text

from .audit import write_audit
from .errors import AppError
from .listing import run_list
from .pii import PII_FIELDS, customer_view


KYC_STATUSES = ("pending", "approved", "rejected")


def list_customers(conn) -> list[dict]:
    rows = conn.execute(text("SELECT * FROM customer ORDER BY id")).mappings()
    return [customer_view(dict(r)) for r in rows]


def search_customers(conn, q=None, kyc_status=None, sort=None, direction=None,
                     page: int = 1, page_size: int = 25) -> dict:
    """Paged customer list, always masked. Search covers the masked last four digits only."""
    where, params = [], {}
    if kyc_status:
        if kyc_status not in KYC_STATUSES:
            raise AppError(422, "kyc_status must be one of " + ", ".join(KYC_STATUSES))
        where.append("c.kyc_status = :k")
        params["k"] = kyc_status
    result = run_list(
        conn, select="c.*", frm="customer c", where=where, params=params,
        search=("c.id", "c.name", "c.email", "substr(c.ssn, -4)", "substr(c.bank_account, -4)"), q=q,
        sorts={"id": "c.id", "name": "c.name", "email": "c.email", "kyc_status": "c.kyc_status"},
        default_sort="id", tiebreak="c.id", sort=sort, direction=direction,
        page=page, page_size=page_size)
    result["items"] = [customer_view(row) for row in result["items"]]
    result["kyc_status"] = kyc_status or ""
    return result


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


_COMMITTED = ("COALESCE((SELECT SUM(r.amount_cents) FROM refund r WHERE r.charge_id = ch.id "
              "AND r.status IN ('pending_approval', 'approved')), 0)")
_CHARGE_SELECT = (f"ch.id, ch.customer_id, cu.name AS customer_name, cu.kyc_status, ch.amount_cents, "
                  f"ch.created_at, {_COMMITTED} AS committed_cents, "
                  f"ch.amount_cents - {_COMMITTED} AS remaining_cents")
_CHARGE_FROM = "charge ch JOIN customer cu ON cu.id = ch.customer_id"


def list_charges(conn, customer_id: int | None = None) -> list[dict]:
    sql = f"SELECT {_CHARGE_SELECT} FROM {_CHARGE_FROM} "
    params = {}
    if customer_id is not None:
        sql += "WHERE ch.customer_id = :c "
        params["c"] = customer_id
    return [dict(r) for r in conn.execute(text(sql + "ORDER BY ch.id"), params).mappings()]


def get_charge(conn, charge_id: int) -> dict | None:
    row = conn.execute(text(f"SELECT {_CHARGE_SELECT} FROM {_CHARGE_FROM} WHERE ch.id = :i"),
                       {"i": charge_id}).mappings().first()
    return dict(row) if row else None


def search_charges(conn, q=None, customer_id=None, refundable=False, kyc_status=None, sort=None,
                   direction=None, page: int = 1, page_size: int = 25) -> dict:
    where, params = [], {}
    if customer_id is not None:
        where.append("ch.customer_id = :c")
        params["c"] = customer_id
    if refundable:
        where.append(f"ch.amount_cents - {_COMMITTED} > 0")
    if kyc_status:
        if kyc_status not in KYC_STATUSES:
            raise AppError(422, "kyc_status must be one of " + ", ".join(KYC_STATUSES))
        where.append("cu.kyc_status = :k")
        params["k"] = kyc_status
    result = run_list(
        conn, select=_CHARGE_SELECT, frm=_CHARGE_FROM, where=where, params=params,
        search=("ch.id", "cu.name", "cu.email"), q=q,
        sorts={"id": "ch.id", "customer": "cu.name", "created_at": "ch.created_at",
               "amount": "ch.amount_cents", "refunded": _COMMITTED,
               "remaining": f"ch.amount_cents - {_COMMITTED}", "kyc_status": "cu.kyc_status"},
        default_sort="created_at", default_dir="desc", tiebreak="ch.id", sort=sort, direction=direction,
        page=page, page_size=page_size)
    result.update(refundable=bool(refundable), kyc_status=kyc_status or "", customer_id=customer_id)
    return result


def role_assignments(conn) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT u.username, ra.role FROM role_assignment ra JOIN app_user u ON u.id = ra.user_id "
            "ORDER BY u.username, ra.role"
        )
    ).mappings()
    return [dict(r) for r in rows]
