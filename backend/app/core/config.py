from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    APP_ENV: str = "development"
    SECRET_KEY: str = "dev-secret-key-change-in-production-min-32"
    DEBUG: bool = False

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]

    # Supabase
    DATABASE_URL: str = ""
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_ANON_KEY: str = ""

    # Redis (optional — rate limiting degrades gracefully without it)
    REDIS_URL: str = ""
    REDIS_PASSWORD: str = ""

    # LLM — Gemini 2.5 Flash primary
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""          # fallback
    ANTHROPIC_API_KEY: str = ""     # fallback

    # File limits
    MAX_FILE_SIZE_MB: int = 10
    RATE_LIMIT_PER_MINUTE: int = 20
    ANALYSIS_TIMEOUT_SECONDS: int = 120

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",")]
        return v

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
