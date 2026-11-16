"""AC20: record-level access by region (refunds and KYC)."""
import pytest
from sqlalchemy import text

from app.foundation import scope
from app.foundation.auth import User, scopes_for
from app.foundation.db import make_engine
from app.foundation.permissions import permissions_for
from tests.conftest import request_refund

LISTS = pytest.mark.xfail(strict=False, reason="needs worker B's lists")


@pytest.fixture
def regions(sql, add_user):
    """Customer 1 (charges 1-6) and 3 are US, customer 2 (charge 7) is EU and KYC-approved.
    agent1/approver1/kyc1 are US, agent2 is EU, approver2 and kyc2 are EU."""
    add_user("approver2", ["refund_approver"])
    add_user("kyc2", ["kyc_reviewer"])
    sql.execute("UPDATE customer SET region = 'EU', kyc_status = 'approved' WHERE id = 2")
    sql.execute("UPDATE role_assignment SET region = 'US' WHERE user_id IN "
                "(SELECT id FROM app_user WHERE username IN ('agent1', 'approver1', 'kyc1'))")
    sql.execute("UPDATE role_assignment SET region = 'EU' WHERE user_id IN "
                "(SELECT id FROM app_user WHERE username IN ('agent2', 'approver2', 'kyc2'))")


def _user(roles, region):
    return User(id=99, username="t", roles=tuple(roles), permissions=permissions_for(roles),
                scopes=scopes_for([(r, region) for r in roles]))


def test_ac20_scope_functions(db_path, regions):
    us, eu = _user(["refund_agent"], "US"), _user(["refund_agent"], "EU")
    admin = _user(["admin"], "EU")
    assert scope.regions_for(us, "refund:create") == frozenset({"US"})
    assert scope.regions_for(eu, "refund:create") == frozenset({"EU"})
    assert scope.regions_for(_user(["refund_agent"], "ALL"), "refund:create") is None
    assert scope.regions_for(eu, "kyc:review") == frozenset()  # not held: nothing
    assert all(scope.regions_for(admin, p) is None for p in admin.permissions)  # admin is ALL
    system = User(id=0, username="system", roles=(), permissions=frozenset(), is_system=True,
                  scopes={"x": frozenset({"EU"})})
    assert scope.regions_for(system, "refund:create") is None
    engine = make_engine(db_path)
    with engine.begin() as conn:
        for user, perm, expected in ((us, "refund:create", [1, 3]), (eu, "refund:create", [2]),
                                     (admin, "audit:read", [1, 2, 3]), (eu, "kyc:review", [])):
            cond, params = scope.customer_filter(user, perm, "c.id")
            ids = [r[0] for r in conn.execute(text(f"SELECT c.id FROM customer c WHERE {cond} ORDER BY c.id"),
                                              params)]
            assert ids == expected
        scope.check_customer(conn, us, "refund:create", 1)
        scope.check_customer(conn, eu, "refund:create", 2)
        for user, cid in ((us, 2), (eu, 1), (eu, 3), (eu, 999)):
            with pytest.raises(Exception) as exc:
                scope.check_customer(conn, user, "refund:create", cid)
            assert exc.value.status == 404
    engine.dispose()


def test_ac20_login_fills_scopes(login, regions):
    from app.foundation.auth import user_from_request
    client = login("agent2")
    # Scopes come from role_assignment.region on every request.
    class R:  # minimal request stand-in
        cookies = client.cookies
        app = client.app
    user = user_from_request(R)
    assert user.scopes["refund:create"] == frozenset({"EU"})


def test_ac20_eu_agent_cannot_request_or_view_us_refund(login, regions):
    agent2 = login("agent2")
    assert request_refund(agent2, charge_id=1, amount_cents=100000).status_code == 404
    eu = request_refund(agent2, charge_id=7, amount_cents=100000)
    assert eu.status_code == 201, eu.text
    us = request_refund(login("agent1"), charge_id=1, amount_cents=100000)
    assert us.status_code == 201, us.text
    us_id = us.json()["id"]
    approver2 = login("approver2")
    for path in (f"/api/refunds/{us_id}/approve", f"/api/refunds/{us_id}/reject"):
        r = approver2.post(path, json={"reason": "Duplicate charge"})
        assert r.status_code == 404, (path, r.text)
    # The US approver can still decide it; approver2 decides the EU one.
    assert approver2.post(f"/api/refunds/{eu.json()['id']}/approve", json={"reason": "Duplicate charge"}).status_code == 200
    assert login("approver1").post(f"/api/refunds/{eu.json()['id']}/reject",
                                   json={"reason": "Duplicate charge"}).status_code in (404, 409)
    assert login("approver1").post(f"/api/refunds/{us_id}/approve", json={"reason": "Duplicate charge"}).status_code == 200


def test_ac20_eu_kyc_reviewer_cannot_decide_us_customer(login, sql, regions):
    sql.execute("UPDATE customer SET kyc_status = 'pending' WHERE id IN (1, 2)")
    kyc2 = login("kyc2")
    assert kyc2.post("/api/kyc/1/decision", json={"decision": "approve", "reason": "Documents verified"}).status_code == 404
    assert sql.execute("SELECT kyc_status FROM customer WHERE id = 1").fetchone()[0] == "pending"
    assert kyc2.post("/api/kyc/2/decision", json={"decision": "approve", "reason": "Documents verified"}).status_code == 200
    assert login("kyc1").post("/api/kyc/2/decision", json={"decision": "reject", "reason": "Documents verified"}).status_code in (404, 409)


@LISTS
def test_ac20_eu_agent_detail_list_count_search_hide_us(login, regions):
    us_id = request_refund(login("agent1"), charge_id=1, amount_cents=100000).json()["id"]
    agent2 = login("agent2")
    assert agent2.get(f"/api/refunds/{us_id}").status_code == 404
    assert agent2.get(f"/refunds/{us_id}").status_code == 404
    listed = agent2.get("/api/refunds").json()
    assert us_id not in [r["id"] for r in listed["items"]] and listed["total"] == 0
    assert agent2.get("/api/refunds", params={"q": "Ada"}).json()["total"] == 0
    customers = agent2.get("/api/customers").json()
    assert [c["id"] for c in customers["items"]] == [2] and customers["total"] == 1
    assert agent2.get("/api/customers/1").status_code == 404
    assert login("approver2").get("/api/refunds", params={"status": "pending_approval"}).json()["total"] == 0


@LISTS
def test_ac20_eu_kyc_queue_hides_us(login, sql, regions):
    sql.execute("UPDATE customer SET kyc_status = 'pending' WHERE id IN (1, 2)")
    queue = login("kyc2").get("/api/kyc/queue").json()
    assert [c["id"] for c in queue["items"]] == [2] and queue["total"] == 1
    assert login("kyc2").get("/api/kyc/queue", params={"q": "Ada"}).json()["total"] == 0
