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
from typing import Callable

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
    return None  # stage 0 stub: worker A implements


def deliver(engine, message_id: int) -> dict:
    """Attempt delivery of one message (up to MAX_ATTEMPTS in total), auditing every attempt."""
    raise NotImplementedError


def deliver_pending(engine, limit: int = 100) -> list[int]:
    """Deliver every pending message; returns the ids attempted."""
    return []  # stage 0 stub: worker A implements


def retry(engine, actor, message_id: int, reason: str) -> dict:
    """connector:retry only, failed messages only, reason required; audited; then delivers."""
    raise NotImplementedError


def latest_for(conn, entity: str, entity_id) -> dict | None:
    """The newest message for a record (for example the refund page's delivery status)."""
    return None  # stage 0 stub: worker A implements
