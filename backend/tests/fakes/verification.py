from __future__ import annotations

import uuid

from placepulse.verification import VerificationChallenge


class DeterministicVerificationProvider:
    """Predictable verification behavior for tests without external delivery."""

    def __init__(self, accepted_code: str = "123456") -> None:
        self.accepted_code = accepted_code

    async def start(self, user_id: uuid.UUID, email: str) -> VerificationChallenge:
        return VerificationChallenge(challenge_id=f"test:{user_id}:{email.casefold()}")

    async def confirm(self, challenge_id: str, code: str) -> bool:
        return challenge_id.startswith("test:") and code == self.accepted_code
