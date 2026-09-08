"""
Regression tests for a critical authentication bypass in
POST /api/v1/auth/oauth-verify.

Previously, ANY failure to verify the Google OAuth token against Supabase
— including Supabase not being configured, or Supabase explicitly
rejecting the token as invalid/expired/forged — fell through to minting a
brand-new, fully valid HireLens session JWT for a freshly-random user id
and a shared hardcoded email. That meant POSTing literally any garbage
string as `access_token` returned a working authenticated session with
zero verification: a complete auth bypass, not a degraded-mode fallback.
"""

from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_db

client = TestClient(app)


def test_oauth_verify_rejects_when_db_not_configured():
    app.dependency_overrides[get_db] = lambda: None
    try:
        res = client.post("/api/v1/auth/oauth-verify", json={"access_token": "anything-at-all"})
        assert res.status_code == 401
        assert "access_token" not in res.json()
    finally:
        app.dependency_overrides.clear()


def test_oauth_verify_rejects_garbage_token_instead_of_minting_a_session():
    mock_db = MagicMock()
    mock_db.auth.get_user.side_effect = Exception("invalid JWT: malformed token")

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        res = client.post("/api/v1/auth/oauth-verify", json={"access_token": "not-a-real-token"})
        assert res.status_code == 401
        body = res.json()
        assert "access_token" not in body
        # The old bug specifically minted this hardcoded identity — make
        # sure it never appears anywhere in the response.
        assert "google_user@hirelens.ai" not in str(body)
    finally:
        app.dependency_overrides.clear()


def test_oauth_verify_rejects_when_supabase_returns_no_user():
    mock_db = MagicMock()
    mock_db.auth.get_user.return_value = MagicMock(user=None)

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        res = client.post("/api/v1/auth/oauth-verify", json={"access_token": "expired-token"})
        assert res.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_oauth_verify_succeeds_for_a_genuinely_verified_supabase_user():
    mock_db = MagicMock()
    fake_user = MagicMock()
    fake_user.id = "real-user-id-123"
    fake_user.email = "recruiter@realcompany.com"
    fake_user.user_metadata = {"full_name": "Real Recruiter"}
    mock_db.auth.get_user.return_value = MagicMock(user=fake_user)
    mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        res = client.post("/api/v1/auth/oauth-verify", json={"access_token": "genuinely-valid-token"})
        assert res.status_code == 200
        body = res.json()
        assert body["user"]["email"] == "recruiter@realcompany.com"
        assert body["user"]["id"] == "real-user-id-123"
        assert "access_token" in body
    finally:
        app.dependency_overrides.clear()
