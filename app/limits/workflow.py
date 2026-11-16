"""Tool 3: account limit overrides, declared on the shared workflow engine. No automatic approval."""
import sqlite3

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.foundation import workflow as engine
from app.foundation.connectors import Outbound
from app.foundation.db import utcnow
from app.foundation.errors import AppError
from app.foundation.pii import redact_text
from app.foundation.workflow import Transition, Workflow

PENDING, APPROVED, REJECTED = "pending_approval", "approved", "rejected"
STATUSES = (PENDING, APPROVED, REJECTED)
MAX_LIMIT_CENTS = 5_000_000


def _customer(conn, customer_id):
    return conn.execute(text("SELECT id, kyc_status, daily_limit_cents FROM customer WHERE id = :i"),
                        {"i": customer_id}).mappings().first()


def guard_kyc_approved(conn, row, actor):
    customer = _customer(conn, row["customer_id"])
    if customer is None:
        raise AppError(422, f"customer {row['customer_id']} does not exist")
    if customer["kyc_status"] != "approved":
        raise AppError(422, f"customer KYC status is {customer['kyc_status']}; it must be approved")


def guard_valid_request(conn, row, actor):
    requested = row["requested_limit_cents"]
    if isinstance(requested, bool) or not isinstance(requested, int):
        raise AppError(422, "requested limit must be a whole number of cents")
    if not row["reason"] or not row["reason"].strip():
        raise AppError(422, "a reason is required")
    customer = _customer(conn, row["customer_id"])
    if customer is None:
        raise AppError(422, f"customer {row['customer_id']} does not exist")
    if requested <= customer["daily_limit_cents"]:
        raise AppError(422, "requested limit must be above the current limit")
    if requested > MAX_LIMIT_CENTS:
        raise AppError(422, f"requested limit must be at most {MAX_LIMIT_CENTS} cents")
    pending = conn.execute(text("SELECT 1 FROM limit_override WHERE customer_id = :c AND status = :p"),
                           {"c": row["customer_id"], "p": PENDING}).first()
    if pending:
        raise AppError(422, "this customer already has a pending limit request")


def guard_still_above(conn, row, actor):
    if row["requested_limit_cents"] <= _customer(conn, row["customer_id"])["daily_limit_cents"]:
        raise AppError(422, "requested limit is no longer above the current limit")


def guard_not_own_request(conn, row, actor):
    if row["requested_by"] == actor.username:
        raise AppError(403, "you cannot decide a limit request you made")


def _ledger(row, actor):
    return {"override_id": row["id"], "customer_id": row["customer_id"],
            "daily_limit_cents": row["requested_limit_cents"]}


def _new_limit(row, actor):
    return {"daily_limit_cents": row["requested_limit_cents"]}


LIMIT_WORKFLOW = Workflow(
    entity="limit_override",
    table="limit_override",
    state_column="status",
    states=STATUSES,
    audit_columns=("customer_id", "current_limit_cents", "requested_limit_cents", "requested_by"),
    updated_at_column="updated_at",
    customer_of=lambda conn, row: row["customer_id"],
    transitions=(
        Transition("request", None, PENDING, "limit:request",
                   guards=(guard_kyc_approved, guard_valid_request), actor_column="requested_by"),
        Transition("approve", PENDING, APPROVED, "limit:approve",
                   guards=(guard_not_own_request, guard_kyc_approved, guard_still_above),
                   actor_column="decided_by", audit_extra=_new_limit,
                   sends=(Outbound("ledger", "limit.update", _ledger),)),
        Transition("reject", PENDING, REJECTED, "limit:approve", guards=(guard_not_own_request,),
                   actor_column="decided_by"),
    ),
)


def request_override(conn, actor, customer_id: int, requested_limit_cents: int, reason: str) -> dict:
    customer = _customer(conn, customer_id)
    values = {
        "customer_id": customer_id,
        "current_limit_cents": customer["daily_limit_cents"] if customer else 0,
        "requested_limit_cents": requested_limit_cents,
        "reason": redact_text(reason.strip()) if isinstance(reason, str) else reason,
        "created_at": utcnow(),
    }
    try:
        new_id = engine.create(conn, LIMIT_WORKFLOW, "request", actor, values, values["reason"])
    except (IntegrityError, sqlite3.IntegrityError) as exc:
        if "UNIQUE" in str(exc):
            raise AppError(422, "this customer already has a pending limit request")
        raise
    return get_override(conn, new_id)


def decide_override(conn, actor, override_id: int, decision: str, reason: str) -> dict:
    if decision not in ("approve", "reject"):
        raise AppError(422, "decision must be approve or reject")
    if "limit:approve" not in actor.permissions:
        raise AppError(403, "missing permission limit:approve")
    if not isinstance(reason, str) or not reason.strip():
        raise AppError(422, "a reason is required")
    row = engine.fire(conn, LIMIT_WORKFLOW, decision, override_id, actor, redact_text(reason.strip()))
    if decision == "approve":
        # Same transaction as the transition, its audit event and the ledger message.
        conn.execute(text("UPDATE customer SET daily_limit_cents = :v WHERE id = :c"),
                     {"v": row["requested_limit_cents"], "c": row["customer_id"]})
    return get_override(conn, override_id)


LIMIT_SELECT = "lo.*, cu.name AS customer_name, cu.daily_limit_cents AS customer_limit_cents"
LIMIT_FROM = "limit_override lo JOIN customer cu ON cu.id = lo.customer_id"


def get_override(conn, override_id: int) -> dict:
    row = conn.execute(text(f"SELECT {LIMIT_SELECT} FROM {LIMIT_FROM} WHERE lo.id = :i"),
                       {"i": override_id}).mappings().first()
    if row is None:
        raise AppError(404, f"limit request {override_id} not found")
    return dict(row)
