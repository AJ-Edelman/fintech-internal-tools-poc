"""Tool 2: KYC review flow, AC7 (PII), AC10 (cross-tool rule) and AC14 (migration 001 -> 002)."""
import json
import os
import sqlite3

from fastapi.testclient import TestClient

from app.foundation.db import applied_versions, migrate
from app.main import create_app
from tests.conftest import (BANK_1, BANK_2, BANK_3, SSN_1, SSN_2, SSN_3, audit_rows,
                            request_refund, seed_basics)

RAW_VALUES = (SSN_1, SSN_2, SSN_3, BANK_1, BANK_2, BANK_3)


def test_kyc_reviewer_works_the_queue_through_the_workflow_engine(login, sql):
    kyc = login("kyc1")
    queue = kyc.get("/api/kyc/queue").json()["items"]
    assert [c["id"] for c in queue] == [2]
    assert "Ben Rivers" in kyc.get("/kyc/queue").text
    assert kyc.get("/kyc/2").status_code == 200

    assert kyc.post("/api/kyc/2/decision", json={"decision": "approve", "reason": ""}).status_code == 422
    assert kyc.post("/api/kyc/2/decision", json={"decision": "maybe", "reason": "x"}).status_code == 422
    assert kyc.post("/api/kyc/999/decision", json={"decision": "approve", "reason": "x"}).status_code == 404
    assert sql.execute("SELECT kyc_status FROM customer WHERE id = 2").fetchone()[0] == "pending"

    decided = kyc.post("/api/kyc/2/decision", json={"decision": "approve", "reason": "documents match"})
    assert decided.status_code == 200
    assert decided.json()["kyc_status"] == "approved"
    assert SSN_2 not in decided.text and BANK_2 not in decided.text
    events = [e for e in audit_rows(sql, "customer", 2) if e["action"].startswith("customer.kyc_")]
    assert [(e["actor"], e["action"], e["reason"]) for e in events] == [
        ("kyc1", "customer.kyc_approve", "documents match")]
    assert json.loads(events[0]["before"]) == {"kyc_status": "pending"}
    assert json.loads(events[0]["after"]) == {"kyc_status": "approved"}

    assert kyc.get("/api/kyc/queue").json()["items"] == []
    # Already decided customers cannot be decided again.
    for customer_id in (1, 2, 3):
        again = kyc.post(f"/api/kyc/{customer_id}/decision", json={"decision": "reject", "reason": "again"})
        assert again.status_code == 409
    assert sql.execute("SELECT kyc_status FROM customer WHERE id = 2").fetchone()[0] == "approved"


def test_kyc_reject_through_the_page_form(login, sql):
    kyc = login("kyc1")
    assert kyc.post("/kyc/2/decision", data={"decision": "reject", "reason": ""}).status_code == 422
    response = kyc.post("/kyc/2/decision", data={"decision": "reject", "reason": "mismatch"})
    assert response.status_code == 303
    assert sql.execute("SELECT kyc_status FROM customer WHERE id = 2").fetchone()[0] == "rejected"
    assert kyc.post("/kyc/2/decision", data={"decision": "approve", "reason": "x"}).status_code == 409


def test_ac7_agent_sees_masked_values_everywhere(login, sql):
    agent = login("agent1")
    request_refund(agent, charge_id=1, amount_cents=75000)
    for path in ("/api/customers", "/api/customers/1", "/customers", "/customers/1", "/api/charges",
                 "/refunds", "/api/refunds", "/refunds/new", "/refunds/1", "/api/refunds/1"):
        response = agent.get(path)
        assert response.status_code == 200, path
        for raw in RAW_VALUES:
            assert raw not in response.text, (path, raw)
    detail = agent.get("/api/customers/1").json()
    assert (detail["ssn"], detail["bank_account"]) == ("***-**-3456", "****3456")
    assert "***-**-3456" in agent.get("/customers/1").text and "****3456" in agent.get("/customers/1").text
    assert sql.execute("SELECT COUNT(*) FROM audit_event WHERE action = 'customer.pii_view'").fetchone()[0] == 0


