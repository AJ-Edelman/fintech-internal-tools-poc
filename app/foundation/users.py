"""Admin user management: add users, change roles, deactivate. Every change is audited."""
import re
from dataclasses import replace

from sqlalchemy import text

from .audit import write_audit
from .auth import create_user
from .errors import AppError
from . import lists
from .permissions import PERMISSION_LABELS, ROLE_LABELS, ROLE_PERMISSIONS, roles_granting

MANAGE = "user:manage"
_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,31}$")
MIN_PASSWORD = 8


REGION_CHOICES = ("ALL", "US", "EU")


def _clean_region(region) -> str:
    region = (region or "ALL").strip().upper() if isinstance(region, str) else region
    if region not in REGION_CHOICES:
        raise AppError(422, "region must be one of " + ", ".join(REGION_CHOICES))
    return region


def _regions_of(conn, user_id: int) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute(
        text("SELECT role, region FROM role_assignment WHERE user_id = :u"), {"u": user_id})}


def role_assignments(conn) -> list[dict]:
    """Every assignment with its region, for the access review."""
    rows = conn.execute(text(
        "SELECT u.username, ra.role, ra.region FROM role_assignment ra JOIN app_user u ON u.id = ra.user_id "
        "ORDER BY u.username, ra.role")).mappings()
    return [dict(r) for r in rows]


def _roles_of(conn, user_id: int) -> list[str]:
    return [r[0] for r in conn.execute(
        text("SELECT role FROM role_assignment WHERE user_id = :u ORDER BY role"), {"u": user_id})]


def _describe(row: dict, roles: list[str], regions: dict | None = None) -> dict:
    perms = sorted(set().union(*(ROLE_PERMISSIONS.get(r, frozenset()) for r in roles)) if roles else [])
    regions = regions or {}
    region_set = sorted({"ALL" if r == "admin" else regions.get(r, "ALL") for r in roles})
    return {**row, "active": bool(row["active"]), "roles": roles,
            "regions": {r: ("ALL" if r == "admin" else regions.get(r, "ALL")) for r in roles},
            "region": region_set[0] if len(region_set) == 1 else ("mixed" if region_set else "ALL"),
            "role_labels": [ROLE_LABELS.get(r, r) for r in roles],
            "can": [PERMISSION_LABELS.get(p, p) for p in perms]}


_ROLES_EXPR = "(SELECT group_concat(ra.role, ' ') FROM role_assignment ra WHERE ra.user_id = u.id)"
ACCESS_REVIEW_LIST = lists.register(lists.ListSpec(
    name="access_review", permission="access_review:read", source="app_user u",
    columns=(lists.Column("username", "User", "u.username", searchable=True, sortable=True),
             lists.Column("status", "Status", "u.active", sortable=True),
             lists.Column("id", "ID", "u.id", sortable=True),
             lists.Column("roles", "Roles", _ROLES_EXPR, searchable=True)),
    default_sort="username", tiebreak="u.id", extra={"select": "u.id, u.username, u.active"}))


def list_users(conn, q=None, role=None, status=None, sort=None, direction=None,
               page: int = 1, page_size: int = 25) -> dict:
    where, params = [], {}
    if role:
        if role not in ROLE_PERMISSIONS:
            raise AppError(422, "role must be one of " + ", ".join(ROLE_PERMISSIONS))
        where.append("EXISTS (SELECT 1 FROM role_assignment ra WHERE ra.user_id = u.id AND ra.role = :role)")
        params["role"] = role
    if status:
        if status not in ("active", "inactive"):
            raise AppError(422, "status must be active or inactive")
        where.append("u.active = :active")
        params["active"] = 1 if status == "active" else 0
    spec = replace(ACCESS_REVIEW_LIST, where=tuple(where), extra={**ACCESS_REVIEW_LIST.extra, "params": params})
    query = {k: str(v) for k, v in {"q": q, "sort": sort, "dir": direction, "page": page,
                                    "page_size": page_size}.items() if v not in (None, "")}
    result = lists.run(conn, spec, None, query)
    result["items"] = [_describe(row, _roles_of(conn, row["id"]), _regions_of(conn, row["id"]))
                       for row in result["items"]]
    result.update(role=role or "", status=status or "")
    return result


def role_overview(conn) -> list[dict]:
    out = []
    for role, perms in ROLE_PERMISSIONS.items():
        holders = [r[0] for r in conn.execute(text(
            "SELECT u.username FROM role_assignment ra JOIN app_user u ON u.id = ra.user_id "
            "WHERE ra.role = :r AND u.active = 1 ORDER BY u.username"), {"r": role})]
        out.append({"role": role, "label": ROLE_LABELS.get(role, role), "holders": holders,
                    "can": [PERMISSION_LABELS.get(p, p) for p in sorted(perms)]})
    return out


def _require_manage(actor) -> None:
    if MANAGE not in actor.permissions:
        raise AppError(403, f"missing permission {MANAGE}")


