"""Strict opaque wire contracts. No key, password or card plaintext input exists.

The confirmed flag records the client's explicit consent after its own key check;
it is not cryptographic proof and never replaces server authentication/authorization.
"""

import base64
import binascii
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from sallimbook.vault.formats import (
    CARD_CIPHERTEXT_BYTES,
    KEY_CHECK_CIPHERTEXT_BYTES,
    MAX_PBKDF2_ITERATIONS,
    MAX_SAFE_INTEGER,
    MIN_PBKDF2_ITERATIONS,
    NONCE_BYTES,
    SALT_BYTES,
    WRAPPED_HVK_BYTES,
)


def _uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError("Use a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError("Use a canonical UUID") from None
    if str(parsed) != value:
        raise ValueError("Use a canonical UUID")
    return parsed


def _one(value: object) -> int:
    if type(value) is not int or value != 1:
        raise ValueError("Unsupported format version")
    return 1


def _card_schema(value: object) -> int:
    if type(value) is not int or value not in (1, 2):
        raise ValueError("Unsupported card payload schema")
    return value


def _confirmed(value: object) -> bool:
    if value is not True:
        raise ValueError("Explicit key-check confirmation is required")
    return True


def decode_opaque(value: str) -> bytes:
    """Decode only an already size-bounded value; reject noncanonical padding bits."""
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except ValueError, binascii.Error:
        raise ValueError("Use canonical unpadded base64url") from None
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != value:
        raise ValueError("Use canonical unpadded base64url")
    return raw


def _opaque(size: int):
    length = (size * 8 + 5) // 6

    def validate(value: str) -> str:
        if len(decode_opaque(value)) != size:
            raise ValueError("Invalid opaque value length")
        return value

    return Annotated[
        str,
        StringConstraints(
            strict=True, min_length=length, max_length=length, pattern=r"^[A-Za-z0-9_-]+$"
        ),
        AfterValidator(validate),
    ]


CanonicalUUID = Annotated[UUID, BeforeValidator(_uuid)]
PositiveVersion = Annotated[int, Field(strict=True, ge=1, le=MAX_SAFE_INTEGER)]
Count = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE_INTEGER)]
FormatOne = Annotated[Literal[1], BeforeValidator(_one)]
Confirmed = Annotated[Literal[True], BeforeValidator(_confirmed)]
Nonce = _opaque(NONCE_BYTES)
Salt = _opaque(SALT_BYTES)
WrappedHvk = _opaque(WRAPPED_HVK_BYTES)
CardCiphertext = _opaque(CARD_CIPHERTEXT_BYTES) | _opaque(48)
CardSchema = Annotated[Literal[1, 2], BeforeValidator(_card_schema)]
KeyCheckCiphertext = _opaque(KEY_CHECK_CIPHERTEXT_BYTES)
LastFour = Annotated[
    str, StringConstraints(strict=True, min_length=4, max_length=4, pattern=r"^[0-9]{4}$")
]
type VersionState = Literal["staging", "current", "retired", "aborted"]
type MembershipState = Literal["active", "revoked"]
type ShareState = Literal["pending", "accepted", "cancelled", "expired"]


class VaultModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, validate_default=True)


class OpaqueEnvelope(VaultModel):
    format_version: FormatOne
    key_version: PositiveVersion
    nonce: Nonce = Field(repr=False)


class KeyCheckInput(OpaqueEnvelope):
    ciphertext: KeyCheckCiphertext = Field(repr=False)


class MemberWrappingInput(OpaqueEnvelope):
    member_id: CanonicalUUID
    generation: PositiveVersion
    kdf: Literal["PBKDF2-HMAC-SHA256"]
    iterations: Annotated[
        int, Field(strict=True, ge=MIN_PBKDF2_ITERATIONS, le=MAX_PBKDF2_ITERATIONS)
    ]
    salt: Salt = Field(repr=False)
    wrapped_hvk: WrappedHvk = Field(repr=False)


class RecoveryWrappingInput(OpaqueEnvelope):
    generation: PositiveVersion
    kdf: Literal["HKDF-SHA256"]
    salt: Salt = Field(repr=False)
    wrapped_hvk: WrappedHvk = Field(repr=False)