def test_ac7_kyc_reviewer_sees_full_values_on_detail_only_and_the_view_is_audited(login, sql):
    kyc = login("kyc1")
    # Lists and queues stay masked, and write no view event.
    for path in ("/api/customers", "/customers", "/api/kyc/queue", "/kyc/queue"):
        response = kyc.get(path)
        assert response.status_code == 200, path
        for raw in RAW_VALUES:
            assert raw not in response.text, (path, raw)
    assert "***-**-4321" in kyc.get("/customers").text
    assert sql.execute("SELECT COUNT(*) FROM audit_event WHERE action = 'customer.pii_view'").fetchone()[0] == 0

    api = kyc.get("/api/customers/2")
    assert (api.json()["ssn"], api.json()["bank_account"]) == (SSN_2, BANK_2)
    page = kyc.get("/customers/2")
    assert SSN_2 in page.text and BANK_2 in page.text
    review = kyc.get("/kyc/2")
    assert SSN_2 in review.text and BANK_2 in review.text

    views = sql.execute("SELECT * FROM audit_event WHERE action = 'customer.pii_view' ORDER BY id").fetchall()
    assert len(views) == 3
    for view in views:
        assert (view["actor"], view["entity"], view["entity_id"]) == ("kyc1", "customer", "2")
        assert json.loads(view["after"]) == {"fields": ["ssn", "bank_account"]}


def test_ac7_no_audit_row_contains_a_raw_ssn_or_bank_account(login, sql):
    agent, approver, kyc, admin = login("agent1"), login("approver1"), login("kyc1"), login("admin1")
    # Do a bit of everything, including typing PII into free-text reasons.
    refund = request_refund(agent, charge_id=1, amount_cents=75000,
                            reason=f"customer read me SSN {SSN_1} and account {BANK_1}").json()
    approver.post(f"/api/refunds/{refund['id']}/approve", json={"reason": f"confirmed {SSN_1} / {BANK_1}"})
    request_refund(agent, charge_id=2, amount_cents=100, reason=f"ssn no dashes {SSN_1.replace('-', '')}")
    for customer_id in (1, 2, 3):
        kyc.get(f"/api/customers/{customer_id}")
        kyc.get(f"/kyc/{customer_id}")
    kyc.post("/api/kyc/2/decision", json={"decision": "reject", "reason": f"SSN {SSN_2} acct {BANK_2} mismatch"})
    admin.put("/api/settings/auto-approve-limit", json={"value_cents": 100, "reason": f"see {BANK_3} {SSN_3}"})

    rows = sql.execute("SELECT * FROM audit_event").fetchall()
    assert len(rows) >= 12
    needles = set(RAW_VALUES) | {v.replace("-", "") for v in RAW_VALUES}
    for row in rows:
        blob = " ".join("" if value is None else str(value) for value in tuple(row))
        for needle in needles:
            assert needle not in blob, (row["id"], row["action"], needle)
    # The audit pages show the same redacted rows.
    for needle in needles:
        assert needle not in admin.get("/api/audit?limit=500").text
        assert needle not in admin.get("/admin/audit").text
    reasons = [r["reason"] for r in rows if r["action"] == "refund.request"]
    assert "customer read me SSN ***-**-3456 and account ****3456" in reasons


