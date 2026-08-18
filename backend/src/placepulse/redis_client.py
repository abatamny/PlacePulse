from __future__ import annotations

from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis

from placepulse.config import Settings


class RedisClient:
    def __init__(self, settings: Settings) -> None:
        self.client: Redis = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            username=settings.redis_user,
            password=settings.redis_password,
            decode_responses=True,
            socket_connect_timeout=settings.connect_timeout_seconds,
            socket_timeout=settings.connect_timeout_seconds,
            health_check_interval=30,
            max_connections=settings.redis_pool_size,
        )

    async def ping(self) -> None:
        response = await cast(Awaitable[bool], self.client.ping())
        if response is not True:
            raise ConnectionError("Redis ping did not return success")

    async def close(self) -> None:
        await self.client.aclose()
