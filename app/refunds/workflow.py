"""Tool 1: refund requests with maker-checker approval, declared on the shared workflow engine."""
import sqlite3

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.foundation import workflow as engine
from app.foundation.audit import SYSTEM_ACTOR
from app.foundation.db import utcnow
from app.foundation.errors import AppError
from app.foundation.pii import redact_text
from datetime import datetime, timedelta, timezone

from app.foundation import settings
from app.foundation.listing import run_list
from app.foundation.settings import get_auto_approve_limit
from app.foundation.workflow import SYSTEM, Transition, Workflow

PENDING, APPROVED, REJECTED = "pending_approval", "approved", "rejected"
STATUSES = (PENDING, APPROVED, REJECTED)


def committed_cents(conn, charge_id: int, exclude_refund_id: int | None = None) -> int:
    return conn.execute(
        text(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM refund WHERE charge_id = :c "
            "AND status IN ('pending_approval', 'approved') AND id IS NOT :x"
        ),
        {"c": charge_id, "x": exclude_refund_id},
    ).scalar()


def guard_valid_request(conn, row, actor):
    amount = row["amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise AppError(422, "amount must be a positive whole number of cents")
    if not row["reason"] or not row["reason"].strip():
        raise AppError(422, "a reason is required")
    charge = conn.execute(
        text("SELECT amount_cents FROM charge WHERE id = :c"), {"c": row["charge_id"]}
    ).first()
    if charge is None:
        raise AppError(422, f"charge {row['charge_id']} does not exist")
    if committed_cents(conn, row["charge_id"]) + amount > charge.amount_cents:
        raise AppError(422, "refund would exceed the charge amount (pending plus approved)")


def guard_customer_kyc_approved(conn, row, actor):
    """Cross-tool rule (tool 2): refunds are created or approved only for KYC-approved customers."""
    if not settings.get(conn, settings.REFUND_REQUIRES_KYC):
        return
    status = conn.execute(
        text("SELECT cu.kyc_status FROM charge ch JOIN customer cu ON cu.id = ch.customer_id "
             "WHERE ch.id = :c"),
        {"c": row["charge_id"]},
    ).scalar()
    if status != "approved":
        raise AppError(422, f"customer KYC status is {status}; it must be approved")


def guard_charge_not_too_old(conn, row, actor):
    days = settings.get(conn, settings.MAX_REFUND_AGE)
    if days is None:
        return
    created = conn.execute(text("SELECT created_at FROM charge WHERE id = :c"),
                           {"c": row["charge_id"]}).scalar()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    if created is not None and created.replace(" ", "T") < cutoff:
        raise AppError(422, f"charge is older than {days} days; refunds are no longer allowed")


def guard_not_own_request(conn, row, actor):
    if row["requested_by"] == actor.username:
        raise AppError(403, "you cannot decide a refund you requested")


def _auto_approval_audit(row, actor):
    return {"approver": SYSTEM_ACTOR, "requested_by": row["requested_by"]}


REFUND_WORKFLOW = Workflow(
    entity="refund",
    table="refund",
    state_column="status",
    states=STATUSES,
    audit_columns=("charge_id", "amount_cents", "requested_by"),
    updated_at_column="updated_at",
    transitions=(
        Transition("request", None, PENDING, "refund:create",
                   guards=(guard_valid_request, guard_customer_kyc_approved, guard_charge_not_too_old),
                   actor_column="requested_by"),
        Transition("auto_approve", PENDING, APPROVED, None, actor_column="decided_by",
                   audit_extra=_auto_approval_audit),
        Transition("approve", PENDING, APPROVED, "refund:approve",
                   guards=(guard_not_own_request, guard_customer_kyc_approved),
                   actor_column="decided_by"),
        Transition("reject", PENDING, REJECTED, "refund:approve", guards=(guard_not_own_request,),
                   actor_column="decided_by"),
    ),
)


def _is_cap_error(exc: Exception) -> bool:
    return "refund cap exceeded" in str(exc)


def request_refund(conn, actor, charge_id: int, amount_cents: int, reason: str) -> dict:
    values = {
        "charge_id": charge_id,
        "amount_cents": amount_cents,
        # Free text is stored redacted: refund readers do not hold pii:read.
        "reason": redact_text(reason.strip()) if isinstance(reason, str) else reason,
        "created_at": utcnow(),
    }
    try:
        refund_id = engine.create(conn, REFUND_WORKFLOW, "request", actor, values, values["reason"])
    except (IntegrityError, sqlite3.IntegrityError) as exc:
        if _is_cap_error(exc):
            raise AppError(422, "refund would exceed the charge amount (pending plus approved)")
        raise
    # Threshold: automatic only while the charge's pending + approved total stays within the limit.
    if committed_cents(conn, charge_id) <= get_auto_approve_limit(conn):
        engine.fire(conn, REFUND_WORKFLOW, "auto_approve", refund_id, SYSTEM,
                    "within auto-approve limit")
    return get_refund(conn, refund_id)


def decide_refund(conn, actor, refund_id: int, decision: str, reason: str) -> dict:
    if decision not in ("approve", "reject"):
        raise AppError(422, "decision must be approve or reject")
    if "refund:approve" not in actor.permissions:
        raise AppError(403, "missing permission refund:approve")
    if not isinstance(reason, str) or not reason.strip():
        raise AppError(422, "a reason is required")
    engine.fire(conn, REFUND_WORKFLOW, decision, refund_id, actor, reason.strip())
    return get_refund(conn, refund_id)


def get_refund(conn, refund_id: int) -> dict:
    row = conn.execute(text(f"SELECT {_REFUND_SELECT} FROM {_REFUND_FROM} WHERE r.id = :i"),
                       {"i": refund_id}).mappings().first()
    if row is None:
        raise AppError(404, f"refund {refund_id} not found")
    return dict(row)


_REFUND_SELECT = ("r.*, ch.customer_id, cu.name AS customer_name, ch.amount_cents AS charge_amount_cents")
_REFUND_FROM = "refund r JOIN charge ch ON ch.id = r.charge_id JOIN customer cu ON cu.id = ch.customer_id"
_REFUND_SORTS = {"id": "r.id", "amount": "r.amount_cents", "status": "r.status", "customer": "cu.name",
                 "charge": "r.charge_id", "requested_by": "r.requested_by", "decided_by": "r.decided_by",
                 "created_at": "r.created_at"}


def list_refunds(conn, status: str | None, page: int, page_size: int, q: str | None = None,
                 sort: str | None = None, direction: str | None = None) -> dict:
    if status is not None and status not in STATUSES:
        raise AppError(422, "status must be one of " + ", ".join(STATUSES))
    where, params = [], {}
    if status is not None:
        where, params = ["r.status = :s"], {"s": status}
    result = run_list(
        conn, select=_REFUND_SELECT, frm=_REFUND_FROM, where=where, params=params,
        search=("r.id", "r.charge_id", "cu.name", "r.requested_by", "r.decided_by", "r.reason"), q=q,
        sorts=_REFUND_SORTS, default_sort="id", tiebreak="r.id", sort=sort, direction=direction,
        page=page, page_size=page_size)
    result["status"] = status
    return result