def test_ac10_creating_a_refund_for_pending_or_rejected_customer_is_422(login, sql):
    agent = login("agent1")
    for charge_id, status in ((7, "pending"), (8, "rejected")):
        response = request_refund(agent, charge_id=charge_id, amount_cents=100)
        assert response.status_code == 422, status
        assert "KYC" in response.json()["detail"]
        form = agent.post("/refunds/new", data={"charge_id": str(charge_id), "amount": "1.00", "reason": "x"})
        assert form.status_code == 422, status
    assert sql.execute("SELECT COUNT(*) FROM refund").fetchone()[0] == 0
    assert sql.execute("SELECT COUNT(*) FROM audit_event WHERE entity = 'refund'").fetchone()[0] == 0

    # Once KYC approves the pending customer, the same request goes through.
    assert login("kyc1").post("/api/kyc/2/decision",
                              json={"decision": "approve", "reason": "ok"}).status_code == 200
    assert request_refund(agent, charge_id=7, amount_cents=100).status_code == 201
    assert request_refund(agent, charge_id=8, amount_cents=100).status_code == 422


def _database_at_001(tmp_path) -> str:
    """A database stopped at migration 001 holding customers, refunds and audit events."""
    path = str(tmp_path / "at-001.db")
    assert migrate(path, target=1) == [1]
    seed_basics(path)
    con = sqlite3.connect(path, isolation_level=None)
    stamp = "2026-02-01T00:00:00.000000Z"
    rows = [  # (charge_id, amount, status, decided_by)
        (1, 75000, "pending_approval", None),   # customer 1
        (7, 80000, "pending_approval", None),   # customer 2
        (8, 90000, "pending_approval", None),   # customer 3
        (2, 10000, "approved", "system"),
    ]
    for charge_id, amount, status, decided_by in rows:
        refund_id = con.execute(
            "INSERT INTO refund (charge_id, amount_cents, reason, status, requested_by, decided_by, "
            "created_at, updated_at) VALUES (?, ?, 'requested before 002', ?, 'agent1', ?, ?, ?)",
            (charge_id, amount, status, decided_by, stamp, stamp)).lastrowid
        con.execute(
            "INSERT INTO audit_event (actor, action, entity, entity_id, before, after, reason, created_at) "
            "VALUES ('agent1', 'refund.request', 'refund', ?, NULL, ?, 'requested before 002', ?)",
            (str(refund_id), json.dumps({"amount_cents": amount, "charge_id": charge_id,
                                         "requested_by": "agent1", "status": "pending_approval"}), stamp))
        if status == "approved":
            con.execute(
                "INSERT INTO audit_event (actor, action, entity, entity_id, before, after, reason, created_at) "
                "VALUES ('system', 'refund.auto_approve', 'refund', ?, ?, ?, 'within auto-approve limit', ?)",
                (str(refund_id), json.dumps({"status": "pending_approval"}),
                 json.dumps({"approver": "system", "decided_by": "system", "requested_by": "agent1",
                             "status": "approved"}), stamp))
    con.close()
    return path


