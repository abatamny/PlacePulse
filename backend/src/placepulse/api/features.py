from __future__ import annotations

import ipaddress
import secrets
from typing import Any, cast

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from placepulse.api.errors import DomainError
from placepulse.api.schemas import (
    LocationData,
    LocationRequest,
    LoginRequest,
    LogoutData,
    RegisterRequest,
    RegistrationData,
    SessionData,
    SuccessEnvelope,
    UserView,
)
from placepulse.auth import AuthService
from placepulse.location import LocationService
from placepulse.logging import request_id_context
from placepulse.security import new_opaque_token

SESSION_COOKIE = "placepulse_session"
CSRF_COOKIE = "placepulse_csrf"


def _serialized_data(data: BaseModel) -> dict[str, Any]:
    return data.model_dump(mode="json")


def success_response(data: BaseModel, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "data": _serialized_data(data),
            "meta": {"schema_version": 1},
            "request_id": request_id_context.get(),
        },
        headers={"Cache-Control": "no-store"},
    )


def _secure_cookie(request: Request) -> bool:
    forwarded = request.headers.get("X-Forwarded-Proto", "").split(",", maxsplit=1)[0].strip()
    return (
        request.app.state.settings.env == "azure"
        or request.url.scheme == "https"
        or forwarded == "https"
    )


def _set_csrf_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        CSRF_COOKIE,
        token,
        max_age=request.app.state.settings.session_ttl_seconds,
        secure=_secure_cookie(request),
        httponly=False,
        samesite="lax",
        path="/",
    )


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=request.app.state.settings.session_ttl_seconds,
        secure=_secure_cookie(request),
        httponly=True,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        secure=_secure_cookie(request),
        httponly=True,
        samesite="lax",
        path="/",
    )


def _clear_csrf_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        CSRF_COOKIE,
        secure=_secure_cookie(request),
        httponly=False,
        samesite="lax",
        path="/",
    )


def _require_csrf(request: Request) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE)
    header_token = request.headers.get("X-CSRF-Token")
    if (
        cookie_token is None
        or header_token is None
        or not secrets.compare_digest(cookie_token, header_token)
    ):
        raise DomainError(403, "CSRF_FAILED", "The request could not be verified.")


def trusted_client_ip(request: Request) -> str:
    candidate = request.headers.get("X-PlacePulse-Client-IP")
    if candidate is None and request.client is not None:
        candidate = request.client.host
    try:
        return str(ipaddress.ip_address(candidate or "127.0.0.1"))
    except ValueError:
        return "127.0.0.1"


def _auth(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise DomainError(503, "SERVICE_UNAVAILABLE", "Authentication is unavailable.")
    return cast(AuthService, service)


def _location(request: Request) -> LocationService:
    service = getattr(request.app.state, "location_service", None)
    if service is None:
        raise DomainError(503, "SERVICE_UNAVAILABLE", "Location services are unavailable.")
    return cast(LocationService, service)


async def _current_user(request: Request) -> UserView:
    user = await _auth(request).session_user(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise DomainError(401, "AUTH_REQUIRED", "Authentication is required.")
    return user


def install_feature_routes(application: FastAPI) -> None:
    @application.get("/auth/session", response_model=SuccessEnvelope[SessionData])
    async def session(request: Request) -> JSONResponse:
        session_token = request.cookies.get(SESSION_COOKIE)
        user = await _auth(request).session_user(session_token)
        csrf_token = request.cookies.get(CSRF_COOKIE) or new_opaque_token()
        response = success_response(
            SessionData(authenticated=user is not None, user=user, csrf_token=csrf_token)
        )
        _set_csrf_cookie(response, request, csrf_token)
        if session_token is not None and user is None:
            _clear_session_cookie(response, request)
        return response

    @application.post(
        "/auth/register",
        response_model=SuccessEnvelope[RegistrationData],
        status_code=201,
    )
    async def register(payload: RegisterRequest, request: Request) -> JSONResponse:
        _require_csrf(request)
        user = await _auth(request).register(
            handle=payload.handle,
            email=str(payload.email),
            password=payload.password.get_secret_value(),
            client_ip=trusted_client_ip(request),
        )
        return success_response(RegistrationData(user=user), status_code=201)

    @application.post("/auth/login", response_model=SuccessEnvelope[SessionData])
    async def login(payload: LoginRequest, request: Request) -> JSONResponse:
        _require_csrf(request)
        result = await _auth(request).login(
            email=str(payload.email),
            password=payload.password.get_secret_value(),
            client_ip=trusted_client_ip(request),
        )
        await _auth(request).revoke_session(request.cookies.get(SESSION_COOKIE))
        csrf_token = request.cookies.get(CSRF_COOKIE) or new_opaque_token()
        response = success_response(
            SessionData(authenticated=True, user=result.user, csrf_token=csrf_token)
        )
        _set_session_cookie(response, request, result.token)
        _set_csrf_cookie(response, request, csrf_token)
        return response

    @application.post("/auth/logout", response_model=SuccessEnvelope[LogoutData])
    async def logout(request: Request) -> JSONResponse:
        _require_csrf(request)
        token = request.cookies.get(SESSION_COOKIE)
        user = await _auth(request).session_user(token)
        if user is not None:
            await _location(request).leave(user.id)
        await _auth(request).revoke_session(token)
        response = success_response(LogoutData())
        _clear_session_cookie(response, request)
        _clear_csrf_cookie(response, request)
        return response

    @application.get("/location/current", response_model=SuccessEnvelope[LocationData])
    async def current_location(request: Request) -> JSONResponse:
        user = await _current_user(request)
        return success_response(await _location(request).current(user.id))

    @application.post("/location/resolve", response_model=SuccessEnvelope[LocationData])
    async def resolve_location(payload: LocationRequest, request: Request) -> JSONResponse:
        _require_csrf(request)
        user = await _current_user(request)
        await _auth(request).enforce_rate_limit(
            "location-user", str(user.id), limit=12, window_seconds=60
        )
        result = await _location(request).resolve(
            user_id=user.id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            accuracy_meters=payload.accuracy_meters,
        )
        return success_response(result)

    @application.post("/location/leave", response_model=SuccessEnvelope[LocationData])
    async def leave_location(request: Request) -> JSONResponse:
        _require_csrf(request)
        user = await _current_user(request)
        await _auth(request).enforce_rate_limit(
            "location-user", str(user.id), limit=12, window_seconds=60
        )
        return success_response(await _location(request).leave(user.id))
