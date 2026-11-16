"""Product feedback 2, 3, 4, 6, 7 and 9: dollars on screens, reason dropdowns with Other, the (Max ...) label,
and quick approve / reject from the refund queue and the KYC list."""
import re

import pytest

from .conftest import BANK_1, BANK_2, SSN_1, SSN_2, audit_rows, request_refund


def visible(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", " ", html)))


def refund_row(sql, refund_id=1):
    return sql.execute("SELECT * FROM refund WHERE id = ?", (refund_id,)).fetchone()


def new_refund(client, **data):
    return client.post("/refunds/new", data={"charge_id": "1", **data})


def audit_dump(sql) -> str:
    return "\n".join("|".join(str(v) for v in row) for row in sql.execute("SELECT * FROM audit_event"))


# --- feedback 2: dollars on screens, cents in storage and the API ---------------------

@pytest.mark.parametrize("typed, cents", [("750", 75000), ("750.00", 75000), ("$1,250.50", 125050),
                                          ("0.01", 1), ("12.3", 1230), (" 20 ", 2000)])
def test_refund_form_takes_dollars_and_stores_cents(login, sql, typed, cents):
    agent = login("agent1")
    response = new_refund(agent, amount=typed, reason_choice="Duplicate charge")
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/refunds/1"
    assert refund_row(sql)["amount_cents"] == cents
    assert agent.get("/api/refunds/1").json()["amount_cents"] == cents


@pytest.mark.parametrize("typed", ["", "abc", "12.345", "-5", "0", "0.00", "1e3", "ten", "2000.01", "1.2.3", "."])
def test_refund_form_rejects_bad_amounts(login, sql, typed):
    agent = login("agent1")
    response = new_refund(agent, amount=typed, reason_choice="Duplicate charge")
    assert response.status_code == 422, response.text
    assert sql.execute("SELECT COUNT(*) FROM refund").fetchone()[0] == 0
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 0


def test_refund_form_error_keeps_what_was_typed(login):
    agent = login("agent1")
    response = new_refund(agent, amount="12.345", reason_choice="Other", reason_other="my special case")
    assert response.status_code == 422
    assert 'value="12.345"' in response.text and 'value="my special case"' in response.text
    assert "fractions of a cent" in response.text


def test_json_api_stays_in_integer_cents(login, sql):
    agent = login("agent1")
    for bad in ("750.00", 7.5, "750", True, None):
        response = agent.post("/api/refunds", json={"charge_id": 1, "amount_cents": bad, "reason": "x"})
        assert response.status_code == 422, bad
    created = request_refund(agent, amount_cents=75000)
    assert created.status_code == 201
    body = created.json()
    assert body["amount_cents"] == 75000 and isinstance(body["amount_cents"], int)
    assert isinstance(body["charge_amount_cents"], int)
    assert refund_row(sql)["amount_cents"] == 75000
    charge = agent.get("/api/charges?q=1&customer_id=1").json()["items"][0]
    assert (charge["amount_cents"], charge["committed_cents"], charge["remaining_cents"]) == (200000, 75000, 125000)


def test_screens_show_dollars_and_never_cents(login, sql):
    agent, approver, admin, kyc = login("agent1"), login("approver1"), login("admin1"), login("kyc1")
    request_refund(agent, amount_cents=75050)
    request_refund(agent, charge_id=2, amount_cents=1234)
    pages = {
        "/refunds": agent, "/refunds/1": agent, "/refunds/new": agent, "/refunds/new?charge_id=1": agent,
        "/charges": agent, "/customers/1": agent, "/refunds/queue": approver, "/admin/settings": admin,
        "/admin/audit": admin, "/kyc/queue": kyc,
    }
    for path, client in pages.items():
        response = client.get(path)
        assert response.status_code == 200, path
        text_ = visible(re.sub(r"(?s)<details.*?</details>", " ", response.text))
        assert not re.search(r"\bcents?\b", text_, re.I), (path, re.findall(r".{30}\bcents?\b.{30}", text_, re.I))
        assert "_cents" not in text_, path
        for raw in ("75050", "200000", "124950", "50000", "75000"):
            assert raw not in text_, (path, raw)
    assert "$750.50" in agent.get("/refunds").text and "$12.34" in agent.get("/refunds").text
    assert "$750.50" in agent.get("/refunds/1").text
    assert "$750.50" in approver.get("/refunds/queue").text and "$2,000.00" in approver.get("/refunds/queue").text
    assert "$1,249.50" in agent.get("/charges").text
    assert "$750.50" in visible(admin.get("/admin/audit").text)
    assert "$500.00" in agent.get("/refunds/new?charge_id=1").text  # the auto-approve limit, in dollars


def test_audit_page_describes_a_limit_change_in_dollars(login):
    admin = login("admin1")
    admin.post("/admin/settings", data={"amount": "250"})
    text_ = visible(re.sub(r"(?s)<details.*?</details>", " ", admin.get("/admin/audit").text))
    assert "$500.00" in text_ and "$250.00" in text_


# --- feedback 6: (Max XYZ) ------------------------------------------------------------

def test_refund_amount_label_shows_the_max_and_follows_refunds(login, sql):
    agent, approver = login("agent1"), login("approver1")
    assert "Refund amount requested (Max $2,000.00)" in agent.get("/refunds/new?charge_id=1").text
    request_refund(agent, amount_cents=75000)  # pending counts
    assert "Refund amount requested (Max $1,250.00)" in agent.get("/refunds/new?charge_id=1").text
    request_refund(agent, amount_cents=25050)
    html = agent.get("/refunds/new?charge_id=1").text
    assert "Refund amount requested (Max $999.50)" in html and 'data-max="99950"' in html
    approver.post("/api/refunds/1/reject", json={"reason": "Insufficient evidence"})  # rejected frees the amount
    assert "Refund amount requested (Max $1,749.50)" in agent.get("/refunds/new?charge_id=1").text
    sql.execute("UPDATE charge SET amount_cents = 123456789 WHERE id = 2")
    assert "(Max $1,234,567.89)" in agent.get("/refunds/new?charge_id=2").text


def test_max_is_enforced_on_the_server_and_shown_as_zero_when_used_up(login, sql):
    agent = login("agent1")
    over = new_refund(agent, amount="2000.01", reason_choice="Duplicate charge")
    assert over.status_code == 422 and "exceed the charge amount" in over.text
    assert "(Max $2,000.00)" in over.text
    assert new_refund(agent, amount="2,000.00", reason_choice="Duplicate charge").status_code == 303
    assert "(Max $0.00)" in agent.get("/refunds/new?charge_id=1").text
    assert new_refund(agent, amount="0.01", reason_choice="Duplicate charge").status_code == 422
    assert sql.execute("SELECT SUM(amount_cents) FROM refund WHERE charge_id = 1").fetchone()[0] == 200000


def test_refund_form_for_unknown_or_missing_charge(login):
    agent = login("agent1")
    assert agent.get("/refunds/new?charge_id=999").status_code == 422
    assert agent.post("/refunds/new", data={"amount": "5", "reason_choice": "Duplicate charge"}).status_code == 422
    assert agent.post("/refunds/new", data={"charge_id": "999", "amount": "5",
                                            "reason_choice": "Duplicate charge"}).status_code == 422


# --- feedback 3: agents pick a reason or type one under Other -------------------------

def test_refund_form_has_the_reason_dropdown_with_other(login, sql):
    html = login("agent1").get("/refunds/new?charge_id=1").text
    select = re.search(r'(?s)<select name="reason_choice".*?</select>', html).group(0)
    assert "required" in select.split(">")[0]
    options = re.findall(r"<option[^>]*>([^<]*)</option>", select)
    assert options[0] == "Choose a reason" and options[-1].startswith("Other")
    assert options[1:-1] == ["Duplicate charge", "Product not received", "Product defective or not as described",
                             "Cancelled order or subscription", "Billing error or wrong amount",
                             "Fraudulent or unauthorized charge", "Goodwill gesture"]
    assert 'name="reason_other"' in html


def test_agent_reason_from_the_list_is_stored_and_audited(login, sql):
    agent = login("agent1")
    assert new_refund(agent, amount="750", reason_choice="Product not received").status_code == 303
    assert refund_row(sql)["reason"] == "Product not received"
    event = audit_rows(sql, "refund", 1)[0]
    assert (event["action"], event["actor"], event["reason"]) == ("refund.request", "agent1", "Product not received")


def test_agent_other_requires_typed_text(login, sql):
    agent = login("agent1")
    for other in ("", "   ", None):
        data = {"amount": "10", "reason_choice": "Other"}
        if other is not None:
            data["reason_other"] = other
        response = new_refund(agent, **data)
        assert response.status_code == 422, repr(other)
        assert "type a reason when you choose Other" in response.text
    assert sql.execute("SELECT COUNT(*) FROM refund").fetchone()[0] == 0
    assert new_refund(agent, amount="10", reason_choice="Other", reason_other="  wrong size shipped ").status_code == 303
    assert refund_row(sql)["reason"] == "wrong size shipped"
    assert audit_rows(sql, "refund", 1)[0]["reason"] == "wrong size shipped"


def test_agent_must_give_a_reason(login, sql):
    agent = login("agent1")
    response = new_refund(agent, amount="10")
    assert response.status_code == 422 and "a reason is required" in response.text
    not_listed = new_refund(agent, amount="10", reason_choice="Because I said so")
    assert not_listed.status_code == 422 and "choose a reason from the list" in not_listed.text
    # An approver's reason is not an agent's reason.
    assert new_refund(agent, amount="10", reason_choice="Matches refund policy").status_code == 422
    for body in ({"charge_id": 1, "amount_cents": 1000}, {"charge_id": 1, "amount_cents": 1000, "reason": ""},
                 {"charge_id": 1, "amount_cents": 1000, "reason": "   "}):
        assert agent.post("/api/refunds", json=body).status_code == 422, body
    assert sql.execute("SELECT COUNT(*) FROM refund").fetchone()[0] == 0


def test_typed_reasons_are_redacted_before_they_are_stored_or_audited(login, sql):
    agent, approver, kyc = login("agent1"), login("approver1"), login("kyc1")
    new_refund(agent, amount="750", reason_choice="Other", reason_other=f"customer SSN {SSN_1} acct {BANK_1}")
    request_refund(agent, charge_id=2, amount_cents=75000, reason=f"ssn{SSN_2}x and {BANK_2}")
    approver.post("/refunds/1/decision", data={"decision": "approve", "reason_choice": "Other",
                                               "reason_other": f"verified {SSN_1} / {BANK_1}", "source": "queue"})
    approver.post("/api/refunds/2/reject", json={"reason": f"no: {SSN_2} {BANK_2}"})
    assert kyc.get("/kyc/2").status_code == 200  # an audited unmasked view
    assert kyc.get("/api/customers/1").json()["ssn"] == SSN_1
    kyc.post("/kyc/2/decision", data={"decision": "reject", "reason_choice": "Other",
                                      "reason_other": f"SSN {SSN_2} is on a watchlist, account {BANK_2}",
                                      "source": "queue"})
    assert sql.execute("SELECT status FROM refund WHERE id = 1").fetchone()[0] == "approved"
    assert sql.execute("SELECT kyc_status FROM customer WHERE id = 2").fetchone()[0] == "rejected"
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] >= 7
    dump = audit_dump(sql)
    stored = "\n".join(r["reason"] for r in sql.execute("SELECT reason FROM refund"))
    for secret in (SSN_1, SSN_2, BANK_1, BANK_2, SSN_1.replace("-", ""), SSN_2.replace("-", "")):
        assert secret not in dump, secret
        assert secret not in stored, secret
    assert "***-**-3456" in dump and "****3456" in dump
    admin = login("admin1")
    for path in ("/api/audit?limit=500", "/admin/audit", "/api/audit?q=900-12-3456", "/api/audit?q=4000123456"):
        text_ = admin.get(path).text
        assert SSN_1 not in text_.replace("q=900-12-3456", "") and BANK_2 not in text_, path
    assert admin.get("/api/audit?q=900-12-3456").json()["total"] == 0


