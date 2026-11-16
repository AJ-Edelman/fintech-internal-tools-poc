"""Product feedback 5 and 8: every list is searched, filtered, sorted and paged on the server."""
import re

import pytest

from .conftest import BANK_1, SSN_1, SSN_2, request_refund

NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"


def ids(body) -> list:
    return [item["id"] for item in body["items"]]


def get(client, url):
    response = client.get(url)
    assert response.status_code == 200, (url, response.text)
    return response.json()


def visible(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", " ", html)))


def order(html: str, *needles: str) -> list[str]:
    """The needles in the order they first appear inside the table body."""
    body = html[html.index("<tbody>"):html.index("</tbody>")]
    return [n for _, n in sorted((body.index(n), n) for n in needles if n in body)]


@pytest.fixture
def many(sql):
    """37 more customers (ids 4-40) with one charge each (ids 9-45) of rising amounts."""
    for i in range(4, 41):
        status = ("pending", "approved", "rejected")[i % 3]
        sql.execute("INSERT INTO customer (id, name, email, ssn, bank_account, kyc_status) VALUES (?, ?, ?, ?, ?, ?)",
                    (i, f"Cust {i:03d}", f"c{i}@bulk.test", f"900-55-{1000 + i}", f"70001234{1000 + i}", status))
        sql.execute(f"INSERT INTO charge (id, customer_id, amount_cents, created_at) VALUES (?, ?, ?, {NOW})",
                    (i + 5, i, i * 100))
    return sql


# --- customers ------------------------------------------------------------------------

def test_customers_search_filter_sort(login):
    agent = login("agent1")
    assert ids(get(agent, "/api/customers")) == [1, 2, 3]
    assert ids(get(agent, "/api/customers?q=riv")) == [2]  # case-insensitive, substring of the name
    assert ids(get(agent, "/api/customers?q=CLEO@example")) == [3]
    assert ids(get(agent, "/api/customers?q=3456")) == [1]  # last four of the SSN or account
    assert ids(get(agent, "/api/customers?q=nobody")) == []
    assert get(agent, "/api/customers?q=nobody")["total"] == 0
    assert ids(get(agent, "/api/customers?kyc_status=approved")) == [1]
    assert ids(get(agent, "/api/customers?kyc_status=pending&q=ada")) == []
    assert ids(get(agent, "/api/customers?sort=name&dir=desc")) == [3, 2, 1]
    assert ids(get(agent, "/api/customers?sort=kyc_status&dir=asc")) == [1, 2, 3]
    assert ids(get(agent, "/api/customers?sort=email&dir=desc")) == [3, 2, 1]


def test_customers_search_cannot_probe_full_ssn_or_account(login):
    agent = login("agent1")
    for probe in (SSN_1, "900-12", "900", BANK_1, "40001234", "12-3456"):
        body = get(agent, f"/api/customers?q={probe}")
        assert body["total"] == 0 and body["items"] == [], probe
    text_ = agent.get("/api/customers?q=3456").text
    assert SSN_1 not in text_ and BANK_1 not in text_ and "***-**-3456" in text_


def test_search_treats_like_wildcards_literally(login, sql):
    agent = login("agent1")
    for probe in ("%25", "_", "a%25e", "A_a"):
        assert get(agent, f"/api/customers?q={probe}")["total"] == 0, probe
    sql.execute("UPDATE customer SET name = '100% Real_Name' WHERE id = 2")
    assert ids(get(agent, "/api/customers?q=0%25 R")) == [2]
    assert ids(get(agent, "/api/customers?q=l_N")) == [2]
    assert get(agent, "/api/customers?q=' OR 1=1 --")["total"] == 0


@pytest.mark.parametrize("url", [
    "/api/customers?sort=ssn", "/api/customers?sort=id;drop table customer", "/api/customers?dir=sideways",
    "/api/customers?kyc_status=maybe", "/api/customers?page=0", "/api/customers?page_size=0",
    "/api/customers?page_size=201", "/api/charges?sort=secret", "/api/charges?kyc_status=x",
    "/api/charges?dir=up", "/api/refunds?sort=reason", "/api/refunds?status=done", "/api/refunds?dir=x",
    "/customers?sort=bank_account", "/charges?sort=nope", "/refunds?sort=nope", "/refunds/new?sort=nope",
    "/customers?page=0", "/customers/1?sort=nope",
])
def test_bad_list_parameters_are_422_for_agents(login, url):
    assert login("agent1").get(url).status_code == 422, url


@pytest.mark.parametrize("url", [
    "/api/users?sort=password_hash", "/api/users?role=root", "/api/users?status=gone", "/api/users?dir=x",
    "/admin/access-review?sort=nope", "/admin/audit?sort=nope", "/admin/audit?date_from=yesterday",
    "/admin/audit?page_size=501",
])
def test_bad_list_parameters_are_422_for_admins(login, url):
    assert login("admin1").get(url).status_code == 422, url


def test_customers_paging_totals(login, many):
    agent = login("agent1")
    seen = []
    for page in (1, 2, 3, 4):
        body = get(agent, f"/api/customers?page={page}&page_size=12")
        assert (body["total"], body["pages"], body["page"], body["page_size"]) == (40, 4, page, 12)
        seen += ids(body)
    assert seen == list(range(1, 41))
    beyond = get(agent, "/api/customers?page=5&page_size=12")
    assert beyond["items"] == [] and beyond["total"] == 40
    filtered = get(agent, "/api/customers?kyc_status=approved&q=Cust&sort=name&dir=desc&page=2&page_size=5")
    expected = sorted((i for i in range(4, 41) if i % 3 == 1), reverse=True)
    assert filtered["total"] == len(expected) and ids(filtered) == expected[5:10]
    assert {i["kyc_status"] for i in filtered["items"]} == {"approved"}


def test_customers_page_is_rendered_from_the_server_side_result(login, many):
    agent = login("agent1")
    html = agent.get("/customers?sort=name&dir=desc&page_size=3").text
    assert order(html, "Cust 040", "Cust 039", "Cust 038", "Ada Stone") == ["Cust 040", "Cust 039", "Cust 038"]
    assert "Page 1 of 14 (40 total)" in visible(html)
    html = agent.get("/customers?q=Cust 01&page=2&page_size=4").text
    assert order(html, *[f"Cust {i:03d}" for i in range(4, 41)]) == ["Cust 014", "Cust 015", "Cust 016", "Cust 017"]
    assert "Page 2 of 3 (10 total)" in visible(html)
    html = agent.get("/customers?kyc_status=rejected&page_size=200").text
    assert "Cleo Field" in html and "Ada Stone" not in html and "Ben Rivers" not in html
    assert 'name="q"' in html and "sort=name" in html and "sort=email" in html and "sort=kyc_status" in html
    assert SSN_1 not in html and SSN_2 not in html


# --- charges (feedback 5) -------------------------------------------------------------

def test_charges_search_filter_sort(login, sql):
    agent = login("agent1")
    for charge, amount in ((1, 5000), (2, 900000), (7, 100), (8, 30000)):
        sql.execute("UPDATE charge SET amount_cents = ? WHERE id = ?", (amount, charge))
    assert ids(get(agent, "/api/charges")) == [1, 2, 3, 4, 5, 6, 7, 8]
    assert ids(get(agent, "/api/charges?sort=amount&dir=asc"))[:3] == [7, 1, 8]
    assert ids(get(agent, "/api/charges?sort=amount&dir=desc"))[0] == 2
    assert ids(get(agent, "/api/charges?q=rivers")) == [7]
    assert ids(get(agent, "/api/charges?q=cleo@example.test")) == [8]
    assert ids(get(agent, "/api/charges?q=8")) == [8]
    assert ids(get(agent, "/api/charges?customer_id=1")) == [1, 2, 3, 4, 5, 6]
    assert ids(get(agent, "/api/charges?customer_id=1&q=ben")) == []
    assert ids(get(agent, "/api/charges?kyc_status=pending")) == [7]
    assert ids(get(agent, "/api/charges?kyc_status=rejected")) == [8]
    assert get(agent, "/api/charges?kyc_status=approved")["total"] == 6
    assert ids(get(agent, "/api/charges?sort=customer&dir=desc"))[:2] == [8, 7]
    assert ids(get(agent, "/api/charges?sort=id&dir=desc&page=2&page_size=3")) == [5, 4, 3]


def test_charges_refundable_filter_and_remaining_follow_refunds(login, sql):
    agent, approver = login("agent1"), login("approver1")
    assert request_refund(agent, charge_id=1, amount_cents=200000).status_code == 201  # pending, whole charge
    assert request_refund(agent, charge_id=2, amount_cents=30000).status_code == 201  # auto-approved
    rejected = request_refund(agent, charge_id=3, amount_cents=200000).json()["id"]
    assert approver.post(f"/api/refunds/{rejected}/reject", json={"reason": "Insufficient evidence"}).status_code == 200
    everything = {c["id"]: c for c in get(agent, "/api/charges")["items"]}
    assert (everything[1]["committed_cents"], everything[1]["remaining_cents"]) == (200000, 0)
    assert (everything[2]["committed_cents"], everything[2]["remaining_cents"]) == (30000, 170000)
    assert (everything[3]["committed_cents"], everything[3]["remaining_cents"]) == (0, 200000)  # rejected frees it
    refundable = get(agent, "/api/charges?refundable=true")
    assert ids(refundable) == [2, 3, 4, 5, 6, 7, 8] and refundable["total"] == 7
    assert ids(get(agent, "/api/charges?sort=remaining&dir=asc"))[:2] == [1, 2]
    assert ids(get(agent, "/api/charges?sort=refunded&dir=desc"))[:2] == [1, 2]
    html = agent.get("/charges?show=refundable&sort=id&dir=asc").text
    assert "Page 1 of 1 (7 total)" in visible(html)
    assert 'href="/refunds/new?charge_id=2"' in html and 'href="/refunds/new?charge_id=1"' not in html
    assert "Page 1 of 1 (8 total)" in visible(agent.get("/charges").text)


def test_charges_paging_totals(login, many):
    agent = login("agent1")
    body = get(agent, "/api/charges?sort=amount&dir=asc&page=2&page_size=10")
    assert (body["total"], body["pages"]) == (45, 5)
    assert ids(body) == list(range(19, 29))  # charges 9..45 hold 400..4000 cents, so page 2 is ids 19..28
    assert [c["amount_cents"] for c in body["items"]] == sorted(c["amount_cents"] for c in body["items"])
    assert ids(get(agent, "/api/charges?q=Cust 02&sort=id&dir=asc&page_size=4&page=3")) == [33, 34]
    assert get(agent, "/api/charges?q=Cust 02")["total"] == 10


def test_charge_picker_is_a_searchable_sortable_table_not_a_dropdown(login, many):
    agent = login("agent1")
    html = agent.get("/refunds/new").text
    assert '<select name="charge_id"' not in html and "<option" not in html
    assert 'type="search"' in html and 'name="q"' in html
    for key in ("id", "customer", "created_at", "amount", "refunded", "remaining", "kyc_status"):
        assert f"sort={key}" in html, key
    assert "Page 1 of 2 (45 total)" in visible(html)  # 25 per page, not one endless list
    # 25 rows; since the UI polish, rows whose customer is not KYC-approved show the reason, not a button.
    assert html.count('href="/refunds/new?charge_id=') + html.count('small muted">KYC ') == 25
    found = agent.get("/refunds/new?q=Cust 019").text
    assert "Page 1 of 1 (1 total)" in visible(found)
    assert found.count('href="/refunds/new?charge_id=') == 1 and 'href="/refunds/new?charge_id=24"' in found
    by_amount = agent.get("/refunds/new?sort=amount&dir=desc&page_size=3").text
    assert order(by_amount, "#8<", "#7<", "#6<", "#45<") == ["#8<", "#7<", "#6<"]  # equal amounts break on id
    assert "$2,000.00" in by_amount


def test_charge_picker_hides_charges_with_nothing_left_unless_asked(login):
    agent = login("agent1")
    request_refund(agent, charge_id=1, amount_cents=200000)
    assert 'href="/refunds/new?charge_id=1"' not in agent.get("/refunds/new").text
    assert "Page 1 of 1 (7 total)" in visible(agent.get("/refunds/new").text)
    assert "Page 1 of 1 (8 total)" in visible(agent.get("/refunds/new?show=all").text)


def test_customer_detail_charges_are_listed_with_search_and_paging(login):
    agent = login("agent1")
    html = agent.get("/customers/1?sort=id&dir=desc&page_size=4").text
    assert "(6 total)" in visible(html) and "Page 1 of 2" in visible(html)
    assert agent.get("/customers/1?q=7").status_code == 200
    assert "(0 total)" in visible(agent.get("/customers/1?q=7").text)  # charge 7 belongs to another customer


# --- refunds --------------------------------------------------------------------------

@pytest.fixture
def refunds(login):
    """1: agent1 pending 750 on charge 1; 2: agent2 auto-approved 20 on charge 2; 3: agent1 rejected 900 on
    charge 3; 4: agent2 approved 800 on charge 4; 5: agent2 pending 1,000 on charge 5."""
    a1, a2, approver = login("agent1"), login("agent2"), login("approver1")
    assert request_refund(a1, 1, 75000, "Duplicate charge").json()["status"] == "pending_approval"
    assert request_refund(a2, 2, 2000, "Goodwill gesture").json()["status"] == "approved"
    assert request_refund(a1, 3, 90000, "parcel never arrived").status_code == 201
    assert request_refund(a2, 4, 80000, "Billing error or wrong amount").status_code == 201
    assert request_refund(a2, 5, 100000, "Duplicate charge").status_code == 201
    assert approver.post("/api/refunds/3/reject", json={"reason": "Insufficient evidence"}).status_code == 200
    assert approver.post("/api/refunds/4/approve", json={"reason": "Matches refund policy"}).status_code == 200
    return approver


def test_refunds_search_filter_sort_page(refunds):
    client = refunds
    assert ids(get(client, "/api/refunds")) == [1, 2, 3, 4, 5]
    assert ids(get(client, "/api/refunds?status=pending_approval")) == [1, 5]
    assert ids(get(client, "/api/refunds?status=approved")) == [2, 4]
    assert ids(get(client, "/api/refunds?status=rejected")) == [3]
    assert ids(get(client, "/api/refunds?q=agent2")) == [2, 4, 5]
    assert ids(get(client, "/api/refunds?q=PARCEL")) == [3]
    assert ids(get(client, "/api/refunds?q=duplicate&status=pending_approval")) == [1, 5]
    assert ids(get(client, "/api/refunds?q=system")) == [2]  # decided_by of the automatic approval
    assert ids(get(client, "/api/refunds?q=approver1")) == [3, 4]
    assert ids(get(client, "/api/refunds?sort=amount&dir=desc")) == [5, 3, 4, 1, 2]
    assert ids(get(client, "/api/refunds?sort=amount&dir=asc&status=approved")) == [2, 4]
    assert ids(get(client, "/api/refunds?sort=requested_by&dir=desc")) == [5, 4, 2, 3, 1]
    assert ids(get(client, "/api/refunds?sort=status&dir=asc")) == [2, 4, 1, 5, 3]
    paged = get(client, "/api/refunds?sort=amount&dir=desc&page=2&page_size=2")
    assert ids(paged) == [4, 1] and (paged["total"], paged["pages"]) == (5, 3)
    assert get(client, "/api/refunds?q=agent2&page=2&page_size=2")["total"] == 3
    assert ids(get(client, "/api/refunds?q=agent2&page=2&page_size=2")) == [5]
    assert get(client, "/api/refunds?q=zzz") | {"items": [], "total": 0} == get(client, "/api/refunds?q=zzz")


def test_refunds_page_and_queue_page_use_the_server_result(refunds):
    client = refunds
    html = client.get("/refunds?status=approved&sort=amount&dir=desc").text
    assert order(html, "$800.00", "$20.00", "$750.00", "$1,000.00") == ["$800.00", "$20.00"]
    assert "Page 1 of 1 (2 total)" in visible(html)
    html = client.get("/refunds?q=agent1&page_size=1&page=2").text
    assert "Page 2 of 2 (2 total)" in visible(html) and 'href="/refunds/3"' in html and 'href="/refunds/1"' not in html
    queue = client.get("/refunds/queue?sort=amount&dir=desc").text
    assert order(queue, 'href="/refunds/5"', 'href="/refunds/1"') == ['href="/refunds/5"', 'href="/refunds/1"']
    assert 'href="/refunds/2"' not in queue and 'href="/refunds/3"' not in queue and 'href="/refunds/4"' not in queue
    assert "Page 1 of 1 (2 total)" in visible(queue)
    searched = client.get("/refunds/queue?q=agent2").text
    assert 'href="/refunds/5"' in searched and 'href="/refunds/1"' not in searched
    assert "Page 1 of 1 (1 total)" in visible(searched)
    for key in ("id", "customer", "amount", "requested_by", "created_at"):
        assert f"sort={key}" in queue, key


# --- KYC queue ------------------------------------------------------------------------

def test_kyc_queue_page_filters_searches_sorts_and_pages(login, many):
    kyc = login("kyc1")
    pending = [2] + [i for i in range(4, 41) if i % 3 == 0]
    html = kyc.get("/kyc/queue?page_size=200").text
    assert f"({len(pending)} total)" in visible(html)
    assert html.count('/decision"') == len(pending)
    assert "Ada Stone" not in html and "Cleo Field" not in html and "Ben Rivers" in html
    everyone = kyc.get("/kyc/queue?status=all&page_size=200").text
    assert "(40 total)" in visible(everyone) and "Ada Stone" in everyone
    assert everyone.count('/decision"') == len(pending)  # only pending rows can be decided
    rejected = kyc.get("/kyc/queue?status=rejected&sort=name&dir=desc&page_size=2").text
    assert order(rejected, "Cust 038", "Cust 035", "Cleo Field") == ["Cust 038", "Cust 035"]
    found = kyc.get("/kyc/queue?q=ben@example").text
    assert "(1 total)" in visible(found) and 'action="/kyc/2/decision"' in found
    assert "(0 total)" in visible(kyc.get("/kyc/queue?q=ada").text)  # Ada is approved, not in the pending view
    page2 = kyc.get("/kyc/queue?page=2&page_size=5&sort=id&dir=asc").text
    assert [int(m) for m in re.findall(r'action="/kyc/(\d+)/decision"', page2)] == pending[5:10]
    assert kyc.get("/kyc/queue?status=bogus").status_code == 422
    assert SSN_1 not in everyone and SSN_2 not in everyone and "***-**-" in everyone


# --- users ----------------------------------------------------------------------------

def test_users_search_filter_sort_page(login, sql):
    admin = login("admin1")
    names = lambda url: [u["username"] for u in get(admin, url)["items"]]  # noqa: E731
    assert names("/api/users") == ["admin1", "agent1", "agent2", "approver1", "kyc1"]
    assert names("/api/users?sort=username&dir=desc") == ["kyc1", "approver1", "agent2", "agent1", "admin1"]
    assert names("/api/users?q=agent") == ["agent1", "agent2"]
    assert names("/api/users?q=kyc_reviewer") == ["kyc1"]  # search covers the role too
    assert names("/api/users?role=refund_agent") == ["agent1", "agent2"]
    assert names("/api/users?role=admin") == ["admin1"]
    assert names("/api/users?role=refund_agent&q=2") == ["agent2"]
    assert names("/api/users?status=inactive") == []
    assert admin.put(f"/api/users/{sql.execute('SELECT id FROM app_user WHERE username = ?', ('agent2',)).fetchone()[0]}"
                     "/active", json={"active": False}).status_code == 200
    assert names("/api/users?status=inactive") == ["agent2"]
    assert names("/api/users?status=active&role=refund_agent") == ["agent1"]
    assert names("/api/users?sort=status&dir=asc")[0] == "agent2"
    body = get(admin, "/api/users?page=2&page_size=2")
    assert [u["username"] for u in body["items"]] == ["agent2", "approver1"]
    assert (body["total"], body["pages"]) == (5, 3)
    assert get(admin, "/api/users?page=4&page_size=2")["items"] == []
    html = admin.get("/admin/access-review?role=refund_agent&sort=username&dir=desc").text
    assert order(html, ">agent2<", ">agent1<", ">kyc1<") == [">agent2<", ">agent1<"]
    assert "Page 1 of 1 (2 total)" in visible(html)
    assert "(1 total)" in visible(admin.get("/admin/access-review?q=approver").text)


# --- audit log ------------------------------------------------------------------------

def test_audit_search_filter_sort_page(refunds, login):
    admin = login("admin1")
    assert admin.put("/api/settings/session_timeout_minutes", json={"value": 45}).status_code == 200
    total = get(admin, "/api/audit?entity=refund")["total"]
    assert total == 8  # five requests, one automatic approval, one reject, one approve
    assert get(admin, "/api/audit?actor=agent2")["total"] == 3
    assert get(admin, "/api/audit?action=refund.reject")["total"] == 1
    assert get(admin, "/api/audit?actor=system&entity=refund")["items"][0]["action"] == "refund.auto_approve"
    assert get(admin, "/api/audit?q=parcel")["total"] == 1
    assert get(admin, "/api/audit?q=Insufficient evidence")["items"][0]["actor"] == "approver1"
    assert get(admin, "/api/audit?actor=admin1&action=setting.change")["total"] == 1
    paged = get(admin, "/api/audit?entity=refund&limit=3&offset=3")
    assert len(paged["items"]) == 3 and paged["total"] == 8
    newest_first = [e["id"] for e in get(admin, "/api/audit?entity=refund&limit=500")["items"]]
    assert newest_first == sorted(newest_first, reverse=True)
    assert [e["id"] for e in paged["items"]] == newest_first[3:6]

    html = admin.get("/admin/audit?actor=agent1").text
    assert "(2 total)" in visible(html)
    html = admin.get("/admin/audit?entity=refund&sort=actor&dir=asc&page_size=3&page=3").text
    assert "Page 3 of 3 (8 total)" in visible(html)
    assert "(1 total)" in visible(admin.get("/admin/audit?q=parcel").text)
    # 9 business events plus 2 payout delivery attempts (BUILD_SPEC_2 connections).
    assert "(11 total)" in visible(admin.get("/admin/audit?date_from=2000-01-01&date_to=2999-12-31").text)
    assert "(0 total)" in visible(admin.get("/admin/audit?date_to=2000-01-01").text)
    assert "(0 total)" in visible(admin.get("/admin/audit?action=refund.reject&actor=agent1").text)


# --- permissions on the lists ---------------------------------------------------------

LISTS = {
    "/api/customers": {"agent1", "approver1", "kyc1"},
    "/api/charges": {"agent1", "approver1", "kyc1"},
    "/customers": {"agent1", "approver1", "kyc1"},
    "/charges": {"agent1", "approver1", "kyc1"},
    "/api/refunds": {"agent1", "approver1"},
    "/refunds": {"agent1", "approver1"},
    "/refunds/new": {"agent1"},
    "/refunds/queue": {"approver1"},
    "/kyc/queue": {"kyc1"},
    "/api/kyc/queue": {"kyc1"},
    "/api/users": {"admin1"},
    "/admin/access-review": {"admin1"},
    "/api/audit": {"admin1"},
    "/admin/audit": {"admin1"},
}


@pytest.mark.parametrize("username", ["agent1", "approver1", "kyc1", "admin1"])
def test_each_list_is_open_only_to_the_right_roles(login, username):
    client = login(username)
    for path, allowed in LISTS.items():
        status = client.get(path + "?q=a&page=1").status_code
        assert status == (200 if username in allowed else 403), (username, path, status)


def test_lists_without_a_session(anon):
    for path in LISTS:
        response = anon.get(path + "?q=a")
        if path.startswith("/api/"):
            assert response.status_code == 401, path
        else:
            assert response.status_code == 303 and response.headers["location"].startswith("/login?next="), path