def _clean_roles(roles) -> list[str]:
    if not isinstance(roles, (list, tuple)) or not all(isinstance(r, str) for r in roles):
        raise AppError(422, "roles must be a list")
    roles = [r for r in roles if r]  # an unticked form sends nothing or an empty value: no role
    unknown = [r for r in roles if r not in ROLE_PERMISSIONS]
    if unknown:
        raise AppError(422, "unknown role: " + ", ".join(unknown))
    return sorted(set(roles))


def _get(conn, user_id: int) -> dict:
    row = conn.execute(text("SELECT id, username, active FROM app_user WHERE id = :i"),
                       {"i": user_id}).mappings().first()
    if row is None:
        raise AppError(404, f"user {user_id} not found")
    return dict(row)


def _other_active_managers(conn, user_id: int) -> int:
    roles = roles_granting(MANAGE)
    marks = ", ".join(f":r{i}" for i in range(len(roles)))
    return conn.execute(text(
        f"SELECT COUNT(DISTINCT u.id) FROM app_user u JOIN role_assignment ra ON ra.user_id = u.id "
        f"WHERE u.active = 1 AND u.id <> :i AND ra.role IN ({marks})"),
        {"i": user_id, **{f"r{i}": r for i, r in enumerate(roles)}}).scalar()


def add_user(conn, actor, username, password, roles, region="ALL") -> dict:
    _require_manage(actor)
    username = username.strip().lower() if isinstance(username, str) else ""
    if not _USERNAME_RE.match(username) or username == "system":
        raise AppError(422, "username must be 3 to 32 characters: lowercase letters, digits, dot, dash or "
                            "underscore, starting with a letter")
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise AppError(422, f"starting password must be at least {MIN_PASSWORD} characters")
    roles = _clean_roles(roles)
    region = _clean_region(region)
    if conn.execute(text("SELECT 1 FROM app_user WHERE username = :u"), {"u": username}).first():
        raise AppError(422, f"user {username} already exists")
    user_id = create_user(conn, username, password, roles, region)
    write_audit(conn, actor=actor.username, action="user.create", entity="user", entity_id=user_id,
                before=None, after={"username": username, "roles": roles, "region": region, "active": True})
    return _describe(_get(conn, user_id), roles, _regions_of(conn, user_id))


def set_roles(conn, actor, user_id: int, roles, region=None) -> dict:
    """Replace a user's roles. `region` applies to every role; None keeps each kept role's region
    (new roles get ALL)."""
    _require_manage(actor)
    roles = _clean_roles(roles)
    region = None if region in (None, "") else _clean_region(region)
    target = _get(conn, user_id)
    if target["id"] == actor.id:
        raise AppError(422, "you cannot change your own access")
    old = _roles_of(conn, user_id)
    old_regions = _regions_of(conn, user_id)
    losing_manage = any(r in roles_granting(MANAGE) for r in old) and \
        not any(r in roles_granting(MANAGE) for r in roles)
    if losing_manage and target["active"] and _other_active_managers(conn, user_id) == 0:
        raise AppError(422, "the last admin cannot be removed")
    conn.execute(text("DELETE FROM role_assignment WHERE user_id = :u"), {"u": user_id})
    new_regions = {r: region or old_regions.get(r, "ALL") for r in roles}
    for role in roles:
        conn.execute(text("INSERT INTO role_assignment (user_id, role, region) VALUES (:u, :r, :g)"),
                     {"u": user_id, "r": role, "g": new_regions[role]})
    write_audit(conn, actor=actor.username, action="user.roles_change", entity="user", entity_id=user_id,
                before={"username": target["username"], "roles": old, "regions": old_regions},
                after={"username": target["username"], "roles": roles, "regions": new_regions})
    return _describe(target, roles, new_regions)


def set_active(conn, actor, user_id: int, active: bool) -> dict:
    _require_manage(actor)
    if not isinstance(active, bool):
        raise AppError(422, "active must be true or false")
    target = _get(conn, user_id)
    if target["id"] == actor.id:
        raise AppError(422, "you cannot deactivate yourself")
    roles = _roles_of(conn, user_id)
    if not active and any(r in roles_granting(MANAGE) for r in roles) \
            and _other_active_managers(conn, user_id) == 0:
        raise AppError(422, "the last admin cannot be deactivated")
    conn.execute(text("UPDATE app_user SET active = :a WHERE id = :i"), {"a": int(active), "i": user_id})
    if not active:
        conn.execute(text("DELETE FROM user_session WHERE user_id = :i"), {"i": user_id})
    write_audit(conn, actor=actor.username, action="user.reactivate" if active else "user.deactivate",
                entity="user", entity_id=user_id,
                before={"username": target["username"], "active": bool(target["active"])},
                after={"username": target["username"], "active": active})
    target["active"] = int(active)
    return _describe(target, roles, _regions_of(conn, user_id))
