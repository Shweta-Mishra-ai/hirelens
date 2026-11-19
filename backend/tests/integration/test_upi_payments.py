"""
UPI payments verified by an operator: a customer claims a payment with its
transaction reference, an operator approves or rejects it, and approval
grants the plan for a period that then lapses back to free.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core import local_db
from app.core.config import settings
from app.core.dependencies import get_db
from app.core.security import create_access_token
from app.main import app
from app.services import billing
from tests.fake_supabase import FakeSupabase

client = TestClient(app)


def _signup(prefix="payer"):
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    res = client.post("/api/v1/auth/signup", json={"email": email, "password": "Password123!", "full_name": "Pay Er"})
    assert res.status_code == 200, res.text
    body = res.json()
    return {"id": body["user"]["id"], "email": email, "headers": {"Authorization": f"Bearer {body['access_token']}"}}


def _ref():
    return str(uuid.uuid4().int)[:12]


@pytest.fixture
def upi(monkeypatch):
    monkeypatch.setattr(settings, "PAYMENT_UPI_ID", "hirelens@okbank")
    monkeypatch.setattr(settings, "PAYMENT_PAYEE_NAME", "HireLens")
    monkeypatch.setattr(settings, "PRO_PRICE_INR", 499)
    monkeypatch.setattr(settings, "TEAM_PRICE_INR", 0)
    monkeypatch.setattr(settings, "PLAN_PERIOD_DAYS", 30)
    monkeypatch.setattr(settings, "UPGRADE_URL", "")


@pytest.fixture
def operator(monkeypatch):
    op = _signup("op")
    monkeypatch.setattr(settings, "ADMIN_EMAILS", op["email"])
    return op


@pytest.fixture(autouse=True)
def _clean():
    yield
    app.dependency_overrides.pop(get_db, None)


def _claim(user, ref=None, plan="pro"):
    reference = _ref() if ref is None else ref
    return client.post("/api/v1/billing/payments", json={"plan": plan, "reference": reference}, headers=user["headers"])


def _pending_for(operator, email):
    rows = client.get("/api/v1/billing/admin/payments", headers=operator["headers"]).json()["payments"]
    return [r for r in rows if r["email"] == email]


class TestOffer:
    def test_nothing_is_for_sale_without_a_upi_id(self, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_UPI_ID", "")
        monkeypatch.setattr(settings, "PRO_PRICE_INR", 499)
        monkeypatch.setattr(settings, "UPGRADE_URL", "")
        user = _signup()
        body = client.get("/api/v1/billing/plans", headers=user["headers"]).json()
        assert body["plans"] == [] and body["upi_id"] is None
        assert body["usage"]["upgrade_url"] is None
        assert _claim(user).status_code == 422

    def test_only_priced_plans_are_offered_and_upgrade_points_in_app(self, upi):
        user = _signup()
        body = client.get("/api/v1/billing/plans", headers=user["headers"]).json()
        assert [p["plan"] for p in body["plans"]] == ["pro"]
        assert body["plans"][0]["price_inr"] == 499
        assert body["upi_id"] == "hirelens@okbank"
        assert body["usage"]["upgrade_url"] == "/upgrade"
        assert _claim(user, plan="team").status_code == 422

    def test_an_operator_link_still_wins(self, upi, monkeypatch):
        monkeypatch.setattr(settings, "UPGRADE_URL", "https://pay.example.com")
        user = _signup()
        assert client.get("/api/v1/billing/usage", headers=user["headers"]).json()["upgrade_url"] == "https://pay.example.com"


class TestClaim:
    def test_a_claim_is_recorded_as_pending_with_the_plan_price(self, upi):
        user = _signup()
        res = _claim(user, ref="4021 5678 9012")
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["status"] == "pending" and body["amount_inr"] == 499
        assert body["reference"] == "402156789012"  # spaces removed
        mine = client.get("/api/v1/billing/payments", headers=user["headers"]).json()["payments"]
        assert [m["id"] for m in mine] == [body["id"]]

    @pytest.mark.parametrize("ref", ["", "12345", "abc$%^123456", "x" * 40])
    def test_a_malformed_reference_is_refused(self, upi, ref):
        user = _signup()
        assert _claim(user, ref=ref).status_code == 422

    def test_one_waiting_claim_per_account(self, upi):
        user = _signup()
        assert _claim(user).status_code == 201
        res = _claim(user)
        assert res.status_code == 409
        assert "waiting" in res.json()["message"]

    def test_a_reference_cannot_be_claimed_twice(self, upi):
        a, b = _signup(), _signup()
        ref = _ref()
        assert _claim(a, ref=ref).status_code == 201
        res = _claim(b, ref=ref)
        assert res.status_code == 409
        assert "already been submitted" in res.json()["message"]

    def test_a_rejected_reference_can_be_resubmitted(self, upi, operator):
        user = _signup()
        ref = _ref()
        pid = _claim(user, ref=ref).json()["id"]
        assert client.post(f"/api/v1/billing/admin/payments/{pid}/reject", json={"note": "Not in statement"},
                           headers=operator["headers"]).status_code == 200
        mine = client.get("/api/v1/billing/payments", headers=user["headers"]).json()["payments"]
        assert mine[0]["status"] == "rejected" and mine[0]["note"] == "Not in statement"
        assert _claim(user, ref=ref).status_code == 201

    def test_claims_are_rate_limited(self, upi):
        user = _signup()
        codes = [_claim(user, ref="bad").status_code for _ in range(11)]
        assert codes[:10] == [422] * 10
        assert codes[10] == 429


class TestApproval:
    def test_approval_grants_the_plan_for_the_period(self, upi, operator):
        user = _signup()
        pid = _claim(user).json()["id"]
        pending = _pending_for(operator, user["email"])
        assert [p["id"] for p in pending] == [pid]
        res = client.post(f"/api/v1/billing/admin/payments/{pid}/approve", headers=operator["headers"])
        assert res.status_code == 200, res.text
        usage = client.get("/api/v1/billing/usage", headers=user["headers"]).json()
        assert usage["plan"] == "pro"
        ends = datetime.fromisoformat(usage["plan_expires_at"])
        assert timedelta(days=29, hours=23) < ends - datetime.now(timezone.utc) <= timedelta(days=30)
        assert client.get("/api/v1/billing/payments", headers=user["headers"]).json()["payments"][0]["status"] == "approved"

    def test_a_claim_is_decided_once(self, upi, operator):
        user = _signup()
        pid = _claim(user).json()["id"]
        assert client.post(f"/api/v1/billing/admin/payments/{pid}/approve", headers=operator["headers"]).status_code == 200
        again = client.post(f"/api/v1/billing/admin/payments/{pid}/approve", headers=operator["headers"])
        assert again.status_code == 409
        assert client.post(f"/api/v1/billing/admin/payments/{pid}/reject", headers=operator["headers"]).status_code == 409

    def test_a_renewal_adds_to_the_time_left(self, upi, operator):
        user = _signup()
        first = _claim(user).json()["id"]
        client.post(f"/api/v1/billing/admin/payments/{first}/approve", headers=operator["headers"])
        end1 = datetime.fromisoformat(client.get("/api/v1/billing/usage", headers=user["headers"]).json()["plan_expires_at"])
        second = _claim(user).json()["id"]
        client.post(f"/api/v1/billing/admin/payments/{second}/approve", headers=operator["headers"])
        end2 = datetime.fromisoformat(client.get("/api/v1/billing/usage", headers=user["headers"]).json()["plan_expires_at"])
        assert abs((end2 - end1) - timedelta(days=30)) < timedelta(seconds=5)

    def test_a_lapsed_plan_is_free(self, upi):
        user = _signup()
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        local_db.set_subscription(user["id"], "pro", current_period_end=past)
        usage = client.get("/api/v1/billing/usage", headers=user["headers"]).json()
        assert usage["plan"] == "free" and usage["plan_expires_at"] is None

    def test_an_operator_change_does_not_expire(self, upi, operator):
        user = _signup()
        client.post("/api/v1/billing/admin/plan", json={"email": user["email"], "plan": "team"}, headers=operator["headers"])
        usage = client.get("/api/v1/billing/usage", headers=user["headers"]).json()
        assert usage["plan"] == "team" and usage["plan_expires_at"] is None

    def test_customers_cannot_approve(self, upi, operator):
        user = _signup()
        pid = _claim(user).json()["id"]
        assert client.post(f"/api/v1/billing/admin/payments/{pid}/approve", headers=user["headers"]).status_code == 403
        assert client.get("/api/v1/billing/admin/payments", headers=user["headers"]).status_code == 403

    def test_unknown_or_malformed_ids_are_404(self, upi, operator):
        for pid in (str(uuid.uuid4()), "not-a-uuid"):
            assert client.post(f"/api/v1/billing/admin/payments/{pid}/approve", headers=operator["headers"]).status_code == 404

    def test_the_quota_error_points_at_the_upgrade_page(self, upi):
        import asyncio
        import json
        from starlette.requests import Request
        from app.core.exceptions import QuotaExceeded
        from app.main import quota_handler

        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        response = asyncio.run(quota_handler(request, QuotaExceeded("Used up", plan="free", limit=5, remaining=0)))
        assert response.status_code == 402
        assert json.loads(response.body)["upgrade_url"] == "/upgrade"

    def test_deleting_the_account_removes_its_claims(self, upi):
        user = _signup()
        _claim(user)
        assert client.post("/api/v1/auth/delete-account", json={"confirm_email": user["email"]},
                           headers=user["headers"]).status_code == 200
        assert local_db.list_payment_requests(user_id=user["id"]) == []


class TestSupabasePath:
    def _setup(self, monkeypatch):
        uid, op_email = str(uuid.uuid4()), "ops@example.com"
        monkeypatch.setattr(settings, "ADMIN_EMAILS", op_email)
        fake = FakeSupabase({
            "profiles": [{"id": uid, "email": "cust@acme.com"}],
            "payment_requests": [], "subscriptions": [], "usage_events": [],
            "session_revocations": [], "deleted_accounts": [],
        })
        app.dependency_overrides[get_db] = lambda: fake
        user = {"Authorization": f"Bearer {create_access_token({'sub': uid, 'email': 'cust@acme.com'})}"}
        op = {"Authorization": f"Bearer {create_access_token({'sub': str(uuid.uuid4()), 'email': op_email})}"}
        return fake, uid, user, op

    def test_claim_approve_and_plan_in_supabase(self, upi, monkeypatch):
        fake, uid, user, op = self._setup(monkeypatch)
        res = client.post("/api/v1/billing/payments", json={"plan": "pro", "reference": "402156789012"}, headers=user)
        assert res.status_code == 201, res.text
        rows = client.get("/api/v1/billing/admin/payments", headers=op).json()["payments"]
        assert rows[0]["email"] == "cust@acme.com"
        assert client.post(f"/api/v1/billing/admin/payments/{rows[0]['id']}/approve", headers=op).status_code == 200
        sub = fake.tables["subscriptions"][0]
        assert sub["plan"] == "pro" and sub["provider"] == "upi" and sub["provider_reference"] == "402156789012"
        assert sub["current_period_end"]
        assert client.get("/api/v1/billing/usage", headers=user).json()["plan"] == "pro"

    def test_a_failed_grant_puts_the_claim_back(self, upi, monkeypatch):
        fake, uid, user, op = self._setup(monkeypatch)
        pid = client.post("/api/v1/billing/payments", json={"plan": "pro", "reference": "402156789013"}, headers=user).json()["id"]
        fake.fail("subscriptions", "upsert")
        res = client.post(f"/api/v1/billing/admin/payments/{pid}/approve", headers=op)
        assert res.status_code == 503
        assert "still waiting" in res.json()["message"]
        assert fake.tables["payment_requests"][0]["status"] == "pending"

    def test_an_outage_is_503(self, upi, monkeypatch):
        fake, uid, user, op = self._setup(monkeypatch)
        fake.fail("payment_requests", "select")
        assert client.get("/api/v1/billing/payments", headers=user).status_code == 503
        assert client.get("/api/v1/billing/admin/payments", headers=op).status_code == 503
        assert client.post("/api/v1/billing/payments", json={"plan": "pro", "reference": "402156789014"},
                           headers=user).status_code == 503