# --- feedback 4 and 7: approver dropdown and quick decisions from the queue -----------

def test_queue_rows_carry_a_quick_decision_form(login):
    agent, approver = login("agent1"), login("approver1")
    request_refund(agent, amount_cents=75000)
    request_refund(agent, charge_id=2, amount_cents=90000)
    html = approver.get("/refunds/queue").text
    for refund_id in (1, 2):
        form = re.search(rf'(?s)<form method="post" action="/refunds/{refund_id}/decision".*?</form>', html).group(0)
        assert 'name="source" value="queue"' in form
        assert '<select name="reason_choice"' in form and 'name="reason_other"' in form
        assert 'name="decision" value="approve"' in form and 'name="decision" value="reject"' in form
        options = re.findall(r"<option[^>]*>([^<]*)</option>", form)
        for expected in ("Verified with customer", "Matches refund policy", "Confirmed duplicate or billing error",
                         "Confirmed fraud", "Goodwill approved by manager", "Outside refund window",
                         "Does not meet refund policy", "Insufficient evidence", "Already refunded",
                         "Suspected abuse"):
            assert expected in options, expected
        assert 'value="Other"' in form


def test_quick_approve_from_the_queue(login, sql):
    agent, approver = login("agent1"), login("approver1")
    request_refund(agent, amount_cents=75000)
    response = approver.post("/refunds/1/decision", data={
        "decision": "approve", "reason_choice": "Verified with customer", "source": "queue"})
    assert response.status_code == 303 and response.headers["location"] == "/refunds/queue?done=approve&id=1"
    row = refund_row(sql)
    assert (row["status"], row["decided_by"]) == ("approved", "approver1")
    event = audit_rows(sql, "refund", 1)[-1]
    assert (event["action"], event["actor"], event["reason"]) == ("refund.approve", "approver1", "Verified with customer")
    after = approver.get(response.headers["location"])
    assert after.status_code == 200 and "Refund #1 approved." in after.text
    assert 'action="/refunds/1/decision"' not in after.text


