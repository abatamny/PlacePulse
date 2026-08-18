from __future__ import annotations

from typing import Any, cast

import httpx

from placepulse.api.app import FeatureServices, ServiceClients, create_app
from placepulse.api.schemas import LocationData, UserView, VerificationView
from placepulse.auth import AuthService, SessionResult
from placepulse.config import Settings
from placepulse.location import LocationService
from placepulse.verification import DisabledVerificationProvider


class FakeHealthClient:
    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeAuthService:
    def __init__(self, user: UserView | None = None) -> None:
        self.user = user
        self.registration_headers_seen = False
        self.revoked_tokens: list[str | None] = []
        self.rate_limit_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def session_user(self, token: str | None) -> UserView | None:
        del token
        return self.user

    async def register(self, **values: Any) -> UserView:
        del values
        assert self.user is not None
        return self.user

    async def login(self, **values: Any) -> SessionResult:
        del values
        assert self.user is not None
        return SessionResult(token="opaque-session-token", user=self.user)  # noqa: S106

    async def revoke_session(self, token: str | None) -> None:
        self.revoked_tokens.append(token)

    async def enforce_rate_limit(self, *args: Any, **kwargs: Any) -> None:
        self.rate_limit_calls.append((args, kwargs))


class FakeLocationService:
    @staticmethod
    def _inactive() -> LocationData:
        return LocationData.model_validate(
            {
                "status": "inactive",
                "selected_place": None,
                "containment_path": [],
                "uncertain_places": [],
                "selection": {
                    "strategy": "recorded_active_visit",
                    "reason_code": "NO_ACTIVE_VISIT",
                },
                "visit": None,
            }
        )

    async def resolve(self, **values: Any) -> LocationData:
        del values
        return self._inactive()

    async def leave(self, user_id: Any) -> LocationData:
        del user_id
        return self._inactive()


def _user() -> UserView:
    return UserView(
        id="5a1f13aa-92cc-4a20-836b-6b9a7a3c5f11",
        handle="campus_user",
        email="campus@example.test",
        verification=VerificationView(status="pending_provider_configuration"),
    )


