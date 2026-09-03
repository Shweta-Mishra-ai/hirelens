from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        # This tells pydantic-settings to NOT try JSON parsing strings
        env_parse_none_str="None",
    )

    APP_ENV: str = "development"
    SECRET_KEY: str = "dev-secret-key-change-in-production-min-32"
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

    # JD Match (Feature 2)
    JD_MAX_CHARS: int = 6000

    # Public Data Verification (Feature 3)
    GITHUB_TOKEN: str = ""             # optional — raises GitHub rate limit 60/hr → 5000/hr
    VERIFY_TIMEOUT_SECONDS: int = 20   # per external HTTP call

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
