from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]
# Local layout: <repo>/apps/api/app/config -> <repo>. Container layout: /app/app/config -> /app.
REPO_ROOT = API_DIR.parents[1] if len(API_DIR.parents) > 1 else API_DIR.parent


class Settings(BaseSettings):
    """Runtime configuration. Every value can be overridden by environment variables."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", API_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -------------------------------------------------------
    APP_NAME: str = "RESOLVE API"
    ENV: Literal["development", "test", "production"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    FRONTEND_URL: str = "http://localhost:5173"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:8080"
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False
    DEMO_MODE: bool = True
    DEMO_AI_ENABLED: bool = False
    AUTO_CREATE_SCHEMA: bool = True

    # --- Security ----------------------------------------------------------
    SECRET_KEY: str = "dev-only-change-me-please-0f8a1c9d2b7e4"
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "resolve"
    JWT_AUDIENCE: str = "resolve-api"
    ACCESS_TOKEN_TTL_MINUTES: int = 30
    REFRESH_TOKEN_TTL_DAYS: int = 14
    PASSWORD_MIN_LENGTH: int = 10
    ALLOW_SELF_APPROVAL: bool = False
    APPROVAL_EXPIRY_HOURS: int = 48
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "600/minute"
    RATE_LIMIT_LOGIN: str = "10/minute"
    RATE_LIMIT_STORAGE_URI: str = "memory://"
    MAX_UPLOAD_MB: int = 25
    CREDENTIAL_ENCRYPTION_KEY: str = ""

    # --- Database / cache --------------------------------------------------
    DATABASE_URL: str = f"sqlite:///{(API_DIR / 'var' / 'resolve.db').as_posix()}"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""
    CELERY_TASK_ALWAYS_EAGER: bool = False
    TASK_RUNNER: Literal["auto", "celery", "inline"] = "auto"
    TASK_INLINE_MAX_CONCURRENCY: int = 3

    # --- Storage -----------------------------------------------------------
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_LOCAL_DIR: str = str(API_DIR / "var" / "storage")
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_BUCKET: str = "resolve-documents"
    S3_REGION: str = "us-east-1"
    S3_USE_SSL: bool = False

    # --- Document processing ----------------------------------------------
    OCR_ENABLED: bool = True
    OCR_PROVIDER: Literal["tesseract", "none"] = "tesseract"
    TESSERACT_CMD: str = ""
    OCR_MIN_TEXT_CHARS_PER_PAGE: int = 80
    OCR_LANGUAGE: str = "eng+tha"
    OCR_TIMEOUT_SECONDS: int = 90
    PDF_RENDER_DPI: int = 200
    MAX_DECOMPRESSED_MB: int = 200
    DOCUMENT_DETAIL_MAX_CHARS: int = 60_000

    # --- AI ----------------------------------------------------------------
    AI_PROVIDER: Literal["openai", "ollama", "stub", "none"] = "none"
    AI_BASE_URL: str = "https://api.openai.com/v1"
    AI_API_KEY: str = ""
    AI_MODEL: str = "gpt-4o-mini"
    AI_TIMEOUT_SECONDS: float = 60.0
    AI_MAX_RETRIES: int = 2
    AI_TEMPERATURE: float = 0.0
    AI_MAX_OUTPUT_TOKENS: int = 2500
    AI_INPUT_COST_PER_1K: float = 0.0
    AI_OUTPUT_COST_PER_1K: float = 0.0
    AI_EMBEDDING_PROVIDER: Literal["openai", "ollama", "stub", "none"] = "none"
    AI_EMBEDDING_BASE_URL: str = ""
    AI_EMBEDDING_API_KEY: str = ""
    AI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    AI_EMBEDDING_DIM: int = 384
    AI_EXTRACTION_ENABLED: bool = True
    AI_INVESTIGATION_ENABLED: bool = True

    # --- Retrieval ---------------------------------------------------------
    CHUNK_SIZE: int = 900
    CHUNK_OVERLAP: int = 120
    RETRIEVAL_TOP_K: int = 6
    RETRIEVAL_MIN_SCORE: float = 0.18
    KEYWORD_WEIGHT: float = 0.45
    VECTOR_WEIGHT: float = 0.55

    # --- Email -------------------------------------------------------------
    EMAIL_BACKEND: Literal["sink", "smtp"] = "sink"
    EMAIL_SINK_DIR: str = str(API_DIR / "var" / "mail")
    EMAIL_FROM: str = "resolve@localhost"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = False

    # --- Automation --------------------------------------------------------
    N8N_BASE_URL: str = ""
    N8N_API_KEY: str = ""
    N8N_WEBHOOK_SECRET: str = "dev-n8n-webhook-secret"
    WEBHOOK_TIMEOUT_SECONDS: float = 10.0
    WEBHOOK_MAX_ATTEMPTS: int = 3

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def celery_enabled(self) -> bool:
        if self.CELERY_TASK_ALWAYS_EAGER or self.TASK_RUNNER == "inline":
            return False
        return bool(self.CELERY_BROKER_URL) and self.TASK_RUNNER != "inline"

    @property
    def ai_configured(self) -> bool:
        if self.AI_PROVIDER == "none":
            return False
        return not (self.AI_PROVIDER in {"openai"} and not self.AI_API_KEY)

    @property
    def embeddings_configured(self) -> bool:
        if self.AI_EMBEDDING_PROVIDER == "none":
            return False
        return not (self.AI_EMBEDDING_PROVIDER == "openai" and not self.AI_EMBEDDING_API_KEY and not self.AI_API_KEY)

    def fernet_key(self) -> bytes:
        """Derive a stable Fernet key from an explicit secret or the application secret."""
        material = self.CREDENTIAL_ENCRYPTION_KEY or self.SECRET_KEY
        digest = hashlib.sha256(material.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    def validate_runtime(self) -> list[str]:
        """Return a list of configuration problems that must block production startup."""
        problems: list[str] = []
        if self.is_production:
            if self.SECRET_KEY.startswith("dev-only"):
                problems.append("SECRET_KEY must be set to a strong random value in production")
            if "*" in self.cors_origins:
                problems.append("CORS_ORIGINS must not contain '*' in production")
            if self.is_sqlite:
                problems.append("DATABASE_URL must point to PostgreSQL in production")
            if self.DEBUG:
                problems.append("DEBUG must be false in production")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Ensure base directories exist for the local development configuration.
Path(settings.STORAGE_LOCAL_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.EMAIL_SINK_DIR).mkdir(parents=True, exist_ok=True)
if settings.is_sqlite:
    Path(settings.DATABASE_URL.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)


__all__ = ["Settings", "get_settings", "settings", "API_DIR", "REPO_ROOT", "Field"]
