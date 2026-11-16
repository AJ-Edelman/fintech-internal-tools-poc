"""Append-only audit log. Always written on the caller's connection so it commits with the change."""
import json

from sqlalchemy import text

from .db import utcnow
from .pii import redact

SYSTEM_ACTOR = "system"


def write_audit(conn, *, actor: str, action: str, entity: str, entity_id, before=None,
                after=None, reason: str | None = None) -> None:
    conn.execute(
        text(
            "INSERT INTO audit_event (actor, action, entity, entity_id, before, after, reason, created_at) "
            "VALUES (:actor, :action, :entity, :entity_id, :before, :after, :reason, :created_at)"
        ),
        {
            "actor": actor,
            "action": action,
            "entity": entity,
            "entity_id": str(entity_id),
            "before": None if before is None else json.dumps(redact(before), sort_keys=True),
            "after": None if after is None else json.dumps(redact(after), sort_keys=True),
            "reason": None if reason is None else redact(reason),
            "created_at": utcnow(),
        },
    )


def _row(r) -> dict:
    d = dict(r)
    d["before"] = json.loads(d["before"]) if d["before"] else None
    d["after"] = json.loads(d["after"]) if d["after"] else None
    return d


def history(conn, entity: str, entity_id) -> list[dict]:
    rows = conn.execute(
        text("SELECT * FROM audit_event WHERE entity = :e AND entity_id = :i ORDER BY id"),
        {"e": entity, "i": str(entity_id)},
    ).mappings()
    return [_row(r) for r in rows]


def recent(conn, limit: int = 100, offset: int = 0) -> list[dict]:
    rows = conn.execute(
        text("SELECT * FROM audit_event ORDER BY id DESC LIMIT :l OFFSET :o"),
        {"l": limit, "o": offset},
    ).mappings()
    return [_row(r) for r in rows]
