from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI

from placepulse.api.app import ServiceClients, create_app
from placepulse.config import Settings


class FakeClient:
    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


async def run_websocket(app: FastAPI, path: str, text: str) -> list[dict[str, Any]]:
    incoming = iter(
        [
            {"type": "websocket.connect"},
            {"type": "websocket.receive", "text": text},
        ]
    )
    outgoing: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return next(incoming)

    async def send(message: dict[str, Any]) -> None:
        outgoing.append(message)

    scope: dict[str, Any] = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "scheme": "ws",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "subprotocols": [],
        "state": {},
    }
    await app(scope, receive, send)
    return outgoing


def assert_message_types(messages: Sequence[dict[str, Any]], expected: list[str]) -> None:
    assert [message["type"] for message in messages] == expected


async def test_transport_probe_is_available_only_in_test_environment(
    settings: Settings,
) -> None:
    test_app = create_app(
        settings=settings,
        clients=ServiceClients(FakeClient(), FakeClient()),
    )
    outgoing = await run_websocket(
        test_app,
        "/ws/_test/echo",
        "placepulse-websocket-probe",
    )
    assert_message_types(outgoing, ["websocket.accept", "websocket.send", "websocket.close"])
    assert outgoing[1]["text"] == "placepulse-websocket-probe"
    assert outgoing[2]["code"] == 1000

    local_app = create_app(
        settings=settings.model_copy(update={"env": "local"}),
        clients=ServiceClients(FakeClient(), FakeClient()),
    )
    test_only_paths = {"/_test/body", "/ws/_test/echo"}
    assert all(getattr(route, "path", None) not in test_only_paths for route in local_app.routes)


async def test_transport_probe_rejects_oversized_messages(settings: Settings) -> None:
    app = create_app(
        settings=settings,
        clients=ServiceClients(FakeClient(), FakeClient()),
    )
    outgoing = await run_websocket(app, "/ws/_test/echo", "x" * 129)
    assert_message_types(outgoing, ["websocket.accept", "websocket.close"])
    assert outgoing[1]["code"] == 1009
