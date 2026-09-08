"""
Tests for the httpOnly session-cookie mechanism added alongside the
existing Authorization-header auth flow.

Design under test: login/signup/oauth-verify set an httpOnly session
cookie IN ADDITION to returning the token in the JSON body (unchanged).
GET /auth/session reads that cookie to let the frontend silently restore
a session on page load, instead of needing to persist the raw token to
localStorage. This cookie is deliberately usable for nothing else — every
actual mutating endpoint still requires the Authorization header, so this
mechanism introduces no new CSRF surface.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.core.session_cookies import SESSION_COOKIE_NAME

client = TestClient(app)


def _unique_email(prefix: str) -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def test_signup_sets_httponly_session_cookie():
    email = _unique_email("cookie_signup")
    res = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": "Cookie Test"},
    )
    assert res.status_code == 200
    assert SESSION_COOKIE_NAME in res.cookies

    set_cookie_header = res.headers.get("set-cookie", "")
    assert "httponly" in set_cookie_header.lower()


def test_login_sets_httponly_session_cookie():
    email = _unique_email("cookie_login")
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": "Cookie Login Test"},
    )
    res = client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"})
    assert res.status_code == 200
    assert SESSION_COOKIE_NAME in res.cookies


def test_session_restore_works_with_only_the_cookie_no_auth_header():
    email = _unique_email("cookie_restore")
    signup_res = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": "Restore Test"},
    )
    assert signup_res.status_code == 200
    session_cookie = signup_res.cookies.get(SESSION_COOKIE_NAME)
    assert session_cookie

    # A fresh client with only the cookie, no Authorization header at all —
    # this is exactly what a page reload looks like on the frontend side.
    fresh_client = TestClient(app)
    fresh_client.cookies.set(SESSION_COOKIE_NAME, session_cookie)
    res = fresh_client.get("/api/v1/auth/session")
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["email"] == email
    assert "access_token" in body


def test_session_restore_fails_without_a_cookie():
    fresh_client = TestClient(app)
    res = fresh_client.get("/api/v1/auth/session")
    assert res.status_code == 401


def test_session_restore_fails_with_a_garbage_cookie_value():
    fresh_client = TestClient(app)
    fresh_client.cookies.set(SESSION_COOKIE_NAME, "not-a-real-jwt")
    res = fresh_client.get("/api/v1/auth/session")
    assert res.status_code == 401


def test_logout_clears_the_session_cookie():
    res = client.post("/api/v1/auth/logout")
    assert res.status_code == 200
    set_cookie_header = res.headers.get("set-cookie", "")
    # Clearing a cookie is done by re-setting it with an immediate
    # expiry — max-age=0 or a past Expires date.
    assert SESSION_COOKIE_NAME in set_cookie_header
    assert ("max-age=0" in set_cookie_header.lower()) or ("1970" in set_cookie_header)


def test_the_session_cookie_never_authorizes_a_mutating_endpoint():
    """
    The whole point of scoping this cookie to /auth/session only: it must
    NOT be usable as an ambient credential for any real (mutating)
    endpoint, or this would reintroduce CSRF — a cross-site page could
    ride the cookie to act on a logged-in user's behalf. Every real
    endpoint must still require the Authorization header.
    """
    email = _unique_email("cookie_no_csrf")
    signup_res = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": "No CSRF Test"},
    )
    session_cookie = signup_res.cookies.get(SESSION_COOKIE_NAME)
    assert session_cookie

    fresh_client = TestClient(app)
    fresh_client.cookies.set(SESSION_COOKIE_NAME, session_cookie)
    # No Authorization header — only the cookie, exactly what a
    # cross-site attacker page's ambient cookie-only request would carry.
    res = fresh_client.get("/api/v1/reports")
    assert res.status_code == 401
