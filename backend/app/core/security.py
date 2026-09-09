import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import AuthError

ALGORITHM = "HS256"


def _expire_minutes() -> int:
    """Token lifetime, read at call time so it can be configured per deploy.

    This was a hardcoded 7 days. Keeping that as the default avoids silently
    logging everyone out daily on an app people leave open, but the value is
    a real security/UX tradeoff — the longer it is, the longer a leaked token
    keeps working — so it belongs in configuration rather than in a constant
    nobody can change without a deploy. See ACCESS_TOKEN_EXPIRE_MINUTES in
    app/core/config.py.
    """
    return settings.ACCESS_TOKEN_EXPIRE_MINUTES


# Kept as a module attribute because existing call sites (the session-cookie
# max-age, tests) import it directly. Reads the configured value.
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES


def create_access_token(data: dict) -> str:
    """Mint an access token.

    `jti` and `iat` exist so a token can be revoked before it expires:
      - `jti` — a unique id, so logout can denylist this exact token;
      - `iat` — when it was issued, so "revoke everything for this user"
        (password reset, sign out everywhere) can be a single cutoff
        timestamp instead of a list of tokens we would have to track.
    Without both, a signed-out token stayed valid for its full lifetime and
    there was no way to take it back. See app/core/token_revocation.py.
    """
    payload = data.copy()
    now = datetime.now(timezone.utc)
    payload["iat"] = now
    payload["exp"] = now + timedelta(minutes=_expire_minutes())
    payload.setdefault("jti", str(uuid.uuid4()))
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise AuthError("Invalid or expired token.")