class CardEnvelopeInput(OpaqueEnvelope):
    payload_schema_version: CardSchema
    last_four: LastFour
    ciphertext: CardCiphertext = Field(repr=False)

    @model_validator(mode="after")
    def schema_length(self) -> Self:
        if len(decode_opaque(self.ciphertext)) != (43 if self.payload_schema_version == 1 else 48):
            raise ValueError("Card schema and ciphertext length must match")
        return self


def _bundle(key_check, members, recovery):
    rows = [key_check, *members, recovery]
    if any(row.key_version != key_check.key_version for row in rows):
        raise ValueError("Bundle key versions must match")
    if len({row.nonce for row in rows}) != len(rows):
        raise ValueError("Each envelope requires a distinct nonce")
    if len({row.member_id for row in members}) != len(members):
        raise ValueError("Each member must appear once")
    if len({row.salt for row in members}) != len(members):
        raise ValueError("Each member wrapping requires a fresh salt")


class VaultInitialize(VaultModel):
    key_check: KeyCheckInput
    member_wrapping: MemberWrappingInput
    recovery_wrapping: RecoveryWrappingInput

    @model_validator(mode="after")
    def initial_version(self) -> Self:
        _bundle(self.key_check, [self.member_wrapping], self.recovery_wrapping)
        if (
            self.key_check.key_version != 1
            or self.member_wrapping.generation != 1
            or self.recovery_wrapping.generation != 1
        ):
            raise ValueError("Initialize with version and generations one")
        return self


class VaultShareCreate(VaultModel):
    wrapping: MemberWrappingInput


class VaultKeyConfirmation(VaultModel):
    key_version: PositiveVersion
    key_check_confirmed: Confirmed


class VaultMemberRewrap(VaultModel):
    wrapping: MemberWrappingInput
    key_check_confirmed: Confirmed


class VaultRecover(VaultModel):
    member_wrapping: MemberWrappingInput
    recovery_wrapping: RecoveryWrappingInput
    key_check_confirmed: Confirmed

    @model_validator(mode="after")
    def same_key(self) -> Self:
        if self.member_wrapping.key_version != self.recovery_wrapping.key_version:
            raise ValueError("Recovery bundle key versions must match")
        if self.member_wrapping.nonce == self.recovery_wrapping.nonce:
            raise ValueError("Each envelope requires a distinct nonce")
        return self


class VaultRotationStart(VaultModel):
    reason: Literal["routine", "key_compromised", "member_access_removed"]


class VaultRotationPrepare(VaultModel):
    key_check: KeyCheckInput
    member_wrappings: Annotated[list[MemberWrappingInput], Field(min_length=1, max_length=2)]
    recovery_wrapping: RecoveryWrappingInput

    @model_validator(mode="after")
    def same_key(self) -> Self:
        _bundle(self.key_check, self.member_wrappings, self.recovery_wrapping)
        if self.key_check.key_version == 1:
            raise ValueError("Rotation requires a newly allocated key version")
        return self


class VaultRotationCardWrite(VaultModel):
    source_envelope_id: CanonicalUUID
    source_revision: PositiveVersion
    envelope: CardEnvelopeInput


class VaultEmptyMutation(VaultModel):
    """An explicit empty body for cancel, revoke and abort operations."""


class VaultMutationReference(VaultModel):
    id: CanonicalUUID
    version: PositiveVersion


class VaultMemberSummary(VaultModel):
    member_id: CanonicalUUID
    status: Literal["not_enrolled", "active", "revoked"]
    version: PositiveVersion | None
    next_wrapping_generation: PositiveVersion

    @model_validator(mode="after")
    def membership_version(self) -> Self:
        if (self.status == "not_enrolled") != (self.version is None):
            raise ValueError("Only an enrolled membership has a resource version")
        return self


class VaultStatusResponse(VaultModel):
    household_id: CanonicalUUID
    initialized: Annotated[bool, Field(strict=True)]
    id: CanonicalUUID | None
    version: PositiveVersion | None
    current_key_version: PositiveVersion | None
    own_membership: Literal["not_enrolled", "active", "revoked"]
    rotation_required: Annotated[bool, Field(strict=True)]
    pending_rotation_id: CanonicalUUID | None
    members: Annotated[list[VaultMemberSummary], Field(max_length=2)]

    @model_validator(mode="after")
    def initialized_shape(self) -> Self:
        initialized_fields = (self.id, self.version, self.current_key_version)
        if self.initialized:
            if any(value is None for value in initialized_fields):
                raise ValueError("An initialized vault requires its current version")
        elif (
            any(value is not None for value in initialized_fields)
            or self.own_membership != "not_enrolled"
            or self.rotation_required
            or self.pending_rotation_id is not None
            or self.members
        ):
            raise ValueError("An uninitialized vault has no key or membership state")
        if len({member.member_id for member in self.members}) != len(self.members):
            raise ValueError("Duplicate member")
        return self


