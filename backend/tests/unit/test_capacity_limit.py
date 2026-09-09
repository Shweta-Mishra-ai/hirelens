"""
Unit tests for the configurable active-recruiter capacity limit.

MAX_ACTIVE_RECRUITERS used to be a hardcoded 5000 wired directly into
CapacityLimitExceeded's message and repeated in health.py's diagnostics —
unchangeable without a code deploy, and a message quoting that exact
round number to end users. These tests pin the fix: the limit is one
setting, the message reflects whatever it is actually set to, and the
default is high enough that it functions as a safety valve rather than a
growth ceiling a real launch could organically hit.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.exceptions import CapacityLimitExceeded
from app.core.dependencies import get_db

client = TestClient(app)


def test_capacity_limit_exceeded_message_reflects_the_configured_value():
    exc = CapacityLimitExceeded(42)
    assert exc.http_status == 429
    assert exc.code == "capacity_limit_exceeded"
    assert "42" in exc.message


def test_capacity_limit_exceeded_has_a_sensible_fallback_message_with_no_limit():
    exc = CapacityLimitExceeded()
    assert exc.http_status == 429
    assert "capacity limit" in exc.message.lower()


def test_default_capacity_is_a_safety_valve_not_a_growth_cap():
    """The default must not be a small, marketing-flavoured round number
    that a real launch could ever reach organically."""
    assert settings.MAX_ACTIVE_RECRUITERS >= 10_000


def test_signup_capacity_limit_enforced(monkeypatch):
    # Capacity is checked against distinct Supabase Auth users (via the
    # admin API), not `reports` rows — see _count_active_users(). Mock that
    # helper directly rather than the underlying paginated admin call.
    monkeypatch.setattr(settings, "MAX_ACTIVE_RECRUITERS", 5000)
    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch(
            "app.api.v1.endpoints.auth._count_active_users", return_value=5000
        ):
            response = client.post(
                "/api/v1/auth/signup",
                json={
                    "email": "newrecruiter@example.com",
                    "password": "Password123!",
                    "full_name": "New Recruiter",
                },
            )
        assert response.status_code == 429
        data = response.json()
        assert data["error"] == "capacity_limit_exceeded"
        assert "5,000" in data["message"]
    finally:
        app.dependency_overrides.clear()


def test_signup_capacity_limit_respects_a_lowered_setting(monkeypatch):
    """The whole point: an operator can tune this without a redeploy."""
    monkeypatch.setattr(settings, "MAX_ACTIVE_RECRUITERS", 3)
    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch("app.api.v1.endpoints.auth._count_active_users", return_value=3):
            response = client.post(
                "/api/v1/auth/signup",
                json={
                    "email": "another@example.com",
                    "password": "Password123!",
                    "full_name": "Another Recruiter",
                },
            )
        assert response.status_code == 429
        assert "3" in response.json()["message"]
    finally:
        app.dependency_overrides.clear()


def test_capacity_check_counts_distinct_users_not_reports():
    """
    Regression test: a single recruiter with many reports must not exhaust
    capacity for everyone else. _count_active_users should reflect distinct
    auth users (via the admin API), never the number of report rows.
    """
    from app.api.v1.endpoints.auth import _count_active_users

    mock_db = MagicMock()
    # One recruiter, 3000 reports — should NOT read as 3000 users.
    mock_db.auth.admin.list_users.side_effect = [
        [MagicMock() for _ in range(1)],  # single active user, first page
    ]
    count = _count_active_users(mock_db)
    assert count == 1


def test_health_diagnostics_reports_the_configured_capacity(monkeypatch):
    """Diagnostics used to import a hardcoded constant straight out of
    auth.py; it now reads the same setting signup enforces against."""
    monkeypatch.setattr(settings, "MAX_ACTIVE_RECRUITERS", 12345)
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "diag-admin@example.com")
    monkeypatch.setattr(settings, "APP_ENV", "production")

    email = "diag-admin@example.com"
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": "Diag Admin", "company": "Co"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password123!"}
    ).json()["access_token"]

    res = client.get(
        "/api/v1/health/diagnostics", headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    assert res.json()["capacity"]["max_supported_users"] == 12345


def test_db_client_reuse():
    import app.core.dependencies as deps
    deps._supabase_client = None

    with patch("app.core.config.settings.SUPABASE_URL", "https://example.supabase.co"), \
         patch("app.core.config.settings.SUPABASE_SERVICE_KEY", "secret-key-12345"), \
         patch("supabase.create_client") as mock_create:
        mock_inst = MagicMock()
        mock_create.return_value = mock_inst

        # First call creates client
        db1 = deps.get_db()
        assert db1 is mock_inst
        assert mock_create.call_count == 1

        # Second call reuses cached client
        db2 = deps.get_db()
        assert db2 is mock_inst
        assert mock_create.call_count == 1
