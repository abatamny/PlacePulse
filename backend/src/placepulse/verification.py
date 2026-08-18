from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


class VerificationProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class VerificationChallenge:
    challenge_id: str


class VerificationProvider(Protocol):
    async def start(self, user_id: uuid.UUID, email: str) -> VerificationChallenge: ...
    async def confirm(self, challenge_id: str, code: str) -> bool: ...


class DisabledVerificationProvider:
    async def start(self, user_id: uuid.UUID, email: str) -> VerificationChallenge:
        del user_id, email
        raise VerificationProviderUnavailable("Account verification is not configured")

    async def confirm(self, challenge_id: str, code: str) -> bool:
        del challenge_id, code
        raise VerificationProviderUnavailable("Account verification is not configured")
