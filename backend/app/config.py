from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-secret-change-me-in-production"
# `neon env pull` writes DATABASE_URL to .env.local in the repo root.
NEON_ENV_FILE = Path(__file__).resolve().parents[2] / ".env.local"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(NEON_ENV_FILE, ".env"), env_prefix="GAUGE_", extra="ignore"
    )

    # "production" refuses to start with the development JWT secret.
    environment: str = "development"
    # GAUGE_DATABASE_URL wins; otherwise Neon's DATABASE_URL (its pooled connection).
    database_url: str = Field(
        "postgresql+psycopg://gauge:gauge@localhost:5432/gauge",
        validation_alias=AliasChoices("GAUGE_DATABASE_URL", "DATABASE_URL"),
    )
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
    cors_origins: list[str] = ["http://localhost:5173"]
    # The built frontend (frontend/dist). When set, the API serves it too, so one
    # service hosts the whole app on one origin.
    frontend_dist: Path | None = None
    # Largest item upload accepted, in bytes.
    max_upload_bytes: int = 5 * 1024 * 1024

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> "Settings":
        if self.environment == "production" and self.jwt_secret == DEV_JWT_SECRET:
            raise ValueError("Set GAUGE_JWT_SECRET: the development secret is not allowed")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
