"""Stored settings. Each change is audited with the old and new value."""
from sqlalchemy import text

from .audit import write_audit
from .errors import AppError

AUTO_APPROVE_LIMIT = "auto_approve_limit_cents"
AUTO_APPROVE_LIMIT_MAX_CENTS = 75_000


def get_auto_approve_limit(conn) -> int:
    row = conn.execute(text("SELECT value FROM setting WHERE key = :k"), {"k": AUTO_APPROVE_LIMIT}).first()
    return int(row.value)


def set_auto_approve_limit(conn, actor, value_cents, reason: str) -> int:
    if "settings:write" not in actor.permissions:
        raise AppError(403, "missing permission settings:write")
    if isinstance(value_cents, bool) or not isinstance(value_cents, int):
        raise AppError(422, "limit must be a whole number of cents")
    if value_cents < 0 or value_cents > AUTO_APPROVE_LIMIT_MAX_CENTS:
        raise AppError(422, f"limit must be between 0 and {AUTO_APPROVE_LIMIT_MAX_CENTS} cents")
    if not reason or not reason.strip():
        raise AppError(422, "a reason is required")
    old = get_auto_approve_limit(conn)
    conn.execute(
        text("UPDATE setting SET value = :v WHERE key = :k"),
        {"v": str(value_cents), "k": AUTO_APPROVE_LIMIT},
    )
    write_audit(conn, actor=actor.username, action="setting.change", entity="setting",
                entity_id=AUTO_APPROVE_LIMIT, before={"value": old}, after={"value": value_cents},
                reason=reason.strip())
    return value_cents
