from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any, cast

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from placepulse.api.errors import DomainError
from placepulse.auth import AuthService
from placepulse.config import Settings
from placepulse.security import PasswordService


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.key = ""

    def incr(self, key: str) -> FakePipeline:
        self.key = key
        return self

    def expire(self, key: str, seconds: int) -> FakePipeline:
        assert key == self.key
        assert seconds > 0
        return self

    async def execute(self) -> list[int | bool]:
        count = self.redis.counters.get(self.key, 0) + 1
        self.redis.counters[self.key] = count
        return [count, True]


class FakeRedis:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    def pipeline(self, *, transaction: bool) -> FakePipeline:
        assert transaction is True
        return FakePipeline(self)

    async def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        self.expirations[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        self.expirations.pop(key, None)
        return int(existed)


class FakeResult:
    def __init__(self, row: Any) -> None:
        self.row = row

    def one_or_none(self) -> Any:
        return self.row


class FakeConnection:
    def __init__(self, engine: FakeEngine) -> None:
        self.engine = engine

    async def execute(self, statement: Any, parameters: Any) -> FakeResult:
        del statement, parameters
        return FakeResult(self.engine.row)


class FakeConnectionContext(AbstractAsyncContextManager[FakeConnection]):
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback


class FakeEngine:
    def __init__(self, row: Any = None) -> None:
        self.row = row

    def connect(self) -> FakeConnectionContext:
        return FakeConnectionContext(FakeConnection(self))


class FakePasswords:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.seen_hashes: list[str | None] = []

    async def verify(self, password_hash: str | None, password: str) -> bool:
        del password
        self.seen_hashes.append(password_hash)
        return self.result


def _row() -> Any:
    return type(
        "UserRow",
        (),
        {
            "id": uuid.UUID("5a1f13aa-92cc-4a20-836b-6b9a7a3c5f11"),
            "handle": "Display_Case",
            "email": "person@example.test",
            "password_hash": "$argon2id$stored-hash",
            "email_verified_at": None,
        },
    )()


def _service(
    settings: Settings,
    engine: FakeEngine,
    redis: FakeRedis,
    passwords: FakePasswords,
) -> AuthService:
    return AuthService(
        cast(AsyncEngine, engine),
        cast(Redis, redis),
        settings,
        cast(PasswordService, passwords),
    )


async def test_unknown_and_wrong_password_failures_are_generic(settings: Settings) -> None:
    engine = FakeEngine()
    redis = FakeRedis()
    passwords = FakePasswords(False)
    service = _service(settings, engine, redis, passwords)

    with pytest.raises(DomainError) as unknown:
        await service.login(
            email="missing@example.test",
            password="wrong-password",  # noqa: S106
            client_ip="192.0.2.1",
        )
    engine.row = _row()
    with pytest.raises(DomainError) as wrong:
        await service.login(
            email="person@example.test",
            password="wrong-password",  # noqa: S106
            client_ip="192.0.2.1",
        )

    assert (unknown.value.status_code, unknown.value.code, unknown.value.message) == (
        wrong.value.status_code,
        wrong.value.code,
        wrong.value.message,
    )
    assert passwords.seen_hashes == [None, "$argon2id$stored-hash"]


async def test_session_tokens_are_hashed_fixed_ttl_and_revocable(settings: Settings) -> None:
    engine = FakeEngine(_row())
    redis = FakeRedis()
    service = _service(settings, engine, redis, FakePasswords(True))

    result = await service.login(
        email="Person@Example.test",
        password="correct-password",  # noqa: S106
        client_ip="192.0.2.2",
    )
    assert len(redis.values) == 1
    key = next(iter(redis.values))
    assert result.token not in key
    assert redis.expirations[key] == 43_200
    assert (await service.session_user(result.token)) == result.user

    await service.revoke_session(result.token)
    assert redis.values == {}


async def test_rate_limit_keys_hide_identity_and_reject_over_limit(settings: Settings) -> None:
    redis = FakeRedis()
    service = _service(settings, FakeEngine(), redis, FakePasswords(False))
    identity = "private@example.test"

    for _ in range(3):
        await service.enforce_rate_limit("register-email", identity, limit=3, window_seconds=3_600)
    with pytest.raises(DomainError) as rejected:
        await service.enforce_rate_limit("register-email", identity, limit=3, window_seconds=3_600)

    assert rejected.value.code == "RATE_LIMITED"
    assert all(identity not in key for key in redis.counters)
