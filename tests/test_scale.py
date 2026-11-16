"""AC11 on the scale database. Runs only when SCALE_DB points at one (`make test-scale`)."""
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.seed import SCALE_TOTAL, scale_counts
from tests.paging import check_paging

SCALE_DB = os.environ.get("SCALE_DB")
pytestmark = pytest.mark.skipif(
    not SCALE_DB or not os.path.exists(SCALE_DB),
    reason="scale database not built; run `make seed-scale` then `make test-scale`",
)


@pytest.fixture(scope="module")
def scale_client(tmp_path_factory):
    # Work on a copy: logging in writes a session row, and tests must not change ./data/.
    path = str(tmp_path_factory.mktemp("scale") / "scale-copy.db")
    shutil.copy(SCALE_DB, path)
    app = create_app(path)
    with TestClient(app) as client:
        assert client.post("/api/login", json={"username": "agent1", "password": "demo"}).status_code == 200
        yield client
    app.state.engine.dispose()


def test_ac11_scale_paging_with_status_filter(scale_client):
    counts = scale_counts(SCALE_TOTAL)
    assert counts == {"approved": 30000, "pending_approval": 12500, "rejected": 7500}
    for status in ("approved", "pending_approval"):
        assert counts[status] > 10000
    for status, known_total in counts.items():
        check_paging(scale_client, SCALE_TOTAL, status, known_total, page_size=50)
    check_paging(scale_client, SCALE_TOTAL, None, SCALE_TOTAL, page_size=200)


# --- AC18 at scale: customers, refunds and KYC lists over 50,000 rows -----------------------

import sqlite3

from tests.paging import (CUSTOMER_FIELDS, CUSTOMER_SORTS, REFUND_FIELDS, REFUND_SORTS, check_list,
                          customer_rows, customers_fetch, kyc_fetch, refund_rows, refunds_fetch)


@pytest.fixture(scope="module")
def scale_lists(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("scale-lists") / "scale-lists.db")
    shutil.copy(SCALE_DB, path)
    con = sqlite3.connect(path)
    con.executemany(
        "INSERT INTO customer (name, email, ssn, bank_account, kyc_status) VALUES (?, ?, ?, ?, ?)",
        ((f"Scale {n % 97} Person{n}", f"p{(n * 7919) % 50021}@example.test",
          f"900-{n % 90 + 10:02d}-{n % 10000:04d}", f"41{n:08d}", ("pending", "approved", "rejected")[n % 3])
         for n in range(1, 50_001)))
    con.commit()
    con.row_factory = sqlite3.Row
    app = create_app(path)
    clients = {}
    for username in ("agent1", "kyc1"):
        c = TestClient(app)
        assert c.post("/api/login", json={"username": username, "password": "demo"}).status_code == 200
        clients[username] = c
    yield con, clients
    for c in clients.values():
        c.close()
    con.close()
    app.state.engine.dispose()


def test_ac18_scale_customers_list(scale_lists):
    con, clients = scale_lists
    rows = customer_rows(con)
    assert len(rows) >= 50_000
    check_list(customers_fetch(clients["agent1"], 200), rows, CUSTOMER_FIELDS,
               ["Person4999", "p1234@"], CUSTOMER_SORTS, 200)


def test_ac18_scale_refunds_list(scale_lists):
    con, clients = scale_lists
    rows = refund_rows(con)
    assert len(rows) == SCALE_TOTAL
    check_list(refunds_fetch(clients["agent1"], 200), rows, REFUND_FIELDS, ["4999"], REFUND_SORTS, 200)


def test_ac18_scale_kyc_queue(scale_lists):
    con, clients = scale_lists
    rows = customer_rows(con, "WHERE kyc_status = 'pending'")
    assert len(rows) > 10_000
    check_list(kyc_fetch(clients["kyc1"], 200), rows, CUSTOMER_FIELDS, ["Person1234"], CUSTOMER_SORTS, 200)
