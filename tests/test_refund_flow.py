"""AC2 (flow, threshold, limit setting) and AC9 (history rebuilt from audit_event alone)."""
import json

from tests.conftest import audit_rows, request_refund


def test_ac2_750_goes_pending_then_approver_approves_with_audit_per_step(login, sql):
    agent, approver = login("agent1"), login("approver1")

    created = request_refund(agent, charge_id=1, amount_cents=75000, reason="item not received")
    assert created.status_code == 201
    refund = created.json()
    assert refund["status"] == "pending_approval"
    assert refund["requested_by"] == "agent1"
    assert refund["decided_by"] is None
    events = audit_rows(sql, "refund", refund["id"])
    assert [(e["actor"], e["action"]) for e in events] == [("agent1", "refund.request")]

    decided = approver.post(f"/api/refunds/{refund['id']}/approve", json={"reason": "verified"})
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
    assert decided.json()["decided_by"] == "approver1"
    events = audit_rows(sql, "refund", refund["id"])
    assert [(e["actor"], e["action"]) for e in events] == [
        ("agent1", "refund.request"),
        ("approver1", "refund.approve"),
    ]
    assert json.loads(events[1]["before"]) == {"status": "pending_approval"}
    assert json.loads(events[1]["after"])["status"] == "approved"
    assert events[1]["reason"] == "verified"


def test_ac2_500_00_on_fresh_charge_is_approved_by_system(login, sql):
    agent = login("agent1")
    refund = request_refund(agent, charge_id=1, amount_cents=50000).json()
    assert refund["status"] == "approved"
    assert refund["decided_by"] == "system"
    events = audit_rows(sql, "refund", refund["id"])
    assert [(e["actor"], e["action"]) for e in events] == [
        ("agent1", "refund.request"),
        ("system", "refund.auto_approve"),
    ]
    after = json.loads(events[1]["after"])
    assert after["approver"] == "system"
    assert after["requested_by"] == "agent1"
    assert after["status"] == "approved"


def test_ac2_500_01_on_fresh_charge_is_pending(login, sql):
    agent = login("agent1")
    refund = request_refund(agent, charge_id=1, amount_cents=50001).json()
    assert refund["status"] == "pending_approval"
    assert [e["action"] for e in audit_rows(sql, "refund", refund["id"])] == ["refund.request"]


def test_ac2_threshold_counts_the_charge_total_not_just_this_request(login):
    agent = login("agent1")
    assert request_refund(agent, charge_id=1, amount_cents=30000).json()["status"] == "approved"
    # 300.00 + 200.01 pushes the charge's pending + approved total over 500.00.
    assert request_refund(agent, charge_id=1, amount_cents=20001).json()["status"] == "pending_approval"
    # Still over the limit while the previous one is pending.
    assert request_refund(agent, charge_id=1, amount_cents=1).json()["status"] == "pending_approval"


def test_ac2_admin_changes_limit_boundary_moves_and_change_is_audited(login, sql):
    agent, admin = login("agent1"), login("admin1")
    changed = admin.put("/api/settings/auto-approve-limit",
                        json={"value_cents": 60000, "reason": "Q4 policy"})
    assert changed.status_code == 200
    assert changed.json()["value_cents"] == 60000

    events = audit_rows(sql, "setting", "auto_approve_limit_cents")
    assert len(events) == 1
    assert events[0]["actor"] == "admin1"
    assert events[0]["action"] == "setting.change"
    assert json.loads(events[0]["before"]) == {"value": 50000}
    assert json.loads(events[0]["after"]) == {"value": 60000}
    assert events[0]["reason"] == "Q4 policy"

    assert request_refund(agent, charge_id=1, amount_cents=60000).json()["status"] == "approved"
    assert request_refund(agent, charge_id=2, amount_cents=60001).json()["status"] == "pending_approval"

    # Moving it down moves the boundary down too.
    assert admin.put("/api/settings/auto-approve-limit",
                     json={"value_cents": 0, "reason": "freeze"}).status_code == 200
    assert request_refund(agent, charge_id=3, amount_cents=1).json()["status"] == "pending_approval"


def test_ac2_hard_maximum_is_75000(login, sql):
    agent, admin = login("agent1"), login("admin1")
    at_max = admin.put("/api/settings/auto-approve-limit",
                       json={"value_cents": 75000, "reason": "max"})
    assert at_max.status_code == 200
    assert request_refund(agent, charge_id=1, amount_cents=75000).json()["status"] == "approved"
    assert request_refund(agent, charge_id=2, amount_cents=75001).json()["status"] == "pending_approval"

    for bad in (75001, 100000, -1):
        response = admin.put("/api/settings/auto-approve-limit",
                             json={"value_cents": bad, "reason": "too far"})
        assert response.status_code == 422, bad
    assert admin.get("/api/settings/auto-approve-limit").json()["value_cents"] == 75000
    assert len(audit_rows(sql, "setting", "auto_approve_limit_cents")) == 1


def test_ac2_limit_change_needs_no_reason_and_form_enforces_the_same_rules(login, sql):
    # Product change after the build: an admin no longer has to type a reason for a limit change.
    # The change is still audited with who, when, old and new value.
    admin = login("admin1")
    assert admin.put("/api/settings/auto-approve-limit",
                     json={"value_cents": 100, "reason": "  "}).status_code == 200
    assert admin.put("/api/settings/auto-approve-limit", json={"value_cents": 200}).status_code == 200
    assert admin.post("/admin/settings", data={"value_cents": "75001", "reason": "x"}).status_code == 422
    assert admin.post("/admin/settings", data={"value_cents": "70000", "reason": "form"}).status_code == 200
    assert admin.get("/api/settings/auto-approve-limit").json()["value_cents"] == 70000
    assert admin.post("/admin/settings", data={"amount": "750.01"}).status_code == 422
    assert admin.post("/admin/settings", data={"amount": "$650.00"}).status_code == 200
    assert admin.get("/api/settings/auto-approve-limit").json()["value_cents"] == 65000
    events = audit_rows(sql, "setting", "auto_approve_limit_cents")
    assert [(e["actor"], json.loads(e["before"])["value"], json.loads(e["after"])["value"], e["reason"])
            for e in events] == [("admin1", 50000, 100, None), ("admin1", 100, 200, None),
                                 ("admin1", 200, 70000, "form"), ("admin1", 70000, 65000, None)]


