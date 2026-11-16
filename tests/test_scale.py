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
