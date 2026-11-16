"""Shared customer and charge model."""
from sqlalchemy import text

from .audit import write_audit
from .errors import AppError
from . import lists, scope
from .lists import Column, Filter, ListSpec
from .pii import PII_FIELDS, customer_view


KYC_STATUSES = ("pending", "approved", "rejected")


def list_customers(conn) -> list[dict]:
    rows = conn.execute(text("SELECT * FROM customer ORDER BY id")).mappings()
    return [customer_view(dict(r)) for r in rows]


CUSTOMER_LIST = lists.register(ListSpec(
    name="customers", permission="customer:read", source="customer c",
    columns=(Column("id", "ID", "c.id", searchable=True, sortable=True),
             Column("name", "Name", "c.name", searchable=True, sortable=True),
             Column("email", "Email", "c.email", searchable=True, sortable=True),
             Column("ssn", "SSN", "c.ssn", searchable=True, kind="masked"),
             Column("bank_account", "Bank account", "c.bank_account", searchable=True, kind="masked"),
             Column("kyc_status", "KYC", "c.kyc_status", sortable=True, kind="status")),
    filters=(Filter("kyc_status", "KYC", "c.kyc_status", tuple((s, s) for s in KYC_STATUSES)),),
    customer_id_expr="c.id", tiebreak="c.id", row_view=customer_view, extra={"select": "c.*"}))

_KYC_SINCE = ("COALESCE((SELECT MIN(a.created_at) FROM audit_event a WHERE a.entity = 'customer' "
              "AND a.entity_id = CAST(c.id AS TEXT)), "
              "(SELECT MIN(ch.created_at) FROM charge ch WHERE ch.customer_id = c.id))")

KYC_QUEUE = lists.register(ListSpec(
    name="kyc_queue", permission="kyc:review", source="customer c",
    columns=CUSTOMER_LIST.columns, filters=CUSTOMER_LIST.filters, customer_id_expr="c.id",
    tiebreak="c.id", waiting_since=_KYC_SINCE, row_view=customer_view, extra={"select": "c.*"}))


def _params(**kw) -> dict:
    return {k: str(v) for k, v in kw.items() if v not in (None, "")}


def search_customers(conn, q=None, kyc_status=None, sort=None, direction=None,
                     page: int = 1, page_size: int = 25, user=None, spec: ListSpec = CUSTOMER_LIST) -> dict:
    """Paged customer list, always masked. Search covers the masked last four digits only."""
    result = lists.run(conn, spec, user, _params(q=q, kyc_status=kyc_status, sort=sort, dir=direction,
                                                 page=page, page_size=page_size))
    result["kyc_status"] = kyc_status or ""
    return result


def get_customer(conn, customer_id: int, viewer, permission: str = "customer:read") -> dict:
    """Masked unless the viewer holds pii:read; an unmasked view is audited."""
    scope.check_customer(conn, viewer, permission, customer_id)
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


CHARGE_LIST = lists.register(ListSpec(
    name="charges", permission="customer:read", source=_CHARGE_FROM,
    columns=(Column("id", "ID", "ch.id", searchable=True, sortable=True),
             Column("customer", "Customer", "cu.name", searchable=True, sortable=True),
             Column("email", "Email", "cu.email", searchable=True),
             Column("created_at", "Date", "ch.created_at", sortable=True, kind="date"),
             Column("amount", "Amount", "ch.amount_cents", sortable=True, kind="money"),
             Column("refunded", "Refunded", _COMMITTED, sortable=True, kind="money"),
             Column("remaining", "Remaining", f"ch.amount_cents - {_COMMITTED}", sortable=True, kind="money"),
             Column("kyc_status", "KYC", "cu.kyc_status", sortable=True, kind="status")),
    filters=(Filter("kyc_status", "KYC", "cu.kyc_status", tuple((s, s) for s in KYC_STATUSES)),),
    customer_id_expr="ch.customer_id", default_sort="created_at", default_dir="desc", tiebreak="ch.id",
    extra={"select": _CHARGE_SELECT}))


def search_charges(conn, q=None, customer_id=None, refundable=False, kyc_status=None, sort=None,
                   direction=None, page: int = 1, page_size: int = 25, user=None) -> dict:
    spec = CHARGE_LIST
    where, binds = list(spec.where), {}
    if customer_id is not None:
        where.append("ch.customer_id = :c")
        binds["c"] = customer_id
    if refundable:
        where.append(f"ch.amount_cents - {_COMMITTED} > 0")
    if where != list(spec.where):
        from dataclasses import replace
        spec = replace(spec, where=tuple(where), extra={**spec.extra, "params": binds})
    result = lists.run(conn, spec, user, _params(q=q, kyc_status=kyc_status, sort=sort, dir=direction,
                                                 page=page, page_size=page_size))
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
