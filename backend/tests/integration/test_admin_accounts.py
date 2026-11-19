"""
The operator screen's API: find an account, see its plan and usage, change
the plan. Operators only; an outage is reported as one, never as "no such
customer".
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.security import create_access_token
from app.main import app
from tests.fake_supabase import FakeSupabase

client = TestClient(app)


def _signup(prefix):
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    res = client.post("/api/v1/auth/signup", json={"email": email, "password": "Password123!", "full_name": prefix.title()})
    assert res.status_code == 200, res.text
    body = res.json()
    return {"id": body["user"]["id"], "email": email, "headers": {"Authorization": f"Bearer {body['access_token']}"}}


@pytest.fixture
def operator(monkeypatch):
    op = _signup("operator")
    monkeypatch.setattr(settings, "ADMIN_EMAILS", op["email"])
    return op


@pytest.fixture(autouse=True)
def _clean_overrides():
    yield
    app.dependency_overrides.pop(get_db, None)


class TestLocalStore:
    def test_lists_newest_accounts_with_their_plan(self, operator):
        customer = _signup("customer")
        client.post("/api/v1/billing/admin/plan", headers=operator["headers"], json={"email": customer["email"], "plan": "pro"})
        res = client.get("/api/v1/billing/admin/accounts", headers=operator["headers"])
        assert res.status_code == 200, res.text
        rows = res.json()["accounts"]
        mine = next(r for r in rows if r["email"] == customer["email"])
        assert mine["plan"] == "pro"
        assert "password_hash" not in mine
        # Newest first.
        stamps = [r["created_at"] for r in rows]
        assert stamps == sorted(stamps, reverse=True)

    def test_search_matches_part_of_an_email_and_treats_wildcards_literally(self, operator):
        a = _signup("find_me")
        _signup("findxme")
        rows = client.get("/api/v1/billing/admin/accounts", params={"q": "find_me"}, headers=operator["headers"]).json()["accounts"]
        emails = {r["email"] for r in rows}
        assert a["email"] in emails
        assert not any(e.startswith("findxme") for e in emails), "_ must not match any character"

    def test_account_detail_includes_this_months_usage(self, operator):
        customer = _signup("detail")
        res = client.get("/api/v1/billing/admin/account", params={"email": customer["email"].upper()}, headers=operator["headers"])
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["user_id"] == customer["id"]
        assert body["usage"]["plan"] == "free"
        assert body["usage"]["used"] == 0

    def test_unknown_email_is_404(self, operator):
        res = client.get("/api/v1/billing/admin/account", params={"email": "nobody-here@example.com"}, headers=operator["headers"])
        assert res.status_code == 404

    def test_customers_cannot_use_it(self, operator):
        customer = _signup("nosy")
        assert client.get("/api/v1/billing/admin/accounts", headers=customer["headers"]).status_code == 403
        assert client.get("/api/v1/billing/admin/account", params={"email": customer["email"]},
                          headers=customer["headers"]).status_code == 403

    def test_me_says_who_is_an_operator(self, operator):
        customer = _signup("plain")
        assert client.get("/api/v1/auth/me", headers=operator["headers"]).json()["is_admin"] is True
        assert client.get("/api/v1/auth/me", headers=customer["headers"]).json()["is_admin"] is False


class TestSupabasePath:
    def _fake(self, operator_email):
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        fake = FakeSupabase({
            "profiles": [
                {"id": a, "email": "old@acme.com", "full_name": "Old", "company": "Acme", "created_at": "2026-10-01T00:00:00+00:00"},
                {"id": b, "email": "new@beta.io", "full_name": "New", "company": "", "created_at": "2026-11-10T00:00:00+00:00"},
            ],
            "subscriptions": [{"user_id": a, "plan": "team"}],
            "usage_events": [],
        })
        app.dependency_overrides[get_db] = lambda: fake
        token = create_access_token({"sub": str(uuid.uuid4()), "email": operator_email})
        return fake, {"Authorization": f"Bearer {token}"}, a, b

    def test_list_and_plans_come_from_supabase(self, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "ops@example.com")
        fake, headers, a, b = self._fake("ops@example.com")
        rows = client.get("/api/v1/billing/admin/accounts", headers=headers).json()["accounts"]
        assert [r["email"] for r in rows] == ["new@beta.io", "old@acme.com"]
        assert {r["email"]: r["plan"] for r in rows} == {"new@beta.io": "free", "old@acme.com": "team"}

    def test_search_filters_in_supabase(self, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "ops@example.com")
        fake, headers, a, b = self._fake("ops@example.com")
        rows = client.get("/api/v1/billing/admin/accounts", params={"q": "ACME"}, headers=headers).json()["accounts"]
        assert [r["email"] for r in rows] == ["old@acme.com"]

    def test_an_outage_is_503_not_no_such_customer(self, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "ops@example.com")
        fake, headers, a, b = self._fake("ops@example.com")
        fake.fail("profiles", "select")
        assert client.get("/api/v1/billing/admin/account", params={"email": "old@acme.com"}, headers=headers).status_code == 503
        assert client.get("/api/v1/billing/admin/accounts", headers=headers).status_code == 503
        res = client.post("/api/v1/billing/admin/plan", headers=headers, json={"email": "old@acme.com", "plan": "pro"})
        assert res.status_code == 503
