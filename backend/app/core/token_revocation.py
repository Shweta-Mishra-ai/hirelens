"""
HireLens — JWT revocation.

The problem this solves: signing out did not sign you out.

A JWT is self-contained — the server validates the signature and the expiry
and nothing else, so a token stays usable until it expires no matter what
happens afterwards. `POST /auth/logout` cleared the httpOnly cookie and the
frontend dropped its copy, but the token string itself remained a valid
credential for the rest of its lifetime. Anyone who had captured it — a
shared or borrowed machine, a browser extension, a screenshot of devtools, a
token that reached a log — kept access for days, and the user had no way to
take it back. "Log out on all devices" was not possible either.

Two revocation shapes, because the two real situations differ:

  1. ONE TOKEN. Ordinary logout. The presented token's `jti` goes on a
     denylist until its own expiry, at which point the entry is worthless and
     removes itself. Other sessions (a second browser, a phone) stay signed
     in, which is what a user expects from "sign out" on this device.

  2. EVERY TOKEN FOR A USER. Password reset, or an explicit "sign out
     everywhere". Storing one cutoff timestamp per user and rejecting any
     token issued before it revokes all of them at once — no need to know
     which tokens exist. This is the case that matters after "someone has my
     session": changing the password has to end it, and before this it did
     not.

STORAGE. Redis when configured (durable, shared across processes). Otherwise
an in-process dict, which carries the same limitation the rest of this app
already documents for its in-memory fallbacks: it is per-process and lost on
restart. Note what that means precisely — a restart does not grant access to
anything new, it forgets revocations, so a token revoked before the restart
becomes usable again until it expires. That is worth knowing rather than
assuming, so it is surfaced as a `config_warnings` entry in production (see
app/core/readiness.py) instead of being a silent property.

WHAT HAPPENS WHEN REDIS IS DOWN. The check degrades to the in-process
denylist; it does not reject the request.

The first implementation of this module failed closed, on the reasoning that
a revocation check is the access decision itself and allowing a request you
cannot verify is unsafe. The test suite immediately showed why that is the
wrong call *here*: with Redis unreachable, every single authenticated request
returned 401. Redis is optional in this app and every other component
degrades gracefully without it, so a fail-closed revocation check turns any
Redis blip — likely, on free-tier infrastructure — into a total outage that
logs out 100% of users.

Weigh the two failures honestly. Fail-closed: everyone is locked out for the
length of the outage, every time. Fail-open-to-memory: for the length of the
outage, a token that was revoked on ANOTHER process (or before a restart)
would work again — which requires an attacker to already hold a revoked
token and to be using it during that specific window. The second is rarer,
narrower, and does not take the product down. Availability of the auth path
is itself a security property.

So: on a Redis error the check consults the local denylist and logs an ERROR.
Writes degrade the same way — a logout during a Redis outage still revokes
locally rather than silently doing nothing.
"""

import time
import logging

logger = logging.getLogger("hirelens")

# jti -> unix timestamp at which the entry may be dropped (the token's own exp)
_mem_revoked_tokens: dict[str, float] = {}
# user_id -> unix timestamp; tokens issued at or before this are all revoked
_mem_user_cutoffs: dict[str, float] = {}

_REDIS_JTI_PREFIX = "revoked:jti:"
_REDIS_USER_PREFIX = "revoked:user:"

# Bound the in-memory maps. Reached only on a deployment with no Redis, where
# this is already a per-process best effort; without a bound a long-running
# process accumulates one entry per logout forever.
_MAX_MEM_ENTRIES = 50_000


def _prune_memory(now: float) -> None:
    expired = [k for k, exp in _mem_revoked_tokens.items() if exp <= now]
    for k in expired:
        _mem_revoked_tokens.pop(k, None)
    if len(_mem_revoked_tokens) > _MAX_MEM_ENTRIES:
        # Drop the soonest-to-expire first: they are closest to being
        # worthless anyway.
        for k, _ in sorted(_mem_revoked_tokens.items(), key=lambda kv: kv[1])[:1000]:
            _mem_revoked_tokens.pop(k, None)


def revoke_token(redis, jti: str, expires_at: float) -> None:
    """Revoke a single token until its own expiry.

    `expires_at` is the token's `exp`, so the entry lives exactly as long as
    the token could have been used and not a second longer — a denylist that
    grows forever is its own availability problem.
    """
    if not jti:
        return
    now = time.time()
    ttl = max(1, int(expires_at - now))

    if redis is not None:
        try:
            redis.setex(f"{_REDIS_JTI_PREFIX}{jti}", ttl, "1")
            return
        except Exception as e:
            # Fall through to memory rather than silently doing nothing —
            # a logout that quietly fails to revoke is the original bug.
            logger.warning(f"Redis revoke failed for jti={jti[:8]}…, using memory: {e}")

    _prune_memory(now)
    _mem_revoked_tokens[jti] = expires_at


def revoke_all_for_user(redis, user_id: str, ttl_seconds: int) -> None:
    """Revoke every token already issued to `user_id`.

    Implemented as a cutoff timestamp rather than by enumerating tokens: we
    do not know which tokens exist, and we do not need to. `ttl_seconds`
    should be the maximum token lifetime — after that, every token issued
    before the cutoff has expired on its own and the entry is redundant.
    """
    if not user_id:
        return
    now = time.time()

    if redis is not None:
        try:
            redis.setex(f"{_REDIS_USER_PREFIX}{user_id}", max(1, int(ttl_seconds)), str(now))
            return
        except Exception as e:
            logger.warning(f"Redis user-revoke failed for {user_id}, using memory: {e}")

    _mem_user_cutoffs[user_id] = now


def is_revoked(redis, jti: str | None, user_id: str | None, issued_at: float | None) -> bool:
    """True if this token has been revoked, individually or with its user.

    Never raises: an unreachable Redis degrades to the local denylist rather
    than rejecting the request. See the module docstring for why that is the
    right tradeoff in this app specifically.
    """
    now = time.time()

    if redis is not None:
        try:
            if jti and redis.get(f"{_REDIS_JTI_PREFIX}{jti}") is not None:
                return True
            if user_id:
                cutoff = redis.get(f"{_REDIS_USER_PREFIX}{user_id}")
                if cutoff is not None and issued_at is not None:
                    value = cutoff.decode() if isinstance(cutoff, bytes) else cutoff
                    # `<=` not `<`: a token minted in the same second as the
                    # revocation must not survive it.
                    if issued_at <= float(value):
                        return True
            return False
        except Exception as e:
            logger.error(
                f"Revocation store unreadable, falling back to in-process denylist "
                f"(revocations made on other processes will not be seen): {e}"
            )

    if jti:
        expires_at = _mem_revoked_tokens.get(jti)
        if expires_at is not None:
            if expires_at > now:
                return True
            _mem_revoked_tokens.pop(jti, None)

    if user_id and issued_at is not None:
        cutoff = _mem_user_cutoffs.get(user_id)
        if cutoff is not None and issued_at <= cutoff:
            return True

    return False


def _reset_for_tests() -> None:
    _mem_revoked_tokens.clear()
    _mem_user_cutoffs.clear()