def test_quick_reject_from_the_queue_with_other(login, sql):
    agent, approver = login("agent1"), login("approver1")
    request_refund(agent, amount_cents=75000)
    response = approver.post("/refunds/1/decision", data={
        "decision": "reject", "reason_choice": "Other", "reason_other": "customer withdrew", "source": "queue"})
    assert response.status_code == 303 and response.headers["location"] == "/refunds/queue?done=reject&id=1"
    assert refund_row(sql)["status"] == "rejected"
    assert audit_rows(sql, "refund", 1)[-1]["reason"] == "customer withdrew"
    assert "Refund #1 rejected." in approver.get(response.headers["location"]).text


@pytest.mark.parametrize("data, message", [
    ({"decision": "approve"}, "a reason is required"),
    ({"decision": "approve", "reason_choice": ""}, "a reason is required"),
    ({"decision": "approve", "reason_choice": "Other"}, "type a reason when you choose Other"),
    ({"decision": "reject", "reason_choice": "Other", "reason_other": "  "}, "type a reason when you choose Other"),
    ({"decision": "approve", "reason_choice": "Insufficient evidence"}, "choose a reason from the list"),
    ({"decision": "reject", "reason_choice": "Verified with customer"}, "choose a reason from the list"),
    ({"decision": "approve", "reason_choice": "Duplicate charge"}, "choose a reason from the list"),
    ({"decision": "maybe", "reason_choice": "Verified with customer"}, "decision must be approve or reject"),
    ({"reason_choice": "Verified with customer"}, "decision must be approve or reject"),
])
def test_quick_decision_needs_a_matching_reason(login, sql, data, message):
    agent, approver = login("agent1"), login("approver1")
    request_refund(agent, amount_cents=75000)
    response = approver.post("/refunds/1/decision", data={**data, "source": "queue"})
    assert response.status_code == 422, response.text
    assert f"Refund #1: {message}" in response.text
    assert 'action="/refunds/1/decision"' in response.text  # back on the queue, row still there
    assert refund_row(sql)["status"] == "pending_approval"
    assert len(audit_rows(sql, "refund", 1)) == 1
    detail = approver.post("/refunds/1/decision", data=data)
    assert detail.status_code == 422 and message in detail.text
    assert refund_row(sql)["status"] == "pending_approval"


