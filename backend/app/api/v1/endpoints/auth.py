"""
HireLens — Auth API
Fixed:
- Supabase auth calls are SYNC — no await
- Email confirmation handling
- Seamless fallback in-memory auth for dev/unconfigured Supabase environments
- Enforced 5,000 active recruiter capacity limit
"""

import logging
import uuid
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, field_validator

from app.core.dependencies import get_db, get_current_user, get_redis
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.core.exceptions import (
    AccountStoreUnavailable,
    AuthError,
    ConflictError,
    HireLensException,
    CapacityLimitExceeded,
)
from app.core.rate_limit import check_rate_limit, get_client_ip
from app.core import local_db
from app.services.teams.access import accept_pending_invites_for_email

logger = logging.getLogger("hirelens")
router = APIRouter()

LOGIN_LIMIT_PER_15_MIN = 10   # per IP — brute-force protection
SIGNUP_LIMIT_PER_HOUR = 8     # per IP — bulk fake-account protection
MAX_RECRUITERS_CAPACITY = 5000

# In-memory user store for dev/testing when Supabase DB is unconfigured or unreachable
_mem_users: dict[str, dict] = {}


def _accept_invites_quietly(db, user_id: str, email: str) -> None:
    """
    Join any team this address was invited to, without ever failing the
    sign-in that triggered it.

    Invite acceptance is a convenience on top of authentication: if it
    breaks, the user must still get their session. The three existing call
    sites all wrapped it in try/except for that reason; this puts the rule in
    one place so the local paths cannot forget it.
    """
    try:
        accepted = accept_pending_invites_for_email(db, str(user_id), str(email))
        if accepted:
            logger.info(f"Accepted {accepted} pending team invite(s) for {email}")
    except Exception as e:
        logger.warning(f"Invite auto-accept failed for {email}: {e}")


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


