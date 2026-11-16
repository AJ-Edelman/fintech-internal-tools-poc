"""AC6 (cap, through API, form and SQL) and AC8 (audit_event is append-only)."""
import sqlite3

import pytest

from tests.conftest import audit_rows, request_refund

INSERT_REFUND = (
    "INSERT INTO refund (charge_id, amount_cents, reason, status, requested_by, created_at, updated_at) "
    "VALUES (?, ?, 'direct sql', ?, 'nobody', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
)


def count(sql, charge_id=1):
    return sql.execute("SELECT COUNT(*) FROM refund WHERE charge_id = ?", (charge_id,)).fetchone()[0]


def test_ac6_single_request_over_the_charge_is_422_api(login, sql):
    agent = login("agent1")
    response = request_refund(agent, charge_id=1, amount_cents=200001)
    assert response.status_code == 422
    assert count(sql) == 0
    assert sql.execute("SELECT COUNT(*) FROM audit_event WHERE entity = 'refund'").fetchone()[0] == 0
    assert request_refund(agent, charge_id=1, amount_cents=200000).status_code == 201


def test_ac6_two_requests_that_together_exceed_the_charge_api(login, sql):
    agent = login("agent1")
    assert request_refund(agent, charge_id=1, amount_cents=120000).json()["status"] == "pending_approval"
    assert request_refund(agent, charge_id=1, amount_cents=80001).status_code == 422
    assert count(sql) == 1
    assert request_refund(agent, charge_id=1, amount_cents=80000).status_code == 201
    assert request_refund(agent, charge_id=1, amount_cents=1).status_code == 422
    # approved refunds count too
    assert request_refund(agent, charge_id=2, amount_cents=40000).json()["status"] == "approved"
    assert request_refund(agent, charge_id=2, amount_cents=160001).status_code == 422


def test_ac6_over_the_cap_is_422_through_the_form(login, sql):
    agent = login("agent1")
    over = agent.post("/refunds/new", data={"charge_id": "1", "amount": "2000.01", "reason": "form"})
    assert over.status_code == 422
    assert "exceed" in over.text
    assert count(sql) == 0

    first = agent.post("/refunds/new", data={"charge_id": "1", "amount": "1200.00", "reason": "form"})
    assert first.status_code == 303
    together = agent.post("/refunds/new", data={"charge_id": "1", "amount": "800.01", "reason": "form"})
    assert together.status_code == 422
    assert count(sql) == 1
    for amount in ("abc", "0", "-1", "1.005", ""):
        bad = agent.post("/refunds/new", data={"charge_id": "1", "amount": amount, "reason": "form"})
        assert bad.status_code == 422, amount
    assert agent.post("/refunds/new", data={"charge_id": "1", "amount": "5", "reason": ""}).status_code == 422
    assert count(sql) == 1


def test_ac6_rejecting_a_request_frees_its_amount(login):
    agent, approver = login("agent1"), login("approver1")
    first = request_refund(agent, charge_id=1, amount_cents=150000).json()
    assert request_refund(agent, charge_id=1, amount_cents=60000).status_code == 422
    assert approver.post(f"/api/refunds/{first['id']}/reject", json={"reason": "no"}).status_code == 200
    assert request_refund(agent, charge_id=1, amount_cents=60000).status_code == 201
    assert request_refund(agent, charge_id=1, amount_cents=140000).status_code == 201
    assert request_refund(agent, charge_id=1, amount_cents=1).status_code == 422


