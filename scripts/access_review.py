"""Print who holds which role (reads the database named by APP_DB)."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.foundation.db import db_path_from_env  # noqa: E402
from app.foundation.permissions import ROLE_PERMISSIONS  # noqa: E402

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else db_path_from_env()
    if not Path(path).exists():
        sys.exit(f"{path} does not exist; run `make setup && make seed` first")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT u.username, ra.role FROM role_assignment ra JOIN app_user u ON u.id = ra.user_id "
        "ORDER BY u.username, ra.role"
    ).fetchall()
    print(f"{'USER':<14}{'ROLE':<18}PERMISSIONS")
    for username, role in rows:
        print(f"{username:<14}{role:<18}{', '.join(sorted(ROLE_PERMISSIONS.get(role, [])))}")
    print(f"{len(rows)} role assignment(s) in {path}")
