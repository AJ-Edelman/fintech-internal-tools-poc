"""AC4, AC5, AC12 and the status-code rules of the foundation."""
import inspect

from app.foundation.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS
from tests.conftest import all_routes, audit_rows, request_refund

LOGIN_PATHS = {"/login", "/api/login"}


def _route_permissions(route):
    found = []
    for dependency in route.dependant.dependencies:
        found.extend(getattr(dependency.call, "required_permissions", ()))
    return found


def test_every_route_except_login_checks_a_permission(app):
    routes = all_routes(app)  # raises on anything that is not a plain route (docs, static, mounts)
    assert len(routes) > 15
    for route in routes:
        permissions = _route_permissions(route)
        if route.path in LOGIN_PATHS:
            assert permissions == []
            continue
        assert permissions, f"{route.methods} {route.path} checks no permission"
        assert set(permissions) <= ALL_PERMISSIONS


def test_routes_never_check_role_names():
    import app.foundation.web as web
    import app.refunds.routes as refund_routes

    for module in (web, refund_routes):
        source = inspect.getsource(module)
        for role in ROLE_PERMISSIONS:
            assert f'"{role}"' not in source and f"'{role}'" not in source, (
                f"{module.__name__} mentions role {role}")
        assert ".roles" not in source


def test_no_session_is_401_on_api_and_redirect_to_login_on_pages(app, anon):
    for route in all_routes(app):
        if route.path in LOGIN_PATHS:
            continue
        path = route.path.replace("{refund_id}", "1").replace("{customer_id}", "1")
        for method in route.methods:
            response = anon.request(method, path)
            if path.startswith("/api/"):
                assert response.status_code == 401, (method, path)
            else:
                assert response.status_code == 303, (method, path)
                assert response.headers["location"].startswith("/login"), (method, path)
    assert anon.get("/login").status_code == 200
    anon.cookies.set("session", "not-a-real-token")
    assert anon.get("/api/refunds").status_code == 401


def test_wrong_password_gets_no_session(anon):
    assert anon.post("/api/login", json={"username": "agent1", "password": "wrong"}).status_code == 401
    assert anon.post("/login", data={"username": "agent1", "password": "wrong"}).status_code == 401
    assert anon.get("/api/refunds").status_code == 401


def test_ac4_user_with_both_refund_roles_cannot_approve_own_request(login, add_user, sql):
    add_user("both1", ["refund_agent", "refund_approver"])
    both = login("both1")
    refund = request_refund(both, charge_id=1, amount_cents=75000, reason="mine").json()
    assert refund["status"] == "pending_approval"

    for action in ("approve", "reject"):
        response = both.post(f"/api/refunds/{refund['id']}/{action}", json={"reason": "self"})
        assert response.status_code == 403
    page = both.post(f"/refunds/{refund['id']}/decision", data={"decision": "approve", "reason": "self"})
    assert page.status_code == 403

    row = sql.execute("SELECT status, decided_by FROM refund WHERE id = ?", (refund["id"],)).fetchone()
    assert (row["status"], row["decided_by"]) == ("pending_approval", None)
    assert [e["action"] for e in audit_rows(sql, "refund", refund["id"])] == ["refund.request"]

    # Someone else can still decide it, and both1 can decide someone else's request.
    assert login("approver1").post(f"/api/refunds/{refund['id']}/approve",
                                   json={"reason": "independent"}).status_code == 200
    other = request_refund(login("agent1"), charge_id=2, amount_cents=75000).json()
    assert both.post(f"/api/refunds/{other['id']}/approve", json={"reason": "ok"}).status_code == 200


def test_ac4_self_approval_rule_does_not_block_automatic_approval(login, add_user):
    add_user("both1", ["refund_agent", "refund_approver"])
    refund = request_refund(login("both1"), charge_id=1, amount_cents=100).json()
    assert (refund["status"], refund["decided_by"]) == ("approved", "system")


def test_ac5_agent_calling_approve_endpoint_gets_403(login, sql):
    agent1, agent2 = login("agent1"), login("agent2")
    refund = request_refund(agent1, amount_cents=75000).json()
    for client in (agent1, agent2):
        for action in ("approve", "reject"):
            response = client.post(f"/api/refunds/{refund['id']}/{action}", json={"reason": "try"})
            assert response.status_code == 403
        assert client.post(f"/refunds/{refund['id']}/decision",
                           data={"decision": "approve", "reason": "try"}).status_code == 403
        assert client.get("/refunds/queue").status_code == 403
    assert agent1.get(f"/api/refunds/{refund['id']}").json()["status"] == "pending_approval"
    assert [e["action"] for e in audit_rows(sql, "refund", refund["id"])] == ["refund.request"]


def test_approver_cannot_create_and_other_roles_cannot_touch_refunds(login):
    body = {"charge_id": 1, "amount_cents": 100, "reason": "x"}
    assert login("approver1").post("/api/refunds", json=body).status_code == 403
    assert login("approver1").get("/refunds/new").status_code == 403
    for username in ("kyc1", "admin1"):
        client = login(username)
        assert client.post("/api/refunds", json=body).status_code == 403
        assert client.get("/api/refunds").status_code == 403
        assert client.get("/refunds").status_code == 403
    # admin is not a superuser
    assert login("admin1").get("/api/customers").status_code == 403


def test_roles_are_read_from_the_database_on_every_request(login, sql):
    agent = login("agent1")
    assert agent.get("/api/refunds").status_code == 200
    sql.execute("DELETE FROM role_assignment WHERE user_id = (SELECT id FROM app_user WHERE username = 'agent1')")
    assert agent.get("/api/refunds").status_code == 403
    assert request_refund(agent).status_code == 403


def test_ac12_admin_lists_role_assignments_others_403_no_session_401(login, anon):
    response = login("admin1").get("/api/access-review")
    assert response.status_code == 200
    pairs = {(a["username"], a["role"]) for a in response.json()["assignments"]}
    assert pairs == {
        ("agent1", "refund_agent"),
        ("agent2", "refund_agent"),
        ("approver1", "refund_approver"),
        ("kyc1", "kyc_reviewer"),
        ("admin1", "admin"),
    }
    page = login("admin1").get("/admin/access-review")
    assert page.status_code == 200 and "refund_approver" in page.text

    for username in ("agent1", "approver1", "kyc1"):
        client = login(username)
        assert client.get("/api/access-review").status_code == 403
        assert client.get("/admin/access-review").status_code == 403
        assert client.get("/api/audit").status_code == 403
    assert anon.get("/api/access-review").status_code == 401
    assert anon.get("/admin/access-review").status_code == 303
