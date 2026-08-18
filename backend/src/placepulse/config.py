from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


def read_secret(path: Path, name: str) -> str:
    try:
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
    except OSError as exc:
        raise RuntimeError(f"Required secret file for {name} is unavailable") from exc
    if not value:
        raise RuntimeError(f"Required secret {name} is empty")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLACEPULSE_", extra="ignore")

    env: Literal["local", "test", "azure"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    postgres_host: str = "postgres"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = Field(default="placepulse", min_length=1, max_length=63)
    postgres_user: str = Field(default="placepulse", min_length=1, max_length=63)
    postgres_password_file: Path = Path("/run/secrets/postgres_password")

    redis_host: str = "redis"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_user: str = Field(default="placepulse", min_length=1, max_length=64)
    redis_password_file: Path = Path("/run/secrets/redis_password")

    seed_password_file: Path = Path("/run/secrets/seed_password")
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=5, ge=0, le=20)
    redis_pool_size: int = Field(default=20, ge=1, le=100)
    connect_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    readiness_timeout_seconds: float = Field(default=1.0, gt=0, le=5)
    session_ttl_seconds: int = Field(default=43_200, ge=300, le=604_800)
    max_location_accuracy_meters: float = Field(default=100.0, gt=0, le=1_000)

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=read_secret(self.postgres_password_file, "postgres_password"),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def redis_password(self) -> str:
        return read_secret(self.redis_password_file, "redis_password")

    @property
    def seed_password(self) -> str:
        return read_secret(self.seed_password_file, "seed_password")


@lru_cache
def get_settings() -> Settings:
    return Settings()
