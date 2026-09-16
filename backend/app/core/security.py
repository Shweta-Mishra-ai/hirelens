import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import AuthError

logger = logging.getLogger("hirelens")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


def create_access_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise AuthError("Invalid or expired token.")


# ── Password hashing ──────────────────────────────────────────────────────────
#
# Passwords are hashed with bcrypt. A construction like
# ``sha256("hirelens_salt_" + password)`` is not a password hash:
#
#   * the salt is a compile-time constant shared by every account, so it adds
#     no per-user entropy and does nothing to stop a precomputed table;
#   * SHA-256 is designed to be fast, which is the opposite of what a password
#     hash needs — commodity hardware does billions of these per second.
#
# A leak of the local database would therefore expose plaintext passwords for
# any account not using a long random password. bcrypt fixes both properties.
#
# We call the ``bcrypt`` package directly rather than through passlib:
# passlib 1.7.4's bcrypt backend probes ``bcrypt.__about__.__version__``,
# which bcrypt 4.1+ removed, and its wrap-bug detection passes an
# over-length secret that modern bcrypt rejects outright. Going direct
# removes a layer that breaks on every bcrypt upgrade.
#
# Legacy hashes are still *verified* so existing local accounts keep working,
# and ``needs_rehash`` lets callers transparently upgrade them on next login.

import bcrypt

_BCRYPT_ROUNDS = 12
_LEGACY_PREFIX = "sha256$legacy$"


def _prepare(password: str) -> bytes:
    """
    bcrypt truncates silently at 72 bytes. Pre-hashing anything longer keeps a
    long passphrase from collapsing to the same hash as its 72-byte prefix.
    """
    raw = password.encode("utf-8")
    if len(raw) > 72:
        return hashlib.sha256(raw).hexdigest().encode("ascii")
    return raw


def _legacy_sha256(password: str) -> str:
    """The pre-bcrypt scheme. Retained only to verify existing stored hashes."""
    return hashlib.sha256(f"hirelens_salt_{password}".encode()).hexdigest()


def _is_legacy(stored_hash: str) -> str | None:
    """Returns the bare legacy digest if `stored_hash` is one, else None."""
    bare = (
        stored_hash[len(_LEGACY_PREFIX):]
        if stored_hash.startswith(_LEGACY_PREFIX)
        else stored_hash
    )
    lowered = bare.lower()
    if len(lowered) == 64 and all(c in "0123456789abcdef" for c in lowered):
        return lowered
    return None


def hash_password(password: str) -> str:
    """Hash a password for storage. Always produces a bcrypt hash."""
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, stored_hash: str) -> bool:
    """
    Check a password against a stored hash.

    Accepts both bcrypt hashes and the legacy unsalted SHA-256 hashes written
    by earlier versions, so upgrading does not lock existing users out.
    """
    if not stored_hash:
        return False

    legacy = _is_legacy(stored_hash)
    if legacy is not None:
        # hmac.compare_digest keeps this constant-time, matching bcrypt's own
        # comparison and avoiding a timing oracle on the legacy path.
        return hmac.compare_digest(_legacy_sha256(password), legacy)

    try:
        return bcrypt.checkpw(_prepare(password), stored_hash.encode("utf-8"))
    except (ValueError, TypeError) as e:
        logger.warning(f"Password verification failed on malformed hash: {e}")
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when `stored_hash` uses a scheme we should upgrade away from."""
    if not stored_hash:
        return True
    if _is_legacy(stored_hash) is not None:
        return True
    # bcrypt hashes look like $2b$<rounds>$<salt+digest>
    parts = stored_hash.split("$")
    if len(parts) < 4 or not parts[1].startswith("2"):
        return True
    try:
        return int(parts[2]) < _BCRYPT_ROUNDS
    except ValueError:
        return True
