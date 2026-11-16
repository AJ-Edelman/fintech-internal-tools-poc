"""AC26 and AC27: BUILD_SPEC_3 fix 2 data-layer rules hold against direct SQL, and 007 upgrades in place."""
import os
import sqlite3

import pytest

from app.foundation.db import applied_versions, migrate
from tests.conftest import request_refund, seed_basics

NOW = "2026-01-01T00:00:00Z"


def _insert_refund(sql, charge_id=1, status="pending_approval", requested_by="agent1", decided_by=None,
                   amount=10000):
    cur = sql.execute(
        "INSERT INTO refund (charge_id, amount_cents, reason, status, requested_by, decided_by, created_at, "
        "updated_at) VALUES (?, ?, 'r', ?, ?, ?, ?, ?)", (charge_id, amount, status, requested_by, decided_by,
                                                          NOW, NOW))
    return cur.lastrowid


def _insert_override(sql, customer_id=1, status="pending_approval", requested_by="agent1", decided_by=None):
    current = sql.execute("SELECT daily_limit_cents FROM customer WHERE id = ?", (customer_id,)).fetchone()[0]
    cur = sql.execute(
        "INSERT INTO limit_override (customer_id, current_limit_cents, requested_limit_cents, reason, status, "
        "requested_by, decided_by, created_at, updated_at) VALUES (?, ?, ?, 'r', ?, ?, ?, ?, ?)",
        (customer_id, current, current + 100000, status, requested_by, decided_by, NOW, NOW))
    return cur.lastrowid


def _row(sql, table, row_id):
    return dict(sql.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone())


def _count(sql, table):
    return sql.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _set_kyc_required(sql, on: bool):
    sql.execute("UPDATE setting SET value = ? WHERE key = 'refund_requires_kyc'", ("true" if on else "false",))


# --- 2(a) no self-decision --------------------------------------------------------------------

@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_ac26_refund_self_decision_by_update_fails_and_row_unchanged(sql, status):
    refund_id = _insert_refund(sql)
    before = _row(sql, "refund", refund_id)
    with pytest.raises(sqlite3.IntegrityError, match="cannot decide own refund"):
        sql.execute("UPDATE refund SET status = ?, decided_by = requested_by WHERE id = ?", (status, refund_id))
    assert _row(sql, "refund", refund_id) == before


@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_ac26_refund_self_decided_insert_fails(sql, status):
    n = _count(sql, "refund")
    with pytest.raises(sqlite3.IntegrityError, match="cannot decide own refund"):
        _insert_refund(sql, status=status, decided_by="agent1")
    assert _count(sql, "refund") == n


def test_ac26_refund_decided_by_someone_else_still_works(sql):
    refund_id = _insert_refund(sql)
    sql.execute("UPDATE refund SET status = 'approved', decided_by = 'approver1' WHERE id = ?", (refund_id,))
    assert _row(sql, "refund", refund_id)["status"] == "approved"


@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_ac26_limit_override_self_decision_by_update_fails_and_row_unchanged(sql, status):
    override_id = _insert_override(sql)
    before = _row(sql, "limit_override", override_id)
    with pytest.raises(sqlite3.IntegrityError, match="cannot decide own limit override"):
        sql.execute("UPDATE limit_override SET status = ?, decided_by = requested_by WHERE id = ?",
                    (status, override_id))
    assert _row(sql, "limit_override", override_id) == before


@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_ac26_limit_override_self_decided_insert_fails(sql, status):
    n = _count(sql, "limit_override")
    with pytest.raises(sqlite3.IntegrityError, match="cannot decide own limit override"):
        _insert_override(sql, status=status, decided_by="agent1")
    assert _count(sql, "limit_override") == n


# --- 2(b) refunds need approved KYC while the setting is on ------------------------------------

@pytest.mark.parametrize("charge_id", [7, 8])  # customer 2 pending, customer 3 rejected
def test_ac26_refund_insert_for_non_kyc_customer_fails(sql, charge_id):
    n = _count(sql, "refund")
    with pytest.raises(sqlite3.IntegrityError, match="requires approved KYC"):
        _insert_refund(sql, charge_id=charge_id)
    assert _count(sql, "refund") == n


