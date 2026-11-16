"""Stored settings. Each change is audited with the old and new value."""
import json
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from sqlalchemy import text

from .audit import write_audit
from .errors import AppError
from .pii import redact_text

AUTO_APPROVE_LIMIT = "auto_approve_limit_cents"
AUTO_APPROVE_LIMIT_MAX_CENTS = 75_000
SESSION_TIMEOUT = "session_timeout_minutes"
REFUND_REQUIRES_KYC = "refund_requires_kyc"
MAX_REFUND_AGE = "max_refund_age_days"
OTHER = "Other"


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    kind: str  # cents | int | bool | optional_int | list
    help: str
    minimum: int | None = None
    maximum: int | None = None
    group: str = "Refunds"


SPECS: dict[str, Spec] = {s.key: s for s in (
    Spec(AUTO_APPROVE_LIMIT, "Auto-approve limit", "cents",
         "Refunds that keep a charge's pending plus approved total at or under this amount are approved "
         "automatically.", 0, AUTO_APPROVE_LIMIT_MAX_CENTS),
    Spec(MAX_REFUND_AGE, "Maximum refund age (days)", "optional_int",
         "Refunds cannot be requested on charges older than this. Leave blank for no limit.", 1, 3650),
    Spec(REFUND_REQUIRES_KYC, "Refunds require approved KYC", "bool",
         "When on, a refund can be created or approved only for a customer whose KYC is approved."),
    Spec(SESSION_TIMEOUT, "Session timeout (minutes)", "int",
         "Users are logged out after this many minutes without activity.", 1, 1440, "Security"),
    Spec("reasons_refund_request", "Refund request reasons", "list",
         "Shown to agents when they request a refund.", group="Reason lists"),
    Spec("reasons_refund_approve", "Refund approval reasons", "list",
         "Shown to approvers when they approve a refund.", group="Reason lists"),
    Spec("reasons_refund_reject", "Refund rejection reasons", "list",
         "Shown to approvers when they reject a refund.", group="Reason lists"),
    Spec("reasons_kyc_approve", "KYC approval reasons", "list",
         "Shown to KYC reviewers when they approve a customer.", group="Reason lists"),
    Spec("reasons_kyc_reject", "KYC rejection reasons", "list",
         "Shown to KYC reviewers when they reject a customer.", group="Reason lists"),
)}


def get(conn, key: str):
    row = conn.execute(text("SELECT value FROM setting WHERE key = :k"), {"k": key}).first()
    if row is None:
        raise AppError(404, f"setting {key} not found")
    return json.loads(row.value)


def all_settings(conn) -> list[dict]:
    return [{"spec": spec, "value": get(conn, key)} for key, spec in SPECS.items()]


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate(spec: Spec, value):
    if spec.kind in ("cents", "int", "optional_int"):
        if value is None and spec.kind == "optional_int":
            return None
        if not _is_int(value):
            unit = "cents" if spec.kind == "cents" else "a whole number"
            raise AppError(422, f"{spec.label.lower()} must be a whole number of cents"
                           if spec.kind == "cents" else f"{spec.label} must be {unit}")
        if value < spec.minimum or value > spec.maximum:
            if spec.kind == "cents":
                raise AppError(422, f"limit must be between ${spec.minimum / 100:,.2f} and "
                                    f"${spec.maximum / 100:,.2f} ({spec.minimum} to {spec.maximum} cents)")
            raise AppError(422, f"{spec.label} must be between {spec.minimum} and {spec.maximum}")
        return value
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise AppError(422, f"{spec.label} must be on or off")
        return value
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise AppError(422, f"{spec.label} must be a list of reasons")
    cleaned = []
    for item in (redact_text(v.strip()) for v in value):
        if item and item.lower() != OTHER.lower() and item not in cleaned:
            cleaned.append(item)
    if not cleaned or len(cleaned) > 20 or any(len(v) > 80 for v in cleaned):
        raise AppError(422, f"{spec.label} needs 1 to 20 reasons of at most 80 characters each")
    return cleaned


def set_value(conn, actor, key: str, value, reason: str | None = None):
    if "settings:write" not in actor.permissions:
        raise AppError(403, "missing permission settings:write")
    spec = SPECS.get(key)
    if spec is None:
        raise AppError(404, f"setting {key} not found")
    value = _validate(spec, value)
    old = get(conn, key)
    reason = reason.strip() if isinstance(reason, str) else ""
    if key in (REFUND_REQUIRES_KYC, MAX_REFUND_AGE) and not reason:
        raise AppError(422, "a reason is required")
    conn.execute(text("UPDATE setting SET value = :v WHERE key = :k"), {"v": json.dumps(value), "k": key})
    write_audit(conn, actor=actor.username, action="setting.change", entity="setting", entity_id=key,
                before={"value": old}, after={"value": value},
                reason=redact_text(reason) if reason else None)
    return value


def get_auto_approve_limit(conn) -> int:
    return int(get(conn, AUTO_APPROVE_LIMIT))


def set_auto_approve_limit(conn, actor, value_cents, reason: str | None = None) -> int:
    """A reason is optional: the audit event already records who, when, old and new value."""
    return set_value(conn, actor, AUTO_APPROVE_LIMIT, value_cents, reason)


def reason_options(conn, key: str) -> list[str]:
    return list(get(conn, key))


def resolve_reason(conn, key: str, choice: str | None, other: str | None, typed: str | None = None) -> str:
    """Turn a dropdown choice (or 'Other' plus typed text) into the reason to store."""
    if not choice:
        if typed and typed.strip():
            return typed.strip()
        raise AppError(422, "a reason is required")
    if choice == OTHER:
        if not other or not other.strip():
            raise AppError(422, "type a reason when you choose Other")
        return other.strip()
    if choice not in reason_options(conn, key):
        raise AppError(422, "choose a reason from the list")
    return choice


def refund_rules(conn) -> dict:
    """The two stored rules that can block a refund request, in the form lists need to show them."""
    days = get(conn, MAX_REFUND_AGE)
    cutoff = None
    if days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    return {"requires_kyc": bool(get(conn, REFUND_REQUIRES_KYC)), "max_age_days": days, "cutoff": cutoff}
