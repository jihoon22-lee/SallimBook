import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

LoginName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]{2,63}$",
    ),
]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(InputModel):
    login_name: LoginName
    password: SecretStr = Field(min_length=1, max_length=128)
    device_label: DisplayName


class InstallClaim(InputModel):
    """An Android install's device row from an earlier sign-in; empty on its first sign-in."""

    device_id: UUID | None = None
    key: SecretStr | None = Field(default=None, min_length=32, max_length=128)

    @model_validator(mode="after")
    def _both_or_neither(self) -> InstallClaim:
        if (self.device_id is None) != (self.key is None):
            raise ValueError("device_id and key go together")
        if self.key is not None and not re.fullmatch(
            r"[A-Za-z0-9_-]{32,128}", self.key.get_secret_value()
        ):
            raise ValueError("malformed install key")
        return self


class NativeLoginRequest(LoginRequest):
    # Opt-in, so an older app that never sends it keeps the old response.
    install: InstallClaim | None = None


class ReauthenticationRequest(InputModel):
    password: SecretStr = Field(min_length=1, max_length=128)


class PasswordChangeRequest(InputModel):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=15, max_length=128)


class InvitationRequest(InputModel):
    intended_login: LoginName


class InvitationAcceptance(InputModel):
    token: SecretStr = Field(min_length=32, max_length=128)
    password: SecretStr = Field(min_length=15, max_length=128)
    display_name: DisplayName


class SetupRequest(InputModel):
    display_name: DisplayName
    password: SecretStr = Field(min_length=15, max_length=128)
    device_label: DisplayName


class ConnectionRequest(SetupRequest):
    # This low-entropy, short-lived code has a dedicated global guess limit;
    # it is never accepted as a session, refresh token or legacy invitation.
    code: SecretStr = Field(
        min_length=8, max_length=8, json_schema_extra={"pattern": r"^[0-9]{8}$"}
    )

    @field_validator("code")
    @classmethod
    def validate_connection_code(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"[0-9]{8}", value.get_secret_value()):
            raise ValueError("Connection code must contain exactly eight ASCII digits")
        return value


class SetupStatusResponse(BaseModel):
    available: bool


class ConnectionCodeResponse(BaseModel):
    code: str = Field(pattern=r"^[0-9]{8}$", repr=False)
    expires_at: datetime


class RefreshRequest(InputModel):
    refresh_token: SecretStr = Field(min_length=32, max_length=128)


class MemberResponse(BaseModel):
    user_id: UUID
    member_id: UUID
    household_id: UUID
    display_name: str
    role: Literal["owner", "member"]


class RevokedDevicesResponse(BaseModel):
    revoked_devices: int = Field(ge=0)


class WebLoginResponse(BaseModel):
    member: MemberResponse
    csrf_token: str = Field(repr=False)
    expires_at: datetime


class CsrfResponse(BaseModel):
    csrf_token: str = Field(repr=False)


class NativeTokenResponse(BaseModel):
    access_token: str = Field(repr=False)
    refresh_token: str = Field(repr=False)
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int = Field(default=600, ge=1, le=600)
    refresh_expires_at: datetime


class InstallDevice(BaseModel):
    device_id: UUID
    # Only when a new row was made; the install keeps its key otherwise.
    key: str | None = Field(default=None, repr=False)


class NativeLoginResponse(NativeTokenResponse):
    # Present only when the sign-in sent an install claim.
    install: InstallDevice | None = None


class InvitationResponse(BaseModel):
    id: UUID
    token: str = Field(repr=False)
    expires_at: datetime


class DeviceResponse(BaseModel):
    id: UUID
    label: str
    platform: Literal["web", "android"]
    status: Literal["active", "revoked"]
    last_seen_at: datetime
    version: int
    current: bool
    # Named without "session": native clients refuse credential-like response field names.
    login_state: Literal["active", "expired", "revoked"]


class DeviceListResponse(BaseModel):
    items: list[DeviceResponse]
    next_cursor: UUID | None
