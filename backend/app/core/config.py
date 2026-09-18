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
        Parse ALLOWED_ORIGINS from any format:
        - "http://localhost:3000"
        - "http://localhost:3000,https://app.vercel.app"
        - '["http://localhost:3000"]'
        """
        val = self.ALLOWED_ORIGINS.strip()
        
        # JSON array format: ["url1","url2"]
        if val.startswith("["):
            import json
            try:
                return json.loads(val)
            except Exception:
                pass
        
        # Comma-separated: url1,url2
        if "," in val:
            return [o.strip() for o in val.split(",") if o.strip()]
        
        # Single URL
        return [val] if val else ["http://localhost:3000"]

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
