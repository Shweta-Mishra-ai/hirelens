"""
HireLens — Auth API.

Handles signup/login against Supabase Auth with a graceful in-memory
fallback for local development, plus registration capacity protection
(see settings.MAX_ACTIVE_RECRUITERS in app/core/config.py) against a
scripted signup flood.
"""

import logging
import bcrypt
from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, EmailStr, field_validator

from app.core.config import settings
from app.core.dependencies import get_db, get_current_user, get_redis, require_admin, assert_not_revoked
from app.core.security import create_access_token, decode_token
from app.core.exceptions import AuthError, CapacityLimitExceeded
from app.core.rate_limit import check_rate_limit, get_client_ip
from app.core import local_db
from app.core.session_cookies import set_session_cookie, clear_session_cookie, read_session_cookie
from app.services.teams.access import accept_pending_invites_for_email

logger = logging.getLogger("hirelens")
router = APIRouter()

LOGIN_LIMIT_PER_15_MIN = 10   # per IP — brute-force protection
SIGNUP_LIMIT_PER_HOUR = 8     # per IP — bulk fake-account protection
# MAX_RECRUITERS_CAPACITY used to live here as a hardcoded 5000 — see
# settings.MAX_ACTIVE_RECRUITERS (app/core/config.py) and the docstring on
# CapacityLimitExceeded for why a magic number baked into code was the
# actual bug being fixed, not just where the constant happened to sit.

# In-memory user store for dev/testing when Supabase DB is unconfigured or unreachable
_mem_users: dict[str, dict] = {}


def _hash_pw(pw: str) -> str:
    """
    Same fix as app/core/local_db.py — this used to be its own separate
    copy of sha256(f"hirelens_salt_{pw}"), a fast hash with one hardcoded
    salt shared by every user. This store is purely in-process (recreated
    empty on every restart), so there's no persisted legacy data to
    migrate here — just switch straight to bcrypt.
    """
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_mem_pw(pw: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), stored_hash.encode("utf-8"))
    except ValueError:
        return False


