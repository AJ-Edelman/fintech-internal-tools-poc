"""One-click demo sign-in is environment-gated and only lists active seed accounts."""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.foundation.auth import create_user
from app.seed import DEMO_PASSWORD, DEMO_USERS


@pytest.fixture
def demo_client(app):
    with app.state.engine.begin() as conn:
        existing = {row.username for row in conn.execute(text("SELECT username FROM app_user"))}
        for username, roles, region in DEMO_USERS:
            if username not in existing:
                create_user(conn, username, DEMO_PASSWORD, roles, region)
    with TestClient(app, follow_redirects=False) as client:
        yield client


def demo_forms(html):
    forms = {}
    for body in re.findall(r'<form\b[^>]*data-demo-login[^>]*>(.*?)</form>', html, re.S):
        fields = {
            name: value
            for name, value in re.findall(r'<input\b[^>]*name="([^"]+)"[^>]*value="([^"]*)"', body)
        }
        forms[fields["username"]] = fields
    return forms


def test_flag_off_lists_accounts_without_one_click_login(monkeypatch, demo_client):
    monkeypatch.delenv("LEDGERLINE_DEMO_LOGIN", raising=False)
    response = demo_client.get("/login")
    assert response.status_code == 200
    assert "data-demo-login" not in response.text
    assert 'value="demo"' not in response.text
    for username in ("approver2", "kyc2", "limits1", "limits2"):
        assert username in response.text

    assert demo_client.post(
        "/login", data={"username": "agent1", "password": DEMO_PASSWORD, "next": "/refunds"}
    ).status_code == 303
    assert "Switch user" not in demo_client.get("/refunds").text


def test_flag_on_offers_grouped_sign_in_and_switch_user(monkeypatch, demo_client):
    monkeypatch.setenv("LEDGERLINE_DEMO_LOGIN", "1")
    response = demo_client.get("/login", params={"next": "/kyc/queue"})
    assert response.status_code == 200
    forms = demo_forms(response.text)
    assert len(forms) == 9
    assert set(forms) == {username for username, _roles, _region in DEMO_USERS}
    assert all(
        fields == {"username": username, "password": DEMO_PASSWORD, "next": "/kyc/queue"}
        for username, fields in forms.items()
    )
    failed_login = demo_client.post("/login", data={"username": "missing", "password": "wrong"})
    assert failed_login.status_code == 401
    assert len(demo_forms(failed_login.text)) == 9

    groups = re.findall(
        r'<section class="demo-group">\s*<h2>(.*?)</h2>(.*?)</section>',
        response.text,
        re.S,
    )
    assert [label for label, _body in groups] == [
        "Refunds", "KYC review", "Account limits", "Admin"
    ]
    for label, expected_users in (
        ("Refunds", ("agent1", "agent2", "approver1", "approver2")),
        ("KYC review", ("kyc1", "kyc2")),
        ("Account limits", ("limits1", "limits2")),
        ("Admin", ("admin1",)),
    ):
        body = dict(groups)[label]
        assert all(f'value="{username}"' in body for username in expected_users)

    assert demo_client.post("/login", data=forms["kyc2"]).status_code == 303
    kyc_page = demo_client.get("/kyc/queue")
    assert kyc_page.status_code == 200
    assert "KYC queue" in kyc_page.text
    assert "Switch user" in kyc_page.text

    logout = demo_client.post("/logout")
    assert logout.status_code == 303 and logout.headers["location"] == "/login"
    assert demo_client.get("/login").status_code == 200

    limits_form = demo_forms(demo_client.get("/login", params={"next": "/limits/new"}).text)["limits1"]
    assert demo_client.post("/login", data=limits_form).status_code == 303
    limits_page = demo_client.get("/limits/new")
    assert limits_page.status_code == 200
    assert "Request limit" in limits_page.text


def test_flag_on_omits_deactivated_seed_user(monkeypatch, demo_client, sql):
    monkeypatch.setenv("LEDGERLINE_DEMO_LOGIN", "1")
    sql.execute("UPDATE app_user SET active = 0 WHERE username = 'limits1'")

    response = demo_client.get("/login")
    forms = demo_forms(response.text)
    assert len(forms) == 8
    assert "limits1" not in forms
    account_limits = re.search(
        r'<section class="demo-group">\s*<h2>Account limits</h2>(.*?)</section>',
        response.text,
        re.S,
    ).group(1)
    assert 'name="limits1"' not in account_limits
