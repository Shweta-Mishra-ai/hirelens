import logging
import os
import secrets
from pathlib import Path
from typing import List
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

logger = logging.getLogger("hirelens")

# Where a development machine keeps its own signing key.
_DEV_SECRET_PATH = Path(
    os.getenv("HIRELENS_DEV_SECRET_PATH")
    or (Path(__file__).resolve().parent.parent.parent / "data" / ".dev-secret")
)


def _development_secret() -> str:
    """
    A signing key for development, generated once per machine and kept out of
    git.

    There is deliberately no hardcoded default. A constant like
    ``"dev-secret-key-change-in-production-min-32"`` shipped in the source
    means every install that forgets to set SECRET_KEY shares one publicly
    known key — and this repository was public for a period, so anyone who
    read it could mint valid tokens for any such deployment. It also trips
    every secret scanner that looks at the repo, which is noise that trains
    people to ignore real findings.

    Generated on first run rather than per process, because a key that
    changes on every restart invalidates every session — under ``--reload``
    that means being signed out on every file save, which is indistinguishable
    from a bug.
    """
    try:
        if _DEV_SECRET_PATH.exists():
            existing = _DEV_SECRET_PATH.read_text(encoding="utf-8").strip()
            if len(existing) >= 32:
                return existing
        generated = secrets.token_urlsafe(48)
        _DEV_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DEV_SECRET_PATH.write_text(generated, encoding="utf-8")
        try:
            _DEV_SECRET_PATH.chmod(0o600)
        except OSError:
            pass  # Windows, or a filesystem without POSIX modes.
        return generated
    except OSError:
        # A read-only or otherwise unwritable checkout. Still better than a
        # shared constant: this key is unique to the process, and production
        # never reaches here because it refuses to start without an explicit
        # SECRET_KEY.
        return secrets.token_urlsafe(48)



# ── CORS origins ────────────────────────────────────────────────────────────
#
# A browser's `Origin` header is a scheme, host and optional port. Nothing
# else — no trailing slash, no path, and the host lower-cased. Starlette's
# CORSMiddleware compares it to the configured list by exact string equality.
#
# So every one of these, typed into a hosting dashboard, silently blocks the
# entire frontend:
#
#     https://app.vercel.app/          trailing slash
#     https://app.vercel.app/login     someone pasted the page they were on
#     HTTPS://App.Vercel.App           copied from a mixed-case source
#     "https://app.vercel.app"         quotes kept from a JSON example
#     app.vercel.app                   scheme left off
#
# and the failure is invisible from the server: the browser refuses to send
# the request, so there is no log line, no error, no request id — on either
# this API or Supabase. The only symptom is "sign-in does nothing".
#
# Normalising here is not tidiness. It is the difference between a deployment
# that works and one that is silently broken with a correct-looking config.

_ORIGIN_SEPARATORS = ",;\n\r\t "


def normalize_origin(raw: str) -> str | None:
    """
    Turn one configured value into the exact string a browser would send, or
    None if it cannot be one.
    """
    from urllib.parse import urlsplit

    value = raw.strip().strip('"').strip("'").strip()
    if not value:
        return None
    if value == "*":
        # Meaningful to CORS, and refused outright in production by the
        # startup check in main.py. Passed through unchanged.
        return "*"

    if "//" not in value:
        # A bare host. It can only have meant https, and leaving it as-is
        # guarantees it never matches anything.
        logger.warning(
            "ALLOWED_ORIGINS entry %r has no scheme; reading it as https://%s. "
            "An origin must include the scheme to match anything.",
            raw, value,
        )
        value = f"https://{value}"

    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        logger.error(
            "Ignoring ALLOWED_ORIGINS entry %r — it is not a usable origin. "
            "Expected something like https://your-app.vercel.app", raw,
        )
        return None

    # Scheme and host are case-insensitive; the port is part of the origin.
    origin = f"{parts.scheme.lower()}://{parts.netloc.lower()}"
    if parts.path.strip("/") or parts.query or parts.fragment:
        logger.warning(
            "ALLOWED_ORIGINS entry %r contains a path; using %s. A browser "
            "never sends a path in the Origin header.", raw, origin,
        )
    return origin


def parse_origins(raw: str) -> List[str]:
    """
    Read ALLOWED_ORIGINS in any of the shapes a person actually types, and
    return normalised origins with duplicates removed and order preserved.

    Accepts a JSON array, or a list separated by commas, semicolons, newlines
    or spaces.
    """
    value = (raw or "").strip()
    if not value:
        return ["http://localhost:3000"]

    items: List[str]
    if value.startswith("["):
        import json
        try:
            loaded = json.loads(value)
            items = [str(i) for i in loaded] if isinstance(loaded, list) else [value]
        except Exception:
            logger.warning(
                "ALLOWED_ORIGINS starts with '[' but is not valid JSON; "
                "reading it as a plain separated list instead."
            )
            items = _split_origins(value.strip("[]"))
    else:
        items = _split_origins(value)

    seen: dict[str, None] = {}
    for item in items:
        origin = normalize_origin(item)
        if origin is not None:
            seen[origin] = None

    return list(seen) or ["http://localhost:3000"]