def test_detail_page_decision_uses_the_dropdown_too(login, sql):
    agent, approver = login("agent1"), login("approver1")
    request_refund(agent, amount_cents=75000)
    html = approver.get("/refunds/1").text
    assert 'action="/refunds/1/decision"' in html and '<select name="reason_choice"' in html
    assert "Matches refund policy" in html and "Outside refund window" in html
    response = approver.post("/refunds/1/decision", data={"decision": "reject",
                                                          "reason_choice": "Outside refund window"})
    assert response.status_code == 303 and response.headers["location"] == "/refunds/1"
    assert refund_row(sql)["status"] == "rejected"
    assert audit_rows(sql, "refund", 1)[-1]["reason"] == "Outside refund window"
    assert 'action="/refunds/1/decision"' not in approver.get("/refunds/1").text


def test_deciding_twice_from_the_queue_is_a_conflict(login, sql):
    agent, approver = login("agent1"), login("approver1")
    request_refund(agent, amount_cents=75000)
    data = {"decision": "approve", "reason_choice": "Verified with customer", "source": "queue"}
    assert approver.post("/refunds/1/decision", data=data).status_code == 303
    again = approver.post("/refunds/1/decision", data={**data, "decision": "reject",
                                                       "reason_choice": "Suspected abuse"})
    assert again.status_code == 409
    assert refund_row(sql)["status"] == "approved"
    assert approver.post("/refunds/999/decision", data=data).status_code == 404


