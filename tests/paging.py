"""Shared paging check used by the small test (make test) and the scale test (make test-scale)."""
from app.seed import scale_status


def expected_ids(total: int, status: str | None) -> list[int]:
    return [i for i in range(1, total + 1) if status is None or scale_status(i) == status]


def check_paging(client, total: int, status: str | None, known_total: int, page_size: int) -> None:
    ids = expected_ids(total, status)
    assert len(ids) == known_total
    last_page = -(-known_total // page_size)
    middle = max(1, last_page // 2)
    query = f"&status={status}" if status else ""
    for page in (1, middle, last_page):
        response = client.get(f"/api/refunds?page={page}&page_size={page_size}{query}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == known_total
        got = [item["id"] for item in body["items"]]
        assert got == ids[(page - 1) * page_size: page * page_size], (status, page)
        assert got == sorted(got) and got
        if status:
            assert {item["status"] for item in body["items"]} == {status}
    beyond = client.get(f"/api/refunds?page={last_page + 1}&page_size={page_size}{query}").json()
    assert beyond["items"] == [] and beyond["total"] == known_total


# --- AC18: shared list search / sort / count, used by the small and the scale tests ---------

import re


def matching(rows: list[dict], fields, q: str) -> list[dict]:
    q = q.lower()
    return [r for r in rows if any(q in str(f(r)).lower() for f in fields)]


def ordered(rows: list[dict], key, direction: str) -> list[int]:
    return [r["id"] for r in sorted(rows, key=lambda r: (key(r), r["id"]), reverse=direction == "desc")]


def check_list(fetch, rows: list[dict], fields, queries, sorts: dict, page_size: int) -> None:
    """fetch(q, sort, dir, page) -> (ids, total). Search returns exactly the matching rows,
    sorting by each column in both directions is correct, and the count matches."""
    assert len(sorts) >= 2
    for q in queries:
        expected = matching(rows, fields, q)
        assert expected, q
        got, page = [], 1
        while True:
            ids, total = fetch(q, "id", "asc", page)
            assert total == len(expected), (q, total, len(expected))
            if not ids:
                break
            got += ids
            page += 1
        assert got == sorted(r["id"] for r in expected), q
    for name, key in sorts.items():
        for direction in ("asc", "desc"):
            want = ordered(rows, key, direction)
            last = -(-len(want) // page_size)
            for page in sorted({1, last}):
                ids, total = fetch("", name, direction, page)
                assert total == len(rows)
                assert ids == want[(page - 1) * page_size: page * page_size], (name, direction, page)


def html_ids(body: str, prefix: str) -> list[int]:
    seen = []
    for m in re.findall(rf'href="{prefix}(\d+)"', body):
        if int(m) not in seen:
            seen.append(int(m))
    return seen


def html_total(body: str) -> int:
    return int(re.search(r"\((\d+) total\)", body).group(1))


def customer_rows(con, where: str = "") -> list[dict]:
    return [dict(r) for r in con.execute(
        f"SELECT id, name, email, ssn, bank_account, kyc_status FROM customer {where}").fetchall()]


def refund_rows(con) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT r.id, r.charge_id, r.amount_cents, r.reason, r.requested_by, r.decided_by, "
        "cu.name AS customer_name FROM refund r JOIN charge ch ON ch.id = r.charge_id "
        "JOIN customer cu ON cu.id = ch.customer_id").fetchall()]


CUSTOMER_FIELDS = (lambda r: r["id"], lambda r: r["name"], lambda r: r["email"],
                   lambda r: r["ssn"][-4:], lambda r: r["bank_account"][-4:])
CUSTOMER_SORTS = {"name": lambda r: r["name"], "email": lambda r: r["email"]}
REFUND_FIELDS = (lambda r: r["id"], lambda r: r["charge_id"], lambda r: r["customer_name"],
                 lambda r: r["requested_by"], lambda r: r["decided_by"] if r["decided_by"] else "\0",
                 lambda r: r["reason"])
REFUND_SORTS = {"amount": lambda r: r["amount_cents"], "customer": lambda r: r["customer_name"]}


def customers_fetch(client, page_size):
    def fetch(q, sort, direction, page):
        body = client.get("/api/customers", params={"q": q, "sort": sort, "dir": direction, "page": page,
                                                    "page_size": page_size}).json()
        return [i["id"] for i in body["items"]], body["total"]
    return fetch


def refunds_fetch(client, page_size):
    def fetch(q, sort, direction, page):
        body = client.get("/api/refunds", params={"q": q, "sort": sort, "dir": direction, "page": page,
                                                  "page_size": page_size}).json()
        return [i["id"] for i in body["items"]], body["total"]
    return fetch


def kyc_fetch(client, page_size):
    def fetch(q, sort, direction, page):
        r = client.get("/kyc/queue", params={"q": q, "sort": sort, "dir": direction, "page": page,
                                             "page_size": page_size, "status": "pending"})
        assert r.status_code == 200, r.text
        return html_ids(r.text, "/kyc/"), html_total(r.text)
    return fetch