def test_ac26_missing_setting_row_means_kyc_required(sql):
    sql.execute("DELETE FROM setting WHERE key = 'refund_requires_kyc'")
    with pytest.raises(sqlite3.IntegrityError, match="requires approved KYC"):
        _insert_refund(sql, charge_id=7)


def test_ac26_refund_approve_after_kyc_revoked_fails_and_row_unchanged(sql):
    refund_id = _insert_refund(sql, charge_id=1)
    sql.execute("UPDATE customer SET kyc_status = 'pending' WHERE id = 1")
    before = _row(sql, "refund", refund_id)
    with pytest.raises(sqlite3.IntegrityError, match="requires approved KYC"):
        sql.execute("UPDATE refund SET status = 'approved', decided_by = 'approver1' WHERE id = ?", (refund_id,))
    assert _row(sql, "refund", refund_id) == before
    # Rejecting is still allowed.
    sql.execute("UPDATE refund SET status = 'rejected', decided_by = 'approver1' WHERE id = ?", (refund_id,))
    assert _row(sql, "refund", refund_id)["status"] == "rejected"


def test_ac26_moving_approved_refund_to_non_kyc_charge_fails(sql):
    refund_id = _insert_refund(sql, charge_id=1)
    sql.execute("UPDATE refund SET status = 'approved', decided_by = 'approver1' WHERE id = ?", (refund_id,))
    before = _row(sql, "refund", refund_id)
    with pytest.raises(sqlite3.IntegrityError, match="requires approved KYC"):
        sql.execute("UPDATE refund SET charge_id = 7 WHERE id = ?", (refund_id,))
    assert _row(sql, "refund", refund_id) == before


def test_ac26_with_kyc_setting_off_rule_2b_no_longer_blocks(sql):
    _set_kyc_required(sql, False)
    refund_id = _insert_refund(sql, charge_id=7)
    sql.execute("UPDATE refund SET status = 'approved', decided_by = 'approver1' WHERE id = ?", (refund_id,))
    assert _row(sql, "refund", refund_id)["status"] == "approved"
    _insert_refund(sql, charge_id=8, status="approved", decided_by="approver1")
    # 2(a) still applies with the setting off.
    with pytest.raises(sqlite3.IntegrityError, match="cannot decide own refund"):
        _insert_refund(sql, charge_id=8, status="approved", decided_by="agent1")


# --- 2(c) auto-approve limit range -------------------------------------------------------------

def _limit(sql):
    return sql.execute("SELECT value FROM setting WHERE key = 'auto_approve_limit_cents'").fetchone()[0]


@pytest.mark.parametrize("bad", ["75001", "-1", "500.5", "50000.0", "abc", "", "true", "1e4", "1000000",
                                 75001, -1, 500.5])
def test_ac26_auto_approve_limit_bad_update_fails_and_row_unchanged(sql, bad):
    before = _limit(sql)
    with pytest.raises(sqlite3.IntegrityError, match="auto-approve limit"):
        sql.execute("UPDATE setting SET value = ? WHERE key = 'auto_approve_limit_cents'", (bad,))
    assert _limit(sql) == before


@pytest.mark.parametrize("bad", ["75001", "-5", "1.5", "x"])
def test_ac26_auto_approve_limit_bad_insert_or_replace_fails_and_row_unchanged(sql, bad):
    before = _limit(sql)
    with pytest.raises(sqlite3.IntegrityError, match="auto-approve limit"):
        sql.execute("INSERT OR REPLACE INTO setting (key, value) VALUES ('auto_approve_limit_cents', ?)", (bad,))
    assert _limit(sql) == before
    sql.execute("DELETE FROM setting WHERE key = 'auto_approve_limit_cents'")
    with pytest.raises(sqlite3.IntegrityError, match="auto-approve limit"):
        sql.execute("INSERT INTO setting (key, value) VALUES ('auto_approve_limit_cents', ?)", (bad,))


def test_ac26_renaming_another_setting_to_the_limit_key_is_checked(sql):
    sql.execute("DELETE FROM setting WHERE key = 'auto_approve_limit_cents'")
    sql.execute("INSERT INTO setting (key, value) VALUES ('scratch', '99999')")
    with pytest.raises(sqlite3.IntegrityError, match="auto-approve limit"):
        sql.execute("UPDATE setting SET key = 'auto_approve_limit_cents' WHERE key = 'scratch'")


