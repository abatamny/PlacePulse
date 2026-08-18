from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from placepulse.api.schemas import LocationRequest, LoginRequest, PlaceView, RegisterRequest
from placepulse.location import Candidate, LocationService
from placepulse.security import PasswordService, new_opaque_token, token_digest
from placepulse.verification import DisabledVerificationProvider, VerificationProviderUnavailable
from tests.fakes.verification import DeterministicVerificationProvider


async def test_password_service_uses_argon2id_and_checks_wrong_passwords() -> None:
    passwords = PasswordService()
    password_hash = await passwords.hash("correct horse battery staple")
    assert password_hash.startswith("$argon2id$")
    assert await passwords.verify(password_hash, "correct horse battery staple") is True
    assert await passwords.verify(password_hash, "wrong password") is False
    assert await passwords.verify(None, "wrong password") is False


def test_opaque_tokens_are_random_and_only_digests_are_stable() -> None:
    first = new_opaque_token()
    second = new_opaque_token()
    assert first != second
    assert len(first) >= 32
    assert token_digest(first) == token_digest(first)
    assert first not in token_digest(first)


async def test_disabled_verification_provider_never_claims_success() -> None:
    provider = DisabledVerificationProvider()
    with pytest.raises(VerificationProviderUnavailable):
        await provider.start(uuid.uuid4(), "person@example.test")
    with pytest.raises(VerificationProviderUnavailable):
        await provider.confirm("challenge", "123456")


async def test_verification_fake_is_deterministic_and_test_only() -> None:
    provider = DeterministicVerificationProvider()
    user_id = uuid.UUID("5a1f13aa-92cc-4a20-836b-6b9a7a3c5f11")
    challenge = await provider.start(user_id, "Person@Example.test")
    assert challenge.challenge_id == f"test:{user_id}:person@example.test"
    assert await provider.confirm(challenge.challenge_id, "123456") is True
    assert await provider.confirm(challenge.challenge_id, "000000") is False


def test_auth_and_coordinate_schemas_bound_external_input() -> None:
    valid = RegisterRequest(
        handle="Campus_User",
        email="Person@Example.test",
        password="a sufficiently long password",  # noqa: S106
    )
    assert str(valid.email) == "Person@example.test"
    with pytest.raises(ValidationError):
        RegisterRequest(handle="bad space", email="invalid", password="short")  # noqa: S106
    with pytest.raises(ValidationError):
        LoginRequest(email="person@example.test", password="x" * 129)
    with pytest.raises(ValidationError):
        LoginRequest(email="person@example.test", password="x" * 11)
    with pytest.raises(ValidationError):
        LocationRequest(latitude=float("nan"), longitude=35, accuracy_meters=5)
    with pytest.raises(ValidationError):
        LocationRequest(latitude=91, longitude=35, accuracy_meters=5)


def _place(name: str, parent: uuid.UUID | None = None) -> PlaceView:
    return PlaceView(
        id=uuid.uuid4(),
        name=name,
        osm_type="way",
        osm_id=abs(hash(name)) + 1,
        parent_place_id=parent,
    )


def test_location_selection_requires_one_explainable_parent_chain() -> None:
    campus = _place("Campus")
    building = _place("Building", campus.id)
    chain = LocationService._single_chain(
        [Candidate(campus, True, True), Candidate(building, True, True)]
    )
    assert chain == [building, campus]

    unrelated = _place("Unrelated")
    assert (
        LocationService._single_chain(
            [Candidate(campus, True, True), Candidate(unrelated, True, True)]
        )
        is None
    )
