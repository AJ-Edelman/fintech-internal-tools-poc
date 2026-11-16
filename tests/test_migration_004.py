"""AC21: a database at migration 002 with data upgrades to 004 with every row intact,
every customer US, and existing assignments still working."""
import os
import sqlite3

from fastapi.testclient import TestClient

from app.foundation.db import applied_versions, migrate
from app.main import create_app
from tests.conftest import request_refund, seed_basics


def _dump(path) -> dict:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "AND name <> 'schema_migration' ORDER BY name")]
    out = {t: [dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in tables}
    con.close()
    return out


def _database_at_002(tmp_path) -> str:
    path = str(tmp_path / "at002.db")
    assert migrate(path, target=2) == [1, 2]
    seed_basics(path)  # five users with roles, three customers, eight charges
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("INSERT INTO refund (charge_id, amount_cents, reason, status, requested_by, created_at, "
                "updated_at) VALUES (1, 100000, 'pre-003', 'pending_approval', 'agent1', 'x', 'x')")
    con.close()
    return path


def test_ac21_database_at_002_upgrades_to_004_with_every_row_intact(tmp_path):
    path = _database_at_002(tmp_path)
    before = _dump(path)
    assert len(before["customer"]) == 3 and len(before["role_assignment"]) == 5
    assert len(before["refund"]) == 1
    assert "region" not in before["customer"][0]
    inode = os.stat(path).st_ino

    assert migrate(path, target=4) == [3, 4]
    assert applied_versions(path) == [1, 2, 3, 4]
    assert os.stat(path).st_ino == inode, "upgraded in place, not recreated"
    after = _dump(path)
    assert set(after) == set(before) | {"limit_override"} and after["limit_override"] == []
    for table, rows in before.items():
        assert len(after[table]) == len(rows), table
        for old, new in zip(rows, after[table]):
            if table == "customer":
                assert new.pop("region") == "US"
                assert new.pop("daily_limit_cents") == 500000  # 004 default
            if table == "role_assignment":
                assert new.pop("region") == "ALL"
            assert new == old, table
    assert migrate(path, target=4) == []


def test_ac21_existing_assignments_still_work_after_upgrade(tmp_path):
    path = _database_at_002(tmp_path)
    migrate(path)
    app = create_app(path)
    try:
        with TestClient(app, follow_redirects=False) as agent, \
                TestClient(app, follow_redirects=False) as approver:
            for client, name in ((agent, "agent1"), (approver, "approver1")):
                assert client.post("/api/login", json={"username": name, "password": "demo"}).status_code == 200
            assert approver.post("/api/refunds/1/approve", json={"reason": "Duplicate charge"}).status_code == 200
            created = request_refund(agent, charge_id=2, amount_cents=100000)
            assert created.status_code == 201, created.text
            assert agent.get(f"/api/refunds/{created.json()['id']}").status_code == 200
            decided = approver.post(f"/api/refunds/{created.json()['id']}/reject",
                                    json={"reason": "Duplicate charge"})
            assert decided.status_code == 200, decided.text
    finally:
        app.state.engine.dispose()
