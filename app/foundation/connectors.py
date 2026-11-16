"""Outbound connections (BUILD_SPEC_2 item 1). Owner after stage 0: worker A.

Contract:
- A transition declares `sends=(Outbound(...),)`. The workflow engine calls `enqueue` on the
  caller's connection, right after the transition's audit event, so the message, the state change
  and the audit event commit together or not at all.
- `deliver_pending` runs after the request's transaction has committed (an app middleware in
  app/main.py calls it). Each attempt and outcome is an audit event. `pending` -> `sent`, or
  `failed` after MAX_ATTEMPTS attempts.
- The idempotency key is f"{kind}:{entity}:{entity_id}"; the receiver applies a key at most once.
- Payloads are redacted with the PII rules before they are stored or sent.
"""
from dataclasses import dataclass
import json
from typing import Callable

from sqlalchemy import text

from .audit import SYSTEM_ACTOR, write_audit
from .db import utcnow
from .errors import AppError
from .fake_services import get_fake
from .pii import redact

MAX_ATTEMPTS = 3
PENDING, SENT, FAILED = "pending", "sent", "failed"
STATUSES = (PENDING, SENT, FAILED)


@dataclass(frozen=True)
class Outbound:
    connector: str  # receiver name; its address is the setting f"connector_{connector}_url"
    kind: str  # message type, e.g. "refund.payout"
    payload: Callable[[dict, object], dict]  # payload(row_after_transition, actor) -> dict


def idempotency_key(kind: str, entity: str, entity_id) -> str:
    return f"{kind}:{entity}:{entity_id}"


def enqueue(conn, *, connector: str, kind: str, entity: str, entity_id, payload: dict,
            audit_event_id: int) -> int | None:
    """Insert one pending message on the caller's connection. Returns its id."""
    key = idempotency_key(kind, entity, entity_id)
    now = utcnow()
    conn.execute(text(
        "INSERT INTO connector_message "
        "(connector, kind, entity, entity_id, idempotency_key, payload, status, audit_event_id, "
        "created_at, updated_at) VALUES (:connector, :kind, :entity, :entity_id, :key, :payload, "
        ":status, :audit_id, :now, :now) ON CONFLICT(idempotency_key) DO NOTHING"
    ), {"connector": connector, "kind": kind, "entity": entity, "entity_id": str(entity_id),
        "key": key, "payload": json.dumps(redact(payload), sort_keys=True), "status": PENDING,
        "audit_id": audit_event_id, "now": now})
    return conn.execute(text("SELECT id FROM connector_message WHERE idempotency_key = :key"),
                        {"key": key}).scalar_one()


def _message(conn, message_id: int) -> dict:
    row = conn.execute(text("SELECT * FROM connector_message WHERE id = :id"),
                       {"id": message_id}).mappings().first()
    if row is None:
        raise AppError(404, f"connector message {message_id} not found")
    return dict(row)


def _receiver(conn, connector: str):
    value = conn.execute(text("SELECT value FROM setting WHERE key = :key"),
                         {"key": f"connector_{connector}_url"}).scalar_one_or_none()
    if value is None:
        raise ValueError(f"receiver address for {connector} is not configured")
    address = json.loads(value)
    if not isinstance(address, str) or not address.startswith("fake://"):
        raise ValueError("only fake:// receiver addresses are supported")
    return get_fake(address.removeprefix("fake://"))


def deliver(engine, message_id: int) -> dict:
    """Attempt delivery of one message (up to MAX_ATTEMPTS in total), auditing every attempt."""
    while True:
        # The in-process receiver call is short. The lock serializes concurrent delivery/retry,
        # and the receiver's key also protects a resend after an uncertain outcome or rollback.
        with engine.begin() as conn:
            row = _message(conn, message_id)
            if row["status"] != PENDING:
                return row
            attempt = row["attempts"] + 1
            error = None
            try:
                outcome = _receiver(conn, row["connector"]).receive(
                    row["idempotency_key"], json.loads(row["payload"]))
                status = SENT
            except Exception as exc:
                error = redact(str(exc))
                outcome = "error"
                status = FAILED if attempt >= MAX_ATTEMPTS else PENDING
            now = utcnow()
            conn.execute(text(
                "UPDATE connector_message SET status = :status, attempts = :attempts, "
                "last_error = :error, updated_at = :now WHERE id = :id"
            ), {"status": status, "attempts": attempt, "error": error, "now": now,
                "id": message_id})
            write_audit(conn, actor=SYSTEM_ACTOR, action="connector.attempt",
                        entity="connector_message", entity_id=message_id,
                        before={"status": row["status"], "attempts": row["attempts"]},
                        after={"status": status, "attempts": attempt, "outcome": outcome,
                               "last_error": error}, reason=error)
            row.update(status=status, attempts=attempt, last_error=error, updated_at=now)
        if status != PENDING:
            return row


def deliver_pending(engine, limit: int = 100) -> list[int]:
    """Deliver every pending message; returns the ids attempted."""
    with engine.begin() as conn:
        ids = list(conn.execute(text(
            "SELECT id FROM connector_message WHERE status = :status ORDER BY id LIMIT :limit"
        ), {"status": PENDING, "limit": max(0, limit)}).scalars())
    for message_id in ids:
        deliver(engine, message_id)
    return ids


def retry(engine, actor, message_id: int, reason: str) -> dict:
    """connector:retry only, failed messages only, reason required; audited; then delivers."""
    if "connector:retry" not in actor.permissions:
        raise AppError(403, "missing permission connector:retry")
    if not isinstance(reason, str) or not reason.strip():
        raise AppError(422, "a reason is required")
    with engine.begin() as conn:
        row = _message(conn, message_id)
        if row["status"] != FAILED:
            raise AppError(409, "only failed connector messages can be retried")
        conn.execute(text(
            "UPDATE connector_message SET status = :status, attempts = 0, last_error = NULL, "
            "updated_at = :now WHERE id = :id"
        ), {"status": PENDING, "now": utcnow(), "id": message_id})
        write_audit(conn, actor=actor.username, action="connector.retry",
                    entity="connector_message", entity_id=message_id,
                    before={"status": row["status"], "attempts": row["attempts"]},
                    after={"status": PENDING, "attempts": 0}, reason=reason.strip())
    return deliver(engine, message_id)


def latest_for(conn, entity: str, entity_id) -> dict | None:
    """The newest message for a record (for example the refund page's delivery status)."""
    row = conn.execute(text(
        "SELECT * FROM connector_message WHERE entity = :entity AND entity_id = :id "
        "ORDER BY id DESC LIMIT 1"
    ), {"entity": entity, "id": str(entity_id)}).mappings().first()
    return dict(row) if row is not None else None