def _dump(path: str) -> dict:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "AND name <> 'schema_migration' ORDER BY name")]
    out = {t: [dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in tables}
    con.close()
    return out


def test_ac14_database_at_001_upgrades_to_002_with_every_row_intact(tmp_path):
    path = _database_at_001(tmp_path)
    assert applied_versions(path) == [1]
    before = _dump(path)
    assert len(before["customer"]) == 3 and len(before["refund"]) == 4
    assert len(before["audit_event"]) == 5 and len(before["app_user"]) == 5
    assert "kyc_status" not in before["customer"][0]
    inode = os.stat(path).st_ino

    assert migrate(path, target=2) == [2]
    assert applied_versions(path) == [1, 2]
    assert os.stat(path).st_ino == inode, "the database file must be upgraded in place, not recreated"
    after = _dump(path)

    assert sorted(after) == sorted(before), "no table added or dropped by 002"
    for table in before:
        if table == "customer":
            continue
        assert after[table] == before[table], table
    assert len(after["customer"]) == len(before["customer"])
    for old, new in zip(before["customer"], after["customer"]):
        assert new.pop("kyc_status") == "pending"
        assert new == old

    # Running it again changes nothing, and the 001 rules still hold after the upgrade.
    assert migrate(path, target=2) == []
    assert _dump(path) == _dump(path) and applied_versions(path) == [1, 2]
    con = sqlite3.connect(path, isolation_level=None)
    for statement in ("UPDATE audit_event SET actor = 'x'", "DELETE FROM audit_event",
                      "INSERT INTO refund (charge_id, amount_cents, reason, status, requested_by, created_at, "
                      "updated_at) VALUES (1, 125001, 'x', 'approved', 'x', 'x', 'x')",
                      "UPDATE customer SET kyc_status = 'bogus' WHERE id = 1"):
        try:
            con.execute(statement)
        except sqlite3.DatabaseError:
            continue
        raise AssertionError(f"should have been rejected after upgrade: {statement}")
    con.close()


def test_ac10_approving_a_refund_requested_before_002_for_unapproved_customer_is_422(tmp_path):
    path = _database_at_001(tmp_path)
    migrate(path)
    con = sqlite3.connect(path, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("UPDATE customer SET kyc_status = 'rejected' WHERE id = 3")
    by_charge = {r["charge_id"]: r["id"] for r in con.execute("SELECT id, charge_id FROM refund")}
    app = create_app(path)

    def client(username):
        c = TestClient(app, follow_redirects=False)
        assert c.post("/api/login", json={"username": username, "password": "demo"}).status_code == 200
        return c

    approver, kyc = client("approver1"), client("kyc1")
    events_before = con.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0]
    for charge_id, status in ((1, "pending"), (7, "pending"), (8, "rejected")):
        refund_id = by_charge[charge_id]
        response = approver.post(f"/api/refunds/{refund_id}/approve", json={"reason": "looks fine"})
        assert response.status_code == 422, (charge_id, status)
        page = approver.post(f"/refunds/{refund_id}/decision", data={"decision": "approve", "reason": "ok"})
        assert page.status_code == 422, (charge_id, status)
        row = con.execute("SELECT status, decided_by FROM refund WHERE id = ?", (refund_id,)).fetchone()
        assert (row["status"], row["decided_by"]) == ("pending_approval", None)
    assert con.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == events_before

    # After KYC approves customer 1 the old request can be approved; history from before 002 is kept.
    assert kyc.post("/api/kyc/1/decision", json={"decision": "approve", "reason": "verified"}).status_code == 200
    approved = approver.post(f"/api/refunds/{by_charge[1]}/approve", json={"reason": "looks fine"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    history = [(e["actor"], e["action"]) for e in audit_rows(con, "refund", by_charge[1])]
    assert history == [("agent1", "refund.request"), ("approver1", "refund.approve")]
    # A refund for a rejected customer can still be rejected, which frees its amount.
    assert approver.post(f"/api/refunds/{by_charge[8]}/reject", json={"reason": "kyc rejected"}).status_code == 200
    for c in (approver, kyc):
        c.close()
    con.close()
    app.state.engine.dispose()


def test_ac7_pii_typed_into_a_refund_reason_is_stored_and_shown_masked(login, sql):
    agent = login("agent1")
    created = request_refund(agent, charge_id=1, amount_cents=75000,
                             reason=f"customer gave SSN {SSN_1} and account {BANK_1}")
    assert created.status_code == 201
    refund_id = created.json()["id"]
    stored = sql.execute("SELECT reason FROM refund WHERE id = ?", (refund_id,)).fetchone()[0]
    assert stored == "customer gave SSN ***-**-3456 and account ****3456"
    approver = login("approver1")
    for client in (agent, approver):
        for path in ("/api/refunds", f"/api/refunds/{refund_id}", "/refunds", f"/refunds/{refund_id}"):
            body = client.get(path).text
            assert SSN_1 not in body and BANK_1 not in body, path
    assert SSN_1 not in created.text and BANK_1 not in created.text
    assert SSN_1 not in approver.get("/refunds/queue").text


def test_ac7_ssn_glued_to_other_characters_never_reaches_an_audit_row(login, sql):
    agent, approver, kyc, admin = login("agent1"), login("approver1"), login("kyc1"), login("admin1")
    glued = [f"ssn{SSN_1} end", f"_{SSN_1}_ end", f"1{SSN_1} end", f"{SSN_1}9 end", f"x{SSN_2}y{SSN_3}z"]
    for charge_id, reason in enumerate(glued, start=1):
        assert request_refund(agent, charge_id=charge_id, amount_cents=75000, reason=reason).status_code == 201
    assert approver.post("/api/refunds/1/reject", json={"reason": f"k{SSN_1} acct{BANK_1}"}).status_code == 200
    assert kyc.post("/api/kyc/2/decision",
                    json={"decision": "reject", "reason": f"x{SSN_2} acct{BANK_2}"}).status_code == 200
    assert admin.put("/api/settings/auto-approve-limit",
                     json={"value_cents": 50000, "reason": f"id{SSN_3} n{BANK_3}"}).status_code == 200
    rows = sql.execute("SELECT * FROM audit_event").fetchall()
    assert len(rows) == 8
    for table in ("audit_event", "refund"):
        for row in sql.execute(f"SELECT * FROM {table}").fetchall():
            blob = " ".join("" if value is None else str(value) for value in tuple(row))
            for raw in RAW_VALUES:
                assert raw not in blob, (table, row["id"], raw)
    reasons = [r["reason"] for r in rows]
    assert "ssn***-**-3456 end" in reasons and "1***-**-3456 end" in reasons


def test_ac7_ssn_overlapping_an_ssn_shaped_prefix_never_reaches_an_audit_row(login, sql):
    agent, approver, kyc, admin = login("agent1"), login("approver1"), login("kyc1"), login("admin1")
    overlapping = [f"123-45-6{SSN_1}", f"999-99-9{SSN_1}x", f"{SSN_1[:10]}{SSN_1}", f"123-45-6{SSN_2} _{BANK_2}_ {SSN_2}"]
    for charge_id, reason in enumerate(overlapping, start=1):
        assert request_refund(agent, charge_id=charge_id, amount_cents=75000, reason=reason).status_code == 201
    assert approver.post("/api/refunds/1/reject", json={"reason": overlapping[0]}).status_code == 200
    assert approver.post("/refunds/2/decision",
                         data={"decision": "approve", "reason": overlapping[1]}).status_code == 303
    assert kyc.post("/api/kyc/2/decision", json={"decision": "reject", "reason": overlapping[3]}).status_code == 200
    assert admin.put("/api/settings/auto-approve-limit",
                     json={"value_cents": 0, "reason": overlapping[2]}).status_code == 200
    assert admin.post("/admin/settings", data={"value_cents": "0", "reason": overlapping[0]}).status_code == 200
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 9
    for table in ("audit_event", "refund"):
        for row in sql.execute(f"SELECT * FROM {table}").fetchall():
            blob = " ".join("" if value is None else str(value) for value in tuple(row))
            for raw in RAW_VALUES:
                assert raw not in blob, (table, row["id"], raw)
    for client, path in ((agent, "/api/refunds"), (agent, "/refunds"), (approver, "/refunds/queue"),
                         (admin, "/api/audit?limit=500"), (admin, "/admin/audit")):
        body = client.get(path).text
        for raw in RAW_VALUES:
            assert raw not in body, (path, raw)


def test_redacted_text_never_contains_an_ssn_or_long_digit_run():
    import random
    import re

    from app.foundation.pii import redact_text

    rng = random.Random(7)
    pieces = [SSN_1, SSN_2, BANK_1, BANK_2, "-", "-", "1", "9", "12", "123-45-6", "999-99-", "x", "_", " ", "-17-"]
    for _ in range(20000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 7)))
        out = redact_text(text)
        assert not re.search(r"\d{3}-\d{2}-\d{4}", out), (text, out)
        assert not re.search(r"\d{8,}", out), (text, out)
        for raw in (SSN_1, SSN_2, BANK_1, BANK_2):
            assert raw not in out, (text, out)
