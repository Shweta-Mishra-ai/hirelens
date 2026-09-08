"""
HireLens — admin-only endpoint tests
Run: cd backend && python -m pytest tests/unit/test_admin_gate.py -v

Two endpoints were documented "for administrators" and enforced nothing
beyond a valid token:

  GET /auth/stats          — exact recruiter count and platform capacity
  GET /health/diagnostics  — process memory, live in-flight job counts,
                             rate-limiter internals

This app has open signup and no roles table, so "any authenticated caller"
meant "any stranger who registers". A competitor could read your exact user
numbers; someone probing could watch internal counters move while they did it.

The gate is an explicit ADMIN_EMAILS allowlist. The test that matters most is
the unconfigured one: an empty allowlist in production must deny EVERYONE. A
gate whose failure mode is "open" is the bug, not the fix.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.dependencies import require_admin
from app.core.exceptions import NotFoundError

client = TestClient(app)

ADMIN = {"id": "u-admin", "email": "boss@hirelens.com"}
NORMAL = {"id": "u-normal", "email": "someone@example.com"}


def test_empty_allowlist_denies_everyone_in_production(monkeypatch):
    """The critical case: nobody set ADMIN_EMAILS.

    Fail closed. If an unconfigured gate let everyone through it would be
    exactly the vulnerability being fixed, silently reintroduced by omission.
    """
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "")

    with pytest.raises(NotFoundError):
        require_admin(current_user=ADMIN)
    with pytest.raises(NotFoundError):
        require_admin(current_user=NORMAL)


def test_empty_allowlist_stays_open_in_development(monkeypatch):
    """Diagnostics must remain usable while working on them locally."""
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "")

    assert require_admin(current_user=NORMAL) == NORMAL


def test_listed_admin_passes(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@hirelens.com")

    assert require_admin(current_user=ADMIN) == ADMIN


def test_unlisted_user_is_denied_even_with_a_valid_token(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@hirelens.com")

    with pytest.raises(NotFoundError):
        require_admin(current_user=NORMAL)


def test_allowlist_matching_is_case_and_whitespace_insensitive(monkeypatch):
    """Emails are case-insensitive; a stray space in an env var must not
    silently lock the operator out of their own diagnostics."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ADMIN_EMAILS", " Boss@HireLens.com , ops@hirelens.com ")

    assert require_admin(current_user={"id": "x", "email": "BOSS@hirelens.COM"})
    assert require_admin(current_user={"id": "y", "email": "ops@hirelens.com"})
    with pytest.raises(NotFoundError):
        require_admin(current_user=NORMAL)


def test_denial_is_404_not_403(monkeypatch):
    """403 confirms the endpoint exists and is merely gated — the same
    existence-oracle pattern closed elsewhere in this codebase."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@hirelens.com")

    with pytest.raises(NotFoundError) as exc:
        require_admin(current_user=NORMAL)
    assert exc.value.http_status == 404


def test_missing_email_on_the_user_record_is_denied(monkeypatch):
    """A token without an email claim must not slip through the comparison."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@hirelens.com")

    with pytest.raises(NotFoundError):
        require_admin(current_user={"id": "z"})
    with pytest.raises(NotFoundError):
        require_admin(current_user={"id": "z", "email": None})


class TestEndToEnd:
    """Drive the real endpoints, not just the dependency."""

    def _token(self):
        email = "admin-gate-e2e@example.com"
        client.post(
            "/api/v1/auth/signup",
            json={
                "email": email,
                "password": "AdminGate123!",
                "full_name": "Admin Gate",
                "company": "Co",
            },
        )
        res = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "AdminGate123!"}
        )
        return res.json()["access_token"], email

    def test_ordinary_user_cannot_read_stats_or_diagnostics_in_production(self, monkeypatch):
        token, _ = self._token()
        monkeypatch.setattr(settings, "APP_ENV", "production")
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "someone.else@hirelens.com")
        headers = {"Authorization": f"Bearer {token}"}

        assert client.get("/api/v1/auth/stats", headers=headers).status_code == 404
        assert client.get("/api/v1/health/diagnostics", headers=headers).status_code == 404

    def test_listed_admin_can_read_them(self, monkeypatch):
        token, email = self._token()
        monkeypatch.setattr(settings, "APP_ENV", "production")
        monkeypatch.setattr(settings, "ADMIN_EMAILS", email)
        headers = {"Authorization": f"Bearer {token}"}

        assert client.get("/api/v1/auth/stats", headers=headers).status_code == 200
        assert client.get("/api/v1/health/diagnostics", headers=headers).status_code == 200

    def test_anonymous_is_still_rejected(self):
        assert client.get("/api/v1/auth/stats").status_code == 401
        assert client.get("/api/v1/health/diagnostics").status_code == 401
