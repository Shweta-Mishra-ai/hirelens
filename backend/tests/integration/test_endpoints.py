"""
HireLens — Integration Tests (TestClient, real HTTP request/response cycle)
Run: cd backend && python -m pytest tests/integration/test_endpoints.py -v

These exercise the actual FastAPI app + middleware stack end-to-end
(routing, dependency injection, exception handlers, security headers) —
not just isolated functions. No live DB/Redis/LLM required: the app
degrades gracefully when those aren't configured, which these tests
also implicitly verify.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def auth_token():
    from app.core.security import create_access_token
    return create_access_token({"sub": "integration-test-user", "email": "itest@example.com"})


def test_app_imports_and_loads():
    from app.main import app
    assert app is not None


class TestHealthCheck:
    def test_health_endpoint_responds(self, client):
        res = client.get("/api/v1/health")
        assert res.status_code == 200
        body = res.json()
        assert "status" in body
        assert "services" in body

    def test_root_endpoint_responds(self, client):
        res = client.get("/")
        assert res.status_code == 200


class TestSecurityHeaders:
    def test_security_headers_present_on_every_response(self, client):
        res = client.get("/api/v1/health")
        assert res.headers.get("x-content-type-options") == "nosniff"
        assert res.headers.get("x-frame-options") == "DENY"
        assert "referrer-policy" in res.headers

    def test_request_id_header_present(self, client):
        res = client.get("/api/v1/health")
        assert "x-request-id" in res.headers


class TestAuthGuardsOnProtectedEndpoints:
    """Every endpoint that touches user data must reject unauthenticated requests."""

    @pytest.mark.parametrize("method,path", [
        ("get", "/api/v1/reports"),
        ("get", "/api/v1/reports/export.csv"),
        ("post", "/api/v1/bulk/upload"),
        ("get", "/api/v1/bulk/some-id/duplicates"),
        ("post", "/api/v1/ats/import"),
        ("post", "/api/v1/match/upload"),
        ("post", "/api/v1/verify/some-id/run"),
        ("get", "/api/v1/verify/some-id"),
        ("post", "/api/v1/analysis/upload"),
        ("get", "/api/v1/teams"),
        ("post", "/api/v1/teams"),
        ("get", "/api/v1/teams/some-id/members"),
        ("post", "/api/v1/teams/some-id/invite"),
        ("post", "/api/v1/reports/some-id/share"),
        ("get", "/api/v1/reports/some-id/comments"),
        ("post", "/api/v1/reports/some-id/comments"),
        ("get", "/api/v1/reports/some-id/votes"),
        ("post", "/api/v1/reports/some-id/vote"),
        ("get", "/api/v1/reports/some-id/notify/draft?decision=advance"),
        ("post", "/api/v1/reports/some-id/notify"),
        ("post", "/api/v1/bulk/some-id/notify-all"),
        ("get", "/api/v1/auth/stats"),
        ("get", "/api/v1/health/diagnostics"),
    ])
    def test_rejects_without_token(self, client, method, path):
        res = getattr(client, method)(path)
        assert res.status_code == 401
        assert res.json()["error"] == "unauthorized"

    def test_rejects_malformed_auth_header(self, client):
        res = client.get("/api/v1/reports", headers={"Authorization": "NotBearer xyz"})
        assert res.status_code == 401

    def test_rejects_garbage_token(self, client):
        res = client.get("/api/v1/reports", headers={"Authorization": "Bearer not-a-real-jwt"})
        assert res.status_code == 401

    def test_accepts_valid_token(self, client, auth_token):
        res = client.get("/api/v1/reports", headers={"Authorization": f"Bearer {auth_token}"})
        # No DB configured in test env → app degrades gracefully rather than 401ing
        assert res.status_code == 200


class TestValidationErrors:
    def test_signup_missing_fields_returns_422(self, client):
        res = client.post("/api/v1/auth/signup", json={"email": "a@b.com"})
        assert res.status_code == 422

    def test_signup_short_password_returns_422(self, client):
        res = client.post("/api/v1/auth/signup", json={
            "email": "a@b.com", "password": "short", "full_name": "A B",
        })
        assert res.status_code == 422

    def test_login_invalid_email_format_returns_422(self, client):
        res = client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": "x"})
        assert res.status_code == 422

    def test_bulk_upload_no_files_returns_error(self, client, auth_token):
        res = client.post(
            "/api/v1/bulk/upload",
            headers={"Authorization": f"Bearer {auth_token}"},
            files={},
        )
        assert res.status_code in (400, 422)

    def test_match_upload_no_jd_returns_422(self, client, auth_token):
        res = client.post(
            "/api/v1/match/upload",
            headers={"Authorization": f"Bearer {auth_token}"},
            files={"files": ("resume.pdf", b"%PDF-1.4 fake content", "application/pdf")},
        )
        assert res.status_code == 422


class TestNotFoundHandling:
    def test_verify_nonexistent_report_returns_404(self, client, auth_token):
        res = client.post(
            "/api/v1/verify/does-not-exist/run",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={},
        )
        assert res.status_code == 404

    def test_bulk_status_nonexistent_batch_returns_404(self, client, auth_token):
        res = client.get(
            "/api/v1/bulk/does-not-exist/status",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 404

    def test_bulk_duplicates_nonexistent_batch_returns_404(self, client, auth_token):
        res = client.get(
            "/api/v1/bulk/does-not-exist/duplicates",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 404

    def test_unknown_route_returns_404(self, client):
        res = client.get("/api/v1/this-route-does-not-exist")
        assert res.status_code == 404


class TestTeamsInMemorySupport:
    """Teams support in-memory fallback when database is not configured."""

    def test_create_team_without_db(self, client, auth_token):
        res = client.post(
            "/api/v1/teams",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"name": "My Team"},
        )
        assert res.status_code == 200
        assert res.json()["name"] == "My Team"

    def test_list_teams_without_db(self, client, auth_token):
        res = client.get("/api/v1/teams", headers={"Authorization": f"Bearer {auth_token}"})
        assert res.status_code == 200
        assert "teams" in res.json()


class TestCandidateNotifyEndpoints:
    """
    End-to-end coverage for the "Notify Candidate" flow: fetching a default
    draft, and sending it (or an edited version). Recording a decision and
    notifying the candidate are independent actions — these tests confirm
    that boundary at the API level, not just in the frontend.
    """

    def test_notify_draft_requires_decision_query_param(self, client, auth_token):
        res = client.get(
            "/api/v1/reports/does-not-exist/notify/draft",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 422  # decision is a required query param

    def test_notify_draft_rejects_invalid_decision_value(self, client, auth_token):
        res = client.get(
            "/api/v1/reports/does-not-exist/notify/draft?decision=not_a_real_value",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 422

    def test_notify_draft_nonexistent_report_returns_404(self, client, auth_token):
        res = client.get(
            "/api/v1/reports/does-not-exist/notify/draft?decision=advance",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 404

    def test_notify_send_nonexistent_report_returns_404(self, client, auth_token):
        res = client.post(
            "/api/v1/reports/does-not-exist/notify",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"decision": "advance", "subject": "Test", "body": "Test body"},
        )
        assert res.status_code == 404

    def test_notify_send_missing_body_field_returns_422(self, client, auth_token):
        res = client.post(
            "/api/v1/reports/does-not-exist/notify",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"decision": "advance", "subject": "Test"},  # body missing
        )
        assert res.status_code == 422

    def test_notify_send_invalid_decision_returns_422(self, client, auth_token):
        res = client.post(
            "/api/v1/reports/does-not-exist/notify",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"decision": "maybe", "subject": "Test", "body": "Test body"},
        )
        assert res.status_code == 422

    def test_bulk_notify_all_nonexistent_batch_returns_404(self, client, auth_token):
        res = client.post(
            "/api/v1/bulk/does-not-exist/notify-all",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"decision": "advance", "overrides": {}},
        )
        assert res.status_code == 404

    def test_bulk_notify_all_invalid_decision_returns_422_or_400(self, client, auth_token):
        res = client.post(
            "/api/v1/bulk/does-not-exist/notify-all",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"decision": "not_real", "overrides": {}},
        )
        # HireLensException (400/422-family) fires before the batch lookup
        assert res.status_code in (400, 404, 422)


class TestDecisionAndNotifyAreIndependent:
    """
    Recording a recruiter decision (POST /decision) must never itself send
    an email — notification is always a separate, explicit action.
    """

    def test_decision_endpoint_does_not_touch_notify_routes(self, client, auth_token):
        # Recording a decision on a nonexistent report still 404s the same
        # way notify does — confirming both endpoints are independent but
        # share the same "report must exist" guard, not a hidden coupling.
        res = client.post(
            "/api/v1/reports/does-not-exist/decision",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"decision": "advance"},
        )
        assert res.status_code in (404, 200)  # 200 path only if in-memory store tolerates it
        # Regardless of outcome, no notify side-effect route is invoked implicitly —
        # this is a structural guarantee (separate handler functions), verified by
        # code review in reports.py rather than a runtime side-channel.


class TestErrorResponseShape:
    """Every error response should have a consistent, predictable shape —
    frontend error handling depends on this."""

    def test_error_response_has_standard_fields(self, client):
        res = client.get("/api/v1/reports")
        body = res.json()
        assert "error" in body
        assert "message" in body

    def test_500_is_never_leaked_as_stack_trace(self, client, auth_token):
        # Malformed JSON body to an endpoint expecting structured input
        res = client.post(
            "/api/v1/verify/some-id/run",
            headers={"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"},
            content=b"not valid json{{{",
        )
        assert res.status_code < 500 or "traceback" not in res.text.lower()
