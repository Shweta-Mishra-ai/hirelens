"""
What the health endpoint tells a stranger.

/api/v1/health is the only route reachable without an account — Render
polls it, and an uptime monitor polls it from the public internet. It used
to paste the first 50 characters of the database error straight into the
response, and a PostgREST or Postgres error routinely names the host, the
schema, or the reason a key was rejected. Whether the database is unwell is
fine to publish. Why it is unwell is not.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.dependencies import get_db, get_auth_client
from app.main import app
from tests.fake_supabase import FakeSupabase

client = TestClient(app)

SECRET = "FATAL: password authentication failed for user 'postgres' at db.abcxyz.supabase.co"


@pytest.fixture
def broken_db():
    fake = FakeSupabase({"reports": []})

    def table(name):
        raise RuntimeError(SECRET)

    fake.table = table
    # The same fake stands in for both clients. In production they are
    # deliberately different objects — signing in on the shared
    # service-role client silently hands the whole process to that user
    # (see test_shared_client_not_hijacked.py). What matters here is the
    # behaviour against a Supabase that answers, so one fake is right.
    app.dependency_overrides[get_db] = lambda: fake
    app.dependency_overrides[get_auth_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_auth_client, None)


class TestPublicHealth:
    def test_it_answers_without_a_token(self):
        res = client.get("/api/v1/health")
        assert res.status_code == 200
        assert res.json()["status"] in ("ok", "degraded")

    def test_a_healthy_database_reads_as_ok(self):
        fake = FakeSupabase({"reports": []})
        app.dependency_overrides[get_db] = lambda: fake
        app.dependency_overrides[get_auth_client] = lambda: fake
        try:
            body = client.get("/api/v1/health").json()
            assert body["services"]["database"] == "ok"
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_auth_client, None)

    def test_a_database_failure_is_reported_without_saying_why(self, broken_db):
        res = client.get("/api/v1/health")
        assert res.status_code == 200
        body = res.json()
        assert body["services"]["database"] == "error"
        assert body["status"] == "degraded"
        assert SECRET not in res.text
        assert "password" not in res.text.lower()
        assert "supabase.co" not in res.text

    def test_the_detail_cannot_be_asked_for_as_a_query_parameter(self, broken_db):
        """An argument on the route would have been a query parameter, and
        `?detail=true` would hand the error text to the anonymous caller it
        is being kept from."""
        for query in ("?detail=true", "?detail=1", "?errors=true", "?verbose=true"):
            res = client.get(f"/api/v1/health{query}")
            assert res.status_code == 200, query
            assert SECRET not in res.text, query
            assert "errors" not in res.json(), query

    def test_it_stays_a_200_so_a_blip_does_not_get_the_instance_killed(self, broken_db):
        """Render restarts on a failing health check. A degraded database is
        not a reason to take the whole service down."""
        assert client.get("/api/v1/health").status_code == 200

    def test_no_configuration_values_are_published(self):
        body = client.get("/api/v1/health").json()
        text = str(body)
        for secret in (settings.SECRET_KEY, settings.SUPABASE_SERVICE_KEY, settings.GEMINI_API_KEY):
            if secret:
                assert secret not in text
        # Providers are reported as configured or not, never by value.
        assert body["services"]["gemini"] in ("configured", "not_configured")

    def test_google_sign_in_readiness_is_published_for_the_frontend(self):
        body = client.get("/api/v1/health").json()
        assert isinstance(body["google_auth_ready"], bool)


class TestDiagnostics:
    def test_diagnostics_needs_an_account(self):
        assert client.get("/api/v1/health/diagnostics").status_code in (401, 403)

    def test_a_signed_in_caller_gets_the_reason(self, broken_db):
        creds = {"email": "diag@example.com", "password": "Password123!"}
        res = client.post("/api/v1/auth/signup", json={**creds, "full_name": "Diag Nostic"})
        if res.status_code == 409:
            res = client.post("/api/v1/auth/login", json=creds)
        assert res.status_code == 200, res.text
        headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

        body = client.get("/api/v1/health/diagnostics", headers=headers).json()
        assert body["health"]["services"]["database"] == "error"
        assert SECRET in body["health"]["errors"]["database"]

    def test_capacity_and_metrics_are_reported(self, broken_db):
        creds = {"email": "diag@example.com", "password": "Password123!"}
        res = client.post("/api/v1/auth/signup", json={**creds, "full_name": "Diag Nostic"})
        if res.status_code == 409:
            res = client.post("/api/v1/auth/login", json=creds)
        headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

        body = client.get("/api/v1/health/diagnostics", headers=headers).json()
        assert body["capacity"]["max_supported_users"] > 0
        assert "active_in_memory_jobs" in body["metrics"]
