from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from placepulse.bootstrap import SEED_VERSION, apply_seed
from placepulse.config import get_settings

pytestmark = pytest.mark.integration


def test_alembic_upgrade_is_idempotent() -> None:
    settings = get_settings()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["database_url"] = settings.database_url
    command.upgrade(config, "head")


@pytest.mark.asyncio
async def test_postgis_seed_and_bootstrap_rerun_are_stable(tmp_path: Path) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            extension = await connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
            )
            before = (
                await connection.scalar(text("SELECT count(*) FROM users")),
                await connection.scalar(text("SELECT count(*) FROM places")),
                await connection.scalar(text("SELECT count(*) FROM forum_posts")),
                await connection.scalar(text("SELECT count(*) FROM forum_comments")),
                await connection.scalar(
                    text("SELECT count(*) FROM seed_registry WHERE seed_version = :version"),
                    {"version": SEED_VERSION},
                ),
                await connection.scalar(
                    text("SELECT password_hash FROM users ORDER BY id LIMIT 1")
                ),
                await connection.scalar(text("SELECT count(DISTINCT password_hash) FROM users")),
                await connection.scalar(text("SELECT body FROM forum_posts ORDER BY id LIMIT 1")),
            )
            covers = await connection.scalar(
                text(
                    "SELECT ST_Covers(boundary, ST_SetSRID(ST_Point(35.021595, 32.777691), 4326)) "
                    "FROM places WHERE osm_type = 'way' AND osm_id = 66098525"
                )
            )
        assert extension is not None
        assert before[:5] == (3, 1, 2, 3, 1)
        assert covers is True
        assert isinstance(before[5], str) and before[5].startswith("$argon2id$")
        assert before[6] == 3
        PasswordHasher().verify(before[5], settings.seed_password)
        assert await apply_seed(settings) is False
        changed_seed_secret = tmp_path / "changed_seed_password"
        changed_seed_secret.write_text("a-different-seed-password\n", encoding="utf-8")
        changed_settings = settings.model_copy(update={"seed_password_file": changed_seed_secret})
        assert await apply_seed(changed_settings) is False
        async with engine.connect() as connection:
            after = (
                await connection.scalar(text("SELECT count(*) FROM users")),
                await connection.scalar(text("SELECT count(*) FROM places")),
                await connection.scalar(text("SELECT count(*) FROM forum_posts")),
                await connection.scalar(text("SELECT count(*) FROM forum_comments")),
                await connection.scalar(
                    text("SELECT count(*) FROM seed_registry WHERE seed_version = :version"),
                    {"version": SEED_VERSION},
                ),
                await connection.scalar(
                    text("SELECT password_hash FROM users ORDER BY id LIMIT 1")
                ),
                await connection.scalar(text("SELECT count(DISTINCT password_hash) FROM users")),
                await connection.scalar(text("SELECT body FROM forum_posts ORDER BY id LIMIT 1")),
            )
        assert after == before
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_redis_authenticated_connectivity() -> None:
    settings = get_settings()
    client = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        username=settings.redis_user,
        password=settings.redis_password,
        decode_responses=True,
    )
    try:
        assert await client.ping() is True
        await client.set("placepulse:test:connectivity", "ok", ex=60)
        assert await client.get("placepulse:test:connectivity") == "ok"
    finally:
        await client.delete("placepulse:test:connectivity")
        await client.aclose()
