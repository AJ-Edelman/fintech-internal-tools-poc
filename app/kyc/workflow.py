"""Tool 2: KYC review, declared on the shared workflow engine. A review workflow only."""
from sqlalchemy import text

from app.foundation import workflow as engine
from app.foundation.errors import AppError
from app.foundation.pii import customer_view
from app.foundation.workflow import Transition, Workflow

PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"

KYC_WORKFLOW = Workflow(
    entity="customer",
    table="customer",
    state_column="kyc_status",
    states=(PENDING, APPROVED, REJECTED),
    transitions=(
        Transition("kyc_approve", PENDING, APPROVED, "kyc:review"),
        Transition("kyc_reject", PENDING, REJECTED, "kyc:review"),
    ),
)


def decide_kyc(conn, actor, customer_id: int, decision: str, reason: str) -> dict:
    if "kyc:review" not in actor.permissions:
        raise AppError(403, "missing permission kyc:review")
    if decision not in ("approve", "reject"):
        raise AppError(422, "decision must be approve or reject")
    if not isinstance(reason, str) or not reason.strip():
        raise AppError(422, "a reason is required")
    row = engine.fire(conn, KYC_WORKFLOW, f"kyc_{decision}", customer_id, actor, reason.strip())
    return customer_view(row)


def pending_queue(conn) -> list[dict]:
    rows = conn.execute(
        text("SELECT * FROM customer WHERE kyc_status = 'pending' ORDER BY id")
    ).mappings()
    return [customer_view(dict(r)) for r in rows]