def test_api_decisions_still_need_a_reason(login, sql):
    agent, approver = login("agent1"), login("approver1")
    request_refund(agent, amount_cents=75000)
    for body in ({}, {"reason": ""}, {"reason": "  "}):
        assert approver.post("/api/refunds/1/approve", json=body).status_code == 422, body
        assert approver.post("/api/refunds/1/reject", json=body).status_code == 422, body
    assert refund_row(sql)["status"] == "pending_approval"


@pytest.mark.parametrize("username", ["agent1", "agent2", "kyc1", "admin1"])
def test_only_approvers_can_use_the_quick_decision(login, sql, username):
    request_refund(login("agent1"), amount_cents=75000)
    client = login(username)
    data = {"decision": "approve", "reason_choice": "Verified with customer", "source": "queue"}
    assert client.post("/refunds/1/decision", data=data).status_code == 403
    assert client.get("/refunds/queue").status_code == 403
    assert client.post("/api/refunds/1/approve", json={"reason": "Verified with customer"}).status_code == 403
    assert refund_row(sql)["status"] == "pending_approval"


def test_quick_decisions_without_a_session(anon, login, sql):
    request_refund(login("agent1"), amount_cents=75000)
    data = {"decision": "approve", "reason_choice": "Verified with customer", "source": "queue"}
    for path in ("/refunds/1/decision", "/kyc/2/decision", "/refunds/new"):
        response = anon.post(path, data=data)
        assert response.status_code == 303 and response.headers["location"].startswith("/login"), path
    assert anon.post("/api/refunds/1/approve", json={"reason": "x"}).status_code == 401
    assert anon.post("/api/kyc/2/decision", json={"decision": "approve", "reason": "x"}).status_code == 401
    assert refund_row(sql)["status"] == "pending_approval"
    assert sql.execute("SELECT kyc_status FROM customer WHERE id = 2").fetchone()[0] == "pending"


# --- feedback 9: KYC list quick decisions ---------------------------------------------

def test_kyc_list_rows_carry_a_quick_decision_form(login):
    html = login("kyc1").get("/kyc/queue").text
    form = re.search(r'(?s)<form method="post" action="/kyc/2/decision".*?</form>', html).group(0)
    assert 'name="source" value="queue"' in form and '<select name="reason_choice"' in form
    assert 'name="decision" value="approve"' in form and 'name="decision" value="reject"' in form
    options = re.findall(r"<option[^>]*>([^<]*)</option>", form)
    for expected in ("Identity documents verified", "Details match records", "Verified by phone",
                     "Documents missing or unreadable", "Details do not match", "Suspected fraud",
                     "Sanctions or watchlist match"):
        assert expected in options, expected
    assert 'value="Other"' in form
    assert "Matches refund policy" not in html
    assert SSN_2 not in html and BANK_2 not in html  # the list stays masked