def _split_origins(value: str) -> List[str]:
    out, current = [], []
    for ch in value:
        if ch in _ORIGIN_SEPARATORS:
            if current:
                out.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        out.append("".join(current))
    return out


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_ENV_PATH, ".env"),
        case_sensitive=True,
        # This tells pydantic-settings to NOT try JSON parsing strings
        env_parse_none_str="None",
    )

    APP_ENV: str = "development"
    # No default. Production refuses to start without one (see main.py), and
    # development fills it in below from a key generated on this machine.
    SECRET_KEY: str = ""
    DEBUG: bool = False

    # CORS — stored as plain string, parsed manually
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # Supabase
    DATABASE_URL: str = ""
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_ANON_KEY: str = ""

    # Redis
    REDIS_URL: str = ""
    REDIS_PASSWORD: str = ""

    # LLM
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # Limits
    MAX_FILE_SIZE_MB: int = 10
    # How many proxies sit in front of this app.
    #
    # Rate limits are keyed on the client IP, and behind a proxy that IP comes
    # from X-Forwarded-For — a header the caller also controls. The proxy
    # APPENDS the address it saw, so only the rightmost entries are evidence;
    # everything to the left is whatever the caller chose to send. Reading the
    # leftmost entry means a caller can mint a fresh rate-limit bucket per
    # request simply by changing a header, which takes brute-force protection
    # on sign-in down to nothing.
    #
    # 1 is right for Render, Vercel and most single-proxy setups. Behind
    # Cloudflare in front of Render it is 2. Set 0 when nothing proxies this
    # app, and the header is ignored entirely.
    TRUSTED_PROXY_HOPS: int = 1
    RATE_LIMIT_PER_MINUTE: int = 20
    NOTIFY_RATE_LIMIT_PER_MINUTE: int = 10  # candidate emails are an external cost — tighter limit than general API use
    ANALYSIS_TIMEOUT_SECONDS: int = 120

    # Email Service Settings (Resend & SMTP)
    RESEND_API_KEY: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "HireLens <noreply@hirelens.ai>"
    FRONTEND_URL: str = "https://hirelens-theta.vercel.app"
    # Your Render backend URL — set this in Render env vars to enable keep-alive pings
    BACKEND_URL: str = ""

    # Bulk upload (Feature 1)
    BULK_MAX_FILES: int = 50
    BULK_MAX_TOTAL_MB: int = 150            # total batch payload cap (protects free-tier RAM)
    BULK_CONCURRENCY: int = 3               # simultaneous AI analyses within a batch
    BULK_MAX_CONCURRENT_BATCHES_PER_USER: int = 2
    BATCH_TTL_SECONDS: int = 21_600         # 6 hours — how long batch/job state is kept
    # How long a batch may hold one of a user's concurrent-batch slots before
    # the slot is assumed abandoned and reclaimed. A full batch is at worst
    # ceil(BULK_MAX_FILES / BULK_CONCURRENCY) waves of ANALYSIS_TIMEOUT_SECONDS
    # — 17 x 120s = 34 min — so 45 minutes leaves headroom without leaving a
    # user locked out of bulk upload after a restart mid-batch.
    BATCH_LEASE_SECONDS: int = 2_700

    # JD Match (Feature 2)
    JD_MAX_CHARS: int = 6000

    # Public Data Verification (Feature 3)
    GITHUB_TOKEN: str = ""             # optional — raises GitHub rate limit 60/hr → 5000/hr
    VERIFY_TIMEOUT_SECONDS: int = 20   # per external HTTP call

    @model_validator(mode="after")
    def _fill_development_secret(self):
        """Give development a key of its own; leave production to fail loudly."""
        if not self.SECRET_KEY and self.APP_ENV != "production":
            object.__setattr__(self, "SECRET_KEY", _development_secret())
        return self

    @property
    def allowed_origins_list(self) -> List[str]:
        """
        The origins CORS will accept, normalised so that a value which *looks*
        right in a dashboard actually matches.

        See `parse_origins` — this is the single highest-value normalisation
        in the app, because getting it wrong produces no error anywhere.
        """
        return parse_origins(self.ALLOWED_ORIGINS)

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def has_gemini(self) -> bool:
        return bool(self.GEMINI_API_KEY)

    @property
    def has_groq(self) -> bool:
        return bool(self.GROQ_API_KEY)


settings = Settings()