def _count_active_users(db) -> int:
    """
    Best-effort count of distinct registered recruiters, for the capacity
    gate. Prefers the Supabase Auth admin API (accurate — it counts real
    accounts, not reports). Falls back to distinct user_id values in the
    `reports` table only if the admin API call fails (e.g. older
    supabase-py version without `auth.admin`), which is an undercount
    (recruiters with zero reports won't be seen) but is at least never an
    *overcount* that blocks signups for the wrong reason.
    """
    try:
        # supabase-py v2: auth.admin.list_users() is paginated; walk pages
        # to get an exact count rather than trusting page-size defaults.
        page, per_page, total = 1, 200, 0
        while True:
            resp = db.auth.admin.list_users(page=page, per_page=per_page)
            batch = resp if isinstance(resp, list) else getattr(resp, "users", resp)
            n = len(batch)
            total += n
            if n < per_page:
                break
            page += 1
            if page > 50:  # hard stop — 10k users is comfortably past any sane capacity setting
                break
        return total
    except Exception as e:
        logger.warning(f"Auth admin user count failed, falling back to distinct report owners: {e}")
        res = db.table("reports").select("user_id").execute()
        return len({row["user_id"] for row in (res.data or []) if row.get("user_id")})


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    company: str | None = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        # bcrypt (used for password storage — see app/core/local_db.py) only
        # examines the first 72 BYTES of a password and silently ignores
        # anything after that. Without this check, "correcthorsebattery" and
        # "correcthorsebattery<any 200 more characters>" would hash
        # identically and both would authenticate — a silent truncation
        # footgun rather than a loud, honest rejection.
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must be 72 bytes or fewer.")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Full name is required.")
        if len(v) < 2:
            raise ValueError("Full name must be at least 2 characters.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not v:
            raise ValueError("Password is required.")
        return v


@router.post("/signup")
async def signup(body: SignupRequest, request: Request, response: Response, db=Depends(get_db), redis=Depends(get_redis)):
    """
    Create a new recruiter account.
    Supports both Supabase Auth and graceful fallback in-memory auth.
    """
    check_rate_limit(redis, f"signup:{get_client_ip(request)}", SIGNUP_LIMIT_PER_HOUR, window_seconds=3600)
    email_str = str(body.email).lower().strip()

    # ── Capacity check: max active recruiters ────────────────────────────
    # This used to count rows in the `reports` table as a stand-in for
    # active users. That's wrong two ways: (1) it counts reports, not
    # distinct users, so a single recruiter uploading a few thousand
    # resumes would block every *other* recruiter from ever signing up,
    # and (2) a brand-new recruiter with zero reports was invisible to it
    # anyway. Count actual Supabase Auth users via the admin API (needs
    # the service-role key, which this app already requires) instead.
    if db:
        try:
            total_count = _count_active_users(db)
            if total_count >= settings.MAX_ACTIVE_RECRUITERS:
                raise CapacityLimitExceeded(settings.MAX_ACTIVE_RECRUITERS)
        except CapacityLimitExceeded:
            raise
        except Exception as e:
            logger.warning(f"Capacity check query error during signup: {e}")
    else:
        if len(_mem_users) >= settings.MAX_ACTIVE_RECRUITERS:
            raise CapacityLimitExceeded(settings.MAX_ACTIVE_RECRUITERS)

    if db:
        try:
            # SYNC call — no await
            result = db.auth.sign_up({
                "email": email_str,
                "password": body.password,
                "options": {
                    "data": {
                        "full_name": body.full_name,
                        "company": body.company or "",
                    }
                },
            })

            user = result.user
            if not user:
                # This happens when email confirmation is required
                return {
                    "access_token": None,
                    "token_type": "bearer",
                    "requires_email_confirmation": True,
                    "message": "Account created. Check your email to confirm your account, then log in.",
                    "user": {"email": email_str, "full_name": body.full_name},
                }

            token = create_access_token({
                "sub": str(user.id),
                "email": str(user.email),
            })
            set_session_cookie(response, token)

            try:
                accept_pending_invites_for_email(db, str(user.id), str(user.email))
            except Exception as e:
                logger.warning(f"Invite auto-accept failed during signup for {user.email}: {e}")

            return {
                "access_token": token,
                "token_type": "bearer",
                "requires_email_confirmation": False,
                "user": {
                    "id": str(user.id),
                    "email": str(user.email),
                    "full_name": body.full_name,
                    "company": body.company or "",
                },
            }

        except AuthError:
            raise
        except Exception as e:
            err_str = str(e).lower()
            if "already registered" in err_str or "already exists" in err_str or "duplicate" in err_str:
                raise AuthError("An account with this email already exists. Please log in instead.")
            logger.warning(f"Supabase signup failed for {email_str}: {e} — using local auth store fallback")

    # Persistent local SQLite and in-memory fallback (when DB is unconfigured or Supabase connection fails)
    existing_u = local_db.get_user_by_email(email_str) or _mem_users.get(email_str)
    if existing_u:
        raise AuthError("An account with this email already exists. Please log in instead.")

    u_record = local_db.create_user(email_str, body.password, body.full_name, body.company or "")
    uid = u_record["id"]
    _mem_users[email_str] = {
        "id": uid,
        "email": email_str,
        "password_hash": _hash_pw(body.password),
        "full_name": body.full_name,
        "company": body.company or "",
    }

    token = create_access_token({"sub": uid, "email": email_str})
    set_session_cookie(response, token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "requires_email_confirmation": False,
        "user": {
            "id": uid,
            "email": email_str,
            "full_name": body.full_name,
            "company": body.company or "",
        },
    }


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response, db=Depends(get_db), redis=Depends(get_redis)):
    """
    Login with email and password.
    Returns JWT access token valid for 7 days.
    """
    check_rate_limit(redis, f"login:{get_client_ip(request)}", LOGIN_LIMIT_PER_15_MIN, window_seconds=900)
    email_str = str(body.email).lower().strip()

    if db:
        try:
            # SYNC call — no await
            result = db.auth.sign_in_with_password({
                "email": email_str,
                "password": body.password,
            })

            user = result.user
            if user:
                token = create_access_token({
                    "sub": str(user.id),
                    "email": str(user.email),
                })
                set_session_cookie(response, token)

                try:
                    accept_pending_invites_for_email(db, str(user.id), str(user.email))
                except Exception as e:
                    logger.warning(f"Invite auto-accept failed during login for {user.email}: {e}")

                meta = user.user_metadata or {}
                return {
                    "access_token": token,
                    "token_type": "bearer",
                    "user": {
                        "id": str(user.id),
                        "email": str(user.email),
                        "full_name": meta.get("full_name", ""),
                        "company": meta.get("company", ""),
                    },
                }

        except AuthError:
            raise
        except Exception as e:
            err_str = str(e).lower()
            if "email not confirmed" in err_str:
                raise AuthError("Please confirm your email address before logging in.")
            logger.warning(f"Supabase login error for {email_str}: {e} — checking local auth store fallback")

    # Persistent local SQLite fallback lookup
    local_user = local_db.verify_user_password(email_str, body.password)
    if local_user:
        token = create_access_token({"sub": local_user["id"], "email": local_user["email"]})
        set_session_cookie(response, token)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": local_user["id"],
                "email": local_user["email"],
                "full_name": local_user["full_name"],
                "company": local_user["company"],
            },
        }

    # In-memory fallback store lookup (for unit tests)
    mem_user = _mem_users.get(email_str)
    if mem_user and _verify_mem_pw(body.password, mem_user["password_hash"]):
        token = create_access_token({"sub": mem_user["id"], "email": mem_user["email"]})
        set_session_cookie(response, token)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": mem_user["id"],
                "email": mem_user["email"],
                "full_name": mem_user["full_name"],
                "company": mem_user["company"],
            },
        }

    raise AuthError("Invalid email or password.")


