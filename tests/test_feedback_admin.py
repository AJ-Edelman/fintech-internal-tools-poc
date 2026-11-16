"""Product feedback 10 and 11: user management (add, roles, deactivate), its guards, audit and permissions."""
import re
from types import SimpleNamespace

import pytest

from app.foundation import users
from app.foundation.db import make_engine
from app.foundation.errors import AppError

from .conftest import audit_rows, request_refund

PASSWORD = "S3cret-starting-pw"


def uid(sql, username: str) -> int:
    return sql.execute("SELECT id FROM app_user WHERE username = ?", (username,)).fetchone()["id"]


def roles_of(sql, username: str) -> list[str]:
    return [r["role"] for r in sql.execute(
        "SELECT role FROM role_assignment WHERE user_id = ? ORDER BY role", (uid(sql, username),))]


def audit_dump(sql) -> str:
    return "\n".join("|".join(str(v) for v in row) for row in sql.execute("SELECT * FROM audit_event"))


def add(admin, username="newbie", password=PASSWORD, role_names=("refund_agent",)):
    return admin.post("/api/users", json={"username": username, "password": password,
                                          "role_names": list(role_names)})


# --- adding users ---------------------------------------------------------------------

def test_admin_adds_user_who_can_log_in_with_the_starting_password(login, sql):
    admin = login("admin1")
    response = add(admin, "newbie", PASSWORD, ["refund_agent"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["username"] == "newbie" and body["active"] is True and body["roles"] == ["refund_agent"]
    assert body["id"] == uid(sql, "newbie")
    assert "password" not in response.text.lower() and PASSWORD not in response.text
    newbie = login("newbie", PASSWORD)
    assert request_refund(newbie, amount_cents=1000).status_code == 201
    assert newbie.get("/api/users").status_code == 403


def test_add_user_through_the_form(login, sql):
    admin = login("admin1")
    response = admin.post("/admin/users", data={"username": "formuser", "password": PASSWORD,
                                                "role_names": ["refund_agent", "refund_approver"]})
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/admin/access-review?saved=formuser"
    assert roles_of(sql, "formuser") == ["refund_agent", "refund_approver"]
    assert login("formuser", PASSWORD).get("/api/refunds").status_code == 200
    page = admin.get(response.headers["location"])
    assert page.status_code == 200 and "formuser" in page.text


def test_add_user_with_no_role_can_log_in_but_do_nothing(login):
    admin = login("admin1")
    assert add(admin, "norole", PASSWORD, []).status_code == 201
    norole = login("norole", PASSWORD)
    for path in ("/api/refunds", "/api/customers", "/api/users", "/api/settings", "/api/audit", "/api/kyc/queue"):
        assert norole.get(path).status_code == 403, path


@pytest.mark.parametrize("payload, fragment", [
    ({"username": "newbie", "password": "short", "role_names": []}, "at least 8"),
    ({"username": "ab", "password": PASSWORD, "role_names": []}, "username"),
    ({"username": "1abc", "password": PASSWORD, "role_names": []}, "username"),
    ({"username": "has space", "password": PASSWORD, "role_names": []}, "username"),
    ({"username": "system", "password": PASSWORD, "role_names": []}, "username"),
    ({"username": "agent1", "password": PASSWORD, "role_names": []}, "already exists"),
    ({"username": "newbie", "password": PASSWORD, "role_names": ["superuser"]}, "unknown role"),
])
def test_add_user_validation(login, sql, payload, fragment):
    admin = login("admin1")
    before = sql.execute("SELECT COUNT(*) FROM app_user").fetchone()[0]
    events = sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0]
    response = admin.post("/api/users", json=payload)
    assert response.status_code == 422, response.text
    assert fragment in response.json()["detail"]
    assert sql.execute("SELECT COUNT(*) FROM app_user").fetchone()[0] == before
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == events


def test_add_user_form_error_rerenders_the_page_with_422(login, sql):
    admin = login("admin1")
    response = admin.post("/admin/users", data={"username": "formuser", "password": "short"})
    assert response.status_code == 422
    assert "at least 8" in response.text and "short" not in re.sub(r"<[^>]+>", " ", response.text).split()
    assert sql.execute("SELECT COUNT(*) FROM app_user WHERE username = 'formuser'").fetchone()[0] == 0


def test_user_create_is_audited_without_the_password(login, sql):
    admin = login("admin1")
    assert add(admin, "newbie", PASSWORD, ["kyc_reviewer"]).status_code == 201
    events = audit_rows(sql, "user", uid(sql, "newbie"))
    assert [e["action"] for e in events] == ["user.create"]
    event = events[0]
    assert event["actor"] == "admin1" and event["created_at"]
    assert event["before"] is None
    assert '"username": "newbie"' in event["after"] and "kyc_reviewer" in event["after"]
    row = sql.execute("SELECT password_salt, password_hash FROM app_user WHERE username = 'newbie'").fetchone()
    dump = audit_dump(sql)
    assert PASSWORD not in dump
    assert row["password_hash"] not in dump and row["password_salt"] not in dump
    assert "password" not in dump.lower()
    assert PASSWORD not in row["password_hash"]


def test_failed_logins_and_rejected_passwords_never_reach_the_audit_log(login, anon, sql):
    admin = login("admin1")
    add(admin, "newbie", "pw-too-1")  # exactly 8, accepted
    add(admin, "other", "tiny")  # rejected
    anon.post("/api/login", json={"username": "agent1", "password": "Wrong-Guess-123"})
    anon.post("/login", data={"username": "agent1", "password": "Wrong-Form-456"})
    dump = audit_dump(sql)
    for secret in ("pw-too-1", "tiny", "Wrong-Guess-123", "Wrong-Form-456", "demo"):
        assert secret not in dump, secret


# --- roles ----------------------------------------------------------------------------

def test_grant_and_remove_roles_takes_effect_and_is_audited(login, sql):
    admin, agent = login("admin1"), login("agent1")
    target = uid(sql, "agent1")
    assert agent.get("/api/kyc/queue").status_code == 403
    response = admin.put(f"/api/users/{target}/roles", json={"role_names": ["refund_agent", "kyc_reviewer"]})
    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["kyc_reviewer", "refund_agent"]
    assert agent.get("/api/kyc/queue").status_code == 200  # same session, roles read per request
    response = admin.put(f"/api/users/{target}/roles", json={"role_names": []})
    assert response.status_code == 200 and response.json()["roles"] == []
    assert agent.get("/api/kyc/queue").status_code == 403
    assert agent.get("/api/refunds").status_code == 403
    assert roles_of(sql, "agent1") == []
    events = audit_rows(sql, "user", target)
    assert [e["action"] for e in events] == ["user.roles_change", "user.roles_change"]
    assert all(e["actor"] == "admin1" and e["created_at"] for e in events)
    assert '"roles": ["refund_agent"]' in events[0]["before"]
    assert '"roles": ["kyc_reviewer", "refund_agent"]' in events[0]["after"]
    assert '"roles": []' in events[1]["after"]


def test_roles_form_changes_roles(login, sql):
    admin = login("admin1")
    target = uid(sql, "agent2")
    response = admin.post(f"/admin/users/{target}/roles", data={"role_names": "refund_approver"})
    assert response.status_code == 303 and response.headers["location"] == "/admin/access-review?saved=agent2"
    assert roles_of(sql, "agent2") == ["refund_approver"]


def test_roles_validation_and_missing_user(login, sql):
    admin = login("admin1")
    target = uid(sql, "agent1")
    assert admin.put(f"/api/users/{target}/roles", json={"role_names": ["root"]}).status_code == 422
    assert admin.put(f"/api/users/{target}/roles", json={}).status_code == 422
    assert admin.put("/api/users/9999/roles", json={"role_names": []}).status_code == 404
    assert admin.put("/api/users/9999/active", json={"active": False}).status_code == 404
    assert roles_of(sql, "agent1") == ["refund_agent"]
    assert audit_rows(sql, "user", target) == []


def test_admin_cannot_change_own_access(login, sql):
    admin = login("admin1")
    me = uid(sql, "admin1")
    for response in (
        admin.put(f"/api/users/{me}/roles", json={"role_names": ["admin", "refund_approver"]}),
        admin.put(f"/api/users/{me}/roles", json={"role_names": []}),
        admin.put(f"/api/users/{me}/active", json={"active": False}),
        admin.post(f"/admin/users/{me}/roles", data={"role_names": "refund_agent"}),
        admin.post(f"/admin/users/{me}/active", data={"active": "0"}),
    ):
        assert response.status_code in (403, 422), response.text
        assert "own access" in response.text or "yourself" in response.text
    assert roles_of(sql, "admin1") == ["admin"]
    assert sql.execute("SELECT active FROM app_user WHERE id = ?", (me,)).fetchone()[0] == 1
    assert audit_rows(sql, "user", me) == []
    assert admin.get("/api/users").status_code == 200


def test_own_row_has_no_change_controls_on_the_page(login, sql):
    admin = login("admin1")
    html = admin.get("/admin/access-review").text
    assert f'action="/admin/users/{uid(sql, "admin1")}/' not in html
    assert f'action="/admin/users/{uid(sql, "agent1")}/roles"' in html
    assert f'action="/admin/users/{uid(sql, "agent1")}/active"' in html


def test_second_admin_can_remove_first_but_an_active_admin_always_remains(login, sql):
    admin1 = login("admin1")
    assert add(admin1, "admin2", PASSWORD, ["admin"]).status_code == 201
    admin2 = login("admin2", PASSWORD)
    first = uid(sql, "admin1")
    assert admin2.put(f"/api/users/{first}/roles", json={"role_names": []}).status_code == 200
    assert admin1.get("/api/users").status_code == 403
    # admin2 is now the last admin and cannot drop or deactivate themself.
    second = uid(sql, "admin2")
    assert admin2.put(f"/api/users/{second}/roles", json={"role_names": []}).status_code in (403, 422)
    assert admin2.put(f"/api/users/{second}/active", json={"active": False}).status_code in (403, 422)
    active_admins = sql.execute(
        "SELECT COUNT(*) FROM app_user u JOIN role_assignment ra ON ra.user_id = u.id "
        "WHERE ra.role = 'admin' AND u.active = 1").fetchone()[0]
    assert active_admins == 1


def test_last_admin_guard_in_the_service_layer(db_path, sql):
    """Through HTTP the actor is always another active admin, so call the rule directly with an outside actor."""
    outsider = SimpleNamespace(id=-1, username="outsider", permissions=frozenset({"user:manage"}))
    target = uid(sql, "admin1")
    engine = make_engine(db_path)
    try:
        with pytest.raises(AppError) as removed:
            with engine.begin() as conn:
                users.set_roles(conn, outsider, target, ["refund_agent"])
        assert removed.value.status == 422 and "last admin" in removed.value.detail
        with pytest.raises(AppError) as deactivated:
            with engine.begin() as conn:
                users.set_active(conn, outsider, target, False)
        assert deactivated.value.status == 422 and "last admin" in deactivated.value.detail
        nobody = SimpleNamespace(id=-1, username="nobody", permissions=frozenset())
        with pytest.raises(AppError) as denied:
            with engine.begin() as conn:
                users.add_user(conn, nobody, "sneaky", PASSWORD, ["admin"])
        assert denied.value.status == 403
    finally:
        engine.dispose()
    assert roles_of(sql, "admin1") == ["admin"]
    assert sql.execute("SELECT active FROM app_user WHERE id = ?", (target,)).fetchone()[0] == 1
    assert audit_rows(sql, "user", target) == []


# --- deactivate / reactivate ----------------------------------------------------------

def test_deactivate_ends_sessions_blocks_login_and_reactivate_restores(login, anon, sql):
    admin, agent, agent_again = login("admin1"), login("agent1"), login("agent1")
    target = uid(sql, "agent1")
    assert sql.execute("SELECT COUNT(*) FROM user_session WHERE user_id = ?", (target,)).fetchone()[0] == 2
    response = admin.put(f"/api/users/{target}/active", json={"active": False})
    assert response.status_code == 200 and response.json()["active"] is False
    assert sql.execute("SELECT COUNT(*) FROM user_session WHERE user_id = ?", (target,)).fetchone()[0] == 0
    assert agent.get("/api/refunds").status_code == 401
    assert agent_again.get("/api/refunds").status_code == 401
    page = agent.get("/refunds")
    assert page.status_code == 303 and page.headers["location"].startswith("/login")
    assert anon.post("/api/login", json={"username": "agent1", "password": "demo"}).status_code == 401
    assert anon.post("/login", data={"username": "agent1", "password": "demo"}).status_code == 401

    response = admin.put(f"/api/users/{target}/active", json={"active": True})
    assert response.status_code == 200 and response.json()["active"] is True
    assert agent.get("/api/refunds").status_code == 401  # old sessions stay dead
    assert login("agent1").get("/api/refunds").status_code == 200
    assert roles_of(sql, "agent1") == ["refund_agent"]

    events = audit_rows(sql, "user", target)
    assert [e["action"] for e in events] == ["user.deactivate", "user.reactivate"]
    assert all(e["actor"] == "admin1" and e["created_at"] for e in events)
    assert '"active": true' in events[0]["before"] and '"active": false' in events[0]["after"]
    assert '"active": false' in events[1]["before"] and '"active": true' in events[1]["after"]


def test_deactivate_through_the_form(login, sql):
    admin, approver = login("admin1"), login("approver1")
    target = uid(sql, "approver1")
    response = admin.post(f"/admin/users/{target}/active", data={"active": "0"})
    assert response.status_code == 303
    assert approver.get("/api/refunds").status_code == 401
    html = admin.get("/admin/access-review?status=inactive").text
    assert "approver1" in html and "Reactivate" in html
    assert admin.post(f"/admin/users/{target}/active", data={"active": "1"}).status_code == 303
    assert sql.execute("SELECT active FROM app_user WHERE id = ?", (target,)).fetchone()[0] == 1


def test_deactivated_admin_loses_access_immediately(login, sql):
    admin1 = login("admin1")
    add(admin1, "admin2", PASSWORD, ["admin"])
    admin2 = login("admin2", PASSWORD)
    assert admin2.put(f"/api/users/{uid(sql, 'admin1')}/active", json={"active": False}).status_code == 200
    assert admin1.get("/api/users").status_code == 401
    assert admin1.put(f"/api/users/{uid(sql, 'admin2')}/active", json={"active": False}).status_code == 401
    assert sql.execute("SELECT active FROM app_user WHERE username = 'admin2'").fetchone()[0] == 1


def test_inactive_user_is_dropped_from_the_role_overview_but_listed(login, sql):
    admin = login("admin1")
    admin.put(f"/api/users/{uid(sql, 'kyc1')}/active", json={"active": False})
    listed = admin.get("/api/users?status=inactive").json()
    assert [u["username"] for u in listed["items"]] == ["kyc1"] and listed["total"] == 1
    html = admin.get("/admin/access-review").text
    assert "Inactive" in html


# --- maker-checker with both refund roles ---------------------------------------------

def test_nobody_approves_their_own_refund_even_with_both_refund_roles(login, sql):
    admin = login("admin1")
    assert add(admin, "both", PASSWORD, ["refund_agent", "refund_approver"]).status_code == 201
    both = login("both", PASSWORD)
    created = request_refund(both, amount_cents=75000)
    assert created.status_code == 201 and created.json()["status"] == "pending_approval"
    refund_id = created.json()["id"]
    for action in ("approve", "reject"):
        response = both.post(f"/api/refunds/{refund_id}/{action}", json={"reason": "Matches refund policy"})
        assert response.status_code == 403, response.text
    form = both.post(f"/refunds/{refund_id}/decision", data={
        "decision": "approve", "reason_choice": "Matches refund policy", "source": "queue"})
    assert form.status_code == 403
    assert sql.execute("SELECT status, decided_by FROM refund WHERE id = ?", (refund_id,)).fetchone()[:] == \
        ("pending_approval", None)
    queue = both.get("/refunds/queue").text
    assert f'action="/refunds/{refund_id}/decision"' not in queue
    # Someone else's request can be decided by the same two-role user, and theirs by another approver.
    other = request_refund(login("agent1"), charge_id=2, amount_cents=75000).json()["id"]
    assert both.post(f"/api/refunds/{other}/approve", json={"reason": "Matches refund policy"}).status_code == 200
    assert login("approver1").post(f"/api/refunds/{refund_id}/approve",
                                   json={"reason": "Matches refund policy"}).status_code == 200


def test_granting_the_approver_role_later_still_blocks_own_request(login, sql):
    admin, agent = login("admin1"), login("agent1")
    refund_id = request_refund(agent, amount_cents=75000).json()["id"]
    admin.put(f"/api/users/{uid(sql, 'agent1')}/roles", json={"role_names": ["refund_agent", "refund_approver"]})
    assert agent.post(f"/api/refunds/{refund_id}/approve", json={"reason": "ok"}).status_code == 403
    assert sql.execute("SELECT status FROM refund WHERE id = ?", (refund_id,)).fetchone()[0] == "pending_approval"


# --- permissions ----------------------------------------------------------------------

READS = ["/api/users", "/api/access-review", "/admin/access-review"]
WRITES = [
    ("post", "/api/users", {"json": {"username": "sneaky", "password": PASSWORD, "role_names": ["admin"]}}),
    ("put", "/api/users/1/roles", {"json": {"role_names": ["admin"]}}),
    ("put", "/api/users/5/active", {"json": {"active": False}}),
    ("post", "/admin/users", {"data": {"username": "sneaky", "password": PASSWORD, "role_names": "admin"}}),
    ("post", "/admin/users/1/roles", {"data": {"role_names": "admin"}}),
    ("post", "/admin/users/5/active", {"data": {"active": "0"}}),
]


@pytest.mark.parametrize("username", ["agent1", "approver1", "kyc1"])
def test_non_admins_get_403_on_user_management(login, sql, username):
    client = login(username)
    for path in READS:
        assert client.get(path).status_code == 403, path
    for method, path, kwargs in WRITES:
        assert getattr(client, method)(path, **kwargs).status_code == 403, (method, path)
    assert sql.execute("SELECT COUNT(*) FROM app_user").fetchone()[0] == 5
    assert sql.execute("SELECT COUNT(*) FROM app_user WHERE active = 0").fetchone()[0] == 0
    assert sql.execute("SELECT COUNT(*) FROM role_assignment").fetchone()[0] == 5
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 0


def test_no_session_gets_401_or_login_redirect_on_user_management(anon, sql):
    for path in READS:
        response = anon.get(path)
        if path.startswith("/api/"):
            assert response.status_code == 401, path
        else:
            assert response.status_code == 303 and response.headers["location"].startswith("/login"), path
    for method, path, kwargs in WRITES:
        response = getattr(anon, method)(path, **kwargs)
        if path.startswith("/api/"):
            assert response.status_code == 401, path
        else:
            assert response.status_code == 303 and response.headers["location"].startswith("/login"), path
    assert sql.execute("SELECT COUNT(*) FROM app_user").fetchone()[0] == 5
    assert sql.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 0


# --- the admin screen (feedback 10) ---------------------------------------------------

def test_access_page_uses_plain_labels_not_raw_role_or_permission_names(login):
    html = login("admin1").get("/admin/access-review").text
    visible = re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", " ", html))
    for label in ("Refund agent", "Refund approver", "KYC reviewer", "Admin", "Add a user", "Active"):
        assert label in visible, label
    for raw in ("refund_agent", "refund_approver", "kyc_reviewer", "user:manage", "settings:write",
                "refund:approve", "access_review:read"):
        assert raw not in visible, raw
    assert 'type="password"' in html and 'name="role_names"' in html


def test_users_api_never_returns_password_material(login, sql):
    text_ = login("admin1").get("/api/users").text
    for row in sql.execute("SELECT password_salt, password_hash FROM app_user"):
        assert row["password_salt"] not in text_ and row["password_hash"] not in text_
    assert "password" not in text_.lower()


@pytest.mark.xfail(strict=True, reason=(
    "app bug: the per-user role editor on /admin/access-review is a single-choice <select name=role_names>; "
    "saving it for a user who holds two roles (e.g. refund_agent + refund_approver) silently drops one"))
def test_role_editor_can_keep_a_user_with_two_roles(login, sql):
    admin = login("admin1")
    add(admin, "both", PASSWORD, ["refund_agent", "refund_approver"])
    html = admin.get("/admin/access-review?q=both").text
    target = uid(sql, "both")
    form = re.search(rf'(?s)<form method="post" action="/admin/users/{target}/roles".*?</form>', html).group(0)
    multi = "multiple" in form or form.count('type="checkbox"') >= 2
    assert multi, "role editor must allow more than one role to be submitted"