class KeyCheckResponse(KeyCheckInput):
    household_id: CanonicalUUID


class MemberWrappingResponse(MemberWrappingInput):
    id: CanonicalUUID
    household_id: CanonicalUUID
    version: PositiveVersion


class RecoveryWrappingResponse(RecoveryWrappingInput):
    id: CanonicalUUID
    household_id: CanonicalUUID
    version: PositiveVersion


class VaultOwnWrappingResponse(VaultModel):
    wrapping: MemberWrappingResponse
    key_check: KeyCheckResponse

    @model_validator(mode="after")
    def matching_key(self) -> Self:
        if (
            self.wrapping.household_id != self.key_check.household_id
            or self.wrapping.key_version != self.key_check.key_version
        ):
            raise ValueError("Wrapping and key check must share their scope")
        return self


class VaultRecoveryResponse(VaultModel):
    wrapping: RecoveryWrappingResponse
    key_check: KeyCheckResponse

    @model_validator(mode="after")
    def matching_key(self) -> Self:
        if (
            self.wrapping.household_id != self.key_check.household_id
            or self.wrapping.key_version != self.key_check.key_version
        ):
            raise ValueError("Wrapping and key check must share their scope")
        return self


class CardSecretResponse(CardEnvelopeInput):
    id: CanonicalUUID
    household_id: CanonicalUUID
    card_id: CanonicalUUID
    revision: PositiveVersion
    version: PositiveVersion
    card_version: PositiveVersion


class VaultShareResponse(VaultModel):
    id: CanonicalUUID
    household_id: CanonicalUUID
    source_member_id: CanonicalUUID
    target_member_id: CanonicalUUID
    key_version: PositiveVersion
    state: ShareState
    expires_at: datetime
    closed_at: datetime | None
    version: PositiveVersion


class VaultShareListResponse(VaultModel):
    items: list[VaultShareResponse]
    next_cursor: CanonicalUUID | None


class VaultShareWrappingResponse(VaultOwnWrappingResponse):
    offer: VaultShareResponse

    @model_validator(mode="after")
    def matching_offer(self) -> Self:
        if (
            self.offer.household_id != self.wrapping.household_id
            or self.offer.target_member_id != self.wrapping.member_id
            or self.offer.key_version != self.wrapping.key_version
            or self.offer.state != "pending"
        ):
            raise ValueError("Pending wrapping must belong to the share recipient")
        return self


class VaultRotationCardResponse(VaultModel):
    card_id: CanonicalUUID
    source_envelope_id: CanonicalUUID
    source_revision: PositiveVersion
    last_four: LastFour
    prepared: Annotated[bool, Field(strict=True)]


class VaultRotationMemberResponse(VaultModel):
    member_id: CanonicalUUID
    source_membership_version: PositiveVersion
    prepared: Annotated[bool, Field(strict=True)]


class VaultRotationResponse(VaultModel):
    id: CanonicalUUID
    household_id: CanonicalUUID
    key_version: PositiveVersion
    source_key_version: PositiveVersion
    state: VersionState
    version: PositiveVersion
    key_check_prepared: Annotated[bool, Field(strict=True)]
    recovery_prepared: Annotated[bool, Field(strict=True)]
    cards: list[VaultRotationCardResponse]
    members: Annotated[list[VaultRotationMemberResponse], Field(min_length=1, max_length=2)]

    @model_validator(mode="after")
    def manifest(self) -> Self:
        if self.source_key_version >= self.key_version:
            raise ValueError("Rotation must advance its key version")
        if len({row.card_id for row in self.cards}) != len(self.cards):
            raise ValueError("Duplicate rotation card")
        if len({row.member_id for row in self.members}) != len(self.members):
            raise ValueError("Duplicate rotation member")
        return self
