"""
Security regression tests for the auth endpoints.

`test_oauth_verify_rejects_unverifiable_tokens` is the important one: the
endpoint previously ended by minting a signed 7-day JWT for a synthetic
identity whenever Supabase was unconfigured or the lookup raised. Since the
only input is an unverified token string, that made it an unauthenticated
token issuer — POSTing any value returned a session every other endpoint
accepted.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _signup(email="sec_test@example.com", password="Password123!", **kw):
    return client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": "Sec Test", **kw},
    )


# ── OAuth token issuance ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "token",
    ["", "garbage", "not.a.jwt", "eyJhbGciOiJIUzI1NiJ9.e30.x", "null", " " * 20],
)
def test_oauth_verify_rejects_unverifiable_tokens(token):
    res = client.post("/api/v1/auth/oauth-verify", json={"access_token": token})
    assert res.status_code == 401, (
        f"oauth-verify issued a session for an unverified token: {res.text}"
    )
    assert "access_token" not in res.json()


def test_oauth_verify_response_carries_no_credential():
    res = client.post("/api/v1/auth/oauth-verify", json={"access_token": "anything"})
    body = res.json()
    assert res.status_code == 401
    # Nothing token-shaped may leak into the error body.
    assert not any(k in body for k in ("access_token", "token", "jwt"))


def test_token_minted_by_oauth_bypass_cannot_reach_protected_routes():
    """End-to-end: the bypass must not yield anything usable downstream."""
    res = client.post("/api/v1/auth/oauth-verify", json={"access_token": "x"})
    token = res.json().get("access_token")
    assert token is None

    # And an unauthenticated request stays unauthenticated.
    assert client.get("/api/v1/reports").status_code == 401


# ── Duplicate signup ──────────────────────────────────────────────────────────

def test_duplicate_signup_returns_409_not_401():
    """
    409 Conflict, not 401. A 401 tells the client its session is invalid;
    API clients that auto-logout on 401 would sign the user out in response
    to a duplicate-email signup.
    """
    first = _signup(email="dupe_check@example.com")
    assert first.status_code == 200

    second = _signup(email="dupe_check@example.com")
    assert second.status_code == 409
    body = second.json()
    assert body["error"] == "conflict"
    assert "already exists" in body["message"].lower()


def test_duplicate_signup_is_case_insensitive_on_email():
    assert _signup(email="CaseTest@example.com").status_code == 200
    assert _signup(email="casetest@example.com").status_code == 409


def test_duplicate_signup_does_not_overwrite_the_existing_password():
    _signup(email="nooverwrite@example.com", password="OriginalPw123!")
    _signup(email="nooverwrite@example.com", password="AttackerPw123!")

    # The attacker's password must not work…
    bad = client.post(
        "/api/v1/auth/login",
        json={"email": "nooverwrite@example.com", "password": "AttackerPw123!"},
    )
    assert bad.status_code == 401

    # …and the original must still work.
    good = client.post(
        "/api/v1/auth/login",
        json={"email": "nooverwrite@example.com", "password": "OriginalPw123!"},
    )
    assert good.status_code == 200


# ── Stored credentials ────────────────────────────────────────────────────────

def test_signup_stores_a_bcrypt_hash_not_a_bare_digest():
    from app.core import local_db

    _signup(email="hashcheck@example.com", password="Password123!")
    user = local_db.get_user_by_email("hashcheck@example.com")
    assert user is not None

    stored = user["password_hash"]
    assert stored.startswith("$2"), "password was not stored as a bcrypt hash"
    assert "Password123!" not in stored


def test_no_demo_account_is_seeded():
    """
    init_local_db() used to seed demo@hirelens.ai / Password123! on every
    startup — including any deploy where Supabase was unreachable, which is
    exactly the path a degraded production deploy takes. A publicly-known
    credential with access to candidate reports is a backdoor.
    """
    from app.core import local_db

    local_db.init_local_db()
    assert local_db.get_user_by_email("demo@hirelens.ai") is None

    res = client.post(
        "/api/v1/auth/login",
        json={"email": "demo@hirelens.ai", "password": "Password123!"},
    )
    assert res.status_code == 401


def test_login_rejects_wrong_password():
    _signup(email="pwcheck@example.com", password="RightPassword1!")
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "pwcheck@example.com", "password": "WrongPassword1!"},
    )
    assert res.status_code == 401


def test_login_error_does_not_reveal_whether_the_account_exists():
    missing = client.post(
        "/api/v1/auth/login",
        json={"email": "nosuchuser@example.com", "password": "Whatever123!"},
    )
    _signup(email="realuser@example.com", password="RightPassword1!")
    wrong_pw = client.post(
        "/api/v1/auth/login",
        json={"email": "realuser@example.com", "password": "WrongPassword1!"},
    )
    assert missing.status_code == wrong_pw.status_code == 401
    assert missing.json()["message"] == wrong_pw.json()["message"]


def test_legacy_sha256_account_can_still_log_in_and_is_upgraded():
    """
    Accounts created before the bcrypt switch must keep working, and should
    be migrated transparently on next login rather than in a batch job.
    """
    from app.core import local_db
    from app.core.security import _legacy_sha256

    local_db.init_local_db()
    local_db.create_user("legacy@example.com", "LegacyPw123!", "Legacy User")
    # Force the row back to the old scheme.
    user = local_db.get_user_by_email("legacy@example.com")
    local_db.update_password_hash(user["id"], _legacy_sha256("LegacyPw123!"))

    res = client.post(
        "/api/v1/auth/login",
        json={"email": "legacy@example.com", "password": "LegacyPw123!"},
    )
    assert res.status_code == 200

    upgraded = local_db.get_user_by_email("legacy@example.com")
    assert upgraded["password_hash"].startswith("$2"), "legacy hash was not upgraded on login"
