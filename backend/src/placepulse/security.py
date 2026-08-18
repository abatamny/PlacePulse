from __future__ import annotations

import asyncio
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type


def build_password_hasher() -> PasswordHasher:
    return PasswordHasher(
        time_cost=3,
        memory_cost=65_536,
        parallelism=4,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )


class PasswordService:
    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or build_password_hasher()
        self._dummy_hash = self._hasher.hash("placepulse-dummy-password-not-an-account")
        self._semaphore = asyncio.Semaphore(4)

    async def hash(self, password: str) -> str:
        async with self._semaphore:
            return await asyncio.to_thread(self._hasher.hash, password)

    async def verify(self, password_hash: str | None, password: str) -> bool:
        candidate_hash = password_hash or self._dummy_hash
        async with self._semaphore:
            try:
                return await asyncio.to_thread(self._hasher.verify, candidate_hash, password)
            except (InvalidHashError, VerificationError, VerifyMismatchError):
                return False


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
