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
from urllib.parse import quote
from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, field_validator

from app.core.dependencies import (
    get_db,
    get_current_user,
    get_redis,
    get_auth_client,
    require_admin,
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

# In-memory user store for dev/testing when Supabase DB is unconfigured or unreachable
_mem_users: dict[str, dict] = {}


def _registered_user_count(db) -> int | None:
    """How many accounts exist, or None when it cannot be determined."""
    if db:
        try:
            res = db.table("profiles").select("id", count="exact").limit(1).execute()
            return int(res.count or 0)
        except Exception as e:
            logger.warning(f"Could not count registered users: {e}")
            return None
    return max(local_db.count_users(), len(_mem_users))


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
def signup(
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

    # ── Capacity check ────────────────────────────────────────────────────
    #
    # Counted as distinct accounts, from `profiles` (one row per auth user,
    # kept in step by a trigger — see sql/001). This used
    # `auth.admin.list_users()`, which is paginated and returns 50 users by
    # default, so the count never exceeded 50 and the ceiling could never
    # trigger — while still costing an admin API round trip on every signup.
    #
    # A failure to evaluate capacity must not block signup: the check is a
    # commercial guardrail, not a security control.
    if settings.MAX_REGISTERED_USERS > 0:
        user_count = _registered_user_count(db)
        if user_count is not None and user_count >= settings.MAX_REGISTERED_USERS:
            raise CapacityLimitExceeded(
                "New sign-ups are paused while we add capacity. Please try again later."
            )

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
def login(
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
def oauth_verify(
    body: OAuthVerifyRequest,
    request: Request,
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Verify Supabase session from frontend OAuth (Google) and return custom JWT.
    """
    # Each call is a round trip to Supabase on a token the caller chose; an
    # unlimited endpoint is a free amplifier against it.
    check_rate_limit(redis, f"oauth-verify:{get_client_ip(request)}", 20, window_seconds=900)
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


@router.post("/logout-all")
def logout_everywhere(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """
    Sign this account out on every device, this one included. The client
    drops its own token; every other copy stops working within a minute.
    """
    from app.services import sessions

    sessions.revoke_all(db, current_user["id"])
    logger.info(f"All sessions revoked | user={current_user['id']}")
    return {"status": "ok", "message": "Signed out on every device."}


@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    """Get current authenticated user's profile."""
    return current_user


class DeleteAccountRequest(BaseModel):
    # The account's own email, typed by the person. Guards against a
    # misclick, not an attacker: anyone holding the token knows the address.
    confirm_email: str


@router.post("/delete-account")
def delete_account(
    body: DeleteAccountRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Permanently delete this account and everything it owns. See
    app/services/account_deletion.py for exactly what is removed and in what
    order. The client discards its token; every other copy is refused.
    """
    from app.core.exceptions import ValidationError
    from app.services import account_deletion
    from app.api.v1.endpoints.analysis import _jobs

    email = (current_user.get("email") or "").strip().lower()
    if not email:
        raise ValidationError("Sign out and sign in again, then try deleting your account once more.")
    if body.confirm_email.strip().lower() != email:
        raise ValidationError("Type your account's email address exactly as shown to confirm.")

    account_deletion.delete_account(db, current_user["id"], _jobs)
    # The in-memory mirror of local accounts would otherwise still accept the
    # old password in this process.
    _mem_users.pop(email, None)
    for key in [k for k, v in _mem_users.items() if v.get("id") == current_user["id"]]:
        _mem_users.pop(key, None)
    return {"status": "deleted", "message": "Your account and all of its data have been deleted."}


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
    def mint() -> str | None:
        local_db.purge_expired_password_resets()
        user = local_db.get_user_by_email(email)
        if not user:
            return None
        token = secrets.token_urlsafe(32)
        if not local_db.create_password_reset(user["id"], token, LOCAL_RESET_TTL_SECONDS):
            return None
        return token

    token = await run_in_threadpool(mint)
    if not token:
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
            await run_in_threadpool(
                db.auth.reset_password_for_email, email_str, {"redirect_to": _reset_url()}
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
    _end_other_sessions(db, str(user.id))
    return True


def _end_other_sessions(db, user_id: str) -> None:
    """
    Sign out every session that existed before the password changed. A reset
    is very often done *because* someone else has the account; leaving their
    session working for up to seven days defeats the point. The password has
    already changed, so a failure here is logged rather than raised.
    """
    from app.services import sessions

    try:
        sessions.revoke_all(db, user_id)
    except Exception as e:
        logger.error(f"Password changed for {user_id} but old sessions were not revoked: {e}")


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, db=Depends(get_db)):
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

    _end_other_sessions(db, user_id)

    logger.info(f"Password reset completed for user {user_id}")
    return {"status": "ok", "message": "Password updated. You can sign in with it now."}


@router.get("/stats")
def auth_stats(current_user: dict = Depends(require_admin), db=Depends(get_db)):
    """
    Account totals, for operators listed in ADMIN_EMAILS.

    This counted rows in `reports` — resumes analysed, across every customer —
    and reported it as "active recruiters" to any signed-in user.
    """
    count = _registered_user_count(db)
    return {
        "status": "ok",
        "registered_users": count,
        "capacity": settings.MAX_REGISTERED_USERS or None,
    }
