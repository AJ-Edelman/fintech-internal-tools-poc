"""Engine factory and numbered SQL migrations."""
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
DEFAULT_DB = "data/app.db"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def db_path_from_env() -> str:
    return os.environ.get("APP_DB", DEFAULT_DB)


def make_engine(path: str):
    engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 15}
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):
        # We issue BEGIN ourselves so every transaction takes the write lock up front.
        dbapi_conn.isolation_level = None
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def available_migrations() -> list[tuple[int, str, Path]]:
    found = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = re.match(r"^(\d+)_", path.name)
        if match:
            found.append((int(match.group(1)), path.name, path))
    return sorted(found)


def applied_versions(path: str) -> list[int]:
    con = sqlite3.connect(path)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS schema_migration ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        con.commit()
        return [r[0] for r in con.execute("SELECT version FROM schema_migration ORDER BY version")]
    finally:
        con.close()


def migrate(path: str, target: int | None = None) -> list[int]:
    """Apply pending migrations in order, each in one transaction. Never recreates the file."""
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)
    done = set(applied_versions(path))
    newly = []
    for version, name, file in available_migrations():
        if version in done or (target is not None and version > target):
            continue
        con = sqlite3.connect(path, isolation_level=None)
        try:
            con.execute("PRAGMA foreign_keys = ON")
            script = (
                "BEGIN IMMEDIATE;\n"
                + file.read_text()
                + "\nINSERT INTO schema_migration (version, name, applied_at) "
                + f"VALUES ({version}, '{name}', '{utcnow()}');\nCOMMIT;"
            )
            try:
                con.executescript(script)
            except Exception:
                if con.in_transaction:
                    con.execute("ROLLBACK")
                raise
        finally:
            con.close()
        newly.append(version)
    return newly