@pytest.mark.parametrize("good", ["0", "75000", "123"])
def test_ac26_auto_approve_limit_valid_values_accepted(sql, good):
    sql.execute("UPDATE setting SET value = ? WHERE key = 'auto_approve_limit_cents'", (good,))
    assert _limit(sql) == good
    sql.execute("INSERT OR REPLACE INTO setting (key, value) VALUES ('auto_approve_limit_cents', ?)", (good,))
    assert _limit(sql) == good


# --- AC2 still holds -----------------------------------------------------------------------------

def test_ac26_system_auto_approval_still_works_over_http(login, sql):
    agent = login("agent1")
    response = request_refund(agent, charge_id=1, amount_cents=50000)
    assert response.status_code == 201, response.text
    refund = response.json()
    assert (refund["status"], refund["decided_by"]) == ("approved", "system")
    row = _row(sql, "refund", refund["id"])
    assert (row["status"], row["requested_by"], row["decided_by"]) == ("approved", "agent1", "system")


# --- AC27 migration 006 -> 007 -----------------------------------------------------------------

def _dump(path) -> dict:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "AND name <> 'schema_migration' ORDER BY name")]
    out = {t: [dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in tables}
    con.close()
    return out


def _database_at_006(tmp_path) -> str:
    path = str(tmp_path / "at006.db")
    assert migrate(path, target=6) == [1, 2, 3, 4, 5, 6]
    seed_basics(path)
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("INSERT INTO user_session (token, user_id, created_at, last_seen_at) VALUES ('tok', 1, ?, ?)",
                (NOW, NOW))
    # Rows 007 would refuse today: a self-decided refund and override, and refunds on non-KYC customers.
    for charge_id, status, req, dec in ((1, "pending_approval", "agent1", None),
                                        (2, "approved", "agent1", "approver1"),
                                        (3, "rejected", "agent1", "agent1"),
                                        (7, "approved", "agent2", "approver1"),
                                        (8, "pending_approval", "agent2", None)):
        con.execute("INSERT INTO refund (charge_id, amount_cents, reason, status, requested_by, decided_by, "
                    "created_at, updated_at) VALUES (?, 1000, 'pre-007', ?, ?, ?, ?, ?)",
                    (charge_id, status, req, dec, NOW, NOW))
    for customer_id, status, dec in ((1, "approved", "agent1"), (2, "pending_approval", None)):
        current = con.execute("SELECT daily_limit_cents FROM customer WHERE id = ?", (customer_id,)).fetchone()[0]
        con.execute("INSERT INTO limit_override (customer_id, current_limit_cents, requested_limit_cents, reason, "
                    "status, requested_by, decided_by, created_at, updated_at) VALUES (?, ?, ?, 'pre-007', ?, "
                    "'agent1', ?, ?, ?)", (customer_id, current, current + 1000, status, dec, NOW, NOW))
    con.execute("INSERT INTO audit_event (actor, action, entity, entity_id, created_at) "
                "VALUES ('agent1', 'test.event', 'refund', '1', ?)", (NOW,))
    audit_id = con.execute("SELECT MAX(id) FROM audit_event").fetchone()[0]
    con.execute("INSERT INTO connector_message (connector, kind, entity, entity_id, idempotency_key, payload, "
                "status, audit_event_id, created_at, updated_at) VALUES ('payments', 'payout', 'refund', '2', "
                "'k1', '{}', 'pending', ?, ?, ?)", (audit_id, NOW, NOW))
    con.close()
    return path


def test_ac27_database_at_006_upgrades_to_007_with_every_row_intact(tmp_path):
    path = _database_at_006(tmp_path)
    before = _dump(path)
    for table, rows in before.items():
        assert rows, f"{table} has no data before the upgrade"
    inode = os.stat(path).st_ino

    assert migrate(path, target=7) == [7]
    assert applied_versions(path)[-1] == 7
    assert os.stat(path).st_ino == inode, "upgraded in place, not recreated"
    assert _dump(path) == before
    assert migrate(path, target=7) == []
