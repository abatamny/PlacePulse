from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import FastAPI, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from placepulse.api.errors import DomainError
from placepulse.api.features import install_feature_routes, trusted_client_ip
from placepulse.auth import AuthService
from placepulse.config import Settings, get_settings
from placepulse.database import DatabaseClient
from placepulse.location import LocationService
from placepulse.logging import configure_logging, request_id_context
from placepulse.redis_client import RedisClient
from placepulse.security import PasswordService
from placepulse.verification import DisabledVerificationProvider, VerificationProvider

logger = logging.getLogger(__name__)


class HealthClient(Protocol):
    async def ping(self) -> None: ...
    async def close(self) -> None: ...


@dataclass
class ServiceClients:
    postgres: HealthClient
    redis: HealthClient

    async def close(self) -> None:
        await asyncio.gather(self.postgres.close(), self.redis.close())


@dataclass
class FeatureServices:
    auth: AuthService
    location: LocationService
    verification: VerificationProvider


ClientFactory = Callable[[Settings], ServiceClients]


def _default_client_factory(settings: Settings) -> ServiceClients:
    return ServiceClients(postgres=DatabaseClient(settings), redis=RedisClient(settings))


def _request_id(raw_value: str | None) -> str:
    if raw_value is not None:
        try:
            return str(uuid.UUID(raw_value))
        except (ValueError, AttributeError):
            pass
    return str(uuid.uuid4())


async def _dependency_state(client: HealthClient, timeout_seconds: float) -> str:
    try:
        async with asyncio.timeout(timeout_seconds):
            await client.ping()
    except Exception:
        return "unavailable"
    return "ok"


def create_app(
    *,
    settings: Settings | None = None,
    clients: ServiceClients | None = None,
    feature_services: FeatureServices | None = None,
    client_factory: ClientFactory = _default_client_factory,
) -> FastAPI:
    active_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging(active_settings.log_level, active_settings.env)
        active_clients = clients or client_factory(active_settings)
        application.state.settings = active_settings
        application.state.clients = active_clients
        if feature_services is not None:
            application.state.auth_service = feature_services.auth
            application.state.location_service = feature_services.location
            application.state.verification_provider = feature_services.verification
        elif isinstance(active_clients.postgres, DatabaseClient) and isinstance(
            active_clients.redis, RedisClient
        ):
            passwords = PasswordService()
            application.state.auth_service = AuthService(
                active_clients.postgres.engine,
                active_clients.redis.client,
                active_settings,
                passwords,
            )
            application.state.location_service = LocationService(
                active_clients.postgres.engine, active_settings
            )
            application.state.verification_provider = DisabledVerificationProvider()
        try:
            yield
        finally:
            await active_clients.close()

    application = FastAPI(
        title="PlacePulse API",
        version="0.1.0",
        root_path="/api",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def correlation_and_logging(request: Request, call_next: Callable[[Request], Any]) -> Any:
        request_id = _request_id(request.headers.get("X-Request-ID"))
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            route = request.scope.get("route")
            route_template = getattr(route, "path", "unmatched")
            logger.info(
                "request completed",
                extra={
                    "event": "http_request",
                    "method": request.method,
                    "route": route_template,
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_context.reset(token)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        del request
        details = [
            {"field": ".".join(str(part) for part in item["loc"]), "code": item["type"]}
            for item in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The request is invalid.",
                    "details": details,
                },
                "request_id": request_id_context.get(),
            },
            headers={"Cache-Control": "no-store"},
        )

    @application.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        del request
        headers = {"Cache-Control": "no-store"}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
                "request_id": request_id_context.get(),
            },
            headers=headers,
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        del request
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        message = (
            "The requested resource was not found."
            if exc.status_code == 404
            else "The request failed."
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": code, "message": message, "details": None},
                "request_id": request_id_context.get(),
            },
            headers={"Cache-Control": "no-store"},
        )

    @application.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        del request, exc
        logger.error("unhandled request exception", extra={"event": "unhandled_request_error"})
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal error occurred.",
                    "details": None,
                },
                "request_id": request_id_context.get(),
            },
            headers={"Cache-Control": "no-store"},
        )

    @application.get("/health/live", include_in_schema=True)
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready", include_in_schema=True)
    async def ready(request: Request) -> JSONResponse:
        active_settings: Settings = request.app.state.settings
        active_clients: ServiceClients = request.app.state.clients
        postgres_state, redis_state = await asyncio.gather(
            _dependency_state(active_clients.postgres, active_settings.readiness_timeout_seconds),
            _dependency_state(active_clients.redis, active_settings.readiness_timeout_seconds),
        )

        ready_now = postgres_state == redis_state == "ok"
        return JSONResponse(
            status_code=200 if ready_now else 503,
            content={
                "status": "ready" if ready_now else "unavailable",
                "dependencies": {"postgres": postgres_state, "redis": redis_state},
            },
        )

    install_feature_routes(application)

    if active_settings.env == "test":

        @application.post("/_test/body")
        async def request_body_transport_probe(request: Request) -> dict[str, int]:
            body = await request.body()
            return {"size": len(body)}

        @application.get("/_test/client-ip")
        async def client_ip_transport_probe(request: Request) -> dict[str, str]:
            return {"client_ip": trusted_client_ip(request)}

        @application.websocket("/ws/_test/echo")
        async def websocket_transport_probe(websocket: WebSocket) -> None:
            await websocket.accept()
            message = await websocket.receive_text()
            if len(message) > 128:
                await websocket.close(code=1009)
                return
            await websocket.send_text(message)
            await websocket.close(code=1000)

    return application


app = create_app()
