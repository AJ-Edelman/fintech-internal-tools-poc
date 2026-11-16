"""AC28: the demo seed gives each KYC reviewer pending customers in their region. AC29: the KYC queue API sorts."""
import sqlite3

import pytest

from app.foundation.db import migrate
from app.seed import seed_demo


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "demo.db")
    migrate(path)
    assert seed_demo(path)
    return path


def queue(client, **params) -> list[int]:
    response = client.get("/api/kyc/queue", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "total", "page", "page_size"}
    assert body["total"] == len(body["items"])
    return [item["id"] for item in body["items"]]


def regions(db_path, ids) -> set[str]:
    with sqlite3.connect(db_path) as sql:
        marks = ", ".join("?" for _ in ids)
        return {r[0] for r in sql.execute(f"SELECT region FROM customer WHERE id IN ({marks})", ids)}


def test_ac28_demo_seed_gives_us_and_eu_kyc_reviewers_pending_customers(db_path, login):
    us = queue(login("kyc1"))
    assert len(us) >= 3 and regions(db_path, us) == {"US"}
    eu = queue(login("kyc2"))
    assert len(eu) >= 1 and regions(db_path, eu) == {"EU"}
    with sqlite3.connect(db_path) as sql:
        pending = {r[0]: r[1] for r in sql.execute("SELECT id, region FROM customer WHERE kyc_status = 'pending'")}
    assert sorted(us) == sorted(i for i, r in pending.items() if r == "US")
    assert sorted(eu) == sorted(i for i, r in pending.items() if r == "EU")


def test_ac29_kyc_queue_api_sorts_by_column_and_direction(db_path, login):
    with sqlite3.connect(db_path) as sql:
        for cid, email in ((13, "e@example.test"), (14, "c@example.test"), (15, "a@example.test"),
                           (16, "d@example.test"), (17, "b@example.test")):
            sql.execute("UPDATE customer SET email = ? WHERE id = ?", (email, cid))
        for cid, name in ((13, "Zed Field"), (14, "Amy Marsh"), (15, "Max Hill"), (16, "Bo Lake"),
                          (17, "Lu Wood")):
            sql.execute("UPDATE customer SET name = ? WHERE id = ?", (name, cid))
    kyc2 = login("kyc2")
    assert queue(kyc2, sort="email", dir="asc") == [15, 17, 14, 16, 13]
    assert queue(kyc2, sort="email", dir="desc") == [13, 16, 14, 17, 15]
    assert queue(kyc2, sort="name", dir="asc") == [14, 16, 17, 15, 13]
    assert queue(kyc2, sort="name", dir="desc") == [13, 15, 17, 16, 14]
    assert queue(kyc2) == [13, 14, 15, 16, 17]