async def test_session_establishes_csrf_and_registration_requires_it(settings: Settings) -> None:
    auth = FakeAuthService(_user())
    app = create_app(
        settings=settings,
        clients=ServiceClients(FakeHealthClient(), FakeHealthClient()),
        feature_services=FeatureServices(
            cast(AuthService, auth),
            cast(LocationService, FakeLocationService()),
            DisabledVerificationProvider(),
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            session = await client.get("/auth/session")
            csrf = session.json()["data"]["csrf_token"]
            blocked = await client.post(
                "/auth/register",
                json={
                    "handle": "campus_user",
                    "email": "campus@example.test",
                    "password": "a-long-test-password",
                },
            )
            allowed = await client.post(
                "/auth/register",
                headers={"X-CSRF-Token": csrf},
                json={
                    "handle": "campus_user",
                    "email": "campus@example.test",
                    "password": "a-long-test-password",
                },
            )
    assert session.status_code == 200
    assert session.headers["Cache-Control"] == "no-store"
    assert "placepulse_csrf=" in session.headers["set-cookie"]
    assert blocked.status_code == 403
    assert blocked.headers["Cache-Control"] == "no-store"
    assert blocked.json()["error"]["code"] == "CSRF_FAILED"
    assert allowed.status_code == 201
    assert allowed.json()["data"]["user"]["verification"]["status"] == (
        "pending_provider_configuration"
    )


async def test_azure_login_uses_secure_http_only_session_cookie(settings: Settings) -> None:
    auth = FakeAuthService(_user())
    app = create_app(
        settings=settings.model_copy(update={"env": "azure"}),
        clients=ServiceClients(FakeHealthClient(), FakeHealthClient()),
        feature_services=FeatureServices(
            cast(AuthService, auth),
            cast(LocationService, FakeLocationService()),
            DisabledVerificationProvider(),
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            session = await client.get("/auth/session")
            client.cookies.set("placepulse_session", "previous-session-token")
            response = await client.post(
                "/auth/login",
                headers={"X-CSRF-Token": session.json()["data"]["csrf_token"]},
                json={"email": "campus@example.test", "password": "test-password"},
            )
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(cookie for cookie in cookies if cookie.startswith("placepulse_session="))
    assert response.status_code == 200
    assert "HttpOnly" in session_cookie
    assert "Secure" in session_cookie
    assert "SameSite=lax" in session_cookie
    assert "Domain=" not in session_cookie
    assert auth.revoked_tokens == ["previous-session-token"]


async def test_logout_revokes_session_and_clears_both_cookies(settings: Settings) -> None:
    auth = FakeAuthService(_user())
    app = create_app(
        settings=settings,
        clients=ServiceClients(FakeHealthClient(), FakeHealthClient()),
        feature_services=FeatureServices(
            cast(AuthService, auth),
            cast(LocationService, FakeLocationService()),
            DisabledVerificationProvider(),
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            session = await client.get("/auth/session")
            csrf = session.json()["data"]["csrf_token"]
            client.cookies.set("placepulse_session", "active-session-token")
            response = await client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert auth.revoked_tokens == ["active-session-token"]
    cleared = response.headers.get_list("set-cookie")
    assert any(
        cookie.startswith("placepulse_session=") and "Max-Age=0" in cookie for cookie in cleared
    )
    assert any(
        cookie.startswith("placepulse_csrf=") and "Max-Age=0" in cookie for cookie in cleared
    )


async def test_every_feature_post_requires_csrf(settings: Settings) -> None:
    auth = FakeAuthService(_user())
    app = create_app(
        settings=settings,
        clients=ServiceClients(FakeHealthClient(), FakeHealthClient()),
        feature_services=FeatureServices(
            cast(AuthService, auth),
            cast(LocationService, FakeLocationService()),
            DisabledVerificationProvider(),
        ),
    )
    requests = (
        (
            "/auth/register",
            {
                "handle": "campus_user",
                "email": "campus@example.test",
                "password": "a-long-test-password",
            },
        ),
        ("/auth/login", {"email": "campus@example.test", "password": "test-password"}),
        ("/auth/logout", None),
        ("/location/resolve", {"latitude": 32.77768, "longitude": 35.02152, "accuracy_meters": 5}),
        ("/location/leave", None),
    )
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            responses = [await client.post(path, json=body) for path, body in requests]
    assert [response.status_code for response in responses] == [403] * len(requests)
    assert all(response.json()["error"]["code"] == "CSRF_FAILED" for response in responses)


async def test_location_requires_authentication(settings: Settings) -> None:
    app = create_app(
        settings=settings,
        clients=ServiceClients(FakeHealthClient(), FakeHealthClient()),
        feature_services=FeatureServices(
            cast(AuthService, FakeAuthService()),
            cast(LocationService, FakeLocationService()),
            DisabledVerificationProvider(),
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/location/current")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_location_resolve_and_leave_share_the_user_write_limit(settings: Settings) -> None:
    auth = FakeAuthService(_user())
    app = create_app(
        settings=settings,
        clients=ServiceClients(FakeHealthClient(), FakeHealthClient()),
        feature_services=FeatureServices(
            cast(AuthService, auth),
            cast(LocationService, FakeLocationService()),
            DisabledVerificationProvider(),
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            session = await client.get("/auth/session")
            headers = {"X-CSRF-Token": session.json()["data"]["csrf_token"]}
            resolved = await client.post(
                "/location/resolve",
                headers=headers,
                json={"latitude": 32.77768, "longitude": 35.02152, "accuracy_meters": 5},
            )
            left = await client.post("/location/leave", headers=headers)

    assert resolved.status_code == left.status_code == 200
    assert auth.rate_limit_calls == [
        (("location-user", str(_user().id)), {"limit": 12, "window_seconds": 60}),
        (("location-user", str(_user().id)), {"limit": 12, "window_seconds": 60}),
    ]


def test_openapi_publishes_stable_auth_and_location_models(settings: Settings) -> None:
    app = create_app(
        settings=settings, clients=ServiceClients(FakeHealthClient(), FakeHealthClient())
    )
    document = app.openapi()
    expected_operations = {
        ("/auth/session", "get"),
        ("/auth/register", "post"),
        ("/auth/login", "post"),
        ("/auth/logout", "post"),
        ("/location/current", "get"),
        ("/location/resolve", "post"),
        ("/location/leave", "post"),
    }
    for path, method in expected_operations:
        assert (
            "application/json"
            in document["paths"][path][method]["responses"][
                "200" if method == "get" or path != "/auth/register" else "201"
            ]["content"]
        )
    schemas = document["components"]["schemas"]
    assert {
        "SessionData",
        "RegisterRequest",
        "LoginRequest",
        "LocationRequest",
        "LocationData",
    } <= schemas.keys()


async def test_swagger_ui_uses_the_same_origin_gateway_prefix(settings: Settings) -> None:
    app = create_app(
        settings=settings, clients=ServiceClients(FakeHealthClient(), FakeHealthClient())
    )
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/docs")
    assert response.status_code == 200
    assert "url: '/api/openapi.json'" in response.text


async def test_malformed_coordinates_return_sanitized_no_store_error(settings: Settings) -> None:
    app = create_app(
        settings=settings,
        clients=ServiceClients(FakeHealthClient(), FakeHealthClient()),
        feature_services=FeatureServices(
            cast(AuthService, FakeAuthService(_user())),
            cast(LocationService, FakeLocationService()),
            DisabledVerificationProvider(),
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            session = await client.get("/auth/session")
            response = await client.post(
                "/location/resolve",
                headers={"X-CSRF-Token": session.json()["data"]["csrf_token"]},
                json={"latitude": 91, "longitude": 35, "accuracy_meters": 5},
            )
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert '"latitude":91' not in response.text