def test_ac2_non_admin_changing_limit_gets_403(login, sql):
    for username in ("agent1", "approver1", "kyc1"):
        client = login(username)
        response = client.put("/api/settings/auto-approve-limit",
                              json={"value_cents": 1, "reason": "nope"})
        assert response.status_code == 403, username
        assert client.post("/admin/settings",
                           data={"value_cents": "1", "reason": "nope"}).status_code == 403
    assert login("admin1").get("/api/settings/auto-approve-limit").json()["value_cents"] == 50000
    assert audit_rows(sql, "setting", "auto_approve_limit_cents") == []


def test_rejected_and_decided_requests_cannot_be_decided_again_409(login):
    agent, approver = login("agent1"), login("approver1")
    refund = request_refund(agent, amount_cents=75000).json()
    assert approver.post(f"/api/refunds/{refund['id']}/reject",
                         json={"reason": "no evidence"}).status_code == 200
    for action in ("approve", "reject"):
        again = approver.post(f"/api/refunds/{refund['id']}/{action}", json={"reason": "again"})
        assert again.status_code == 409
    auto = request_refund(agent, charge_id=2, amount_cents=100).json()
    assert approver.post(f"/api/refunds/{auto['id']}/approve",
                         json={"reason": "again"}).status_code == 409


def test_invalid_input_is_422(login):
    agent, approver = login("agent1"), login("approver1")
    for body in (
        {"charge_id": 1, "amount_cents": 0, "reason": "zero"},
        {"charge_id": 1, "amount_cents": -5, "reason": "negative"},
        {"charge_id": 1, "amount_cents": 10.5, "reason": "fraction"},
        {"charge_id": 1, "amount_cents": "100", "reason": "string"},
        {"charge_id": 1, "amount_cents": 100, "reason": "   "},
        {"charge_id": 1, "amount_cents": 100},
        {"charge_id": 9999, "amount_cents": 100, "reason": "no such charge"},
    ):
        assert agent.post("/api/refunds", json=body).status_code == 422, body
    refund = request_refund(agent, amount_cents=75000).json()
    assert approver.post(f"/api/refunds/{refund['id']}/approve", json={"reason": ""}).status_code == 422
    assert agent.get(f"/api/refunds/{refund['id']}").json()["status"] == "pending_approval"
    assert agent.get("/api/refunds?status=bogus").status_code == 422


def test_ac9_history_can_be_rebuilt_from_audit_event_alone(login, sql):
    agent, approver = login("agent1"), login("approver1")
    first = request_refund(agent, charge_id=1, amount_cents=75000, reason="damaged item").json()
    approver.post(f"/api/refunds/{first['id']}/reject", json={"reason": "no photo"})
    second = request_refund(agent, charge_id=2, amount_cents=12345, reason="double billed").json()

    def rebuild(refund_id):
        """Replay audit_event only; the refund table is not read."""
        state, steps = {}, []
        rows = sql.execute(
            "SELECT actor, action, before, after, reason, created_at FROM audit_event "
            "WHERE entity = 'refund' AND entity_id = ? ORDER BY id", (str(refund_id),)).fetchall()
        for row in rows:
            before = json.loads(row["before"]) if row["before"] else None
            after = json.loads(row["after"])
            if before is not None:
                assert before["status"] == state["status"], "before must match the replayed state"
            state.update(after)
            assert row["created_at"].endswith("Z") and row["reason"]
            steps.append((row["actor"], row["action"], before and before["status"], after["status"],
                          row["reason"]))
        return state, steps

    state, steps = rebuild(first["id"])
    assert steps == [
        ("agent1", "refund.request", None, "pending_approval", "damaged item"),
        ("approver1", "refund.reject", "pending_approval", "rejected", "no photo"),
    ]
    assert (state["status"], state["charge_id"], state["amount_cents"], state["requested_by"],
            state["decided_by"]) == ("rejected", 1, 75000, "agent1", "approver1")

    state, steps = rebuild(second["id"])
    assert steps == [
        ("agent1", "refund.request", None, "pending_approval", "double billed"),
        ("system", "refund.auto_approve", "pending_approval", "approved", "within auto-approve limit"),
    ]
    assert (state["status"], state["amount_cents"], state["decided_by"], state["approver"]) == (
        "approved", 12345, "system", "system")

    # The rebuilt state agrees with the live rows.
    for refund_id in (first["id"], second["id"]):
        live = sql.execute("SELECT * FROM refund WHERE id = ?", (refund_id,)).fetchone()
        rebuilt, _ = rebuild(refund_id)
        for column in ("status", "charge_id", "amount_cents", "requested_by", "decided_by"):
            assert rebuilt[column] == live[column]

    # The API detail and the detail page expose the same history.
    api = agent.get(f"/api/refunds/{first['id']}").json()["history"]
    assert [(e["actor"], e["action"]) for e in api] == [("agent1", "refund.request"),
                                                        ("approver1", "refund.reject")]
    page = agent.get(f"/refunds/{first['id']}")
    assert page.status_code == 200
    assert "refund.reject" in page.text and "no photo" in page.text and "approver1" in page.text
