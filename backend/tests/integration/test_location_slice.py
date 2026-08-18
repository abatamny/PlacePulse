from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from placepulse.api.app import create_app
from placepulse.api.errors import DomainError
from placepulse.auth import AuthService
from placepulse.config import get_settings
from placepulse.database import DatabaseClient
from placepulse.location import LocationService
from placepulse.redis_client import RedisClient
from placepulse.security import PasswordService, token_digest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_registration_session_nested_location_and_visit_transitions() -> None:
    settings = get_settings()
    suffix = uuid.uuid4().hex[:12]
    email = f"M4-{suffix}@Example.COM"
    normalized_email = email.casefold()
    handle = f"M4_{suffix}"
    password = "milestone-four-test-password"
    client_ip = f"2001:db8:{suffix[:4]}:{suffix[4:8]}:{suffix[8:12]}::1"
    app = create_app(settings=settings)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            session = await client.get("/auth/session")
            csrf = session.json()["data"]["csrf_token"]
            headers = {"X-CSRF-Token": csrf, "X-PlacePulse-Client-IP": client_ip}
            registration = await client.post(
                "/auth/register",
                headers=headers,
                json={"handle": handle, "email": email, "password": password},
            )
            assert registration.status_code == 201
            user_id = registration.json()["data"]["user"]["id"]
            assert registration.json()["data"]["user"]["email"] == normalized_email
            assert registration.json()["data"]["user"]["handle"] == handle
            assert registration.json()["data"]["user"]["verification"] == {
                "status": "pending_provider_configuration",
                "login_allowed": True,
            }
            duplicate_registration = await client.post(
                "/auth/register",
                headers=headers,
                json={"handle": handle, "email": email, "password": password},
            )
            assert duplicate_registration.status_code == 409
            assert duplicate_registration.json()["error"]["code"] == "ACCOUNT_UNAVAILABLE"

            bad_login = await client.post(
                "/auth/login",
                headers=headers,
                json={"email": "missing@example.com", "password": password},
            )
            assert bad_login.status_code == 401
            assert bad_login.json()["error"]["code"] == "INVALID_CREDENTIALS"

            wrong_password = await client.post(
                "/auth/login",
                headers=headers,
                json={"email": normalized_email, "password": "wrong-password"},
            )
            assert wrong_password.status_code == bad_login.status_code
            assert wrong_password.json()["error"] == bad_login.json()["error"]

            login = await client.post(
                "/auth/login",
                headers=headers,
                json={"email": email, "password": password},
            )
            assert login.status_code == 200
            assert any(
                "HttpOnly" in cookie
                for cookie in login.headers.get_list("set-cookie")
                if cookie.startswith("placepulse_session=")
            )
            redis_client = app.state.clients.redis
            assert isinstance(redis_client, RedisClient)
            session_token = client.cookies.get("placepulse_session")
            assert session_token is not None
            session_key = f"placepulse:session:{token_digest(session_token)}"
            session_ttl = await redis_client.client.ttl(session_key)
            assert settings.session_ttl_seconds - 5 <= session_ttl <= settings.session_ttl_seconds

            rotated_login = await client.post(
                "/auth/login",
                headers=headers,
                json={"email": email, "password": password},
            )
            assert rotated_login.status_code == 200
            assert await redis_client.client.get(session_key) is None
            rotated_token = client.cookies.get("placepulse_session")
            assert rotated_token is not None and rotated_token != session_token
            rotated_key = f"placepulse:session:{token_digest(rotated_token)}"

            location_payload = {
                "latitude": 32.77768,
                "longitude": 35.02152,
                "accuracy_meters": 2,
            }
            first, duplicate = await asyncio.gather(
                client.post("/location/resolve", headers=headers, json=location_payload),
                client.post("/location/resolve", headers=headers, json=location_payload),
            )
            assert first.status_code == duplicate.status_code == 200
            first_data = first.json()["data"]
            duplicate_data = duplicate.json()["data"]
            assert first_data["status"] == "resolved"
            assert first_data["selected_place"]["osm_id"] == 67_222_155
            assert [place["osm_id"] for place in first_data["containment_path"]] == [
                67_222_155,
                66_098_525,
            ]
            assert first_data["visit"]["id"] == duplicate_data["visit"]["id"]
            assert "latitude" not in str(first.json())
            assert "longitude" not in str(first.json())

            low_accuracy = await client.post(
                "/location/resolve",
                headers=headers,
                json={**location_payload, "accuracy_meters": 101},
            )
            assert low_accuracy.json()["data"]["status"] == "low_accuracy"
            current = await client.get("/location/current")
            assert current.json()["data"]["visit"]["id"] == first_data["visit"]["id"]

            parent_fallback = await client.post(
                "/location/resolve",
                headers=headers,
                json={
                    "latitude": 32.7776444,
                    "longitude": 35.0211146,
                    "accuracy_meters": 2,
                },
            )
            fallback_data = parent_fallback.json()["data"]
            assert fallback_data["status"] == "resolved"
            assert fallback_data["selected_place"]["osm_id"] == 66_098_525
            assert [place["osm_id"] for place in fallback_data["uncertain_places"]] == [67_222_155]
            assert fallback_data["visit"]["id"] != first_data["visit"]["id"]

            ambiguous = await client.post(
                "/location/resolve",
                headers=headers,
                json={
                    "latitude": 32.7784636,
                    "longitude": 35.0152537,
                    "accuracy_meters": 2,
                },
            )
            assert ambiguous.json()["data"]["status"] == "ambiguous"
            current = await client.get("/location/current")
            assert current.json()["data"]["visit"]["id"] == fallback_data["visit"]["id"]

            unknown = await client.post(
                "/location/resolve",
                headers=headers,
                json={"latitude": 0, "longitude": 0, "accuracy_meters": 5},
            )
            assert unknown.json()["data"]["status"] == "unknown"
            assert (await client.get("/location/current")).json()["data"]["status"] == "inactive"

            assert await redis_client.client.pexpire(rotated_key, 50) is True
            await asyncio.sleep(0.1)
            expired = await client.get("/location/current")
            assert expired.status_code == 401
            assert expired.json()["error"]["code"] == "AUTH_REQUIRED"

            logout = await client.post("/auth/logout", headers=headers)
            assert logout.status_code == 200
            assert await redis_client.client.get(rotated_key) is None
            assert client.cookies.get("placepulse_session") is None
            assert client.cookies.get("placepulse_csrf") is None
            unauthorized = await client.get("/location/current")
            assert unauthorized.status_code == 401

        database = app.state.clients.postgres
        assert isinstance(database, DatabaseClient)
        async with database.engine.begin() as connection:
            visits = await connection.scalar(
                text("SELECT count(*) FROM visits WHERE user_id = :user_id"),
                {"user_id": uuid.UUID(user_id)},
            )
            active = await connection.scalar(
                text("SELECT count(*) FROM visits WHERE user_id = :user_id AND exited_at IS NULL"),
                {"user_id": uuid.UUID(user_id)},
            )
            assert visits == 2
            assert active == 0
            await connection.execute(
                text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": uuid.UUID(user_id)},
            )


