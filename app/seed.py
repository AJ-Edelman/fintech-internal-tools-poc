"""Demo seed (`make seed`) and scale seed (`make seed-scale`). Synthetic data only."""
import argparse
from datetime import datetime, timedelta, timezone
import sqlite3
import sys

from sqlalchemy import text

from app.foundation.auth import User, create_user
from app.foundation.audit import write_audit
from app.foundation.db import db_path_from_env, make_engine, migrate, utcnow
from app.foundation.permissions import permissions_for

DEMO_PASSWORD = "demo"
DEMO_USERS = [
    ("agent1", ["refund_agent"], "US"),
    ("agent2", ["refund_agent"], "EU"),
    ("approver1", ["refund_approver"], "US"),
    ("approver2", ["refund_approver"], "EU"),
    ("kyc1", ["kyc_reviewer"], "US"),
    ("limits1", ["limits_agent"], "US"),
    ("limits2", ["limits_approver"], "US"),
    ("admin1", ["admin"], "ALL"),
]
# Demo customers 11-20 are EU (11 and 12 are KYC-approved and hold charges); 1-10 are US.
EU_DEMO_CUSTOMERS = range(11, 21)
FIRST = ["Ada", "Ben", "Cleo", "Dev", "Eve", "Finn", "Gia", "Hal", "Ivy", "Jon",
         "Kai", "Lena", "Milo", "Nora", "Omar", "Pia", "Quinn", "Rae", "Sam", "Tess"]
LAST = ["Stone", "Rivers", "Field", "Marsh", "Hill", "Lake", "Wood", "Vale", "Frost", "Reed"]

# Scale seed: status is a fixed function of the refund id, so the counts are known exactly.
SCALE_TOTAL = 50_000
SCALE_CYCLE = 20  # ids with (id - 1) % 20 in 0..11 approved, 12..16 pending, 17..19 rejected


def scale_status(refund_id: int) -> str:
    slot = (refund_id - 1) % SCALE_CYCLE
    if slot < 12:
        return "approved"
    if slot < 17:
        return "pending_approval"
    return "rejected"


def scale_counts(total: int = SCALE_TOTAL) -> dict[str, int]:
    counts = {"approved": 0, "pending_approval": 0, "rejected": 0}
    full, rest = divmod(total, SCALE_CYCLE)
    counts["approved"] = full * 12
    counts["pending_approval"] = full * 5
    counts["rejected"] = full * 3
    for i in range(full * SCALE_CYCLE + 1, full * SCALE_CYCLE + rest + 1):
        counts[scale_status(i)] += 1
    return counts


def synthetic_ssn(n: int) -> str:
    # 9xx area numbers are never issued as real SSNs.
    return f"9{n % 100:02d}-{(n * 7) % 90 + 10:02d}-{(n * 1231) % 9000 + 1000:04d}"


def synthetic_bank_account(n: int) -> str:
    return f"{4000000000 + n * 104729:010d}"


def has_column(conn, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(text(f"PRAGMA table_info({table})")))


def seed_users(conn, regions: bool = True) -> None:
    has_region = has_column(conn, "role_assignment", "region")
    for username, roles, region in DEMO_USERS:
        if has_region:
            # The scale seed keeps every customer US and passes regions=False so its users see them all.
            create_user(conn, username, DEMO_PASSWORD, roles, region if regions else "ALL")
        else:
            create_user(conn, username, DEMO_PASSWORD, roles)


def seed_customers(conn, count: int = 20) -> list[int]:
    kyc = has_column(conn, "customer", "kyc_status")
    ids = []
    for n in range(1, count + 1):
        name = f"{FIRST[(n - 1) % len(FIRST)]} {LAST[(n - 1) % len(LAST)]}"
        params = {"n": name, "e": f"customer{n}@example.test", "s": synthetic_ssn(n),
                  "b": synthetic_bank_account(n)}
        if kyc:
            # 1-12 approved, 13-17 pending, 18-20 rejected
            params["k"] = "approved" if n <= 12 else ("pending" if n <= 17 else "rejected")
            sql = ("INSERT INTO customer (name, email, ssn, bank_account, kyc_status) "
                   "VALUES (:n, :e, :s, :b, :k)")
        else:
            sql = "INSERT INTO customer (name, email, ssn, bank_account) VALUES (:n, :e, :s, :b)"
        ids.append(conn.execute(text(sql), params).lastrowid)
    return ids


