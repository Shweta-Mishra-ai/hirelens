"""
HireLens — Production configuration readiness tests
Run: cd backend && python -m pytest tests/unit/test_readiness.py -v

These cover the "process is healthy, product is broken" failures: the ones
where the container boots, Render's health check goes green, and every real
user still hits a wall. The CORS one is the headline — render.yaml declares
ALLOWED_ORIGINS as `sync: false`, so it only exists if a human typed it into
the dashboard, and the fallback is localhost.
"""

import pytest

from app.core import readiness
from app.core.config import settings


@pytest.fixture
def prod_env(monkeypatch):
    """A fully-configured production deployment, with zero warnings expected.

    Deliberately modelled on the *recommended* shape — frontend and API on one
    registrable domain — rather than the current vercel.app/onrender.com split,
    so "no warnings" means "nothing left to improve", not "nothing detected".
    Individual tests below break one setting at a time, so a warning firing is
    unambiguous about its cause.
    """
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ALLOWED_ORIGINS", "https://app.hirelens.com")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.hirelens.com")
    monkeypatch.setattr(settings, "BACKEND_URL", "https://api.hirelens.com")
    monkeypatch.setattr(settings, "SESSION_COOKIE_CROSS_SITE", None)
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gemini-key")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "resend-key")
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    return settings


def _codes(warnings):
    return {w["code"] for w in warnings}


def test_no_warnings_in_development():
    """Local dev is not a misconfiguration — never nag there."""
    assert readiness.config_warnings() == []


def test_healthy_production_deploy_has_no_warnings(prod_env):
    assert readiness.config_warnings() == []


def test_flags_cors_left_on_localhost(monkeypatch, prod_env):
    """The launch-day classic: ALLOWED_ORIGINS never set in the dashboard.

    The API is fine and /health is green, but the browser blocks every single
    request from the deployed frontend, so the product is fully unusable with
    nothing but a console error to go on.
    """
    monkeypatch.setattr(settings, "ALLOWED_ORIGINS", "http://localhost:3000")

    codes = _codes(readiness.config_warnings())
    assert "cors_localhost_only" in codes
    # ...and it must not also emit the follow-on "FRONTEND_URL not in
    # ALLOWED_ORIGINS" noise, which is the same root cause said twice.
    assert "frontend_url_not_in_cors" not in codes


def test_does_not_flag_a_real_origin_list(monkeypatch, prod_env):
    monkeypatch.setattr(
        settings,
        "ALLOWED_ORIGINS",
        "https://hirelens.vercel.app,https://www.hirelens.ai",
    )
    assert "cors_localhost_only" not in _codes(readiness.config_warnings())


def test_flags_mixed_localhost_and_real_origin_as_healthy(monkeypatch, prod_env):
    """A localhost entry alongside a real one is sloppy but not broken."""
    monkeypatch.setattr(
        settings,
        "ALLOWED_ORIGINS",
        "http://localhost:3000,https://hirelens.vercel.app",
    )
    assert "cors_localhost_only" not in _codes(readiness.config_warnings())


def test_flags_missing_supabase(monkeypatch, prod_env):
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    assert "storage_ephemeral" in _codes(readiness.config_warnings())


def test_flags_missing_llm_key(monkeypatch, prod_env):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    assert "llm_unconfigured" in _codes(readiness.config_warnings())


def test_flags_frontend_url_not_matching_cors(monkeypatch, prod_env):
    """Emailed invite/reset links landing on an origin the API will reject."""
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://old-domain.example.com")
    assert "frontend_url_not_in_cors" in _codes(readiness.config_warnings())


def test_trailing_slash_does_not_trigger_a_false_frontend_url_warning(monkeypatch, prod_env):
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.hirelens.com/")
    assert "frontend_url_not_in_cors" not in _codes(readiness.config_warnings())


def test_flags_backend_url_unset(monkeypatch, prod_env):
    """Without BACKEND_URL the keep-alive pinger is off and cookie site-ness
    can't be determined."""
    monkeypatch.setattr(settings, "BACKEND_URL", "")
    assert "backend_url_unset" in _codes(readiness.config_warnings())


def test_flags_cross_site_session_cookie(monkeypatch, prod_env):
    """The current vercel.app + onrender.com split — a working deployment,
    but one where Safari/Firefox/Incognito users get a flaky-feeling session."""
    monkeypatch.setattr(settings, "ALLOWED_ORIGINS", "https://hirelens.vercel.app")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://hirelens.vercel.app")
    monkeypatch.setattr(settings, "BACKEND_URL", "https://hirelens-api.onrender.com")

    codes = _codes(readiness.config_warnings())
    assert "session_cookie_cross_site" in codes
    assert "backend_url_unset" not in codes


def test_same_registrable_domain_is_not_flagged(monkeypatch, prod_env):
    """app.example.com + api.example.com is the recommended end state."""
    assert "session_cookie_cross_site" not in _codes(readiness.config_warnings())


def test_explicit_cross_site_override_is_respected(monkeypatch, prod_env):
    """An operator who knows better than the heuristic can force it."""
    monkeypatch.setattr(settings, "SESSION_COOKIE_CROSS_SITE", True)
    assert "session_cookie_cross_site" in _codes(readiness.config_warnings())


def test_flags_non_durable_token_revocation(monkeypatch, prod_env):
    """Without Redis, a signed-out token starts working again after a restart."""
    monkeypatch.setattr(settings, "REDIS_URL", "")
    codes = _codes(readiness.config_warnings())
    assert "revocation_not_durable" in codes


def test_flags_missing_email_transport(monkeypatch, prod_env):
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    assert "email_unconfigured" in _codes(readiness.config_warnings())


def test_partial_smtp_config_is_still_flagged(monkeypatch, prod_env):
    """SMTP_HOST alone doesn't send mail — send_raw_email needs all three."""
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_USER", "user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "")
    assert "email_unconfigured" in _codes(readiness.config_warnings())


def test_health_endpoint_surfaces_warnings(monkeypatch, prod_env):
    """The whole point: checkable from outside without container access."""
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setattr(settings, "ALLOWED_ORIGINS", "http://localhost:3000")

    with TestClient(app) as client:
        body = client.get("/api/v1/health").json()

    assert body["status"] == "degraded"
    assert "cors_localhost_only" in {w["code"] for w in body["config_warnings"]}


def test_health_endpoint_reports_no_warnings_when_configured():
    """In development the key must still be present, just empty — a consumer
    checking `config_warnings` shouldn't have to handle a missing field."""
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        body = client.get("/api/v1/health").json()

    assert body["config_warnings"] == []