def test_kyc_quick_approve_and_reject(login, sql):
    kyc = login("kyc1")
    sql.execute("INSERT INTO customer (id, name, email, ssn, bank_account) VALUES "
                "(4, 'Dee Hill', 'dee@example.test', '900-11-2222', '4000111122')")
    response = kyc.post("/kyc/2/decision", data={"decision": "approve", "reason_choice": "Verified by phone",
                                                 "source": "queue"})
    assert response.status_code == 303 and response.headers["location"] == "/kyc/queue?done=approve&id=2"
    assert "Customer #2 approved." in kyc.get(response.headers["location"]).text
    response = kyc.post("/kyc/4/decision", data={"decision": "reject", "reason_choice": "Other",
                                                 "reason_other": "selfie does not match", "source": "queue"})
    assert response.status_code == 303 and response.headers["location"] == "/kyc/queue?done=reject&id=4"
    statuses = dict(sql.execute("SELECT id, kyc_status FROM customer").fetchall())
    assert statuses == {1: "approved", 2: "approved", 3: "rejected", 4: "rejected"}
    approved, rejected = audit_rows(sql, "customer", 2)[-1], audit_rows(sql, "customer", 4)[-1]
    assert (approved["action"], approved["actor"], approved["reason"]) == \
        ("customer.kyc_approve", "kyc1", "Verified by phone")
    assert (rejected["action"], rejected["actor"], rejected["reason"]) == \
        ("customer.kyc_reject", "kyc1", "selfie does not match")
    # Quick decisions from the masked list reveal nothing, so they write no PII-view event.
    assert sql.execute("SELECT COUNT(*) FROM audit_event WHERE action = 'customer.pii_view'").fetchone()[0] == 0
    assert "Nobody is waiting." in kyc.get("/kyc/queue").text
    # The newly approved customer can now get refunds.
    assert request_refund(login("agent1"), charge_id=7, amount_cents=1000).status_code == 201


@pytest.mark.parametrize("data, message", [
    ({"decision": "approve"}, "a reason is required"),
    ({"decision": "reject", "reason_choice": "Other"}, "type a reason when you choose Other"),
    ({"decision": "approve", "reason_choice": "Suspected fraud"}, "choose a reason from the list"),
    ({"decision": "reject", "reason_choice": "Verified by phone"}, "choose a reason from the list"),
    ({"decision": "approve", "reason_choice": "Matches refund policy"}, "choose a reason from the list"),
    ({"decision": "escalate", "reason_choice": "Verified by phone"}, "decision must be approve or reject"),
])
def test_kyc_quick_decision_needs_a_matching_reason(login, sql, data, message):
    kyc = login("kyc1")
    response = kyc.post("/kyc/2/decision", data={**data, "source": "queue"})
    assert response.status_code == 422, response.text
    assert f"Customer #2: {message}" in response.text
    assert 'action="/kyc/2/decision"' in response.text
    assert sql.execute("SELECT kyc_status FROM customer WHERE id = 2").fetchone()[0] == "pending"
    assert audit_rows(sql, "customer", 2) == []


def test_kyc_decided_customers_cannot_be_decided_again(login, sql):
    kyc = login("kyc1")
    data = {"decision": "reject", "reason_choice": "Suspected fraud", "source": "queue"}
    assert kyc.post("/kyc/1/decision", data=data).status_code == 409  # already approved
    assert kyc.post("/kyc/999/decision", data=data).status_code == 404
    assert sql.execute("SELECT kyc_status FROM customer WHERE id = 1").fetchone()[0] == "approved"
    html = kyc.get("/kyc/queue?status=all").text
    assert 'action="/kyc/1/decision"' not in html and 'action="/kyc/3/decision"' not in html


@pytest.mark.parametrize("username", ["agent1", "approver1", "admin1"])
def test_only_kyc_reviewers_can_use_the_kyc_quick_decision(login, sql, username):
    client = login(username)
    data = {"decision": "approve", "reason_choice": "Verified by phone", "source": "queue"}
    assert client.post("/kyc/2/decision", data=data).status_code == 403
    assert client.get("/kyc/queue").status_code == 403
    assert client.post("/api/kyc/2/decision", json={"decision": "approve", "reason": "x"}).status_code == 403
    assert sql.execute("SELECT kyc_status FROM customer WHERE id = 2").fetchone()[0] == "pending"
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 0