def test_ac6_sql_direct_insert_over_the_cap_fails(login, sql):
    for status in ("pending_approval", "approved"):
        with pytest.raises(sqlite3.IntegrityError, match="refund cap exceeded"):
            sql.execute(INSERT_REFUND, (1, 200001, status))
    assert count(sql) == 0

    sql.execute(INSERT_REFUND, (1, 150000, "pending_approval"))
    with pytest.raises(sqlite3.IntegrityError, match="refund cap exceeded"):
        sql.execute(INSERT_REFUND, (1, 50001, "approved"))
    sql.execute(INSERT_REFUND, (1, 50000, "approved"))
    assert count(sql) == 2

    # Updates cannot get around it either: raising an amount, or reviving a rejected row.
    with pytest.raises(sqlite3.IntegrityError, match="refund cap exceeded"):
        sql.execute("UPDATE refund SET amount_cents = 150001 WHERE amount_cents = 150000")
    sql.execute(INSERT_REFUND, (1, 1, "rejected"))
    with pytest.raises(sqlite3.IntegrityError, match="refund cap exceeded"):
        sql.execute("UPDATE refund SET status = 'approved' WHERE status = 'rejected'")
    with pytest.raises(sqlite3.IntegrityError, match="refund cap exceeded"):
        sql.execute("UPDATE charge SET amount_cents = 199999 WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):
        sql.execute(INSERT_REFUND, (1, 0, "rejected"))
    total = sql.execute("SELECT SUM(amount_cents) FROM refund WHERE charge_id = 1 "
                        "AND status IN ('pending_approval', 'approved')").fetchone()[0]
    assert total == 200000


def test_ac8_sql_update_and_delete_on_audit_event_fail_and_leave_the_row_unchanged(login, sql):
    refund = request_refund(login("agent1"), amount_cents=75000).json()
    before = [tuple(r) for r in sql.execute("SELECT * FROM audit_event ORDER BY id")]
    assert len(before) == 1
    event_id = before[0][0]

    for statement in (
        f"UPDATE audit_event SET actor = 'mallory' WHERE id = {event_id}",
        f"UPDATE audit_event SET reason = NULL, after = '{{}}' WHERE id = {event_id}",
        "UPDATE audit_event SET created_at = '1999-01-01T00:00:00Z'",
    ):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            sql.execute(statement)
        assert [tuple(r) for r in sql.execute("SELECT * FROM audit_event ORDER BY id")] == before

    for statement in (f"DELETE FROM audit_event WHERE id = {event_id}", "DELETE FROM audit_event"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            sql.execute(statement)
        assert [tuple(r) for r in sql.execute("SELECT * FROM audit_event ORDER BY id")] == before

    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        sql.execute("INSERT OR REPLACE INTO audit_event (id, actor, action, entity, entity_id, created_at) "
                    f"VALUES ({event_id}, 'mallory', 'x', 'refund', '1', 'now')")
    assert [tuple(r) for r in sql.execute("SELECT * FROM audit_event ORDER BY id")] == before
    assert len(audit_rows(sql, "refund", refund["id"])) == 1


def test_change_and_audit_event_commit_together_or_not_at_all(app, login, sql, monkeypatch):
    import app.foundation.workflow as engine

    agent, approver = login("agent1"), login("approver1")
    refund = request_refund(agent, amount_cents=75000).json()

    def boom(*args, **kwargs):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(engine, "write_audit", boom)
    with pytest.raises(RuntimeError):
        approver.post(f"/api/refunds/{refund['id']}/approve", json={"reason": "ok"})
    with pytest.raises(RuntimeError):
        request_refund(agent, charge_id=2, amount_cents=100)
    monkeypatch.undo()

    assert sql.execute("SELECT status FROM refund WHERE id = ?", (refund["id"],)).fetchone()[0] == "pending_approval"
    assert count(sql, charge_id=2) == 0
    assert len(audit_rows(sql, "refund", refund["id"])) == 1


def test_ac1_replacing_a_charge_cannot_shrink_it_below_its_refunds(login, sql):
    assert request_refund(login("agent1"), charge_id=1, amount_cents=75000).status_code == 201
    for foreign_keys in ("ON", "OFF"):
        sql.execute(f"PRAGMA foreign_keys = {foreign_keys}")
        with pytest.raises(sqlite3.DatabaseError, match="refund cap exceeded"):
            sql.execute("INSERT OR REPLACE INTO charge (id, customer_id, amount_cents, created_at) "
                        "VALUES (1, 1, 74999, '2026-01-01T00:00:00Z')")
    assert sql.execute("SELECT amount_cents FROM charge WHERE id = 1").fetchone()[0] == 200000



def test_integers_too_large_for_the_database_are_422_not_500(login):
    huge = 9999999999999999999
    agent, approver, kyc = login("agent1"), login("approver1"), login("kyc1")
    assert request_refund(agent, charge_id=huge, amount_cents=100).status_code == 422
    assert request_refund(agent, charge_id=1, amount_cents=huge).status_code == 422
    assert agent.post("/refunds/new", data={"charge_id": str(huge), "amount": "1.00",
                                            "reason": "x"}).status_code == 422
    for path in (f"/api/refunds/{huge}", f"/refunds/{huge}", f"/api/customers/{huge}",
                 f"/customers/{huge}", f"/api/charges?customer_id={huge}"):
        assert agent.get(path).status_code == 422, path
    assert approver.post(f"/api/refunds/{huge}/approve", json={"reason": "x"}).status_code == 422
    assert kyc.post(f"/api/kyc/{huge}/decision",
                    json={"decision": "approve", "reason": "x"}).status_code == 422
