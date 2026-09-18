"""
HireLens — FastAPI Dependencies

Shared clients (Supabase, Redis) and the auth dependency.

Both clients are optional: when neither is configured the app runs on the
local SQLite store with in-memory rate limiting. The rule both follow is that
a client is only published to the rest of the app once it has been proven to
work, and a failed attempt is remembered for a short cooldown so a dead
dependency costs one connection timeout per cooldown rather than one per
request.
"""
import logging
import threading
import time
from contextlib import contextmanager
from fastapi import Depends, Header
from app.core.security import decode_token
from app.core.exceptions import AuthError
from app.core.config import settings

logger = logging.getLogger("hirelens")

# How long to wait before probing a dependency that just failed. Long enough
# that an outage does not cost every request a connection timeout, short
# enough that recovery is picked up without a redeploy.
_PROBE_COOLDOWN_SECONDS = 30.0


# ── Supabase DB — pooled singleton client ───────────────────────────────────
_supabase_client = None
_supabase_lock = threading.Lock()
_supabase_failed_at = 0.0


def get_db():
    """
    The shared Supabase client, or None when it is not configured or not
    reachable — callers fall back to the local store.

    The supabase-py v2 client is synchronous: call .execute() directly, never
    await it.
    """
    global _supabase_client, _supabase_failed_at

    if not (settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY):
        return None
    if _supabase_client is not None:
        return _supabase_client

    with _supabase_lock:
        # Another thread may have built it while this one waited.
        if _supabase_client is not None:
            return _supabase_client
        if time.monotonic() - _supabase_failed_at < _PROBE_COOLDOWN_SECONDS:
            return None
        try:
            from supabase import create_client
            client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        except Exception as e:
            _supabase_failed_at = time.monotonic()
            logger.error(f"Supabase client creation failed: {e}")
            return None
        _guard_service_role(client)
        _supabase_client = client
        return client


def _guard_service_role(client) -> None:
    """
    Make the shared client incapable of quietly losing its service-role key.

    The fix for that is not to authenticate on this client at all, and the
    endpoints no longer do. This is the second line, for code written later by
    someone who does not know the rule — including a future version of the
    library that adds another path to the same listener.

    supabase-py stores its auth-state subscribers in a plain dict and calls
    them in insertion order (gotrue_client.py::_notify_all_subscribers), so a
    callback registered after `create_client` runs last and has the final say
    on the headers. This one puts the service-role key back and says loudly
    what happened, instead of leaving the whole process authenticated as
    whoever signed in.
    """
    service_header = f"Bearer {settings.SUPABASE_SERVICE_KEY}"

    def _restore(event, session) -> None:
        if client.options.headers.get("Authorization") == service_header:
            return
        logger.critical(
            "A user session was created on the SHARED Supabase client "
            "(event=%s). Its service-role key has been restored, but the code "
            "that did this must use dependencies.get_auth_client() instead — "
            "on the shared client it makes the entire process act as that one "
            "user, and breaks for everybody when their token expires.",
            event,
        )
        client.options.headers["Authorization"] = service_header
        client.auth._headers["Authorization"] = service_header
        # The listener dropped these so they would be rebuilt with the user's
        # token; drop them again so they are rebuilt with the right key.
        client._postgrest = None
        client._storage = None
        client._functions = None

    try:
        client.auth.on_auth_state_change(_restore)
    except Exception as e:  # pragma: no cover - library shape changed
        logger.warning(f"Could not install the service-role guard: {e}")


# ── Authenticating clients — deliberately NOT shared ────────────────────────
#
# Signing someone in MUST NOT happen on the shared client above, and this is
# not a style preference. supabase-py registers an auth-state listener on
# every client it builds (supabase/_sync/client.py::_listen_to_auth_events).
# On SIGNED_IN it rewrites that client's own credentials to the *user's*
# access token:
#
#     self.options.headers["Authorization"] = Bearer <user jwt>
#     self.auth._headers["Authorization"]   = Bearer <user jwt>
#     self._postgrest = None      # cached client dropped, rebuilt with the above
#
# `auth._headers` is the same dict object handed to `auth.admin`, so the admin
# API loses service-role in the same instant.
#
# On a process-wide singleton that is catastrophic, and it is silent. One
# person signs in and from then on the whole backend talks to Postgres as that
# one person: every query runs under their RLS policies, `admin.list_users`
# and `admin.update_user_by_id` stop being privileged, and the next user's
# request is served with the previous user's token. An hour later their JWT
# expires and every database call in the app starts failing — for everybody —
# until someone signs in again and restarts the cycle. It reads as "the app
# crashes most of the time" and nothing in the logs points at sign-in.
#
# So: authentication gets its own client, used once and thrown away. The
# hijack still happens — it is what the library does — but it happens to an
# object that is discarded before the response is sent.
#
# The anon key is the correct key for signing a user in; the service key is
# accepted as a fallback only so an install that never set the anon key keeps
# working, and it is no less safe here than it was before, because this client
# never outlives the request.