class OAuthVerifyRequest(BaseModel):
    access_token: str


@router.post("/oauth-verify")
async def oauth_verify(body: OAuthVerifyRequest, response: Response, db=Depends(get_db)):
    """
    Verify a Supabase session from frontend OAuth (Google) and return a
    custom JWT.

    CRITICAL: this used to treat ANY failure here — Supabase not
    configured, a network blip, or (most seriously) Supabase genuinely
    rejecting `body.access_token` as invalid/expired/forged — as a reason
    to fall through and mint a brand-new, fully valid session JWT anyway,
    for a freshly-generated random user id and a shared hardcoded email.
    That meant anyone could POST literally any string as `access_token`
    and receive a real, working authenticated session with zero
    verification — a full authentication bypass, not a degraded-mode
    fallback. There is no legitimate "local fallback" for this endpoint:
    the frontend already refuses to attempt Google login at all unless
    Supabase is configured (see the login page), so if we get here and
    can't genuinely verify the token against Supabase, the honest answer
    is "not authenticated" — never a consolation token.
    """
    if not db:
        raise AuthError("Google sign-in is not available: authentication service is not configured.")

    try:
        user_response = db.auth.get_user(body.access_token)
        user = user_response.user if user_response else None
    except Exception as e:
        logger.warning(f"OAuth verification rejected by Supabase: {e}")
        raise AuthError("Google sign-in failed: your session could not be verified.")

    if not user:
        raise AuthError("Google sign-in failed: your session could not be verified.")

    token = create_access_token({
        "sub": str(user.id),
        "email": str(user.email),
    })
    set_session_cookie(response, token)

    try:
        accept_pending_invites_for_email(db, str(user.id), str(user.email))
    except Exception as e:
        logger.warning(f"Invite auto-accept failed during OAuth login for {user.email}: {e}")

    meta = user.user_metadata or {}
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": str(user.email),
            "full_name": meta.get("full_name", meta.get("name", "")),
            "company": meta.get("company", ""),
        },
    }


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current authenticated user's profile."""
    return current_user


