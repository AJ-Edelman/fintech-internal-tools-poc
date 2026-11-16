"""Every test gets its own temporary database; nothing here touches ./data/."""
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.foundation.auth import create_user
from app.foundation.db import make_engine, migrate
from app.main import create_app

USERS = {
    "agent1": ["refund_agent"],
    "agent2": ["refund_agent"],
    "approver1": ["refund_approver"],
    "kyc1": ["kyc_reviewer"],
    "admin1": ["admin"],
}
SSN_1, BANK_1 = "900-12-3456", "4000123456"
SSN_2, BANK_2 = "900-65-4321", "4000987654"
SSN_3, BANK_3 = "900-77-1122", "4000555577"


def seed_basics(db_path: str) -> None:
    """Five demo users, three customers, charges 1-6 ($2,000 each) on customer 1, 7 and 8 on 2 and 3."""
    engine = make_engine(db_path)
    with engine.begin() as conn:
        for username, roles in USERS.items():
            create_user(conn, username, "demo", roles)
        conn.execute(text(
            "INSERT INTO customer (id, name, email, ssn, bank_account) VALUES "
            f"(1, 'Ada Stone', 'ada@example.test', '{SSN_1}', '{BANK_1}'), "
            f"(2, 'Ben Rivers', 'ben@example.test', '{SSN_2}', '{BANK_2}')"))
        for charge_id in range(1, 7):
            conn.execute(text(
                "INSERT INTO charge (id, customer_id, amount_cents, created_at) "
                "VALUES (:i, 1, 200000, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"), {"i": charge_id})
        conn.execute(text(
            "INSERT INTO customer (id, name, email, ssn, bank_account) VALUES "
            f"(3, 'Cleo Field', 'cleo@example.test', '{SSN_3}', '{BANK_3}')"))
        conn.execute(text(
            "INSERT INTO charge (id, customer_id, amount_cents, created_at) VALUES "
            "(7, 2, 200000, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')), (8, 3, 200000, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"))
        # Tool 2 setup data: customer 1 is KYC-approved, 2 stays pending, 3 is rejected.
        if any(r[1] == "kyc_status" for r in conn.execute(text("PRAGMA table_info(customer)"))):
            conn.execute(text("UPDATE customer SET kyc_status = 'approved' WHERE id = 1"))
            conn.execute(text("UPDATE customer SET kyc_status = 'rejected' WHERE id = 3"))
    engine.dispose()


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    migrate(path)
    seed_basics(path)
    return path


@pytest.fixture
def app(db_path):
    application = create_app(db_path)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def login(app):
    clients = []

    def _login(username: str, password: str = "demo") -> TestClient:
        client = TestClient(app, follow_redirects=False)
        response = client.post("/api/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        clients.append(client)
        return client

    yield _login
    for client in clients:
        client.close()


@pytest.fixture
def anon(app):
    with TestClient(app, follow_redirects=False) as client:
        yield client


@pytest.fixture
def sql(db_path):
    """Direct SQL access that bypasses the app entirely."""
    con = sqlite3.connect(db_path, isolation_level=None)
    con.row_factory = sqlite3.Row
    yield con
    con.close()


@pytest.fixture
def add_user(db_path):
    def _add(username: str, roles) -> None:
        engine = make_engine(db_path)
        with engine.begin() as conn:
            create_user(conn, username, "demo", roles)
        engine.dispose()

    return _add


def audit_rows(sql, entity: str, entity_id) -> list[sqlite3.Row]:
    return sql.execute(
        "SELECT * FROM audit_event WHERE entity = ? AND entity_id = ? ORDER BY id",
        (entity, str(entity_id)),
    ).fetchall()


def request_refund(client, charge_id=1, amount_cents=75000, reason="customer request"):
    return client.post("/api/refunds", json={"charge_id": charge_id, "amount_cents": amount_cents,
                                             "reason": reason})


def all_routes(app) -> list:
    """Every APIRoute in the app, looking inside included routers."""
    from fastapi.routing import APIRoute

    found, stack = [], list(app.routes)
    while stack:
        route = stack.pop(0)
        if isinstance(route, APIRoute):
            found.append(route)
        elif hasattr(route, "original_router"):
            stack.extend(route.original_router.routes)
        else:
            raise AssertionError(f"unexpected unguarded route object: {route!r}")
    return found
