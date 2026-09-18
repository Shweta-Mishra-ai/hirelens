"""
HireLens — Auth API

Sign-up, sign-in, Google OAuth, and the session the rest of the API trusts.

Supabase is the identity store when it is configured, and the local store when
it is not — but never both for the same account. A Supabase instance that
answers with a rejection is authoritative; one that cannot be reached at all
produces a 503, because creating an account locally in that moment would fork
the identity of whoever signs up during the outage.
"""

import logging
import secrets
import uuid
from urllib.parse import quote
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, field_validator

from app.core.dependencies import (
    get_db,
    get_current_user,
    get_redis,
    get_auth_client,
)
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
    RateLimitExceeded,
)
from app.core.config import settings
from app.core.rate_limit import check_rate_limit, get_client_ip
from app.core import local_db
from app.services.auth.errors import classify as classify_auth_error
from app.services.email.sender import send_password_reset_email
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


@router.post("/signup")
async def signup(
    body: SignupRequest,
    request: Request,
    db=Depends(get_db),
    redis=Depends(get_redis),
    sb=Depends(get_auth_client),
):
    """
    Create a new recruiter account.
    Supports both Supabase Auth and graceful fallback in-memory auth.
    """
    check_rate_limit(redis, f"signup:{get_client_ip(request)}", SIGNUP_LIMIT_PER_HOUR, window_seconds=3600)
    email_str = str(body.email).lower().strip()

    # ── Capacity check: max 5,000 registered recruiters ─────────────────
    #
    # Counted as DISTINCT USERS, which is what the limit is about. Counting
    # rows in the reports table instead would count resumes analysed: five
    # busy recruiters would close the product to new signups, and five
    # thousand idle ones would sail through.
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
            # SYNC call — no await.
            #
            # On a throwaway client, never on `db`. A successful sign-up hands
            # back a session, and supabase-py reacts by replacing the calling
            # client's service-role credentials with that new user's token.
            # See dependencies.get_auth_client for the full explanation; the short
            # version is that doing this on the shared client hands the whole
            # backend to whoever signed in last.
            if sb is None:
                # Configured but unbuildable. Treated as an outage, not a
                # rejection, so the local store still gets its turn.
                raise ConnectionError("Supabase auth client unavailable")
            result = sb.auth.sign_up({
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

        except HireLensException:
            raise
        except Exception as e:
            # A decision by Supabase stands, whatever it was. That includes the
            # ones a user can act on — a password its policy rejects, an
            # address already registered, too many attempts — which would
            # otherwise all be reported as "the service is unavailable" and
            # send someone away to wait for a problem that is theirs to fix.
            kind, error = classify_auth_error(e, action="signup")
            if kind == "rejected" and error is not None:
                raise error

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

    # Join any team this address was invited to. This belongs on every
    # sign-up path, not only the Supabase one: invites are stored durably in
    # both back-ends, and skipping the call means the invitee signs up, joins
    # nothing, and neither they nor the person who invited them sees an error.
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
async def login(
    body: LoginRequest,
    request: Request,
    db=Depends(get_db),
    redis=Depends(get_redis),
    sb=Depends(get_auth_client),
):
    """
    Login with email and password.
    Returns JWT access token valid for 7 days.
    """
    check_rate_limit(redis, f"login:{get_client_ip(request)}", LOGIN_LIMIT_PER_15_MIN, window_seconds=900)
    email_str = str(body.email).lower().strip()

    if db:
        try:
            # SYNC call — no await.
            #
            # On a throwaway client, never on `db` — see dependencies
            # .get_auth_client. Signing in on the shared client silently swaps its
            # service-role key for this user's JWT, for every request the
            # process serves afterwards.
            if sb is None:
                raise ConnectionError("Supabase auth client unavailable")
            result = sb.auth.sign_in_with_password({
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

        except HireLensException:
            raise
        except Exception as e:
            kind, error = classify_auth_error(e, action="login")
            if kind == "rejected" and error is not None:
                # Supabase decided. Falling through to the local store here
                # would let an old password left behind in the SQLite file beat
                # the real one — the identity provider says no and the app says
                # yes. Note this covers "too many attempts" as its own answer,
                # rather than reporting a correct password as wrong.
                raise error
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
    # The only input to this endpoint is an `access_token` string that nothing
    # has verified yet. Supabase is what turns it into an identity, so if
    # Supabase is unset or the lookup fails, there is no identity — and minting
    # a session anyway would make this an unauthenticated token issuer, where
    # posting any string at all buys a valid session that every other endpoint
    # accepts. An outage means sign-in is unavailable, never that it is open.
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


# How long a locally-issued reset link stays valid. Short, because a reset
# token is a bearer credential sitting in an inbox: anyone who reads that inbox
# can take the account. Supabase manages its own expiry for the hosted flow.
LOCAL_RESET_TTL_SECONDS = 30 * 60


def _reset_url(token: str | None = None) -> str:
    """Where the reset email points.

    Supabase appends its recovery token to this as a URL fragment, so the page
    has to read the fragment rather than the query string. The local flow puts
    its own token in the query string instead, since it mints it here.
    """
    base = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password"
    return f"{base}?token={quote(token, safe='')}" if token else base


async def _issue_local_reset(email: str) -> None:
    """Mint and email a reset link from the local store.

    Every failure is logged and swallowed. The response to a forgot-password
    request is identical whatever happens, so that it cannot be used to find
    out which addresses have accounts.
    """
    local_db.purge_expired_password_resets()
    user = local_db.get_user_by_email(email)
    if not user:
        return

    token = secrets.token_urlsafe(32)
    if not local_db.create_password_reset(user["id"], token, LOCAL_RESET_TTL_SECONDS):
        return

    sent = await send_password_reset_email(
        to_email=email,
        reset_url=_reset_url(token),
        ttl_minutes=LOCAL_RESET_TTL_SECONDS // 60,
    )
    if not sent:
        # Worth an ERROR: the token is live and the person is waiting for an
        # email that no provider accepted, so they are locked out with no sign
        # that anything went wrong.
        logger.error(
            f"Password reset token issued for {email} but no email provider "
            f"accepted the message — configure RESEND_API_KEY or SMTP_*."
        )


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Start a password reset.

    The answer is the same whether or not an account exists. Confirming which
    addresses are registered would turn this endpoint into a way to enumerate
    the customer list, and the person who genuinely owns the address learns
    nothing extra from a different message.
    """
    check_rate_limit(
        redis, f"forgot-password:{get_client_ip(request)}", limit=5, window_seconds=900
    )
    email_str = str(body.email).lower().strip()
    # A second key, so one address cannot be flooded with reset emails from
    # many IPs — the IP limit above does not cover that.
    check_rate_limit(redis, f"forgot-password-addr:{email_str}", limit=3, window_seconds=900)

    if db:
        try:
            # redirect_to is what makes the link land on the reset page. Left
            # out, Supabase sends the recovery token to the project's Site URL,
            # where nothing reads it and the user gets no way to continue.
            db.auth.reset_password_for_email(
                email_str, {"redirect_to": _reset_url()}
            )
        except Exception as e:
            kind, error = classify_auth_error(e, action="reset")
            if kind == "rejected" and isinstance(error, RateLimitExceeded):
                # The one rejection worth surfacing: it is about the request,
                # not about whether the account exists.
                raise error
            logger.warning(f"Password reset request failed for {email_str}: {e}")
    else:
        await _issue_local_reset(email_str)

    return {
        "status": "ok",
        "message": (
            "If an account exists for that address, a password reset link is on "
            "its way. Check your inbox, and your spam folder."
        ),
    }


class ResetPasswordRequest(BaseModel):
    access_token: str
    new_password: str

    @field_validator("access_token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("This reset link is missing its token. Request a new one.")
        return v

    @field_validator("new_password")
    @classmethod
    def validate_pw(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("New password must be at least 8 characters.")
        return v


def _reset_via_supabase(db, token: str, new_password: str) -> bool:
    """
    Set a new password from a recovery token.

    The token is verified first with get_user(jwt), and the password is then
    set through the admin API for exactly that user id.

    Doing it the other way round — set_session() on the shared client, then
    update_user() — would work for one caller and break for two: `db` is a
    process-wide singleton, so one request's recovery session would still be
    attached to it when the next request arrived.
    """
    verified = db.auth.get_user(token)
    user = getattr(verified, "user", None)
    if not user or not getattr(user, "id", None):
        raise AuthError(
            "This password reset link has expired or has already been used. "
            "Request a new one and try again."
        )

    db.auth.admin.update_user_by_id(str(user.id), {"password": new_password})
    return True


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, db=Depends(get_db)):
    """Finish a password reset, using the token from the emailed link."""
    if db:
        try:
            _reset_via_supabase(db, body.access_token, body.new_password)
            return {
                "status": "ok",
                "message": "Password updated. You can sign in with it now.",
            }
        except AuthError:
            raise
        except HireLensException:
            raise
        except Exception as e:
            kind, error = classify_auth_error(e, action="reset")
            if kind == "rejected" and error is not None:
                raise error
            logger.error(f"Password reset failed against Supabase: {e}")
            raise AccountStoreUnavailable()

    user_id = local_db.consume_password_reset(body.access_token, body.new_password)
    if not user_id:
        raise AuthError(
            "This password reset link has expired or has already been used. "
            "Request a new one and try again."
        )

    # The in-process copy would otherwise keep answering with the old hash for
    # the life of this container, so a correct new password would be refused.
    user = local_db.get_user_by_id(user_id)
    if user and user.get("email") in _mem_users:
        _mem_users[user["email"]]["password_hash"] = hash_password(body.new_password)

    logger.info(f"Password reset completed for user {user_id}")
    return {"status": "ok", "message": "Password updated. You can sign in with it now."}


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
