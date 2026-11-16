"""Pages render, the list pages on the server, and the small version of the AC11 paging test."""
import pytest
from fastapi.testclient import TestClient

from app.foundation.db import migrate
from app.main import create_app
from app.seed import scale_counts, scale_status, seed_scale
from tests.conftest import BANK_1, SSN_1, request_refund
from tests.paging import check_paging

SMALL_TOTAL = 230


def test_login_page_and_login_form_flow(anon):
    page = anon.get("/login")
    assert page.status_code == 200 and "Log in" in page.text
    response = anon.post("/login", data={"username": "agent1", "password": "demo", "next": "/refunds"})
    assert response.status_code == 303 and response.headers["location"] == "/refunds"
    assert anon.get("/refunds").status_code == 200
    assert anon.get("/").status_code == 303


def test_refund_pages_render_for_the_right_roles(login):
    agent, approver = login("agent1"), login("approver1")
    refund = request_refund(agent, amount_cents=75000, reason="page test").json()
    assert "page test" in agent.get("/refunds").text
    assert agent.get("/refunds/new").status_code == 200
    assert "page test" in approver.get("/refunds/queue").text
    detail = approver.get(f"/refunds/{refund['id']}")
    assert detail.status_code == 200 and "Approve" in detail.text and "refund.request" in detail.text
    assert "Approve</button>" not in agent.get(f"/refunds/{refund['id']}").text
    decided = approver.post(f"/refunds/{refund['id']}/decision",
                            data={"decision": "approve", "reason": "page ok"})
    assert decided.status_code == 303
    assert "refund.approve" in agent.get(f"/refunds/{refund['id']}").text
    assert "page test" not in approver.get("/refunds/queue").text
    assert approver.post(f"/refunds/{refund['id']}/decision",
                         data={"decision": "approve", "reason": "again"}).status_code == 409
    assert agent.get("/refunds/999999").status_code == 404
    assert agent.get("/refunds?status=approved").status_code == 200


def test_pii_is_masked_for_refund_roles_everywhere(login):
    for username in ("agent1", "approver1"):
        client = login(username)
        for path in ("/api/customers", "/api/customers/1", "/customers", "/customers/1", "/refunds",
                     "/api/charges"):
            body = client.get(path).text
            assert SSN_1 not in body and BANK_1 not in body, (username, path)
        assert client.get("/api/customers/1").json()["ssn"] == "***-**-3456"
        assert client.get("/api/customers/1").json()["bank_account"] == "****3456"
        assert "***-**-3456" in client.get("/customers").text


@pytest.fixture(scope="module")
def small_scale_client(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("scale") / "small-scale.db")
    migrate(path)
    counts = seed_scale(path, total=SMALL_TOTAL)
    assert counts == scale_counts(SMALL_TOTAL)
    app = create_app(path)
    with TestClient(app) as client:
        assert client.post("/api/login", json={"username": "agent1", "password": "demo"}).status_code == 200
        yield client
    app.state.engine.dispose()


def test_ac11_small_paging_with_status_filter(small_scale_client):
    counts = scale_counts(SMALL_TOTAL)
    assert counts == {"approved": 142, "pending_approval": 55, "rejected": 33}
    assert sum(counts.values()) == SMALL_TOTAL
    for status in counts:
        check_paging(small_scale_client, SMALL_TOTAL, status, counts[status], page_size=10)
    check_paging(small_scale_client, SMALL_TOTAL, None, SMALL_TOTAL, page_size=25)


def test_list_page_is_paged_on_the_server(small_scale_client):
    page = small_scale_client.get("/refunds?status=rejected&page=2&page_size=10")
    assert page.status_code == 200
    expected = [i for i in range(1, SMALL_TOTAL + 1) if scale_status(i) == "rejected"][10:20]
    for refund_id in expected:
        assert f'href="/refunds/{refund_id}"' in page.text
    assert page.text.count('href="/refunds/') - page.text.count('href="/refunds/new"') - \
        page.text.count('href="/refunds/queue"') == 10
    assert "Page 2 of 4 (33 total)" in page.text


def test_page_and_page_size_are_validated(small_scale_client):
    for query in ("page=0", "page=-1", "page_size=0", "page_size=100000", "page=abc"):
        assert small_scale_client.get(f"/api/refunds?{query}").status_code == 422, query
