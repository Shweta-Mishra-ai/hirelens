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


# ── Production cookie attributes ────────────────────────────────────────────
# Every test above runs with APP_ENV=development, where the cookie is written
# with samesite=lax, no Secure and no Partitioned. That means the entire
# production branch of set_session_cookie/clear_session_cookie had NO
# coverage — and it is the branch that actually ships.
#
# That gap was not theoretical. Setting Partitioned via starlette's
# `set_cookie(partitioned=True)` raises
#   ValueError: Partitioned cookies are only supported in Python 3.14 and above
# on the pinned python:3.11-slim image, which would have thrown a 500 out of
# login, signup, oauth-verify and logout on the deployed API while the whole
# suite stayed green. These tests exercise the production branch directly.

def _prod_cookie_header(monkeypatch, fn, *args):
    from starlette.responses import Response
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_ENV", "production")
    response = Response()
    fn(response, *args)
    headers = [
        v.decode("latin-1")
        for k, v in response.raw_headers
        if k.lower() == b"set-cookie"
    ]
    assert len(headers) == 1, headers
    return headers[0]


def test_production_session_cookie_has_cross_site_attributes(monkeypatch):
    from app.core.session_cookies import set_session_cookie

    header = _prod_cookie_header(monkeypatch, set_session_cookie, "a.token.value")

    assert header.startswith(f"{SESSION_COOKIE_NAME}=a.token.value")
    assert "HttpOnly" in header
    # SameSite=None is required for the cookie to be sent at all from the
    # Vercel frontend to the Render API, and the spec requires Secure with it.
    assert "SameSite=none" in header
    assert "Secure" in header
    # CHIPS — without it, Chrome's third-party cookie blocking drops the
    # cookie and session restore silently stops working.
    assert "Partitioned" in header


def test_production_logout_cookie_matches_the_set_cookie_attributes(monkeypatch):
    """A partitioned cookie is only overwritten by a matching Set-Cookie.

    If the deletion header omits Partitioned the browser keeps the original
    cookie and logout doesn't actually log the user out.
    """
    from app.core.session_cookies import clear_session_cookie

    header = _prod_cookie_header(monkeypatch, clear_session_cookie)

    assert "Max-Age=0" in header
    assert "SameSite=none" in header
    assert "Secure" in header
    assert "Partitioned" in header


def test_development_cookie_is_not_marked_secure_or_partitioned(monkeypatch):
    """Local dev is same-site over plain http — Secure would make the cookie
    unusable, and Partitioned is pointless there."""
    from starlette.responses import Response
    from app.core.config import settings
    from app.core.session_cookies import set_session_cookie

    monkeypatch.setattr(settings, "APP_ENV", "development")
    response = Response()
    set_session_cookie(response, "a.token.value")
    header = next(
        v.decode("latin-1") for k, v in response.raw_headers if k.lower() == b"set-cookie"
    )

    assert "SameSite=lax" in header
    assert "Secure" not in header
    assert "Partitioned" not in header


def test_partitioned_is_not_applied_twice(monkeypatch):
    """The raw-header rewrite must be idempotent per response."""
    from starlette.responses import Response
    from app.core.config import settings
    from app.core.session_cookies import set_session_cookie, _mark_partitioned

    monkeypatch.setattr(settings, "APP_ENV", "production")
    response = Response()
    set_session_cookie(response, "a.token.value")
    _mark_partitioned(response)
    header = next(
        v.decode("latin-1") for k, v in response.raw_headers if k.lower() == b"set-cookie"
    )

    assert header.count("Partitioned") == 1


def test_production_auth_endpoints_do_not_500_setting_the_cookie(monkeypatch):
    """End-to-end guard for the Python-version trap.

    The failure mode being pinned down here is specifically "works in tests,
    500s in production", so drive the real endpoints with APP_ENV=production
    rather than only unit-testing the helper.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_ENV", "production")

    email = "prod-cookie-path@example.com"
    signup = client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "ProdCookie123!",
            "full_name": "Prod Cookie",
            "company": "Co",
        },
    )
    assert signup.status_code == 200, signup.text

    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "ProdCookie123!"}
    )
    assert login.status_code == 200, login.text

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200, logout.text
