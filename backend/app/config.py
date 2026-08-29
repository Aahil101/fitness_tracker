"""Application settings, loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- Supabase -----------------------------------------------------------
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_anon_key: str = Field(default="", alias="SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field(default="", alias="SUPABASE_SERVICE_ROLE_KEY")
    # Legacy HS256 projects only. New projects use asymmetric JWKS instead.
    supabase_jwt_secret: str = Field(default="", alias="SUPABASE_JWT_SECRET")
    supabase_storage_bucket: str = Field(default="food-photos", alias="SUPABASE_STORAGE_BUCKET")

    # --- Gemini -------------------------------------------------------------
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    #: Additional keys, comma separated. Tried in turn when one is exhausted,
    #: revoked, or has lost access to the model — see services/keypool.py.
    gemini_api_keys: str = Field(default="", alias="GEMINI_API_KEYS")
    #: gemini-2.5-flash is no longer served to projects created recently: a new
    #: key gets "no longer available to new users" while an older key on the same
    #: model succeeds. 3.5-flash is available to both, so the pool stays uniform.
    gemini_model: str = Field(default="gemini-3.5-flash", alias="GEMINI_MODEL")
    gemini_api_base: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        alias="GEMINI_API_BASE",
    )

    # --- USDA FoodData Central ---------------------------------------------
    usda_api_key: str = Field(default="DEMO_KEY", alias="USDA_API_KEY")
    usda_api_base: str = Field(default="https://api.nal.usda.gov/fdc/v1", alias="USDA_API_BASE")

    # --- Upstash Redis (REST) ----------------------------------------------
    upstash_redis_rest_url: str = Field(default="", alias="UPSTASH_REDIS_REST_URL")
    upstash_redis_rest_token: str = Field(default="", alias="UPSTASH_REDIS_REST_TOKEN")

    # --- Rate limits (per user, per window) --------------------------------
    rate_limit_vision_per_hour: int = Field(default=40, alias="RATE_LIMIT_VISION_PER_HOUR")
    rate_limit_chat_per_hour: int = Field(default=80, alias="RATE_LIMIT_CHAT_PER_HOUR")
    rate_limit_insight_per_hour: int = Field(default=20, alias="RATE_LIMIT_INSIGHT_PER_HOUR")

    # --- HTTP / CORS --------------------------------------------------------
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS",
    )
    request_timeout_s: float = Field(default=30.0, alias="REQUEST_TIMEOUT_S")
    # Gemini needs its own, longer budget: a coach reply that reasons over a
    # full day's log routinely runs past the 30s that suits Supabase and USDA,
    # and exceeding it made the chat fall back to the offline reply.
    gemini_timeout_s: float = Field(default=90.0, alias="GEMINI_TIMEOUT_S")
    # Groq backs the text-only AI paths when Gemini's daily free-tier allowance
    # runs out. No vision models are published, so photos stay on Gemini.
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_api_keys: str = Field(default="", alias="GROQ_API_KEYS")
    groq_api_base: str = Field(default="https://api.groq.com/openai/v1", alias="GROQ_API_BASE")
    groq_model: str = Field(default="openai/gpt-oss-120b", alias="GROQ_MODEL")
    max_upload_bytes: int = Field(default=8 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")

    @field_validator("supabase_url", "gemini_api_base", "usda_api_base", "upstash_redis_rest_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @staticmethod
    def _split_keys(primary: str, extra: str) -> list[str]:
        """Primary key first, then the comma-separated extras, de-duplicated."""
        values = [primary, *extra.replace("\n", ",").split(",")]
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            cleaned = value.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                ordered.append(cleaned)
        return ordered

    @property
    def gemini_key_list(self) -> list[str]:
        return self._split_keys(self.gemini_api_key, self.gemini_api_keys)

    @property
    def groq_key_list(self) -> list[str]:
        return self._split_keys(self.groq_api_key, self.groq_api_keys)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_key_list)

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_key_list)

    @property
    def redis_configured(self) -> bool:
        return bool(self.upstash_redis_rest_url and self.upstash_redis_rest_token)

    @property
    def rest_url(self) -> str:
        return f"{self.supabase_url}/rest/v1"

    @property
    def auth_url(self) -> str:
        return f"{self.supabase_url}/auth/v1"

    @property
    def storage_url(self) -> str:
        return f"{self.supabase_url}/storage/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
