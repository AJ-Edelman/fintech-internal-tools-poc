"""Tool 3 (account limit overrides): AC22, AC23 and the tool 3 part of AC20."""
import sqlite3

import pytest

from app.foundation.fake_services import get_fake
from tests.conftest import audit_rows


@pytest.fixture
def limit_users(add_user, sql):
    add_user("limits1", ["limits_agent"])
    add_user("limits2", ["limits_approver"])
    add_user("limits3", ["limits_approver"])
    add_user("bothlim", ["limits_agent", "limits_approver"])
    for name in ("limits1", "limits2", "limits3", "bothlim"):
        sql.execute("UPDATE role_assignment SET region = 'US' WHERE user_id = "
                    "(SELECT id FROM app_user WHERE username = ?)", (name,))


def ask(client, customer_id=1, cents=900000, reason="seasonal volume"):
    return client.post("/api/limits", json={"customer_id": customer_id, "requested_limit_cents": cents,
                                            "reason": reason})


def test_ac22_request_approve_changes_limit_with_one_ledger_message(login, sql, limit_users):
    agent, approver = login("limits1"), login("limits2")
    created = ask(agent)
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["status"] == "pending_approval" and row["current_limit_cents"] == 500000
    assert sql.execute("SELECT daily_limit_cents FROM customer WHERE id = 1").fetchone()[0] == 500000

    decided = approver.post(f"/api/limits/{row['id']}/approve", json={"reason": "volume verified"})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved" and decided.json()["decided_by"] == "limits2"
    assert sql.execute("SELECT daily_limit_cents FROM customer WHERE id = 1").fetchone()[0] == 900000

    events = audit_rows(sql, "limit_override", row["id"])
    assert [(e["actor"], e["action"]) for e in events] == [("limits1", "limit_override.request"),
                                                           ("limits2", "limit_override.approve")]
    messages = sql.execute("SELECT * FROM connector_message WHERE entity = 'limit_override'").fetchall()
    assert len(messages) == 1 and messages[0]["connector"] == "ledger" and messages[0]["status"] == "sent"
    assert len(get_fake("ledger").received) == 1
    detail = agent.get(f"/api/limits/{row['id']}").json()
    assert detail["message"]["status"] == "sent" and len(detail["history"]) == 2
    assert agent.get(f"/limits/{row['id']}").status_code == 200


def test_ac22_pages_render_from_the_shared_pieces(login, limit_users):
    agent, approver = login("limits1"), login("limits2")
    assert agent.get("/limits/new").status_code == 200
    form = agent.post("/limits/new", data={"customer_id": "1", "amount": "7,500.00", "reason": "growth"})
    assert form.status_code == 303
    assert 'data-shared-list="limit_queue"' in approver.get("/limits/queue").text
    assert 'data-shared-list="limit_overrides"' in agent.get("/limits").text
    override_id = int(form.headers["location"].rsplit("/", 1)[1])
    page = approver.post(f"/limits/{override_id}/decision", data={"decision": "reject", "reason": "no"})
    assert page.status_code == 303


def test_ac23_denials(login, sql, limit_users):
    agent, approver, both = login("limits1"), login("limits2"), login("bothlim")
    # self-approval 403, state unchanged
    mine = ask(both).json()
    assert both.post(f"/api/limits/{mine['id']}/approve", json={"reason": "self"}).status_code == 403
    assert both.post(f"/api/limits/{mine['id']}/reject", json={"reason": "self"}).status_code == 403
    assert sql.execute("SELECT status FROM limit_override WHERE id = ?", (mine["id"],)).fetchone()[0] == \
        "pending_approval"
    # a refund agent requesting 403
    assert ask(login("agent1"), cents=600000).status_code == 403
    assert login("approver1").post(f"/api/limits/{mine['id']}/approve", json={"reason": "x"}).status_code == 403
    # second pending request for the same customer 422, and by direct SQL
    second = ask(agent, cents=700000)
    assert second.status_code == 422 and "pending" in second.json()["detail"]
    with pytest.raises(sqlite3.IntegrityError):
        sql.execute("INSERT INTO limit_override (customer_id, current_limit_cents, requested_limit_cents, reason, "
                    "status, requested_by, created_at, updated_at) VALUES (1, 500000, 800000, 'sql', "
                    "'pending_approval', 'x', 'now', 'now')")
    # customer not KYC-approved 422 (2 pending, 3 rejected)
    for customer_id in (2, 3):
        response = ask(agent, customer_id=customer_id)
        assert response.status_code == 422 and "KYC" in response.json()["detail"]
    # at or below the current limit, or above the maximum, 422
    assert approver.post(f"/api/limits/{mine['id']}/reject", json={"reason": "clear"}).status_code == 200
    for cents in (500000, 400000, 5000001):
        assert ask(agent, cents=cents).status_code == 422, cents
    assert ask(agent, cents=5000000).status_code == 201
    assert ask(agent, reason=" ").status_code == 422
    assert sql.execute("SELECT COUNT(*) FROM limit_override WHERE status = 'pending_approval'").fetchone()[0] == 1
    assert sql.execute("SELECT COUNT(*) FROM connector_message WHERE entity = 'limit_override'").fetchone()[0] == 0


def test_ac20_tool3_eu_users_cannot_see_or_act_on_us_customers(login, sql, add_user, limit_users):
    add_user("limitseu", ["limits_agent"])
    add_user("limapeu", ["limits_approver"])
    for name in ("limitseu", "limapeu"):
        sql.execute("UPDATE role_assignment SET region = 'EU' WHERE user_id = "
                    "(SELECT id FROM app_user WHERE username = ?)", (name,))
    us = ask(login("limits1")).json()
    eu_agent, eu_approver = login("limitseu"), login("limapeu")
    assert ask(eu_agent, cents=950000).status_code == 404
    assert eu_agent.get(f"/api/limits/{us['id']}").status_code == 404
    assert eu_agent.get(f"/limits/{us['id']}").status_code == 404
    assert eu_agent.get("/api/limits").json()["total"] == 0
    assert eu_agent.get("/api/limits", params={"q": "Ada"}).json()["total"] == 0
    assert eu_approver.post(f"/api/limits/{us['id']}/approve", json={"reason": "x"}).status_code == 404
    assert sql.execute("SELECT status FROM limit_override WHERE id = ?", (us["id"],)).fetchone()[0] == \
        "pending_approval"
    assert login("limits2").get("/api/limits").json()["total"] == 1
