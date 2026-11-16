"""Stubbed identity: demo users, password login, server-side session, roles read per request."""
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field

from fastapi import Request
from sqlalchemy import text

from datetime import datetime, timedelta, timezone

from . import settings
from .db import utcnow
from .errors import AppError
from .permissions import ROLE_PERMISSIONS, permissions_for

COOKIE = "session"
_ITERATIONS = 20_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return salt, digest.hex()


@dataclass(frozen=True)
class User:
    id: int
    username: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    is_system: bool = False
    # permission -> frozenset of "US", "EU", "ALL" (region scope; worker C fills it)
    scopes: dict = field(default_factory=dict, compare=False, hash=False)

    def can(self, permission: str) -> bool:
        return permission in self.permissions


def scopes_for(assignments) -> dict:
    """permission -> frozenset of regions, from (role, region) pairs. `admin` permissions are ALL."""
    out: dict[str, set] = {}
    for role, region in assignments:
        for perm in ROLE_PERMISSIONS.get(role, frozenset()):
            out.setdefault(perm, set()).add("ALL" if role == "admin" else region)
    return {perm: frozenset(regions) for perm, regions in out.items()}


def create_user(conn, username: str, password: str, roles=(), region: str = "ALL") -> int:
    salt, digest = hash_password(password)
    user_id = conn.execute(
        text("INSERT INTO app_user (username, password_salt, password_hash) VALUES (:u, :s, :h)"),
        {"u": username, "s": salt, "h": digest},
    ).lastrowid
    for role in roles:
        if region == "ALL":  # column default; also works on databases before migration 003
            conn.execute(text("INSERT INTO role_assignment (user_id, role) VALUES (:u, :r)"),
                         {"u": user_id, "r": role})
        else:
            conn.execute(
                text("INSERT INTO role_assignment (user_id, role, region) VALUES (:u, :r, :g)"),
                {"u": user_id, "r": role, "g": region},
            )
    return user_id


def login(conn, username: str, password: str) -> str | None:
    row = conn.execute(
        text("SELECT id, password_salt, password_hash FROM app_user WHERE username = :u AND active = 1"),
        {"u": username},
    ).first()
    if row is None:
        return None
    _, digest = hash_password(password, row.password_salt)
    if not hmac.compare_digest(digest, row.password_hash):
        return None
    token = secrets.token_urlsafe(32)
    conn.execute(
        text("INSERT INTO user_session (token, user_id, created_at, last_seen_at) VALUES (:t, :u, :c, :c)"),
        {"t": token, "u": row.id, "c": utcnow()},
    )
    return token


def logout(conn, token: str | None) -> None:
    if token:
        conn.execute(text("DELETE FROM user_session WHERE token = :t"), {"t": token})


def _expired(last_seen: str, timeout_minutes: int) -> bool:
    seen = datetime.strptime(last_seen, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - seen > timedelta(minutes=timeout_minutes)


def user_from_request(request: Request) -> User | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    with request.app.state.engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT u.id, u.username, COALESCE(s.last_seen_at, s.created_at) AS seen "
                "FROM user_session s JOIN app_user u ON u.id = s.user_id "
                "WHERE s.token = :t AND u.active = 1"
            ),
            {"t": token},
        ).first()
        if row is None:
            return None
        if _expired(row.seen, int(settings.get(conn, settings.SESSION_TIMEOUT))):
            logout(conn, token)
            return None
        conn.execute(text("UPDATE user_session SET last_seen_at = :n WHERE token = :t"),
                     {"n": utcnow(), "t": token})
        assignments = [
            (r[0], r[1])
            for r in conn.execute(
                text("SELECT role, region FROM role_assignment WHERE user_id = :u ORDER BY role"),
                {"u": row.id},
            )
        ]
    roles = tuple(sorted({role for role, _ in assignments}))
    return User(id=row.id, username=row.username, roles=roles, permissions=permissions_for(roles),
                scopes=scopes_for(assignments))


def require(*permissions: str):
    """Route dependency: 401 without a session, 403 unless the caller holds one of `permissions`."""
    assert permissions

    def dependency(request: Request) -> User:
        user = user_from_request(request)
        if user is None:
            raise AppError(401, "not authenticated")
        request.state.user = user
        if not any(p in user.permissions for p in permissions):
            raise AppError(403, "permission denied: needs " + " or ".join(permissions))
        return user

    dependency.required_permissions = permissions
    return dependency
