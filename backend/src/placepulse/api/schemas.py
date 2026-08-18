from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, SecretStr


def _validated_email(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Email must be a string")
    try:
        result = validate_email(value, check_deliverability=False, test_environment=True)
    except EmailNotValidError as exc:
        raise ValueError("Email is not valid") from exc
    return result.normalized


EmailAddress = Annotated[str, BeforeValidator(_validated_email)]


class ApiMeta(BaseModel):
    schema_version: Literal[1] = 1


class SuccessEnvelope[DataT](BaseModel):
    data: DataT
    meta: ApiMeta = Field(default_factory=ApiMeta)
    request_id: uuid.UUID


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    handle: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    email: EmailAddress
    password: SecretStr = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailAddress
    password: SecretStr = Field(min_length=12, max_length=128)


class VerificationView(BaseModel):
    status: Literal["pending_provider_configuration", "verified"]
    login_allowed: bool = True


class UserView(BaseModel):
    id: uuid.UUID
    handle: str
    email: EmailAddress
    verification: VerificationView


class RegistrationData(BaseModel):
    user: UserView


class SessionData(BaseModel):
    authenticated: bool
    user: UserView | None
    csrf_token: str = Field(min_length=32, max_length=128)


class LogoutData(BaseModel):
    logged_out: Literal[True] = True


class LocationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_meters: float = Field(ge=0, le=10_000, allow_inf_nan=False)


class PlaceView(BaseModel):
    id: uuid.UUID
    name: str
    osm_type: Literal["node", "way", "relation"]
    osm_id: int
    parent_place_id: uuid.UUID | None


class VisitView(BaseModel):
    id: uuid.UUID
    place_id: uuid.UUID
    entered_at: datetime
    exited_at: datetime | None = None


class SelectionView(BaseModel):
    strategy: Literal["deepest_confident_containing", "recorded_active_visit"]
    reason_code: Literal[
        "DEEPEST_CONFIDENT_PLACE",
        "PARENT_SELECTED_FOR_ACCURACY",
        "ACCURACY_TOO_LOW",
        "ACCURACY_OVERLAPS_BOUNDARY",
        "OVERLAPPING_PLACE_HIERARCHIES",
        "NO_KNOWN_PLACE",
        "RECORDED_ACTIVE_VISIT",
        "NO_ACTIVE_VISIT",
        "VISIT_LEFT",
    ]


class LocationData(BaseModel):
    status: Literal["resolved", "unknown", "ambiguous", "low_accuracy", "inactive"]
    selected_place: PlaceView | None
    containment_path: list[PlaceView]
    uncertain_places: list[PlaceView]
    selection: SelectionView
    visit: VisitView | None
