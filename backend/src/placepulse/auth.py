from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from placepulse.api.errors import DomainError
from placepulse.api.schemas import UserView, VerificationView
from placepulse.config import Settings
from placepulse.security import PasswordService, new_opaque_token, token_digest

SESSION_PREFIX = "placepulse:session:"
RATE_LIMIT_PREFIX = "placepulse:rate:"


@dataclass(frozen=True)
class SessionResult:
    token: str
    user: UserView


class AuthService:
    def __init__(
        self,
        engine: AsyncEngine,
        redis: Redis,
        settings: Settings,
        passwords: PasswordService,
    ) -> None:
        self._engine = engine
        self._redis = redis
        self._settings = settings
        self._passwords = passwords

    async def enforce_rate_limit(
        self,
        scope: str,
        identity: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> None:
        now = int(time.time())
        bucket = now // window_seconds
        safe_identity = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        key = f"{RATE_LIMIT_PREFIX}{scope}:{safe_identity}:{bucket}"
        pipeline = self._redis.pipeline(transaction=True)
        pipeline.incr(key)
        pipeline.expire(key, window_seconds + 1)
        results = await pipeline.execute()
        count = int(results[0])
        if count > limit:
            retry_after = window_seconds - (now % window_seconds)
            raise DomainError(
                429,
                "RATE_LIMITED",
                "Too many requests. Please try again later.",
                retry_after=retry_after,
            )

    async def register(
        self,
        *,
        handle: str,
        email: str,
        password: str,
        client_ip: str,
    ) -> UserView:
        normalized_email = email.casefold()
        await self.enforce_rate_limit("register-ip", client_ip, limit=5, window_seconds=3_600)
        await self.enforce_rate_limit(
            "register-email", normalized_email, limit=3, window_seconds=3_600
        )
        password_hash = await self._passwords.hash(password)
        user_id = uuid.uuid4()
        try:
            async with self._engine.begin() as connection:
                row = (
                    await connection.execute(
                        text(
                            "INSERT INTO users "
                            "(id, handle, email, password_hash, email_verified_at) "
                            "VALUES (:id, :handle, :email, :password_hash, NULL) "
                            "RETURNING id, handle, email, email_verified_at"
                        ),
                        {
                            "id": user_id,
                            "handle": handle,
                            "email": normalized_email,
                            "password_hash": password_hash,
                        },
                    )
                ).one()
        except IntegrityError as exc:
            raise DomainError(
                409,
                "ACCOUNT_UNAVAILABLE",
                "An account with those details cannot be created.",
            ) from exc
        return self._user_view(row)

    async def login(
        self,
        *,
        email: str,
        password: str,
        client_ip: str,
    ) -> SessionResult:
        normalized_email = email.casefold()
        await self.enforce_rate_limit("login-ip", client_ip, limit=10, window_seconds=900)
        await self.enforce_rate_limit("login-email", normalized_email, limit=5, window_seconds=900)
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT id, handle, email, password_hash, email_verified_at "
                        "FROM users WHERE lower(email) = :email"
                    ),
                    {"email": normalized_email},
                )
            ).one_or_none()
        password_hash = None if row is None else str(row.password_hash)
        if not await self._passwords.verify(password_hash, password):
            raise DomainError(401, "INVALID_CREDENTIALS", "The email or password is incorrect.")
        if row is None:
            raise DomainError(401, "INVALID_CREDENTIALS", "The email or password is incorrect.")

        token = new_opaque_token()
        await self._redis.set(
            f"{SESSION_PREFIX}{token_digest(token)}",
            str(row.id),
            ex=self._settings.session_ttl_seconds,
        )
        return SessionResult(token=token, user=self._user_view(row))

    async def session_user(self, token: str | None) -> UserView | None:
        if not token:
            return None
        key = f"{SESSION_PREFIX}{token_digest(token)}"
        raw_user_id = await self._redis.get(key)
        if not isinstance(raw_user_id, str):
            return None
        try:
            user_id = uuid.UUID(raw_user_id)
        except ValueError:
            await self._redis.delete(key)
            return None
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT id, handle, email, email_verified_at FROM users WHERE id = :user_id"
                    ),
                    {"user_id": user_id},
                )
            ).one_or_none()
        if row is None:
            await self._redis.delete(key)
            return None
        return self._user_view(row)

    async def revoke_session(self, token: str | None) -> None:
        if token:
            await self._redis.delete(f"{SESSION_PREFIX}{token_digest(token)}")

    @staticmethod
    def _user_view(row: Any) -> UserView:
        verified = row.email_verified_at is not None
        return UserView(
            id=row.id,
            handle=row.handle,
            email=row.email,
            verification=VerificationView(
                status="verified" if verified else "pending_provider_configuration"
            ),
        )
