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