@router.get("/session")
async def restore_session(request: Request):
    """
    Restore a session from the httpOnly cookie set at login/signup, so the
    frontend can silently re-authenticate on page load without ever having
    persisted the raw token to localStorage. Deliberately separate from
    get_current_user (which every mutating endpoint uses) rather than
    teaching that dependency to also accept the cookie — if the cookie
    could authorize state-changing requests everywhere, a cross-site
    attacker page could ride the ambient cookie to perform actions on a
    logged-in user's behalf (classic CSRF). Keeping the cookie's power
    scoped to exactly this one safe, read-only endpoint avoids that
    entirely: every real action still requires the Authorization header,
    which a cross-site page cannot set on the victim's behalf.
    """
    token = read_session_cookie(request)
    if not token:
        raise AuthError("No active session.")

    try:
        payload = decode_token(token)
    except AuthError:
        raise AuthError("Session expired or invalid.")

    # Revocation applies here too. Logout clears the cookie from the browser,
    # but a cookie value captured beforehand would otherwise still restore a
    # working session through this endpoint — which is exactly the hole
    # revocation exists to close.
    assert_not_revoked(payload)

    user_id = str(payload.get("sub") or payload.get("user_id") or "")
    email = str(payload.get("email") or "")
    if not user_id:
        raise AuthError("Session expired or invalid.")

    full_name, company = "", ""
    local_user = local_db.get_user_by_id(user_id)
    if local_user:
        full_name = local_user.get("full_name", "")
        company = local_user.get("company", "")
    else:
        mem_user = _mem_users.get(email)
        if mem_user:
            full_name = mem_user.get("full_name", "")
            company = mem_user.get("company", "")

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "company": company,
        },
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    authorization: str = Header(default=""),
    redis=Depends(get_redis),
):
    """Sign out: revoke the token AND clear the session cookie.

    Clearing the cookie used to be the whole of logout, which meant it did
    not actually log anyone out. A JWT is self-contained — signature plus
    expiry is the entire check — so the token string stayed a working
    credential for up to its full lifetime after the user pressed "Sign out".
    Anyone who had captured it (shared machine, browser extension, a token
    that reached a log) kept access, and the user had no way to take it back.

    Now the presented token is denylisted until its own expiry.

    Deliberately still returns 200 for an absent or unparseable token. Logout
    must never fail; a client that cannot complete it would leave the user
    believing they are signed out when they are not.

    ONLY the Authorization header can revoke. The cookie alone clears the
    cookie and stops there, even though revoking it would be "more thorough".

    That restraint is the point. The session cookie is SameSite=None in the
    cross-site deployment, so a browser attaches it automatically to a
    request from ANY site — meaning a random page could POST here and, if the
    cookie were enough, terminate a recruiter's active session mid-review. A
    cross-site page cannot set an Authorization header, so requiring one
    keeps the destructive half of logout out of reach. Clearing the cookie is
    the most such a request can do, which is exactly what it could do before
    revocation existed.

    A cookie belonging to the SAME user as the header token is revoked too:
    header and cookie are normally the same token, and when they differ they
    are still this browser's credentials for this session.
    """
    from app.core.token_revocation import revoke_token

    header_payload = None
    if authorization.startswith("Bearer "):
        header_token = authorization[7:].strip()
        if header_token:
            try:
                header_payload = decode_token(header_token)
            except AuthError:
                header_payload = None  # already invalid — nothing to revoke

    if header_payload is not None:
        payloads = [header_payload]

        cookie_token = read_session_cookie(request)
        if cookie_token:
            try:
                cookie_payload = decode_token(cookie_token)
            except AuthError:
                cookie_payload = None
            if cookie_payload is not None and cookie_payload.get("jti") != header_payload.get("jti"):
                same_user = (cookie_payload.get("sub") or cookie_payload.get("user_id")) == (
                    header_payload.get("sub") or header_payload.get("user_id")
                )
                if same_user:
                    payloads.append(cookie_payload)

        for payload in payloads:
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                revoke_token(redis, str(jti), float(exp))
            elif exp:
                # A token minted before jti existed: fall back to revoking
                # every session for that user, so deploying this code never
                # leaves an older token un-revocable.
                user_id = payload.get("sub") or payload.get("user_id")
                if user_id:
                    revoke_all_sessions(redis, str(user_id))

    clear_session_cookie(response)
    return {"status": "ok"}