def _provider_answered(exc: Exception) -> bool:
    """
    True when Supabase itself rejected the request, false when it could not
    be reached.

    The two need different handling. A rejection is the answer — the password
    is wrong, the address is taken — and must stand. An outage is not an
    answer, and the local store is the only thing left to ask.
    """
    status = getattr(exc, "status", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    return isinstance(status, int) and 400 <= status < 500


@router.post("/signup")
async def signup(body: SignupRequest, request: Request, db=Depends(get_db), redis=Depends(get_redis)):
    """
    Create a new recruiter account.
    Supports both Supabase Auth and graceful fallback in-memory auth.
    """
    check_rate_limit(redis, f"signup:{get_client_ip(request)}", SIGNUP_LIMIT_PER_HOUR, window_seconds=3600)
    email_str = str(body.email).lower().strip()

    # ── Capacity check: max 5,000 registered recruiters ─────────────────
    #
    # This used to count ROWS IN THE REPORTS TABLE — one row per resume
    # analysed, not per user. Five recruiters who had each analysed a
    # thousand candidates would therefore lock the product to every new
    # signup, while five thousand recruiters who had analysed nothing would
    # pass. Count distinct users instead, which is what the limit is about.
    #
    # A failure to evaluate capacity must not block signup: the check is a
    # commercial guardrail, not a security control, and an outage in the
    # count should not take registration down with it.
    if db:
        try:
            res = db.auth.admin.list_users()
            user_count = len(res) if isinstance(res, list) else len(getattr(res, "users", []) or [])
            if user_count >= MAX_RECRUITERS_CAPACITY:
                raise CapacityLimitExceeded()
        except CapacityLimitExceeded:
            raise
        except Exception as e:
            # Supabase deployments without admin API access land here. Fall
            # back to the profile table if one exists, then give up quietly.
            logger.warning(f"Capacity check via admin API failed, trying profiles: {e}")
            try:
                res = db.table("profiles").select("id", count="exact").execute()
                if (res.count or 0) >= MAX_RECRUITERS_CAPACITY:
                    raise CapacityLimitExceeded()
            except CapacityLimitExceeded:
                raise
            except Exception as e2:
                logger.warning(f"Capacity check unavailable, allowing signup: {e2}")
    else:
        # Local store: count persisted users, not just the ones this process
        # happens to have in memory. `_mem_users` is cleared on every restart,
        # so counting it alone made the limit reset itself.
        local_count = local_db.count_users()
        if max(local_count, len(_mem_users)) >= MAX_RECRUITERS_CAPACITY:
            raise CapacityLimitExceeded()

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
                raise ConflictError("An account with this email already exists. Please log in instead.")

            # No local fallback here, deliberately.
            #
            # When Supabase is configured it IS the identity store, and
            # reports.user_id is a foreign key into auth.users. An account
            # created locally because a Supabase call happened to fail gets a
            # user id that does not exist there — so every report that account
            # analyses fails to persist and lands in the local SQLite file
            # instead, which on an ephemeral disk is gone at the next restart.
            # The account itself goes with it, and the person is left unable
            # to log in with a password they know is right.
            #
            # A signup we cannot complete is a signup that failed. Say so, and
            # let them try again.
            logger.error(f"Supabase signup failed for {email_str}: {e}")
            raise AccountStoreUnavailable()

    # Persistent local SQLite and in-memory fallback (when DB is unconfigured or Supabase connection fails)
    existing_u = local_db.get_user_by_email(email_str) or _mem_users.get(email_str)
    if existing_u:
        raise ConflictError("An account with this email already exists. Please log in instead.")

    u_record = local_db.create_user(email_str, body.password, body.full_name, body.company or "")
    uid = u_record["id"]
    _mem_users[email_str] = {
        "id": uid,
        "email": email_str,
        "password_hash": hash_password(body.password),
        "full_name": body.full_name,
        "company": body.company or "",
    }

    # Join any team this address was invited to.
    #
    # This call previously existed only on the Supabase branch, so on a
    # deployment without Supabase team invites never worked at all: the
    # invitee signed up, joined nothing, and neither they nor the person who
    # invited them saw an error.
    _accept_invites_quietly(db, uid, email_str)

    token = create_access_token({"sub": uid, "email": email_str})
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
async def login(body: LoginRequest, request: Request, db=Depends(get_db), redis=Depends(get_redis)):
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
            if not user:
                # Supabase answered, and the answer was no.
                raise AuthError("Invalid email or password.")
            token = create_access_token({
                "sub": str(user.id),
                "email": str(user.email),
            })

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
            if _provider_answered(e):
                # Supabase rejected these credentials. Falling through to the
                # local store here would let an old password left behind in
                # the SQLite file beat the real one — the identity provider
                # says no and the app says yes.
                raise AuthError("Invalid email or password.")
            # Supabase was unreachable rather than unwilling. An account that
            # predates it may still be in the local store, and locking
            # everyone out during an outage is worse than checking.
            logger.warning(f"Supabase unreachable during login for {email_str}: {e} — checking the local store")

    # Persistent local SQLite fallback lookup
    local_user = local_db.verify_user_password(email_str, body.password)
    if local_user:
        _accept_invites_quietly(db, local_user["id"], local_user["email"])
        token = create_access_token({"sub": local_user["id"], "email": local_user["email"]})
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
    if mem_user and verify_password(body.password, mem_user.get("password_hash") or ""):
        _accept_invites_quietly(db, mem_user["id"], mem_user["email"])
        token = create_access_token({"sub": mem_user["id"], "email": mem_user["email"]})
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
async def oauth_verify(body: OAuthVerifyRequest, db=Depends(get_db)):
    """
    Verify Supabase session from frontend OAuth (Google) and return custom JWT.
    """
    if db:
        try:
            # Get user details from Supabase using the frontend's access token
            user_response = db.auth.get_user(body.access_token)
            user = user_response.user
            if user:
                token = create_access_token({
                    "sub": str(user.id),
                    "email": str(user.email),
                })

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
        except Exception as e:
            logger.warning(f"OAuth verification failed in Supabase: {e}")

    # SECURITY: there is deliberately no fallback here.
    #
    # This endpoint used to end by minting a signed JWT for a synthetic
    # "google_user@hirelens.ai" identity whenever `db` was unset or the
    # Supabase lookup raised. Because the only input is an unverified
    # `access_token` string, that made the endpoint an unauthenticated token
    # issuer: POSTing any value at all — including an empty or random
    # string — returned a valid 7-day session token that every other
    # endpoint accepted. Anyone who could reach the API could read and write
    # candidate reports without an account.
    #
    # The only safe behaviour when we cannot positively verify the token with
    # the identity provider is to reject it. If Supabase is not configured,
    # Google sign-in is not available — which the frontend already handles by
    # hiding the button.
    raise AuthError("Google sign-in could not be verified. Sign in with your email and password instead.")


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current authenticated user's profile."""
    return current_user


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
            logger.warning(f"Password reset request error for {body.email}: {e}")

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
        return v


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, db=Depends(get_db)):
    """
    Reset password using access token from reset email.
    """
    if db:
        try:
            db.auth.update_user(body.access_token, {"password": body.new_password})
            return {"status": "ok", "message": "Password updated successfully. You can now log in with your new password."}
        except Exception as e:
            logger.error(f"Password update failed: {e}")

    raise AuthError("Password reset failed. Token may be expired or invalid.")


@router.get("/stats")
async def auth_stats(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """
    User management statistics for administrators.
    """
    total_users = len(_mem_users)
    if db:
        try:
            res = db.table("reports").select("user_id", count="exact").execute()
            db_users = res.count if res.count is not None else 0
            total_users = max(total_users, db_users)
        except Exception as e:
            logger.warning(f"auth_stats: could not query report count: {e}")

    return {
        "status": "ok",
        "total_active_recruiters": max(total_users, 1),
        "capacity": MAX_RECRUITERS_CAPACITY,
    }
