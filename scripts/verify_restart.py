"""AC3: a refund and its audit events survive stopping and restarting the server.

Uses its own temporary database and its own server process; never touches ./data/.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.foundation.auth import create_user  # noqa: E402
from app.foundation.db import make_engine, migrate  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(db: str, port: int) -> subprocess.Popen:
    env = {**os.environ, "APP_DB": db}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env,
    )
    for _ in range(100):
        if proc.poll() is not None:
            raise SystemExit("AC3 FAIL: server exited during startup")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/login", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.1)
    proc.kill()
    raise SystemExit("AC3 FAIL: server did not start")


def stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def login(base: str, username: str) -> httpx.Client:
    client = httpx.Client(base_url=base, timeout=10)
    r = client.post("/api/login", json={"username": username, "password": "demo"})
    assert r.status_code == 200, r.text
    return client


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"AC3 FAIL: {message}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "verify.db")
        migrate(db)
        engine = make_engine(db)
        with engine.begin() as conn:
            create_user(conn, "agent1", "demo", ["refund_agent"])
            create_user(conn, "approver1", "demo", ["refund_approver"])
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(customer)"))]
            conn.execute(text(
                "INSERT INTO customer (id, name, email, ssn, bank_account) "
                "VALUES (1, 'Verify Customer', 'verify@example.test', '900-00-0001', '4000000001')"))
            if "kyc_status" in cols:
                conn.execute(text("UPDATE customer SET kyc_status = 'approved'"))
            conn.execute(text(
                "INSERT INTO charge (id, customer_id, amount_cents, created_at) "
                "VALUES (1, 1, 200000, '2026-01-01T00:00:00Z')"))
        engine.dispose()

        port = free_port()
        base = f"http://127.0.0.1:{port}"
        proc = start(db, port)
        try:
            agent = login(base, "agent1")
            r = agent.post("/api/refunds", json={"charge_id": 1, "amount_cents": 75000,
                                                 "reason": "restart check"})
            check(r.status_code == 201, f"create returned {r.status_code}: {r.text}")
            refund_id = r.json()["id"]
            approver = login(base, "approver1")
            r = approver.post(f"/api/refunds/{refund_id}/approve", json={"reason": "restart ok"})
            check(r.status_code == 200, f"approve returned {r.status_code}: {r.text}")
            before = agent.get(f"/api/refunds/{refund_id}").json()
        finally:
            stop(proc)
        check(len(before["history"]) == 2, "expected two audit events before restart")
        print(f"AC3: server stopped (pid {proc.pid}); refund {refund_id} had "
              f"{len(before['history'])} audit events")

        proc = start(db, port)
        try:
            agent = login(base, "agent1")
            after = agent.get(f"/api/refunds/{refund_id}").json()
        finally:
            stop(proc)
        check(after == before, "refund or audit history changed across the restart")
        check(after["status"] == "approved", "refund status was lost")
        check([e["action"] for e in after["history"]] == ["refund.request", "refund.approve"],
              "audit events were lost")
        print(f"AC3 PASS: refund {refund_id} and its {len(after['history'])} audit events "
              f"survived the restart (new pid {proc.pid})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
