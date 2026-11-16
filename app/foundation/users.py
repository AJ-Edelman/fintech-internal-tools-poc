"""Admin user management: add users, change roles, deactivate. Every change is audited."""
import re

from sqlalchemy import text

from .audit import write_audit
from .auth import create_user
from .errors import AppError
from .listing import run_list
from .permissions import PERMISSION_LABELS, ROLE_LABELS, ROLE_PERMISSIONS, roles_granting

MANAGE = "user:manage"
_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,31}$")
MIN_PASSWORD = 8


def _roles_of(conn, user_id: int) -> list[str]:
    return [r[0] for r in conn.execute(
        text("SELECT role FROM role_assignment WHERE user_id = :u ORDER BY role"), {"u": user_id})]


def _describe(row: dict, roles: list[str]) -> dict:
    perms = sorted(set().union(*(ROLE_PERMISSIONS.get(r, frozenset()) for r in roles)) if roles else [])
    return {**row, "active": bool(row["active"]), "roles": roles,
            "role_labels": [ROLE_LABELS.get(r, r) for r in roles],
            "can": [PERMISSION_LABELS.get(p, p) for p in perms]}


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
    result = run_list(
        conn, select="u.id, u.username, u.active", frm="app_user u", where=where, params=params,
        search=("u.username", "(SELECT group_concat(ra.role, ' ') FROM role_assignment ra WHERE ra.user_id = u.id)"),
        q=q, sorts={"username": "u.username", "status": "u.active", "id": "u.id"},
        default_sort="username", tiebreak="u.id", sort=sort, direction=direction,
        page=page, page_size=page_size)
    result["items"] = [_describe(row, _roles_of(conn, row["id"])) for row in result["items"]]
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


def add_user(conn, actor, username, password, roles) -> dict:
    _require_manage(actor)
    username = username.strip().lower() if isinstance(username, str) else ""
    if not _USERNAME_RE.match(username) or username == "system":
        raise AppError(422, "username must be 3 to 32 characters: lowercase letters, digits, dot, dash or "
                            "underscore, starting with a letter")
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise AppError(422, f"starting password must be at least {MIN_PASSWORD} characters")
    roles = _clean_roles(roles)
    if conn.execute(text("SELECT 1 FROM app_user WHERE username = :u"), {"u": username}).first():
        raise AppError(422, f"user {username} already exists")
    user_id = create_user(conn, username, password, roles)
    write_audit(conn, actor=actor.username, action="user.create", entity="user", entity_id=user_id,
                before=None, after={"username": username, "roles": roles, "active": True})
    return _describe(_get(conn, user_id), roles)


def set_roles(conn, actor, user_id: int, roles) -> dict:
    _require_manage(actor)
    roles = _clean_roles(roles)
    target = _get(conn, user_id)
    if target["id"] == actor.id:
        raise AppError(422, "you cannot change your own access")
    old = _roles_of(conn, user_id)
    losing_manage = any(r in roles_granting(MANAGE) for r in old) and \
        not any(r in roles_granting(MANAGE) for r in roles)
    if losing_manage and target["active"] and _other_active_managers(conn, user_id) == 0:
        raise AppError(422, "the last admin cannot be removed")
    conn.execute(text("DELETE FROM role_assignment WHERE user_id = :u"), {"u": user_id})
    for role in roles:
        conn.execute(text("INSERT INTO role_assignment (user_id, role) VALUES (:u, :r)"),
                     {"u": user_id, "r": role})
    write_audit(conn, actor=actor.username, action="user.roles_change", entity="user", entity_id=user_id,
                before={"username": target["username"], "roles": old},
                after={"username": target["username"], "roles": roles})
    return _describe(target, roles)


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
    return _describe(target, roles)