def seed_demo(path: str) -> bool:
    engine = make_engine(path)
    try:
        with engine.begin() as conn:
            if conn.execute(text("SELECT COUNT(*) FROM app_user")).scalar():
                return False
            seed_users(conn)
            customer_ids = seed_customers(conn, 20)
            if has_column(conn, "customer", "region"):
                conn.execute(text(f"UPDATE customer SET region = 'EU' WHERE id IN "
                                  f"({', '.join(str(i) for i in EU_DEMO_CUSTOMERS)})"))
            now = utcnow()
            # Two charges per customer; the first ten customers also hold one over $1,000.
            for index, customer_id in enumerate(customer_ids):
                first = 150_000 + index * 12_500 if index < 10 else 4_500 + index * 700
                for n, amount in enumerate((first, 2_000 + index * 1_150)):
                    # Spread over the last 110 days so sorting by date and the refund-age limit show up.
                    age = timedelta(days=(index * 11 + n * 5) % 110, hours=index * 3 + n)
                    conn.execute(
                        text("INSERT INTO charge (customer_id, amount_cents, created_at) VALUES (:c, :a, :t)"),
                        {"c": customer_id, "a": amount,
                         "t": (datetime.now(timezone.utc) - age).strftime("%Y-%m-%dT%H:%M:%S.%fZ")},
                    )
            # A few refunds through the real workflow, so they carry audit events.
            from app.refunds.workflow import request_refund

            agent = User(id=0, username="agent1", roles=("refund_agent",),
                         permissions=permissions_for(["refund_agent"]))
            request_refund(conn, agent, 1, 2_500, "Duplicate charge")
            request_refund(conn, agent, 3, 75_000, "Product not received")
            request_refund(conn, agent, 5, 120_000, "Cancelled order or subscription")
            request_refund(conn, agent, 7, 64_000, "Billing error or wrong amount")
            request_refund(conn, agent, 9, 98_500, "Product defective or not as described")
            if has_column(conn, "customer", "region"):
                # EU pending refunds for approver2 (customer 11 holds charges 21-22, customer 12 holds 23-24).
                eu_agent = User(id=0, username="agent2", roles=("refund_agent",),
                                permissions=permissions_for(["refund_agent"]))
                request_refund(conn, eu_agent, 21, 1_500, "Duplicate charge")
                request_refund(conn, eu_agent, 23, 1_200, "Billing error or wrong amount")
            write_audit(conn, actor="system", action="seed.demo", entity="database", entity_id="demo",
                        after={"customers": 20, "charges": 40, "users": len(DEMO_USERS)},
                        reason="make seed")
        return True
    finally:
        engine.dispose()


def seed_scale(path: str, total: int = SCALE_TOTAL, with_users: bool = True) -> dict[str, int]:
    """Load `total` refunds with a known status per id. Direct SQL; the cap trigger still applies."""
    engine = make_engine(path)
    try:
        with engine.begin() as conn:
            if conn.execute(text("SELECT COUNT(*) FROM refund")).scalar():
                raise SystemExit(f"{path} already holds refunds; delete the file to rebuild it")
            if with_users and not conn.execute(text("SELECT COUNT(*) FROM app_user")).scalar():
                seed_users(conn, regions=False)
            customer_ids = seed_customers(conn, 20)
            if has_column(conn, "customer", "kyc_status"):
                conn.execute(text("UPDATE customer SET kyc_status = 'approved'"))
            now = utcnow()
            per_charge = 100
            charges = -(-total // per_charge)
            raw = conn.connection.driver_connection
            first_charge = None
            for i in range(charges):
                cur = raw.execute(
                    "INSERT INTO charge (customer_id, amount_cents, created_at) VALUES (?, ?, ?)",
                    (customer_ids[i % len(customer_ids)], per_charge * 1_000, now),
                )
                first_charge = first_charge or cur.lastrowid
            start = (raw.execute("SELECT COALESCE(MAX(id), 0) FROM refund").fetchone()[0]) + 1
            assert start == 1
            raw.executemany(
                "INSERT INTO refund (id, charge_id, amount_cents, reason, status, requested_by, "
                "decided_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (i, first_charge + (i - 1) // per_charge, 1_000, "scale seed", scale_status(i),
                     "agent1", None if scale_status(i) == "pending_approval" else "approver1", now, now)
                    for i in range(1, total + 1)
                ),
            )
            counts = scale_counts(total)
            write_audit(conn, actor="system", action="seed.scale", entity="database", entity_id="scale",
                        after={"refunds": total, **counts},
                        reason="bulk synthetic load; no per-refund audit events")
        return counts
    finally:
        engine.dispose()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["demo", "scale"])
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)
    if args.mode == "demo":
        path = args.db or db_path_from_env()
        migrate(path)
        print(f"seeded demo data into {path}" if seed_demo(path) else f"{path} is already seeded")
    else:
        path = args.db or "data/scale.db"
        migrate(path)
        counts = seed_scale(path)
        print(f"seeded {sum(counts.values())} refunds into {path}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
