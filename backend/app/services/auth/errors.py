"""
HireLens — Reading what Supabase Auth actually said

Every auth endpoint has to answer the same question about a failed call: did
the identity provider make a decision, or did it fail to answer? The two lead
to completely different behaviour, and getting it wrong is what produces the
worst class of auth bug — telling someone their password is wrong when the
service was merely busy, or letting a stale local password stand in for the
real one.

`classify` reduces an exception to one of three outcomes:

    ("rejected", HireLensException)  the provider decided; show this and stop
    ("unavailable", None)            the provider never answered
    ("unknown", None)                an exception from our own code, not theirs

Supabase sends a machine-readable `code` on AuthApiError, which is what this
matches on. The message text is only a fallback, because it is prose that can
change with a release.
"""

import logging

from app.core.exceptions import (
    AuthError,
    ConflictError,
    ValidationError,
    RateLimitExceeded,
)

logger = logging.getLogger("hirelens")


# The password rules a user can actually do something about. Supabase returns
# one code for all of them, with the specifics in `reasons` or the message.
_WEAK_PASSWORD_ADVICE = (
    "Choose a longer password, or one that mixes letters, numbers and symbols."
)


def _status_of(exc: Exception) -> int | None:
    status = getattr(exc, "status", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _code_of(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    return str(code).lower() if code else ""


def _weak_password_message(exc: Exception) -> str:
    """Say which rule the password broke, when Supabase names one."""
    reasons = getattr(exc, "reasons", None)
    text = str(exc).strip()

    if "known to be weak" in text.lower() or "pwned" in text.lower():
        # Leaked-password protection. This one is worth spelling out: the
        # password may be perfectly strong-looking and still be in a breach
        # corpus, and "choose a stronger password" would be misleading advice.
        return (
            "This password has appeared in a known data breach, so it cannot be "
            "used here. Please choose a different one."
        )

    if reasons:
        named = ", ".join(str(r).replace("_", " ") for r in reasons)
        return f"That password does not meet the requirements ({named}). {_WEAK_PASSWORD_ADVICE}"

    return f"That password is too weak to use. {_WEAK_PASSWORD_ADVICE}"


def classify(exc: Exception, *, action: str) -> tuple[str, Exception | None]:
    """
    Turn a Supabase auth exception into an outcome and, when it was a
    decision, the error to raise.

    `action` is one of "login", "signup" or "reset", and only changes wording.
    """
    code = _code_of(exc)
    status = _status_of(exc)
    text = str(exc).lower()

    # ── Too many requests ────────────────────────────────────────────────
    # Deliberately first, and deliberately NOT treated as a rejection of the
    # credentials. A 429 is Supabase declining to look, and reporting it as
    # "invalid email or password" tells someone their correct password is
    # wrong — which sends them to reset a password that was never the problem.
    if status == 429 or code.startswith("over_") or "rate limit" in text:
        if "email" in code or "email rate" in text:
            return "rejected", RateLimitExceeded(
                retry_after=900,
                message="Too many emails have been sent to this address recently. "
                        "Please wait a few minutes before asking for another.",
            )
        return "rejected", RateLimitExceeded(
            retry_after=60,
            message="Too many attempts. Please wait a minute and try again.",
        )

    # ── Password rejected by policy ──────────────────────────────────────
    if code == "weak_password" or "weak" in text and "password" in text:
        return "rejected", ValidationError(_weak_password_message(exc))

    if code == "same_password":
        return "rejected", ValidationError(
            "That is already your current password. Choose a different one."
        )

    # ── Account state ────────────────────────────────────────────────────
    if code in {"email_exists", "user_already_exists", "phone_exists"} or any(
        s in text for s in ("already registered", "already exists", "duplicate")
    ):
        return "rejected", ConflictError(
            "An account with this email already exists. Please log in instead."
        )

    if code == "email_not_confirmed" or "email not confirmed" in text:
        return "rejected", AuthError(
            "Please confirm your email address first — check your inbox for the "
            "confirmation link we sent when you signed up."
        )

    if code == "email_address_invalid" or "invalid email" in text:
        return "rejected", ValidationError("That email address is not valid.")

    if code == "signup_disabled" or "signups not allowed" in text:
        return "rejected", AuthError("New accounts are not being accepted right now.")

    # ── The reset link itself ────────────────────────────────────────────
    #
    # During a reset, an unauthorized answer can only mean the token in the
    # link did not verify — there is no other credential in play. That
    # includes the shapes Supabase sends with no code at all, such as
    # "invalid claim: missing sub claim" for a truncated or tampered token.
    # Without the status rule those fall through to a generic message, and the
    # person holding a dead link is never told to ask for a new one.
    bad_link_codes = {"otp_expired", "bad_jwt", "session_expired", "session_not_found"}
    bad_link_text = ("expired", "invalid jwt", "token is invalid", "claim", "invalid token")
    if (
        code in bad_link_codes
        or any(s in text for s in bad_link_text)
        or (action == "reset" and status in (401, 403))
    ):
        return "rejected", AuthError(
            "This password reset link has expired or has already been used. "
            "Request a new one and try again."
        )

    # ── Credentials ──────────────────────────────────────────────────────
    if code in {"invalid_credentials", "user_not_found"} or "invalid login" in text:
        if action == "login":
            return "rejected", AuthError("Invalid email or password.")
        return "rejected", AuthError("We could not verify that request.")

    # ── Anything else the provider answered with ─────────────────────────
    # A 4xx we have no specific wording for is still a decision, and passing
    # it off as an outage would tell the user to try again later when trying
    # again will fail identically.
    if status is not None and 400 <= status < 500:
        logger.warning(f"Unmapped Supabase auth rejection during {action}: {code or status} — {exc}")
        if action == "login":
            return "rejected", AuthError("Invalid email or password.")
        if action == "signup":
            return "rejected", ValidationError(
                "We could not create the account with those details. Please check them and try again."
            )
        return "rejected", AuthError("We could not complete that request.")

    # A 5xx, a timeout, a DNS failure, a retryable error — no decision was
    # made, so the caller decides what to fall back to.
    return "unavailable", None
