"""AC25: control changes require a reason, atomically, in both HTTP interfaces."""
import json
import re

import pytest

from .conftest import audit_rows


CHANGES = ("refund_requires_kyc", "max_refund_age_days", "roles", "region", "active")
MISSING = object()


def change(client, sql, interface, kind, reason=MISSING):
    target = sql.execute("SELECT id FROM app_user WHERE username = 'agent1'").fetchone()[0]
    if kind in ("refund_requires_kyc", "max_refund_age_days"):
        api_value = False if kind == "refund_requires_kyc" else 30
        form_body = {} if kind == "refund_requires_kyc" else {"value": "30"}
        api_body = {"value": api_value}
        api_path, form_path = f"/api/settings/{kind}", f"/admin/settings/{kind}"
    else:
        action = "roles" if kind in ("roles", "region") else "active"
        api_path, form_path = f"/api/users/{target}/{action}", f"/admin/users/{target}/{action}"
        if kind == "active":
            api_body, form_body = {"active": False}, {"active": "0"}
        else:
            roles = ["refund_approver"] if kind == "roles" else ["refund_agent"]
            api_body, form_body = {"role_names": roles}, {"role_names": roles}
            if kind == "region":
                api_body["region"] = form_body["region"] = "EU"
    body = api_body if interface == "api" else form_body
    if reason is not MISSING:
        body["reason"] = reason
    if interface == "api":
        return client.put(api_path, json=body)
    return client.post(form_path, data=body)


def snapshot(sql):
    return {table: [tuple(row) for row in sql.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in ("setting", "app_user", "role_assignment", "audit_event")}


@pytest.mark.parametrize("kind", CHANGES)
@pytest.mark.parametrize("interface", ["api", "form"])
@pytest.mark.parametrize("reason", [MISSING, "", " \t\n "])
def test_ac25_missing_or_blank_reason_changes_nothing(login, sql, kind, interface, reason):
    admin = login("admin1")
    login("agent1")  # rejected deactivation must not end the target's sessions
    before = snapshot(sql)
    sessions = sql.execute("SELECT COUNT(*) FROM user_session").fetchone()[0]
    response = change(admin, sql, interface, kind, reason)
    assert response.status_code == 422, response.text
    assert snapshot(sql) == before
    assert sql.execute("SELECT COUNT(*) FROM user_session").fetchone()[0] == sessions


@pytest.mark.parametrize("kind", CHANGES)
@pytest.mark.parametrize("interface", ["api", "form"])
@pytest.mark.parametrize("reason, expected", [
    ("  Quarterly review  ", "Quarterly review"),
    ("Review SSN 900-12-3456 account 4000123456", "Review SSN ***-**-3456 account ****3456"),
])
def test_ac25_reason_is_required_stored_and_redacted(login, sql, kind, interface, reason, expected):
    admin = login("admin1")
    response = change(admin, sql, interface, kind, reason)
    assert response.status_code == (303 if interface == "form" and kind in ("roles", "region", "active") else 200), response.text
    target = sql.execute("SELECT id FROM app_user WHERE username = 'agent1'").fetchone()[0]
    if kind in ("refund_requires_kyc", "max_refund_age_days"):
        value = json.loads(sql.execute("SELECT value FROM setting WHERE key = ?", (kind,)).fetchone()[0])
        assert value == (False if kind == "refund_requires_kyc" else 30)
        events = audit_rows(sql, "setting", kind)
        assert events[-1]["action"] == "setting.change"
    else:
        events = audit_rows(sql, "user", target)
        assignments = sql.execute("SELECT role, region FROM role_assignment WHERE user_id = ? ORDER BY role", (target,)).fetchall()
        if kind == "roles":
            assert [r["role"] for r in assignments] == ["refund_approver"]
        elif kind == "region":
            assert [tuple(r) for r in assignments] == [("refund_agent", "EU")]
        else:
            assert sql.execute("SELECT active FROM app_user WHERE id = ?", (target,)).fetchone()[0] == 0
        assert events[-1]["action"] == ("user.deactivate" if kind == "active" else "user.roles_change")
    assert len(events) == 1
    assert events[0]["actor"] == "admin1" and events[0]["reason"] == expected
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 1
    assert "900-12-3456" not in str(tuple(events[0]))
    assert "4000123456" not in str(tuple(events[0]))


@pytest.mark.parametrize("interface", ["api", "form"])
def test_ac25_limit_still_needs_no_reason(login, sql, interface):
    admin = login("admin1")
    response = (admin.put("/api/settings/auto-approve-limit", json={"value_cents": 12345})
                if interface == "api" else admin.post("/admin/settings", data={"amount": "123.45"}))
    assert response.status_code == 200, response.text
    assert json.loads(sql.execute("SELECT value FROM setting WHERE key = 'auto_approve_limit_cents'").fetchone()[0]) == 12345
    assert audit_rows(sql, "setting", "auto_approve_limit_cents")[-1]["reason"] is None


def test_ac25_forms_require_reasons_only_for_control_changes(login, sql):
    admin = login("admin1")
    settings = admin.get("/admin/settings").text
    for key in ("refund_requires_kyc", "max_refund_age_days"):
        form = re.search(rf'(?s)<form method="post" action="/admin/settings/{key}">.*?</form>', settings).group(0)
        assert 'name="reason" required' in form
        assert "this.form.submit()" not in form
    target = sql.execute("SELECT id FROM app_user WHERE username = 'agent1'").fetchone()[0]
    access = admin.get("/admin/access-review").text
    for action in ("roles", "active"):
        form = re.search(rf'(?s)<form method="post" action="/admin/users/{target}/{action}".*?</form>', access).group(0)
        assert 'name="reason" required' in form


@pytest.mark.parametrize("region", ["APAC", "invalid"])
def test_region_validation_remains_atomic(login, sql, region):
    admin = login("admin1")
    target = sql.execute("SELECT id FROM app_user WHERE username = 'agent1'").fetchone()[0]
    before = snapshot(sql)
    response = admin.put(f"/api/users/{target}/roles", json={
        "role_names": ["refund_agent"], "region": region, "reason": "Access review"})
    assert response.status_code == 422
    assert snapshot(sql) == before