def revoke_all_sessions(redis, user_id: str) -> None:
    """End every session for a user — used by logout's legacy-token path and
    after a password reset."""
    from app.core.token_revocation import revoke_all_for_user

    revoke_all_for_user(redis, user_id, ttl_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request, db=Depends(get_db), redis=Depends(get_redis)):
    """
    Send password reset email via Supabase Auth.
    """
    check_rate_limit(redis, f"forgot-password:{get_client_ip(request)}", limit=5, window_seconds=900)
    if db:
        try:
            db.auth.reset_password_for_email(str(body.email))
        except Exception as e:
            # The email address is deliberately NOT logged. This endpoint is
            # unauthenticated, so anyone can drive what lands in the log, and
            # a reset-request log line is a record of "this person has an
            # account here" — one of the more sensitive things a recruiting
            # tool's logs can accumulate. The rate-limit key already carries
            # the IP if an operator needs to correlate abuse.
            logger.warning(f"Password reset request failed: {e}")

    return {
        "status": "ok",
        "message": f"If an account with {body.email} exists, password reset instructions have been sent.",
    }


class ResetPasswordRequest(BaseModel):
    access_token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_pw(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("New password must be at least 8 characters.")
        if len(v.encode("utf-8")) > 72:
            raise ValueError("New password must be 72 bytes or fewer.")
        return v


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Reset password using access token from reset email.

    Rate limited per IP like /forgot-password was, and this one wasn't. The
    token itself is a Supabase JWT and not guessable, but every call here
    reaches Supabase's admin API on an unauthenticated endpoint — so without
    a limit anyone could drive unlimited upstream requests through it, and
    burn the auth provider's quota for real users trying to reset a password.
    """
    check_rate_limit(redis, f"reset-password:{get_client_ip(request)}", limit=10, window_seconds=900)
    if db:
        try:
            result = db.auth.update_user(body.access_token, {"password": body.new_password})

            # Changing your password has to end the sessions that existed
            # before it. That is the entire point of resetting a password you
            # think someone else has: if their token keeps working, the reset
            # accomplished nothing. Revoking by user cutoff means we do not
            # need to know which tokens are out there.
            user = getattr(result, "user", None)
            user_id = getattr(user, "id", None)
            if user_id:
                revoke_all_sessions(redis, str(user_id))
            else:
                logger.warning(
                    "Password reset succeeded but the user id was not returned — "
                    "existing sessions could NOT be revoked."
                )

            return {"status": "ok", "message": "Password updated successfully. You can now log in with your new password."}
        except Exception as e:
            logger.error(f"Password update failed: {e}")

    raise AuthError("Password reset failed. Token may be expired or invalid.")


@router.get("/stats")
async def auth_stats(current_user: dict = Depends(require_admin), db=Depends(get_db)):
    """
    User management statistics — administrators only (see require_admin).

    This used to be reachable by any authenticated caller despite the
    "for administrators" label, and signup is open, so anyone could register
    and read the exact number of recruiters on the platform.
    """
    total_users = len(_mem_users)
    if db:
        try:
            db_users = _count_active_users(db)
            total_users = max(total_users, db_users)
        except Exception as e:
            logger.warning(f"auth_stats: could not query user count: {e}")

    return {
        "status": "ok",
        "total_active_recruiters": max(total_users, 1),
        "capacity": settings.MAX_ACTIVE_RECRUITERS,
    }
