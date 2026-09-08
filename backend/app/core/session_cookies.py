"""
HireLens — Session Cookie Helpers

Security context: the JWT used to live ONLY in the frontend's Zustand
store, persisted to localStorage. localStorage is readable by any
JavaScript running on the page — there's no XSS injection sink anywhere
in this app today (audited separately), so the practical risk was low,
but it's still a recognized anti-pattern: a token sitting in localStorage
survives indefinitely across tabs/sessions/browser-profile-sync and is
readable by anything that ever runs on the page, including a
third-party script added later.

Rather than rip out the existing Authorization-header flow everywhere
(a large, hard-to-verify change touching ~30 API call sites across every
page), this adds an httpOnly session cookie used for exactly one
purpose: silently restoring a session on page load via a safe GET
request (see the /auth/session endpoint), so the frontend no longer
needs to persist the raw token to localStorage at all. All actual
state-changing requests continue to authenticate via the Authorization
header exactly as before — which means this change introduces NO new
CSRF exposure, since a cookie is never used to authorize a mutating
request; the header a cross-site attacker page cannot set is still what
every real action requires.
"""

from fastapi import Response, Request
from app.core.config import settings
from app.core.security import ACCESS_TOKEN_EXPIRE_MINUTES

SESSION_COOKIE_NAME = "hirelens_session"


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.is_production,
        # Frontend (Vercel) and backend (Render) are different origins in
        # production, so the cookie must be usable cross-site to reach the
        # /auth/session endpoint at all — SameSite=None requires Secure.
        # In local dev (same-site http://localhost) Lax is the safer
        # default and doesn't require HTTPS.
        samesite="none" if settings.is_production else "lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
        path="/",
    )


def read_session_cookie(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE_NAME)