def make_auth_client():
    """
    A fresh, single-use Supabase client for sign-in and sign-up.

    Returns None when Supabase is not configured. Always pair it with
    `close_auth_client` — use `auth_client()` below, which does that for you.
    """
    if not (settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY):
        return None
    key = settings.SUPABASE_ANON_KEY or settings.SUPABASE_SERVICE_KEY
    try:
        from supabase import create_client
        from supabase.client import ClientOptions
    except Exception as e:  # pragma: no cover - import failure is environmental
        logger.error(f"Supabase client import failed: {e}")
        return None
    try:
        return create_client(
            settings.SUPABASE_URL,
            key,
            options=ClientOptions(
                # Nothing here should outlive the request. A refresh timer on
                # a client we are about to drop is a background thread holding
                # a dead session.
                auto_refresh_token=False,
                persist_session=False,
            ),
        )
    except Exception as e:
        logger.error(f"Supabase auth client creation failed: {e}")
        return None


def close_auth_client(client) -> None:
    """Release the throwaway client's sockets and any timer it started."""
    if client is None:
        return
    try:
        client.auth._remove_session()
    except Exception:
        pass
    for closer in (
        lambda: client.auth._http_client.close(),
        lambda: client.postgrest.session.close(),
    ):
        try:
            closer()
        except Exception:
            pass


@contextmanager
def auth_client():
    """
    `with auth_client() as sb:` — a single-use client that is always closed,
    including when the body raises, which sign-in does on every bad password.
    """
    client = make_auth_client()
    try:
        yield client
    finally:
        close_auth_client(client)


def get_auth_client():
    """
    The same thing as a FastAPI dependency: `sb=Depends(get_auth_client)`.

    A generator dependency, so FastAPI closes the client once the response is
    sent whether the handler returned or raised — and so tests can substitute
    a fake through `app.dependency_overrides`, exactly as they do for
    `get_db`. Returns None when Supabase is not configured; the endpoints
    treat that as an outage and fall back to the local store.
    """
    client = make_auth_client()
    try:
        yield client
    finally:
        close_auth_client(client)


# ── Redis — optional, graceful degradation ──────────────────────────────────
_redis_client = None
_redis_lock = threading.Lock()
_redis_failed_at = 0.0


def get_redis():
    """
    The shared Redis client, or None when Redis is not configured or not
    answering — callers fall back to their in-process equivalent.

    Two things matter here, and both are load-bearing:

    The client is published only after `ping()` proves it works. Assigning it
    before the probe means a single failed health check hands every later
    request a client that was never verified, and each of those requests then
    pays the full connect timeout before falling back.

    A failure is remembered for `_PROBE_COOLDOWN_SECONDS`. Without that, an
    unreachable Redis costs one connection timeout on every request that
    touches it — sign-in, upload, batch polling — which turns a degraded
    optional dependency into a slow app.
    """
    global _redis_client, _redis_failed_at

    if _redis_client is not None:
        return _redis_client
    if not settings.REDIS_URL:
        return None

    with _redis_lock:
        if _redis_client is not None:
            return _redis_client
        if time.monotonic() - _redis_failed_at < _PROBE_COOLDOWN_SECONDS:
            return None
        client = None
        try:
            import redis
            client = redis.from_url(
                settings.REDIS_URL,
                password=settings.REDIS_PASSWORD or None,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            client.ping()
        except Exception as e:
            _redis_failed_at = time.monotonic()
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            logger.warning(
                f"Redis unavailable, falling back to in-process state "
                f"(retrying in {_PROBE_COOLDOWN_SECONDS:.0f}s): {e}"
            )
            return None
        _redis_client = client
        logger.info("Redis connected")
        return client


def reset_clients() -> None:
    """Drop both cached clients and any cooldown, so the next call probes
    afresh. Used by tests to keep one case from leaking into the next."""
    global _supabase_client, _redis_client, _supabase_failed_at, _redis_failed_at
    with _supabase_lock:
        _supabase_client = None
        _supabase_failed_at = 0.0
    with _redis_lock:
        if _redis_client is not None:
            try:
                _redis_client.close()
            except Exception:
                pass
        _redis_client = None
        _redis_failed_at = 0.0


# ── Auth dependency ───────────────────────────────────────────────────────────
async def get_current_user(authorization: str = Header(default="")) -> dict:
    """
    Validates Bearer JWT token from Authorization header.
    Raises AuthError (401) if missing, invalid, or expired.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("Authorization header missing or invalid. Format: 'Bearer <token>'")
    
    token = authorization[7:].strip()  # Remove "Bearer " prefix
    if not token:
        raise AuthError("Token is empty.")
    
    payload = decode_token(token)
    
    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise AuthError("Token missing user ID.")
    
    email = payload.get("email", "")
    return {"id": str(user_id), "email": email}


async def get_optional_user(authorization: str = Header(default="")) -> dict | None:
    """Returns user dict or None — for public endpoints."""
    try:
        return await get_current_user(authorization)
    except AuthError:
        return None
