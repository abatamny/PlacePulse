from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from fastapi import FastAPI

from placepulse.api.app import ServiceClients, create_app
from placepulse.config import Settings


class FakeClient:
    def __init__(self, *, fails: bool = False, delay: float = 0) -> None:
        self.fails = fails
        self.delay = delay
        self.pings = 0
        self.closed = False

    async def ping(self) -> None:
        self.pings += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fails:
            raise ConnectionError("internal-host:1234 secret diagnostic")

    async def close(self) -> None:
        self.closed = True


async def _get(app: FastAPI, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, headers=headers)


@pytest.mark.asyncio
async def test_liveness_is_dependency_free_and_sets_request_id(settings: Settings) -> None:
    postgres = FakeClient(fails=True)
    redis = FakeClient(fails=True)
    app = create_app(settings=settings, clients=ServiceClients(postgres, redis))
    response = await _get(app, "/health/live", {"X-Request-ID": "not-a-uuid"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    generated = uuid.UUID(response.headers["X-Request-ID"])
    assert generated.version == 4
    assert postgres.pings == redis.pings == 0
    assert postgres.closed and redis.closed


@pytest.mark.asyncio
async def test_readiness_reports_only_sanitized_dependency_states(settings: Settings) -> None:
    app = create_app(
        settings=settings,
        clients=ServiceClients(FakeClient(), FakeClient(fails=True)),
    )
    response = await _get(app, "/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {"postgres": "ok", "redis": "unavailable"},
    }
    assert "internal-host" not in response.text
    assert "secret" not in response.text


@pytest.mark.asyncio
async def test_readiness_bounds_each_dependency(settings: Settings) -> None:
    app = create_app(
        settings=settings,
        clients=ServiceClients(FakeClient(delay=0.1), FakeClient()),
    )
    response = await _get(app, "/health/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"] == {"postgres": "unavailable", "redis": "ok"}


@pytest.mark.asyncio
async def test_readiness_recovers_without_restarting_the_api(settings: Settings) -> None:
    redis = FakeClient(fails=True)
    app = create_app(settings=settings, clients=ServiceClients(FakeClient(), redis))
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            unavailable = await client.get("/health/ready")
            redis.fails = False
            recovered = await client.get("/health/ready")
    assert unavailable.status_code == 503
    assert recovered.status_code == 200
    assert recovered.json() == {
        "status": "ready",
        "dependencies": {"postgres": "ok", "redis": "ok"},
    }


@pytest.mark.asyncio
async def test_valid_request_id_is_normalized_and_error_envelope_is_stable(
    settings: Settings,
) -> None:
    request_id = uuid.uuid4()
    app = create_app(settings=settings, clients=ServiceClients(FakeClient(), FakeClient()))
    response = await _get(app, "/missing", {"X-Request-ID": str(request_id).upper()})
    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == str(request_id)
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "The requested resource was not found.",
            "details": None,
        },
        "request_id": str(request_id),
    }


@pytest.mark.asyncio
async def test_unhandled_errors_never_expose_internal_details(settings: Settings) -> None:
    app = create_app(settings=settings, clients=ServiceClients(FakeClient(), FakeClient()))

    @app.get("/_test/failure", include_in_schema=False)
    async def failure() -> None:
        raise RuntimeError("postgres:5432 password=leak latitude=32.777691")

    response = await _get(app, "/_test/failure")
    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "An internal error occurred.",
        "details": None,
    }
    assert "postgres" not in response.text
    assert "password" not in response.text
    assert "32.777691" not in response.text
