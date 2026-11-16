"""BUILD_SPEC_2 item 2: shared list screens. AC18 (small), AC19, AC24."""
import re

from fastapi import Depends, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.foundation import lists
from app.foundation.auth import require
from app.foundation.web import page, tx
from app.main import create_app
from tests.conftest import BANK_1, SSN_1, SSN_2, USERS
from tests.paging import (CUSTOMER_FIELDS, CUSTOMER_SORTS, REFUND_FIELDS, REFUND_SORTS, check_list,
                          customer_rows, customers_fetch, kyc_fetch, refund_rows, refunds_fetch)

NAMES = ["Zed Quill", "amy Brook", "Omar Vale", "Lena Ash", "Kai North", "bea Moss", "Ivo Stone"]


def _more_data(sql, customers=57, refunds=83):
    for n in range(customers):
        name = f"{NAMES[n % len(NAMES)]} {n}"
        sql.execute("INSERT INTO customer (name, email, ssn, bank_account, kyc_status) VALUES (?, ?, ?, ?, ?)",
                    (name, f"c{(n * 37) % 101}@example.test", f"900-{n % 90 + 10:02d}-{1000 + n:04d}",
                     f"40{n:08d}", ("pending", "approved", "rejected")[n % 3]))
    # Historical rejected refunds on non-KYC customers: migration 007 refuses these inserts while the
    # KYC rule is on, so the fixture data is loaded with it off and the rule is switched back on.
    sql.execute("UPDATE setting SET value = 'false' WHERE key = 'refund_requires_kyc'")
    for n in range(refunds):
        charge = n % 8 + 1
        sql.execute("INSERT INTO refund (charge_id, amount_cents, reason, status, requested_by, decided_by, "
                    "created_at, updated_at) VALUES (?, ?, ?, 'rejected', ?, 'approver1', ?, ?)",
                    (charge, (n * 7919) % 5000 + 1, f"reason {n % 5}", ("agent1", "agent2")[n % 2],
                     f"2026-01-{n % 28 + 1:02d}T00:00:00Z", "2026-01-01T00:00:00Z"))
    sql.execute("UPDATE setting SET value = 'true' WHERE key = 'refund_requires_kyc'")


def test_ac18_customers_refunds_and_kyc_lists_small(login, sql):
    _more_data(sql)
    agent, kyc = login("agent1"), login("kyc1")
    check_list(customers_fetch(agent, 10), customer_rows(sql), CUSTOMER_FIELDS,
               ["amy", "STONE", "example", "1003"], CUSTOMER_SORTS, 10)
    check_list(refunds_fetch(agent, 10), refund_rows(sql), REFUND_FIELDS,
               ["agent2", "reason 3", "Ada"], REFUND_SORTS, 10)
    check_list(kyc_fetch(kyc, 10), customer_rows(sql, "WHERE kyc_status = 'pending'"), CUSTOMER_FIELDS,
               ["omar", "Ben"], CUSTOMER_SORTS, 10)


def test_queues_show_waiting_time_and_sort_oldest_first(login, sql):
    _more_data(sql, customers=0, refunds=0)
    sql.execute("INSERT INTO refund (charge_id, amount_cents, reason, status, requested_by, created_at, "
                "updated_at) VALUES (1, 100, 'new', 'pending_approval', 'agent1', '2026-03-01T00:00:00Z', "
                "'2026-03-01T00:00:00Z'), (2, 100, 'old', 'pending_approval', 'agent1', "
                "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')")
    body = login("approver1").get("/refunds/queue").text
    assert "Waiting" in body and body.index('href="/refunds/2"') < body.index('href="/refunds/1"')
    assert re.search(r"\d+d \d+h", body)
    assert "Waiting" in login("kyc1").get("/kyc/queue").text


def test_ac19_agent_searching_a_full_ssn_gets_no_match_and_no_ssn(login):
    agent = login("agent1")
    for value in (SSN_1, SSN_1.replace("-", ""), SSN_2, BANK_1):
        for url in ("/api/customers", "/api/charges", "/api/refunds"):
            r = agent.get(url, params={"q": value})
            assert r.status_code == 200 and r.json()["total"] == 0, (url, value)
            assert value not in r.text and SSN_1 not in r.text and BANK_1 not in r.text
        for url in ("/customers", "/charges", "/refunds", "/refunds/new"):
            r = agent.get(url, params={"q": value})
            assert r.status_code == 200, url
            assert "(0 total)" in r.text, (url, value)
            assert value not in r.text and SSN_1 not in r.text and BANK_1 not in r.text
    # the masked last four digits still find the customer
    assert agent.get("/api/customers", params={"q": SSN_1[-4:]}).json()["total"] == 1


# --- AC24: every list route renders through the shared component -----------------------------

def _get_routes(routes, prefix=""):
    for route in routes:
        inner = getattr(route, "original_router", None) or getattr(route, "router", None)
        if inner is not None and not isinstance(route, APIRoute):
            ctx = getattr(route, "include_context", None)
            yield from _get_routes(inner.routes, prefix + (getattr(ctx, "prefix", "") or ""))
        elif isinstance(route, APIRoute) and "GET" in route.methods:
            yield prefix + route.path


def _list_routes_bypassing(app) -> tuple[list[str], list[str]]:
    """GET every HTML route as each demo user; a page with a pager is a list and must carry the
    marker that only lists.render puts there, naming a registered ListSpec."""
    checked, bad = [], []
    clients = []
    for username in USERS:
        c = TestClient(app, follow_redirects=False)
        assert c.post("/api/login", json={"username": username, "password": "demo"}).status_code == 200
        clients.append(c)
    paths = sorted(set(_get_routes(app.routes)))
    assert len(paths) > 10, paths
    for raw in paths:
        if raw.startswith("/api/"):
            continue
        path = re.sub(r"\{[^}]+\}", "1", raw)
        for c in clients:
            r = c.get(path)
            if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
                continue
            if 'class="pager"' in r.text:
                checked.append(path)
                names = re.findall(r'data-shared-list="([^"]+)"', r.text)
                if not names or any(n not in lists.REGISTRY for n in names):
                    bad.append(path)
    for c in clients:
        c.close()
    return sorted(set(checked)), sorted(set(bad))


def test_ac24_every_list_route_uses_the_shared_list_component(app):
    checked, bad = _list_routes_bypassing(app)
    assert bad == []
    for path in ("/customers", "/charges", "/refunds", "/refunds/queue", "/refunds/new", "/kyc/queue",
                 "/admin/audit", "/customers/1"):
        assert path in checked, path


def test_ac24_detects_a_list_route_that_bypasses_the_component(db_path):
    app = create_app(db_path)

    @app.get("/rogue-list")
    def rogue(request: Request, user=Depends(require("customer:read"))):
        result = {"items": [], "total": 0, "page": 1, "pages": 1, "q": "", "sort": "id", "dir": "asc"}
        return page(request, "customers.html", user, result=result, statuses=())

    try:
        _, bad = _list_routes_bypassing(app)
        assert "/rogue-list" in bad
    finally:
        app.state.engine.dispose()
