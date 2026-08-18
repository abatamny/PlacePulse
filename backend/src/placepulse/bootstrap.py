from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from argon2.low_level import Type
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from placepulse.config import Settings, get_settings
from placepulse.logging import configure_logging

logger = logging.getLogger(__name__)

SEED_VERSION = "milestone-2-v1"
SEED_NAMESPACE = uuid.UUID("43becc55-8672-4d1d-a0a2-169922b93d6d")
ADVISORY_LOCK_ID = 5_540_557_365_127_650_372
TECHNION_OSM_ID = 66_098_525
FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "osm" / "technion-way-66098525-v35.geojson"
)
SEED_TIME = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)


def seed_uuid(label: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, label)


def load_and_validate_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    try:
        feature: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("The reviewed Technion OSM fixture is unavailable or malformed") from exc

    properties = feature.get("properties", {})
    geometry = feature.get("geometry", {})
    if (
        feature.get("type") != "Feature"
        or properties.get("osm_type") != "way"
        or properties.get("osm_id") != TECHNION_OSM_ID
        or properties.get("osm_version") != 35
        or geometry.get("type") != "Polygon"
    ):
        raise RuntimeError("The Technion OSM fixture identity or geometry type is invalid")

    rings = geometry.get("coordinates")
    if (
        not isinstance(rings, list)
        or len(rings) != 1
        or not isinstance(rings[0], list)
        or len(rings[0]) < 4
    ):
        raise RuntimeError("The Technion OSM fixture must contain one non-empty exterior ring")
    ring = rings[0]
    if ring[0] != ring[-1]:
        raise RuntimeError("The Technion OSM boundary ring is not closed")
    for coordinate in ring:
        if (
            not isinstance(coordinate, list)
            or len(coordinate) != 2
            or not all(isinstance(value, int | float) for value in coordinate)
            or not -180 <= coordinate[0] <= 180
            or not -90 <= coordinate[1] <= 90
        ):
            raise RuntimeError(
                "The Technion OSM fixture contains an invalid longitude/latitude pair"
            )
    return feature


async def _is_seeded(connection: AsyncConnection) -> bool:
    result = await connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM seed_registry WHERE seed_version = :version)"),
        {"version": SEED_VERSION},
    )
    return bool(result.scalar_one())


async def apply_seed(settings: Settings) -> bool:
    feature = load_and_validate_fixture()
    engine = create_async_engine(
        settings.database_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=settings.connect_timeout_seconds,
        connect_args={"timeout": settings.connect_timeout_seconds, "command_timeout": 30},
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": ADVISORY_LOCK_ID}
            )
            if await _is_seeded(connection):
                return False

            password = settings.seed_password
            if len(password) < 12:
                raise RuntimeError("The seed password must contain at least 12 characters")

            geometry_json = json.dumps(feature["geometry"], separators=(",", ":"))
            geometry_valid = await connection.scalar(
                text(
                    "SELECT ST_IsValid(ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)))"
                ),
                {"geometry": geometry_json},
            )
            if geometry_valid is not True:
                raise RuntimeError("PostGIS rejected the Technion campus boundary as invalid")

            hasher = PasswordHasher(
                time_cost=3,
                memory_cost=65_536,
                parallelism=4,
                hash_len=32,
                salt_len=16,
                type=Type.ID,
            )
            users = (
                (seed_uuid("user-nora"), "nora_campus", "nora@placepulse.invalid"),
                (seed_uuid("user-sami"), "sami_campus", "sami@placepulse.invalid"),
                (seed_uuid("user-lina"), "lina_campus", "lina@placepulse.invalid"),
            )
            for user_id, handle, email in users:
                await connection.execute(
                    text(
                        "INSERT INTO users (id, handle, email, password_hash, created_at) "
                        "VALUES (:id, :handle, :email, :password_hash, :created_at) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "id": user_id,
                        "handle": handle,
                        "email": email,
                        "password_hash": hasher.hash(password),
                        "created_at": SEED_TIME,
                    },
                )

            place_id = seed_uuid("place-technion-campus")
            await connection.execute(
                text(
                    "INSERT INTO places "
                    "(id, osm_type, osm_id, osm_version, name, parent_place_id, "
                    "boundary, source_metadata, created_at) "
                    "VALUES (:id, 'way', :osm_id, 35, :name, NULL, "
                    "ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)), "
                    "CAST(:metadata AS jsonb), :created_at) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "id": place_id,
                    "osm_id": TECHNION_OSM_ID,
                    "name": feature["properties"]["name_en"],
                    "geometry": geometry_json,
                    "metadata": json.dumps(feature["properties"], ensure_ascii=False),
                    "created_at": SEED_TIME,
                },
            )

            posts = (
                (
                    seed_uuid("post-welcome"),
                    users[0][0],
                    "Welcome to the fictional PlacePulse campus forum.",
                ),
                (
                    seed_uuid("post-study"),
                    users[1][0],
                    "What is your favorite quiet study spot on campus?",
                ),
            )
            for post_id, author_id, body in posts:
                await connection.execute(
                    text(
                        "INSERT INTO forum_posts (id, place_id, author_id, body, created_at) "
                        "VALUES (:id, :place_id, :author_id, :body, :created_at) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "id": post_id,
                        "place_id": place_id,
                        "author_id": author_id,
                        "body": body,
                        "created_at": SEED_TIME,
                    },
                )

            comments = (
                (
                    seed_uuid("comment-welcome-1"),
                    posts[0][0],
                    users[1][0],
                    "Glad to be part of this fictional seed community.",
                ),
                (
                    seed_uuid("comment-welcome-2"),
                    posts[0][0],
                    users[2][0],
                    "Hello from another clearly fictional account.",
                ),
                (
                    seed_uuid("comment-study-1"),
                    posts[1][0],
                    users[0][0],
                    "The shaded outdoor tables are my fictional pick.",
                ),
            )
            for comment_id, post_id, author_id, body in comments:
                await connection.execute(
                    text(
                        "INSERT INTO forum_comments (id, post_id, author_id, body, created_at) "
                        "VALUES (:id, :post_id, :author_id, :body, :created_at) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "id": comment_id,
                        "post_id": post_id,
                        "author_id": author_id,
                        "body": body,
                        "created_at": SEED_TIME,
                    },
                )

            await connection.execute(
                text(
                    "INSERT INTO seed_registry (seed_version, applied_at, metadata) "
                    "VALUES (:version, :applied_at, CAST(:metadata AS jsonb)) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "version": SEED_VERSION,
                    "applied_at": SEED_TIME,
                    "metadata": json.dumps({"osm_way": TECHNION_OSM_ID, "osm_version": 35}),
                },
            )
            return True
    finally:
        await engine.dispose()


def run_migrations(settings: Settings) -> None:
    configuration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    configuration.attributes["configure_logger"] = False
    configuration.set_main_option(
        "sqlalchemy.url", settings.database_url.render_as_string(hide_password=False)
    )
    command.upgrade(configuration, "head")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.env, "placepulse-bootstrap")
    logger.info("bootstrap started", extra={"event": "bootstrap_started"})
    run_migrations(settings)
    seeded = asyncio.run(apply_seed(settings))
    logger.info(
        "bootstrap completed",
        extra={"event": "bootstrap_completed", "seed_applied": seeded},
    )


if __name__ == "__main__":
    main()
