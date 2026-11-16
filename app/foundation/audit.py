"""Append-only audit log. Always written on the caller's connection so it commits with the change."""
import json

from sqlalchemy import text

from .db import utcnow
from .errors import AppError
from .listing import run_list
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


def search(conn, q=None, actor=None, action=None, entity=None, date_from=None, date_to=None,
           sort=None, direction=None, page: int = 1, page_size: int = 50) -> dict:
    where, params = [], {}
    for column, value in (("actor", actor), ("action", action), ("entity", entity)):
        if value:
            where.append(f"a.{column} = :{column}")
            params[column] = value
    for name, value, op in (("date_from", date_from, ">="), ("date_to", date_to, "<=")):
        if value:
            if len(value) != 10 or value[4] != "-" or value[7] != "-":
                raise AppError(422, f"{name} must be a date like 2026-01-31")
            where.append(f"substr(a.created_at, 1, 10) {op} :{name}")
            params[name] = value
    result = run_list(
        conn, select="a.*", frm="audit_event a", where=where, params=params,
        search=("a.actor", "a.action", "a.entity", "a.entity_id", "a.reason", "a.before", "a.after"), q=q,
        sorts={"id": "a.id", "when": "a.created_at", "actor": "a.actor", "action": "a.action",
               "entity": "a.entity"},
        default_sort="id", default_dir="desc", tiebreak="a.id", sort=sort, direction=direction,
        page=page, page_size=page_size)
    result["items"] = [_row(r) for r in result["items"]]
    result.update(actor=actor or "", action=action or "", entity=entity or "",
                  date_from=date_from or "", date_to=date_to or "")
    return result


def facets(conn) -> dict:
    return {column: [r[0] for r in conn.execute(
        text(f"SELECT DISTINCT {column} FROM audit_event ORDER BY {column}"))]
        for column in ("actor", "action", "entity")}


def _money(cents) -> str:
    return f"${cents / 100:,.2f}" if isinstance(cents, int) else str(cents)


_SETTING_NAMES = {
    "auto_approve_limit_cents": "the auto-approve limit",
    "session_timeout_minutes": "the session timeout",
    "refund_requires_kyc": "the rule that refunds require approved KYC",
    "max_refund_age_days": "the maximum refund age",
}


def _setting_value(key: str, value) -> str:
    if key == "auto_approve_limit_cents":
        return _money(value)
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None:
        return "no limit"
    if isinstance(value, list):
        return f"{len(value)} reasons"
    return {"session_timeout_minutes": f"{value} minutes", "max_refund_age_days": f"{value} days"}.get(key, str(value))


def describe(e: dict) -> dict:
    """A plain-language sentence and a 'from -> to' line for one audit event."""
    before, after, action = e.get("before") or {}, e.get("after") or {}, e["action"]
    what, change = action, ""
    if action == "refund.request":
        what = f"requested refund #{e['entity_id']} of {_money(after.get('amount_cents'))} on charge #{after.get('charge_id')}"
    elif action == "refund.auto_approve":
        what = f"approved refund #{e['entity_id']} automatically (within the auto-approve limit)"
    elif action in ("refund.approve", "refund.reject"):
        what = f"{'approved' if action.endswith('approve') else 'rejected'} refund #{e['entity_id']}"
    elif action in ("customer.kyc_approve", "customer.kyc_reject"):
        what = f"{'approved' if action.endswith('approve') else 'rejected'} KYC for customer #{e['entity_id']}"
    elif action == "customer.pii_view":
        what = f"viewed the full SSN and bank account of customer #{e['entity_id']}"
    elif action == "setting.change":
        key = e["entity_id"]
        what = f"changed {_SETTING_NAMES.get(key, key.replace('_', ' '))}"
        change = f"{_setting_value(key, before.get('value'))} \u2192 {_setting_value(key, after.get('value'))}"
    elif action == "user.create":
        what = f"added user {after.get('username')}"
        change = "roles: " + (", ".join(after.get("roles", [])) or "none")
    elif action == "user.roles_change":
        what = f"changed the access of {after.get('username')}"
        change = f"{', '.join(before.get('roles', [])) or 'none'} \u2192 {', '.join(after.get('roles', [])) or 'none'}"
    elif action in ("user.deactivate", "user.reactivate"):
        what = f"{'deactivated' if action.endswith('deactivate') else 'reactivated'} user {after.get('username')}"
    elif action.startswith("seed."):
        what = "loaded seed data"
    if not change and "status" in before and "status" in after:
        change = f"{before['status']} \u2192 {after['status']}".replace("_", " ")
    if not change and "kyc_status" in before and "kyc_status" in after:
        change = f"{before['kyc_status']} \u2192 {after['kyc_status']}"
    link = {"refund": f"/refunds/{e['entity_id']}", "customer": f"/customers/{e['entity_id']}"}.get(e["entity"])
    return {**e, "what": what, "change": change, "link": link}
