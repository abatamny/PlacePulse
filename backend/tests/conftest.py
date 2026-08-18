from __future__ import annotations

from pathlib import Path

import pytest

from placepulse.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    postgres_secret = tmp_path / "postgres_password"
    redis_secret = tmp_path / "redis_password"
    seed_secret = tmp_path / "seed_password"
    postgres_secret.write_text("test-postgres-password\n", encoding="utf-8")
    redis_secret.write_text("test-redis-password\n", encoding="utf-8")
    seed_secret.write_text("test-seed-password-long\n", encoding="utf-8")
    return Settings(
        env="test",
        postgres_password_file=postgres_secret,
        redis_password_file=redis_secret,
        seed_password_file=seed_secret,
        readiness_timeout_seconds=0.02,
    )
