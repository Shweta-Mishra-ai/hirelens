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

THIRD-PARTY COOKIE CAVEAT (read this before assuming session restore
"just works" in production):

In the default deployment the frontend is on `*.vercel.app` and this API
is on `*.onrender.com`. Both of those are on the Public Suffix List, so
each deployment is its own registrable site — which makes this cookie a
*third-party* cookie from the browser's point of view, even though the
same user's own tab both sets and reads it.

Browsers that block third-party cookies by default therefore drop it:
Safari (ITP, on by default since 2020), Firefox in strict mode, and
Chrome in Incognito. On those browsers `GET /auth/session` sees no
cookie and every page refresh logs the user out.

Two mitigations are in place:
  1. `partitioned=True` (CHIPS) below — restores this for Chrome under
     third-party cookie blocking, and Safari 18.4+.
  2. A per-tab `sessionStorage` fallback in the frontend auth store
     (see `restoreSession` in frontend/src/store/auth.ts), which keeps a
     refresh working on browsers that drop the cookie regardless.

The real fix is to stop being cross-site: serve the frontend and this
API from one registrable domain (e.g. `app.hirelens.com` +
`api.hirelens.com`). Then `samesite="lax"` first-party cookies work
everywhere and the sessionStorage fallback becomes dead code. That is a
DNS/hosting change, not a code change, so it is documented in the README
rather than assumed here.
"""

from fastapi import Response, Request
from app.core.config import settings
from app.core.security import ACCESS_TOKEN_EXPIRE_MINUTES

SESSION_COOKIE_NAME = "hirelens_session"


def _mark_partitioned(response: Response) -> None:
    """Append `; Partitioned` (CHIPS) to the session Set-Cookie header.

    Written onto the raw header rather than passed as starlette's
    `set_cookie(partitioned=True)` on purpose. That parameter defers to
    Python's `http.cookies`, which only learned the attribute in 3.14 — on
    anything older starlette raises:

        ValueError: Partitioned cookies are only supported in Python 3.14 and above.

    The Dockerfile pins python:3.11-slim, and `partitioned` is only true in
    production, so using the parameter would have thrown a 500 out of login,
    signup, oauth-verify and logout on the deployed API while every test
    (which runs APP_ENV=development) stayed green. Setting the attribute
    directly is version-independent and produces the identical header.

    Unknown cookie attributes are ignored by browsers that don't implement
    them, so this is safe on every client.
    """
    marker = SESSION_COOKIE_NAME.encode("latin-1") + b"="
    for i, (name, value) in enumerate(response.raw_headers):
        if name.lower() == b"set-cookie" and value.startswith(marker):
            if b"partitioned" not in value.lower():
                response.raw_headers[i] = (name, value + b"; Partitioned")


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
    # CHIPS ("Cookies Having Independent Partitioned State"). See the
    # THIRD-PARTY COOKIE CAVEAT above: on *.vercel.app + *.onrender.com this
    # cookie is third-party, and browsers that block third-party cookies drop
    # it entirely. Partitioned opts it into the partitioned cookie jar, which
    # Chrome (and Safari 18.4+) still honour under that blocking. It is keyed
    # by top-level site, which is exactly the scope wanted here anyway.
    if settings.is_production:
        _mark_partitioned(response)


def clear_session_cookie(response: Response) -> None:
    # Not response.delete_cookie(): a partitioned cookie is only overwritten
    # by a Set-Cookie whose attributes match, so a deletion missing
    # `Partitioned` silently leaves the real cookie in place and logout
    # wouldn't actually log anyone out.
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value="",
        httponly=True,
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
        max_age=0,
        path="/",
    )
    if settings.is_production:
        _mark_partitioned(response)


def read_session_cookie(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE_NAME)
