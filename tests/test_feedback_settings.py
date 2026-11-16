"""Product feedback 1 and 12: settings (no typed reason, session timeout, logout, reason lists, KYC switch,
maximum refund age), their audit trail and permissions, and the in-place upgrade across the admin-settings
migration."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.foundation.db import applied_versions, available_migrations, migrate
from app.main import create_app

from .conftest import BANK_1, SSN_1, audit_rows, request_refund, seed_basics

LIST_KEYS = ["reasons_refund_request", "reasons_refund_approve", "reasons_refund_reject",
             "reasons_kyc_approve", "reasons_kyc_reject"]
ALL_KEYS = ["auto_approve_limit_cents", "max_refund_age_days", "refund_requires_kyc",
            "session_timeout_minutes"] + LIST_KEYS


def stored(sql, key):
    return json.loads(sql.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()["value"])


def put(client, key, value):
    return client.put(f"/api/settings/{key}", json={"value": value})


def ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# --- defaults and reading -------------------------------------------------------------

def test_defaults(login, sql):
    items = {i["key"]: i["value"] for i in login("admin1").get("/api/settings").json()["items"]}
    assert set(ALL_KEYS) <= set(items)
    assert items["session_timeout_minutes"] == 60
    assert items["refund_requires_kyc"] is True
    assert items["max_refund_age_days"] == 90
    assert items["auto_approve_limit_cents"] == 50000
    for key in LIST_KEYS:
        assert isinstance(items[key], list) and items[key] and "Other" not in items[key], key
        assert stored(sql, key) == items[key]


# --- feedback 1: no reason needed -----------------------------------------------------

def test_auto_approve_limit_changes_without_a_reason_api(login, sql):
    admin = login("admin1")
    response = admin.put("/api/settings/auto-approve-limit", json={"value_cents": 12345})
    assert response.status_code == 200, response.text
    assert response.json()["value_cents"] == 12345
    assert stored(sql, "auto_approve_limit_cents") == 12345
    event = audit_rows(sql, "setting", "auto_approve_limit_cents")[-1]
    assert (event["actor"], event["action"], event["reason"]) == ("admin1", "setting.change", None)
    assert json.loads(event["before"]) == {"value": 50000} and json.loads(event["after"]) == {"value": 12345}
    assert event["created_at"].startswith(datetime.now(timezone.utc).strftime("%Y-"))


def test_auto_approve_limit_changes_without_a_reason_form_in_dollars(login, sql):
    admin = login("admin1")
    response = admin.post("/admin/settings", data={"amount": "125.50"})
    assert response.status_code == 200, response.text
    assert stored(sql, "auto_approve_limit_cents") == 12550
    assert 'value="125.50"' in response.text
    events = audit_rows(sql, "setting", "auto_approve_limit_cents")
    assert len(events) == 1 and events[0]["reason"] is None
    assert json.loads(events[0]["after"]) == {"value": 12550}


def test_settings_page_asks_for_no_reason(login):
    html = login("admin1").get("/admin/settings").text
    assert 'name="reason"' not in html
    assert "Log out" in html and 'action="/logout"' in html


@pytest.mark.parametrize("amount, cents", [("750", 75000), ("$750.00", 75000), ("0", 0), ("1.5", 150),
                                           (" 12.34 ", 1234), ("0.01", 1)])
def test_limit_form_accepts_dollar_formats(login, sql, amount, cents):
    assert login("admin1").post("/admin/settings", data={"amount": amount}).status_code == 200
    assert stored(sql, "auto_approve_limit_cents") == cents


@pytest.mark.parametrize("amount", ["", "abc", "12.345", "-5", "750.01", "$1,000", "1e2", "1.2.3", ".",
                                    "99999999999999999999999999"])
def test_limit_form_rejects_bad_dollar_amounts(login, sql, amount):
    response = login("admin1").post("/admin/settings", data={"amount": amount})
    assert response.status_code == 422, response.text
    assert stored(sql, "auto_approve_limit_cents") == 50000
    assert audit_rows(sql, "setting", "auto_approve_limit_cents") == []


@pytest.mark.parametrize("value", [-1, 75001, 10**30])
def test_limit_api_stays_in_cents_and_is_capped(login, sql, value):
    assert login("admin1").put("/api/settings/auto-approve-limit", json={"value_cents": value}).status_code == 422
    assert stored(sql, "auto_approve_limit_cents") == 50000


def test_limit_api_rejects_non_integers(login, sql):
    admin = login("admin1")
    for bad in (12.5, "500", True, None):
        assert admin.put("/api/settings/auto-approve-limit", json={"value_cents": bad}).status_code == 422, bad
    assert stored(sql, "auto_approve_limit_cents") == 50000


# --- generic settings: validation and audit -------------------------------------------

@pytest.mark.parametrize("key, new", [
    ("session_timeout_minutes", 5), ("refund_requires_kyc", False), ("max_refund_age_days", 30),
    ("max_refund_age_days", None), ("auto_approve_limit_cents", 100),
    ("reasons_kyc_reject", ["Expired document", "Name mismatch"]),
])
def test_every_setting_change_is_audited_with_who_when_old_new_and_no_reason(login, sql, key, new):
    admin = login("admin1")
    old = stored(sql, key)
    response = put(admin, key, new)
    assert response.status_code == 200, response.text
    assert response.json() == {"key": key, "value": new}
    assert stored(sql, key) == new
    events = audit_rows(sql, "setting", key)
    assert len(events) == 1
    event = events[0]
    assert event["actor"] == "admin1" and event["action"] == "setting.change" and event["reason"] is None
    assert json.loads(event["before"]) == {"value": old} and json.loads(event["after"]) == {"value": new}
    datetime.strptime(event["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 1
    shown = admin.get("/api/audit?entity=setting&entity_id=" + key).json()["items"]
    assert len(shown) == 1 and shown[0]["before"] == {"value": old} and shown[0]["after"] == {"value": new}


@pytest.mark.parametrize("key, bad", [
    ("session_timeout_minutes", 0), ("session_timeout_minutes", 1441), ("session_timeout_minutes", -5),
    ("session_timeout_minutes", None), ("session_timeout_minutes", True), ("session_timeout_minutes", ["5"]),
    ("max_refund_age_days", 0), ("max_refund_age_days", 3651), ("max_refund_age_days", False),
    ("refund_requires_kyc", 1), ("refund_requires_kyc", None), ("refund_requires_kyc", ["true"]),
    ("auto_approve_limit_cents", 75001), ("auto_approve_limit_cents", None),
    ("reasons_refund_request", []), ("reasons_refund_request", 5), ("reasons_refund_request", None),
    ("reasons_refund_request", ["Other"]), ("reasons_refund_request", ["  "]),
    ("reasons_refund_request", ["x" * 81]), ("reasons_refund_request", [f"reason {i}" for i in range(21)]),
])
def test_setting_validation(login, sql, key, bad):
    before = stored(sql, key)
    response = put(login("admin1"), key, bad)
    assert response.status_code == 422, response.text
    assert stored(sql, key) == before
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 0


def test_setting_values_of_the_wrong_json_type_are_rejected(login, sql):
    admin = login("admin1")
    for key, bad in (("session_timeout_minutes", "5"), ("session_timeout_minutes", 5.5),
                     ("reasons_kyc_approve", [1, 2])):
        assert admin.put(f"/api/settings/{key}", json={"value": bad}).status_code == 422, (key, bad)
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 0


@pytest.mark.xfail(strict=True, reason=(
    "app bug: PUT /api/settings/refund_requires_kyc accepts strings; SettingBody.value is a lax pydantic bool, "
    "so 'off' / 'no' / '0' are silently coerced to false and switch the KYC rule off (expected 422)"))
@pytest.mark.parametrize("bad", ["off", "no", "0", "on", "true"])
def test_kyc_switch_api_rejects_strings(login, sql, bad):
    response = put(login("admin1"), "refund_requires_kyc", bad)
    assert response.status_code == 422, response.text
    assert stored(sql, "refund_requires_kyc") is True
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 0


def test_unknown_setting_is_404(login, sql):
    admin = login("admin1")
    assert put(admin, "no_such_setting", 1).status_code == 404
    assert admin.post("/admin/settings/no_such_setting", data={"value": "1"}).status_code == 404
    assert sql.execute("SELECT COUNT(*) FROM setting WHERE key = 'no_such_setting'").fetchone()[0] == 0


def test_settings_forms(login, sql):
    admin = login("admin1")
    assert admin.post("/admin/settings/session_timeout_minutes", data={"value": "15"}).status_code == 200
    assert stored(sql, "session_timeout_minutes") == 15
    assert admin.post("/admin/settings/refund_requires_kyc", data={}).status_code == 200  # unchecked box
    assert stored(sql, "refund_requires_kyc") is False
    assert admin.post("/admin/settings/refund_requires_kyc", data={"value": "on"}).status_code == 200
    assert stored(sql, "refund_requires_kyc") is True
    assert admin.post("/admin/settings/max_refund_age_days", data={"value": ""}).status_code == 200
    assert stored(sql, "max_refund_age_days") is None
    assert admin.post("/admin/settings/max_refund_age_days", data={"value": "45"}).status_code == 200
    assert stored(sql, "max_refund_age_days") == 45
    response = admin.post("/admin/settings/reasons_kyc_approve",
                          data={"value": "Passport checked\r\n\r\n  Utility bill checked  \nOther\nPassport checked"})
    assert response.status_code == 200
    assert stored(sql, "reasons_kyc_approve") == ["Passport checked", "Utility bill checked"]
    for key, bad in (("session_timeout_minutes", "soon"), ("session_timeout_minutes", ""),
                     ("session_timeout_minutes", "0"), ("max_refund_age_days", "ninety"),
                     ("max_refund_age_days", "1.5"), ("reasons_kyc_approve", "  \n ")):
        before = stored(sql, key)
        assert admin.post(f"/admin/settings/{key}", data={"value": bad}).status_code == 422, (key, bad)
        assert stored(sql, key) == before
    actions = sql.execute("SELECT actor, action, reason FROM audit_event").fetchall()
    assert len(actions) == 6 and all(tuple(a) == ("admin1", "setting.change", None) for a in actions)


def test_settings_page_shows_dollars_and_every_setting(login):
    html = login("admin1").get("/admin/settings").text
    assert 'name="amount"' in html and 'value="500.00"' in html and "$750.00" in html
    assert 'name="value_cents"' not in html and "50000" not in html and "75000" not in html
    for key in ALL_KEYS[1:]:
        assert f'action="/admin/settings/{key}"' in html, key
    assert "Duplicate charge" in html


def test_reason_list_entries_are_redacted_before_storage_and_audit(login, sql):
    admin = login("admin1")
    response = put(admin, "reasons_kyc_reject", [f"SSN {SSN_1} mismatch", f"acct {BANK_1}"])
    assert response.status_code == 200
    dump = "\n".join("|".join(str(v) for v in r) for r in sql.execute("SELECT * FROM audit_event"))
    assert SSN_1 not in dump and BANK_1 not in dump
    assert SSN_1 not in json.dumps(stored(sql, "reasons_kyc_reject"))


# --- permissions ----------------------------------------------------------------------

SETTING_CALLS = [
    ("get", "/api/settings", {}),
    ("get", "/api/settings/auto-approve-limit", {}),
    ("put", "/api/settings/auto-approve-limit", {"json": {"value_cents": 1}}),
    ("put", "/api/settings/session_timeout_minutes", {"json": {"value": 1440}}),
    ("put", "/api/settings/refund_requires_kyc", {"json": {"value": False}}),
    ("put", "/api/settings/max_refund_age_days", {"json": {"value": None}}),
    ("put", "/api/settings/reasons_refund_approve", {"json": {"value": ["anything"]}}),
    ("get", "/admin/settings", {}),
    ("post", "/admin/settings", {"data": {"amount": "1"}}),
    ("post", "/admin/settings/refund_requires_kyc", {"data": {}}),
    ("post", "/admin/settings/max_refund_age_days", {"data": {"value": ""}}),
]


@pytest.mark.parametrize("username", ["agent1", "approver1", "kyc1"])
def test_non_admins_get_403_on_settings(login, sql, username):
    client = login(username)
    before = sql.execute("SELECT key, value FROM setting ORDER BY key").fetchall()
    for method, path, kwargs in SETTING_CALLS:
        assert getattr(client, method)(path, **kwargs).status_code == 403, (method, path)
    assert sql.execute("SELECT key, value FROM setting ORDER BY key").fetchall() == before
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 0


def test_no_session_gets_401_or_login_redirect_on_settings(anon, sql):
    before = sql.execute("SELECT key, value FROM setting ORDER BY key").fetchall()
    for method, path, kwargs in SETTING_CALLS:
        response = getattr(anon, method)(path, **kwargs)
        if path.startswith("/api/"):
            assert response.status_code == 401, (method, path)
        else:
            assert response.status_code == 303, (method, path)
            assert response.headers["location"].startswith("/login"), (method, path)
    assert sql.execute("SELECT key, value FROM setting ORDER BY key").fetchall() == before


# --- session timeout and logout -------------------------------------------------------

def test_idle_session_expires_after_the_configured_timeout(login, sql):
    admin, agent = login("admin1"), login("agent1")
    assert put(admin, "session_timeout_minutes", 5).status_code == 200
    agent_id = sql.execute("SELECT id FROM app_user WHERE username = 'agent1'").fetchone()[0]
    sql.execute("UPDATE user_session SET last_seen_at = ? WHERE user_id = ?", (ago(minutes=4), agent_id))
    assert agent.get("/api/refunds").status_code == 200  # inside the window
    seen = sql.execute("SELECT last_seen_at FROM user_session WHERE user_id = ?", (agent_id,)).fetchone()[0]
    assert seen > ago(minutes=1)  # activity moves the window
    sql.execute("UPDATE user_session SET last_seen_at = ? WHERE user_id = ?", (ago(minutes=6), agent_id))
    assert agent.get("/api/refunds").status_code == 401
    assert sql.execute("SELECT COUNT(*) FROM user_session WHERE user_id = ?", (agent_id,)).fetchone()[0] == 0
    page = agent.get("/refunds")
    assert page.status_code == 303 and page.headers["location"] == "/login?next=/refunds"
    assert admin.get("/api/settings").status_code == 200  # other sessions are untouched


def test_timeout_setting_applies_to_existing_sessions_both_ways(login, sql):
    admin, agent = login("admin1"), login("agent1")
    agent_id = sql.execute("SELECT id FROM app_user WHERE username = 'agent1'").fetchone()[0]
    sql.execute("UPDATE user_session SET last_seen_at = ? WHERE user_id = ?", (ago(minutes=90), agent_id))
    put(admin, "session_timeout_minutes", 120)
    assert agent.get("/api/refunds").status_code == 200  # 90 idle minutes is inside 120
    sql.execute("UPDATE user_session SET last_seen_at = ? WHERE user_id = ?", (ago(minutes=61), agent_id))
    put(admin, "session_timeout_minutes", 60)
    assert agent.get("/api/refunds").status_code == 401  # default 60 again: 61 idle minutes is out


def test_default_timeout_is_sixty_minutes(login, sql):
    agent, approver = login("agent1"), login("approver1")
    ids = {r["username"]: r["id"] for r in sql.execute("SELECT id, username FROM app_user")}
    sql.execute("UPDATE user_session SET last_seen_at = ? WHERE user_id = ?", (ago(minutes=59), ids["agent1"]))
    sql.execute("UPDATE user_session SET last_seen_at = ? WHERE user_id = ?", (ago(minutes=61), ids["approver1"]))
    assert agent.get("/api/refunds").status_code == 200
    assert approver.get("/api/refunds").status_code == 401


def test_logout_button_and_api(login, anon, sql):
    agent = login("agent1")
    html = agent.get("/refunds").text
    assert '<form method="post" action="/logout">' in html and "Log out" in html
    response = agent.post("/logout")
    assert response.status_code == 303 and response.headers["location"] == "/login"
    assert sql.execute("SELECT COUNT(*) FROM user_session").fetchone()[0] == 0
    assert agent.get("/api/refunds").status_code == 401
    assert agent.get("/refunds").status_code == 303

    approver = login("approver1")
    token = approver.cookies.get("session")
    assert approver.post("/api/logout").json() == {"logged_out": True}
    assert approver.get("/api/refunds").status_code == 401
    # The token is dead on the server, not just cleared in the browser.
    replay = TestClient(approver.app, follow_redirects=False, cookies={"session": token})
    assert replay.get("/api/refunds").status_code == 401
    replay.close()

    assert anon.post("/api/logout").status_code == 401
    response = anon.post("/logout")
    assert response.status_code == 303 and response.headers["location"].startswith("/login")


def test_logout_only_ends_the_callers_session(login, sql):
    first, second = login("agent1"), login("agent1")
    assert first.post("/api/logout").status_code == 200
    assert second.get("/api/refunds").status_code == 200
    assert sql.execute("SELECT COUNT(*) FROM user_session").fetchone()[0] == 1


# --- refunds require approved KYC (default on) ----------------------------------------

def test_kyc_switch_default_on_blocks_and_off_allows(login, sql):
    admin, agent = login("admin1"), login("agent1")
    for charge in (7, 8):  # customer 2 is pending, customer 3 rejected
        response = request_refund(agent, charge_id=charge, amount_cents=1000)
        assert response.status_code == 422 and "KYC" in response.json()["detail"]
    assert put(admin, "refund_requires_kyc", False).status_code == 200
    for charge in (7, 8):
        assert request_refund(agent, charge_id=charge, amount_cents=1000).status_code == 201
    assert put(admin, "refund_requires_kyc", True).status_code == 200
    assert request_refund(agent, charge_id=7, amount_cents=1000).status_code == 422
    assert sql.execute("SELECT COUNT(*) FROM refund").fetchone()[0] == 2


def test_kyc_switch_also_guards_approval(login, sql):
    admin, agent, approver = login("admin1"), login("agent1"), login("approver1")
    put(admin, "refund_requires_kyc", False)
    refund_id = request_refund(agent, charge_id=7, amount_cents=75000).json()["id"]
    put(admin, "refund_requires_kyc", True)
    response = approver.post(f"/api/refunds/{refund_id}/approve", json={"reason": "Matches refund policy"})
    assert response.status_code == 422 and "KYC" in response.json()["detail"]
    assert sql.execute("SELECT status FROM refund WHERE id = ?", (refund_id,)).fetchone()[0] == "pending_approval"
    put(admin, "refund_requires_kyc", False)
    assert approver.post(f"/api/refunds/{refund_id}/approve",
                         json={"reason": "Matches refund policy"}).status_code == 200


# --- maximum refund age ---------------------------------------------------------------

def set_charge_age(sql, charge_id, days, extra_seconds=0):
    when = datetime.now(timezone.utc) - timedelta(days=days, seconds=extra_seconds)
    sql.execute("UPDATE charge SET created_at = ? WHERE id = ?", (when.strftime("%Y-%m-%dT%H:%M:%SZ"), charge_id))


def test_default_max_refund_age_is_ninety_days(login, sql):
    agent = login("agent1")
    set_charge_age(sql, 1, 90, extra_seconds=3600)
    set_charge_age(sql, 2, 90, extra_seconds=-3600)
    old = request_refund(agent, charge_id=1, amount_cents=1000)
    assert old.status_code == 422 and "90 days" in old.json()["detail"]
    assert request_refund(agent, charge_id=2, amount_cents=1000).status_code == 201
    form = agent.post("/refunds/new", data={"charge_id": "1", "amount": "10.00",
                                            "reason_choice": "Duplicate charge"})
    assert form.status_code == 422 and "older than 90 days" in form.text
    assert sql.execute("SELECT COUNT(*) FROM refund WHERE charge_id = 1").fetchone()[0] == 0


def test_max_refund_age_can_be_changed_and_blank_means_no_limit(login, sql):
    admin, agent = login("admin1"), login("agent1")
    set_charge_age(sql, 1, 40)
    set_charge_age(sql, 2, 4000)
    assert request_refund(agent, charge_id=1, amount_cents=1000).status_code == 201
    put(admin, "max_refund_age_days", 30)
    response = request_refund(agent, charge_id=1, amount_cents=1000)
    assert response.status_code == 422 and "30 days" in response.json()["detail"]
    assert request_refund(agent, charge_id=2, amount_cents=1000).status_code == 422
    assert admin.post("/admin/settings/max_refund_age_days", data={"value": ""}).status_code == 200
    assert request_refund(agent, charge_id=1, amount_cents=1000).status_code == 201
    assert request_refund(agent, charge_id=2, amount_cents=1000).status_code == 201
    html = admin.get("/admin/settings").text
    assert "No limit" in html


def test_pending_refund_on_a_charge_that_aged_out_can_still_be_decided(login, sql):
    agent, approver = login("agent1"), login("approver1")
    refund_id = request_refund(agent, charge_id=1, amount_cents=75000).json()["id"]
    set_charge_age(sql, 1, 200)
    assert approver.post(f"/api/refunds/{refund_id}/approve",
                         json={"reason": "Matches refund policy"}).status_code == 200


# --- admin-editable reason lists ------------------------------------------------------

def test_edited_refund_request_list_drives_the_form(login, sql):
    admin, agent = login("admin1"), login("agent1")
    assert put(admin, "reasons_refund_request", ["Late delivery", "Wrong item", "other"]).status_code == 200
    assert stored(sql, "reasons_refund_request") == ["Late delivery", "Wrong item"]
    html = agent.get("/refunds/new?charge_id=1").text
    assert "<option >Late delivery</option>" in html or ">Late delivery</option>" in html
    assert ">Wrong item</option>" in html and 'value="Other"' in html
    assert "Duplicate charge" not in html
    gone = agent.post("/refunds/new", data={"charge_id": "1", "amount": "10", "reason_choice": "Duplicate charge"})
    assert gone.status_code == 422 and "choose a reason from the list" in gone.text
    ok = agent.post("/refunds/new", data={"charge_id": "1", "amount": "10", "reason_choice": "Late delivery"})
    assert ok.status_code == 303
    assert sql.execute("SELECT reason FROM refund").fetchone()[0] == "Late delivery"


def test_edited_decision_lists_drive_refund_and_kyc_quick_forms(login, sql):
    admin, agent, approver, kyc = login("admin1"), login("agent1"), login("approver1"), login("kyc1")
    put(admin, "reasons_refund_approve", ["Manager signed off"])
    put(admin, "reasons_refund_reject", ["Chargeback already filed"])
    put(admin, "reasons_kyc_approve", ["Video call done"])
    put(admin, "reasons_kyc_reject", ["Fake passport"])
    refund_id = request_refund(agent, amount_cents=75000).json()["id"]
    queue = approver.get("/refunds/queue").text
    assert "Manager signed off" in queue and "Chargeback already filed" in queue
    assert "Matches refund policy" not in queue and "Outside refund window" not in queue
    stale = approver.post(f"/refunds/{refund_id}/decision", data={
        "decision": "approve", "reason_choice": "Matches refund policy", "source": "queue"})
    assert stale.status_code == 422
    fresh = approver.post(f"/refunds/{refund_id}/decision", data={
        "decision": "reject", "reason_choice": "Chargeback already filed", "source": "queue"})
    assert fresh.status_code == 303
    assert audit_rows(sql, "refund", refund_id)[-1]["reason"] == "Chargeback already filed"

    kyc_queue = kyc.get("/kyc/queue").text
    assert "Video call done" in kyc_queue and "Fake passport" in kyc_queue
    assert "Identity documents verified" not in kyc_queue
    assert kyc.post("/kyc/2/decision", data={"decision": "approve", "reason_choice": "Identity documents verified",
                                             "source": "queue"}).status_code == 422
    assert kyc.post("/kyc/2/decision", data={"decision": "approve", "reason_choice": "Video call done",
                                             "source": "queue"}).status_code == 303
    assert audit_rows(sql, "customer", 2)[-1]["reason"] == "Video call done"


def test_other_is_always_offered_even_when_an_admin_tries_to_remove_or_duplicate_it(login, sql):
    admin, agent = login("admin1"), login("agent1")
    put(admin, "reasons_refund_request", ["Only reason", "Other", "OTHER"])
    assert stored(sql, "reasons_refund_request") == ["Only reason"]
    html = agent.get("/refunds/new?charge_id=1").text
    assert html.count('value="Other"') == 1
    ok = agent.post("/refunds/new", data={"charge_id": "1", "amount": "10", "reason_choice": "Other",
                                          "reason_other": "Customer moved abroad"})
    assert ok.status_code == 303
    assert sql.execute("SELECT reason FROM refund").fetchone()[0] == "Customer moved abroad"


# --- upgrade in place across the admin-settings migration ------------------------------

def admin_settings_version() -> int:
    """The admin-settings migration is found by name, so renumbering it does not break this test."""
    found = [version for version, name, _ in available_migrations() if name.endswith("_admin_settings.sql")]
    assert len(found) == 1, found
    return found[0]


def test_existing_database_upgrades_across_admin_settings_in_place_with_data_intact(tmp_path):
    path = str(tmp_path / "old.db")
    every = [version for version, _, _ in available_migrations()]
    target = admin_settings_version()
    earlier = [v for v in every if v < target]
    assert earlier, "there must be migrations before admin settings"
    assert migrate(path, target=earlier[-1]) == earlier
    assert applied_versions(path) == earlier
    seed_basics(path)
    con = sqlite3.connect(path, isolation_level=None)
    con.row_factory = sqlite3.Row
    assert "active" not in [r["name"] for r in con.execute("PRAGMA table_info(app_user)")]
    assert "last_seen_at" not in [r["name"] for r in con.execute("PRAGMA table_info(user_session)")]
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale = (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    con.execute("UPDATE setting SET value = '31000' WHERE key = 'auto_approve_limit_cents'")
    con.execute("INSERT INTO refund (charge_id, amount_cents, reason, status, requested_by, created_at, updated_at) "
                "VALUES (1, 75000, 'legacy free text reason', 'pending_approval', 'agent1', ?, ?)", (stamp, stamp))
    con.execute("INSERT INTO refund (charge_id, amount_cents, reason, status, requested_by, decided_by, created_at, "
                "updated_at) VALUES (2, 1000, 'small one', 'approved', 'agent2', 'system', ?, ?)", (stamp, stamp))
    con.execute("INSERT INTO audit_event (actor, action, entity, entity_id, before, after, reason, created_at) "
                "VALUES ('admin1', 'setting.change', 'setting', 'auto_approve_limit_cents', '{\"value\": 50000}', "
                "'{\"value\": 31000}', 'old style typed reason', ?)", (stamp,))
    con.execute("INSERT INTO user_session (token, user_id, created_at) VALUES ('live-token', 3, ?)", (stamp,))
    con.execute("INSERT INTO user_session (token, user_id, created_at) VALUES ('stale-token', 1, ?)", (stale,))
    tables = ["app_user", "role_assignment", "customer", "charge", "refund", "audit_event", "user_session"]
    before = {t: [dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY 1")] for t in tables}
    inode = (tmp_path / "old.db").stat().st_ino

    newly = migrate(path)  # all pending
    assert target in newly and newly == [v for v in every if v >= target]
    assert applied_versions(path) == every
    assert migrate(path) == []  # idempotent
    assert (tmp_path / "old.db").stat().st_ino == inode  # same file, not recreated

    for table in tables:
        rows = [dict(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY 1")]
        assert before[table] and len(rows) == len(before[table]), table
        for old, new in zip(before[table], rows):
            assert {k: new[k] for k in old} == old, table  # every old column keeps its value
        if table == "app_user":
            assert all(r["active"] == 1 for r in rows)
        if table == "user_session":
            assert all(r["last_seen_at"] is None for r in rows)
    settings = {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT * FROM setting")}
    assert settings["auto_approve_limit_cents"] == 31000  # the admin's value survives
    assert settings["session_timeout_minutes"] == 60
    assert settings["refund_requires_kyc"] is True
    assert settings["max_refund_age_days"] == 90
    assert set(ALL_KEYS) <= set(settings)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE app_user SET active = 2 WHERE id = 1")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM audit_event")

    app = create_app(path)
    try:
        with TestClient(app, follow_redirects=False) as client:
            # Old passwords still work, old data is served, and the new features work on the old data.
            assert client.post("/api/login", json={"username": "admin1", "password": "demo"}).status_code == 200
            assert client.get("/api/settings/auto-approve-limit").json()["value_cents"] == 31000
            assert client.get("/api/users").json()["total"] == 5
            assert client.put("/api/settings/session_timeout_minutes", json={"value": 30}).status_code == 200
        with TestClient(app, follow_redirects=False, cookies={"session": "live-token"}) as approver:
            # A session created before the upgrade has no last_seen_at and keeps working.
            listed = approver.get("/api/refunds").json()
            assert listed["total"] == 2
            assert [r["reason"] for r in listed["items"]] == ["legacy free text reason", "small one"]
            assert approver.post("/api/refunds/1/approve", json={"reason": "Matches refund policy"}).status_code == 200
            assert con.execute("SELECT last_seen_at FROM user_session WHERE token = 'live-token'").fetchone()[0]
        with TestClient(app, follow_redirects=False, cookies={"session": "stale-token"}) as stale_client:
            # A pre-upgrade session older than the timeout is measured from created_at.
            assert stale_client.get("/api/refunds").status_code == 401
    finally:
        app.state.engine.dispose()
        con.close()
