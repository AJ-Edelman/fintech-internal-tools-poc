"""AC15–AC17: transactional outbox, delivery, retries and receiver idempotency."""
import json
import sqlite3

import pytest

from app.foundation import connectors, fake_services
from app.foundation.errors import AppError
from tests.conftest import BANK_1, SSN_1, audit_rows, request_refund


def _messages(admin, **params):
    response = admin.get("/api/connectors/messages", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _approve(agent, approver, amount=75000, charge=1):
    response = request_refund(agent, charge_id=charge, amount_cents=amount)
    assert response.status_code == 201, response.text
    refund = response.json()
    if refund["status"] == "pending_approval":
        response = approver.post(f"/api/refunds/{refund['id']}/approve", json={"reason": "verified"})
        assert response.status_code == 200, response.text
        refund = response.json()
    assert refund["status"] == "approved"
    return refund


@pytest.mark.parametrize("amount", [10000, 75000], ids=["automatic", "human"])
def test_ac15_approval_records_one_message_and_receives_once(login, app, sql, amount):
    agent, approver, admin = login("agent1"), login("approver1"), login("admin1")
    refund = _approve(agent, approver, amount)
    result = _messages(admin)
    assert result["total"] == 1
    message = result["items"][0]
    assert (message["entity"], message["entity_id"], message["status"], message["attempts"]) == (
        "refund", str(refund["id"]), "sent", 1)
    assert message["idempotency_key"] == connectors.idempotency_key("refund.payout", "refund", refund["id"])
    fake = fake_services.get_fake("payments")
    assert fake.calls == 1
    assert fake.received == {message["idempotency_key"]: {
        "refund_id": refund["id"], "charge_id": 1, "amount_cents": amount, "currency": "USD"}}
    event = sql.execute("SELECT * FROM audit_event WHERE id = ?", (message["audit_event_id"],)).fetchone()
    assert event["action"] == ("refund.auto_approve" if amount == 10000 else "refund.approve")
    with app.state.engine.begin() as conn:
        assert connectors.latest_for(conn, "refund", refund["id"])["status"] == "sent"
        assert connectors.latest_for(conn, "refund", 999999) is None
    assert connectors.deliver(app.state.engine, message["id"])["status"] == "sent"
    assert connectors.deliver_pending(app.state.engine) == []
    assert fake.calls == 1
    assert agent.get(f"/api/refunds/{refund['id']}").json()["status"] == "approved"


def test_ac16_failure_three_audited_attempts_then_authorized_retry(login, sql):
    agent, approver, admin = login("agent1"), login("approver1"), login("admin1")
    fake = fake_services.get_fake("payments")
    fake.fail = True
    refund = _approve(agent, approver)
    message = _messages(admin, status="failed")["items"][0]
    assert (message["status"], message["attempts"], fake.calls, len(fake.received)) == ("failed", 3, 3, 0)
    attempts = audit_rows(sql, "connector_message", message["id"])
    assert len(attempts) == 3
    assert all(e["actor"] == "system" and e["action"] == "connector.attempt" for e in attempts)
    assert [json.loads(e["after"])["attempts"] for e in attempts] == [1, 2, 3]
    assert [json.loads(e["after"])["status"] for e in attempts] == ["pending", "pending", "failed"]
    assert agent.get(f"/api/refunds/{refund['id']}").json()["status"] == "approved"
    path = f"/api/connectors/messages/{message['id']}/retry"
    assert agent.post(path, json={"reason": "retry"}).status_code == 403
    assert approver.post(path, json={"reason": "retry"}).status_code == 403
    for body in ({}, {"reason": ""}, {"reason": "  "}):
        assert admin.post(path, json=body).status_code == 422
    assert len(audit_rows(sql, "connector_message", message["id"])) == 3
    assert fake.calls == 3
    fake.fail = False
    response = admin.post(path, json={"reason": "receiver recovered"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "sent"
    assert fake.calls == 4 and len(fake.received) == 1
    events = audit_rows(sql, "connector_message", message["id"])
    assert [e["action"] for e in events] == ["connector.attempt"] * 3 + ["connector.retry", "connector.attempt"]
    assert (events[3]["actor"], events[3]["reason"]) == ("admin1", "receiver recovered")
    assert json.loads(events[3]["before"]) == {"status": "failed", "attempts": 3}
    assert admin.post(path, json={"reason": "again"}).status_code == 409
    assert len(fake.received) == 1


def test_ac15_resend_after_lost_acknowledgment_has_one_receiver_effect(login, monkeypatch, sql):
    agent, admin = login("agent1"), login("admin1")
    fake = fake_services.get_fake("payments")
    receive = fake.receive

    def lost_ack(key, payload):
        outcome = receive(key, payload)
        if fake.calls == 1:
            raise ConnectionError("acknowledgment lost after acceptance")
        return outcome

    monkeypatch.setattr(fake, "receive", lost_ack)
    response = request_refund(agent, amount_cents=10000)
    assert response.status_code == 201
    message = _messages(admin)["items"][0]
    assert (message["status"], message["attempts"], fake.calls, len(fake.received)) == ("sent", 2, 2, 1)
    events = audit_rows(sql, "connector_message", message["id"])
    assert json.loads(events[-1]["after"])["outcome"] == "duplicate"


def test_ac17_denied_transitions_create_no_message(login, add_user, sql):
    add_user("both", ["refund_agent", "refund_approver"])
    agent, both, admin = login("agent1"), login("both"), login("admin1")
    assert request_refund(agent, amount_cents=200001).status_code == 422
    pending = request_refund(both, amount_cents=75000).json()
    assert pending["status"] == "pending_approval"
    assert both.post(f"/api/refunds/{pending['id']}/approve", json={"reason": "self"}).status_code == 403
    assert _messages(admin)["total"] == 0
    assert fake_services.get_fake("payments").calls == 0
    assert sql.execute("SELECT COUNT(*) FROM connector_message").fetchone()[0] == 0
    assert len(audit_rows(sql, "refund", pending["id"])) == 1


def test_ac17_outbox_failure_rolls_back_transition_and_audit(login, monkeypatch, sql):
    agent = login("agent1")
    enqueue = connectors.enqueue

    def abort_after_enqueue(conn, **values):
        enqueue(conn, **values)
        raise AppError(422, "abort transaction after message was inserted")

    monkeypatch.setattr(connectors, "enqueue", abort_after_enqueue)
    assert request_refund(agent, amount_cents=10000).status_code == 422
    assert sql.execute("SELECT COUNT(*) FROM refund").fetchone()[0] == 0
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 0
    assert sql.execute("SELECT COUNT(*) FROM connector_message").fetchone()[0] == 0
    assert fake_services.get_fake("payments").calls == 0


@pytest.mark.parametrize("audit_id", [None, 999999])
def test_ac17_sql_rejects_message_without_valid_audit_even_with_foreign_keys_off(sql, audit_id):
    assert sql.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        sql.execute(
            "INSERT INTO connector_message (connector, kind, entity, entity_id, idempotency_key, "
            "payload, status, audit_event_id, created_at, updated_at) "
            "VALUES ('payments', 'refund.payout', 'refund', '1', 'orphan', '{}', 'pending', ?, 'now', 'now')",
            (audit_id,))
    assert sql.execute("SELECT COUNT(*) FROM connector_message").fetchone()[0] == 0


def test_ac17_sql_cannot_remove_message_audit_reference(login, sql):
    request_refund(login("agent1"), amount_cents=10000)
    for value in (None, 999999):
        with pytest.raises(sqlite3.IntegrityError):
            sql.execute("UPDATE connector_message SET audit_event_id = ?", (value,))


def test_payload_and_delivery_error_and_retry_reason_are_redacted(login, monkeypatch, sql):
    agent, admin = login("agent1"), login("admin1")
    fake = fake_services.get_fake("payments")
    enqueue = connectors.enqueue

    def sensitive_payload(conn, **values):
        values["payload"] = {"ssn": SSN_1, "bank_account": BANK_1,
                             "nested": [{"note": f"{SSN_1} {BANK_1}"}]}
        return enqueue(conn, **values)

    def sensitive_failure(key, payload):
        raise ConnectionError(f"unavailable {SSN_1} {BANK_1}")

    monkeypatch.setattr(connectors, "enqueue", sensitive_payload)
    monkeypatch.setattr(fake, "receive", sensitive_failure)
    response = request_refund(agent, amount_cents=10000)
    assert response.status_code == 201
    message = _messages(admin)["items"][0]
    assert message["status"] == "failed"
    monkeypatch.undo()
    response = admin.post(f"/api/connectors/messages/{message['id']}/retry",
                          json={"reason": f"recover {SSN_1} {BANK_1}"})
    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    content = json.dumps(_messages(admin)) + json.dumps(fake.received)
    content += " ".join(str(tuple(r)) for r in audit_rows(sql, "connector_message", message["id"]))
    assert SSN_1 not in content and BANK_1 not in content
    assert fake.received[message["idempotency_key"]]["ssn"] == "***-**-3456"


def test_receiver_address_comes_from_configuration(login, sql):
    agent, admin = login("agent1"), login("admin1")
    sql.execute("UPDATE setting SET value = ? WHERE key = 'connector_payments_url'", ('"fake://ledger"',))
    assert request_refund(agent, amount_cents=10000).status_code == 201
    assert _messages(admin)["items"][0]["status"] == "sent"
    assert fake_services.get_fake("payments").calls == 0
    assert len(fake_services.get_fake("ledger").received) == 1


def test_message_api_exact_paging_filters_validation_and_permissions(login):
    agent, admin = login("agent1"), login("admin1")
    for charge in range(1, 6):
        assert request_refund(agent, charge_id=charge, amount_cents=10000).status_code == 201
    ids = []
    for page_no, size in ((1, 2), (2, 2), (3, 1), (4, 0)):
        result = _messages(admin, status="sent", page=page_no, page_size=2)
        assert result["total"] == 5 and result["pages"] == 3
        assert len(result["items"]) == size
        ids.extend(row["id"] for row in result["items"])
    assert ids == sorted(set(ids)) and len(ids) == 5
    assert _messages(admin, status="failed")["total"] == 0
    for params in ({"status": "unknown"}, {"page": 0}, {"page_size": 0}, {"page_size": 201}):
        assert admin.get("/api/connectors/messages", params=params).status_code == 422
    assert agent.get("/api/connectors/messages").status_code == 403
    assert agent.get("/admin/connectors").status_code == 403


def test_retry_html_form_enforces_permission_reason_and_state(login):
    agent, admin = login("agent1"), login("admin1")
    fake = fake_services.get_fake("payments")
    fake.fail = True
    assert request_refund(agent, amount_cents=10000).status_code == 201
    message = _messages(admin)["items"][0]
    path = f"/admin/connectors/{message['id']}/retry"
    assert agent.post(path, data={"reason": "retry"}).status_code == 403
    assert admin.post(path, data={"reason": " "}).status_code == 422
    fake.fail = False
    response = admin.post(path, data={"reason": "recovered"})
    assert response.status_code == 303 and response.headers["location"] == "/admin/connectors"
    assert _messages(admin)["items"][0]["status"] == "sent"
    assert admin.post(path, data={"reason": "again"}).status_code == 409
    assert admin.post("/api/connectors/messages/999999/retry", json={"reason": "missing"}).status_code == 404