@pytest.mark.asyncio
async def test_postgis_accuracy_boundaries_and_unrelated_overlap() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    user_id = uuid.uuid4()
    overlap_id = uuid.uuid4()
    service = LocationService(engine, settings)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, handle, email, password_hash) "
                    "VALUES (:id, :handle, :email, :password_hash)"
                ),
                {
                    "id": user_id,
                    "handle": f"geo_{user_id.hex[:12]}",
                    "email": f"geo-{user_id.hex[:12]}@example.test",
                    "password_hash": "integration-placeholder-hash",
                },
            )

        exact_boundary = await service.resolve(
            user_id=user_id,
            latitude=32.7776444,
            longitude=35.0211146,
            accuracy_meters=0,
        )
        assert exact_boundary.status == "resolved"
        assert exact_boundary.selected_place is not None
        assert exact_boundary.selected_place.osm_id == 67_222_155

        uncertain_child = await service.resolve(
            user_id=user_id,
            latitude=32.7776444,
            longitude=35.0211146,
            accuracy_meters=2,
        )
        assert uncertain_child.status == "resolved"
        assert uncertain_child.selected_place is not None
        assert uncertain_child.selected_place.osm_id == 66_098_525
        assert [place.osm_id for place in uncertain_child.uncertain_places] == [67_222_155]
        assert uncertain_child.selection.reason_code == "PARENT_SELECTED_FOR_ACCURACY"

        outside = await service.resolve(
            user_id=user_id,
            latitude=0,
            longitude=0,
            accuracy_meters=5,
        )
        assert outside.status == "unknown"

        campus_boundary = await service.resolve(
            user_id=user_id,
            latitude=32.7784636,
            longitude=35.0152537,
            accuracy_meters=2,
        )
        assert campus_boundary.status == "ambiguous"
        assert campus_boundary.selection.reason_code == "ACCURACY_OVERLAPS_BOUNDARY"

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO places "
                    "(id, osm_type, osm_id, osm_version, name, boundary, source_metadata) "
                    "VALUES (:id, 'way', :osm_id, 1, 'Unrelated test overlap', "
                    "ST_Multi(ST_Buffer(ST_SetSRID(ST_Point(35.02152, 32.77768), 4326)"
                    "::geography, 20)::geometry), CAST('{}' AS jsonb))"
                ),
                {"id": overlap_id, "osm_id": 9_000_000_000 + user_id.int % 100_000_000},
            )
        overlap = await service.resolve(
            user_id=user_id,
            latitude=32.77768,
            longitude=35.02152,
            accuracy_meters=2,
        )
        assert overlap.status == "ambiguous"
        assert overlap.selection.reason_code == "OVERLAPPING_PLACE_HIERARCHIES"
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            await connection.execute(text("DELETE FROM places WHERE id = :id"), {"id": overlap_id})
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_redis_rate_limits_are_isolated_and_atomic() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    redis = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        username=settings.redis_user,
        password=settings.redis_password,
        decode_responses=True,
    )
    scope = f"integration-{uuid.uuid4().hex}"
    service = AuthService(engine, redis, settings, PasswordService())
    try:
        await asyncio.gather(
            *(
                service.enforce_rate_limit(scope, "one-user", limit=3, window_seconds=60)
                for _ in range(3)
            )
        )
        with pytest.raises(DomainError) as rate_error:
            await service.enforce_rate_limit(scope, "one-user", limit=3, window_seconds=60)
        assert rate_error.value.code == "RATE_LIMITED"
    finally:
        keys = [key async for key in redis.scan_iter(match=f"placepulse:rate:{scope}:*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()
        await engine.dispose()
