"""Opaque vault protocol tests with public synthetic bytes, not encryption proofs."""

import base64
from copy import deepcopy
from uuid import UUID

import pytest
from pydantic import ValidationError

from sallimbook.vault.formats import MAX_SAFE_INTEGER
from sallimbook.vault.schemas import (
    CardEnvelopeInput,
    KeyCheckInput,
    MemberWrappingInput,
    RecoveryWrappingInput,
    VaultInitialize,
    VaultKeyConfirmation,
    VaultRecover,
    VaultRotationPrepare,
    VaultStatusResponse,
)

MEMBER = "00000000-0000-4000-8000-000000000001"
OTHER_MEMBER = "00000000-0000-4000-8000-000000000002"
HOUSEHOLD = "00000000-0000-4000-8000-000000000003"


def opaque(size, marker=1):
    return base64.urlsafe_b64encode(bytes([marker]) * size).rstrip(b"=").decode("ascii")


def member_wrap(*, member=MEMBER, key_version=1, nonce=1, salt=1):
    return {
        "format_version": 1,
        "member_id": member,
        "key_version": key_version,
        "generation": 1,
        "kdf": "PBKDF2-HMAC-SHA256",
        "iterations": 600_000,
        "salt": opaque(16, salt),
        "nonce": opaque(12, nonce),
        "wrapped_hvk": opaque(48),
    }


def recovery_wrap(*, key_version=1, nonce=2):
    return {
        "format_version": 1,
        "key_version": key_version,
        "generation": 1,
        "kdf": "HKDF-SHA256",
        "salt": opaque(16),
        "nonce": opaque(12, nonce),
        "wrapped_hvk": opaque(48),
    }


def key_check(*, key_version=1, nonce=3):
    return {
        "format_version": 1,
        "key_version": key_version,
        "nonce": opaque(12, nonce),
        "ciphertext": opaque(45),
    }


def initialization():
    return {
        "key_check": key_check(),
        "member_wrapping": member_wrap(),
        "recovery_wrapping": recovery_wrap(),
    }


def card_envelope():
    return {
        "format_version": 1,
        "key_version": 1,
        "nonce": opaque(12),
        "payload_schema_version": 1,
        "last_four": "0000",
        "ciphertext": opaque(43),
    }


@pytest.mark.parametrize("schema,size", [(1, 43), (2, 48)])
def test_card_payload_versions_have_fixed_ciphertext_sizes(schema, size):
    value = card_envelope() | {"payload_schema_version": schema, "ciphertext": opaque(size)}
    assert CardEnvelopeInput.model_validate(value).model_dump(mode="json") == value


@pytest.mark.parametrize(
    "schema,size", [(1, 48), (2, 43), (3, 48), (True, 43), (2.0, 48), ("2", 48)]
)
def test_card_payload_version_size_mismatch_or_coercion_rejected(schema, size):
    with pytest.raises(ValidationError):
        CardEnvelopeInput.model_validate(
            card_envelope() | {"payload_schema_version": schema, "ciphertext": opaque(size)}
        )


def test_initialization_round_trip_has_only_opaque_envelopes():
    payload = initialization()
    parsed = VaultInitialize.model_validate(payload)
    assert parsed.model_dump(mode="json") == payload
    assert opaque(48) not in repr(parsed)
    assert opaque(45) not in repr(parsed)


@pytest.mark.parametrize("iterations", [600_000, 2_000_000])
def test_kdf_allowed_endpoints(iterations):
    assert MemberWrappingInput.model_validate(member_wrap() | {"iterations": iterations})


@pytest.mark.parametrize("value", [599_999, 2_000_001, True, 600_000.0, "600000", None])
def test_kdf_rejects_downgrade_resource_exhaustion_and_coercion(value):
    with pytest.raises(ValidationError):
        MemberWrappingInput.model_validate(member_wrap() | {"iterations": value})


@pytest.mark.parametrize("field", ["format_version", "key_version", "generation"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", 0, -1, MAX_SAFE_INTEGER + 1])
def test_version_fields_reject_coercion_and_nonportable_values(field, value):
    with pytest.raises(ValidationError):
        MemberWrappingInput.model_validate(member_wrap() | {field: value})


@pytest.mark.parametrize("field", ["format_version", "payload_schema_version"])
def test_card_unknown_format_is_not_silently_accepted(field):
    with pytest.raises(ValidationError):
        CardEnvelopeInput.model_validate(card_envelope() | {field: 2})


@pytest.mark.parametrize(("field", "size"), [("nonce", 12), ("salt", 16), ("wrapped_hvk", 48)])
@pytest.mark.parametrize("delta", [-1, 1])
def test_wrapping_exact_decoded_lengths(field, size, delta):
    with pytest.raises(ValidationError):
        MemberWrappingInput.model_validate(member_wrap() | {field: opaque(size + delta)})


@pytest.mark.parametrize("value", [opaque(12) + "=", " " + opaque(12), opaque(12) + "\n", "+" * 16])
def test_base64url_rejects_padding_whitespace_and_alternate_alphabet(value):
    with pytest.raises(ValidationError):
        MemberWrappingInput.model_validate(member_wrap() | {"nonce": value})


def test_base64url_rejects_nonzero_padding_bits_even_if_bytes_decode_the_same():
    canonical = opaque(16, 0)
    noncanonical = canonical[:-1] + "B"
    assert base64.urlsafe_b64decode(canonical + "==") == base64.urlsafe_b64decode(
        noncanonical + "=="
    )
    with pytest.raises(ValidationError):
        MemberWrappingInput.model_validate(member_wrap() | {"salt": noncanonical})


@pytest.mark.parametrize(
    "ciphertext", [opaque(27), opaque(42), opaque(44), opaque(45), opaque(4096)]
)
def test_card_ciphertext_cannot_hide_arbitrarily_sized_payloads(ciphertext):
    with pytest.raises(ValidationError):
        CardEnvelopeInput.model_validate(card_envelope() | {"ciphertext": ciphertext})


def test_key_check_is_exact_public_marker_length_plus_tag():
    KeyCheckInput.model_validate(key_check())
    with pytest.raises(ValidationError):
        KeyCheckInput.model_validate(key_check() | {"ciphertext": opaque(43)})
    CardEnvelopeInput.model_validate(card_envelope())


@pytest.mark.parametrize("value", ["hmac", "PBKDF2-HMAC-SHA1", "argon2id", "HKDF-SHA256", None])
def test_unknown_or_cross_purpose_kdf_rejected(value):
    with pytest.raises(ValidationError):
        MemberWrappingInput.model_validate(member_wrap() | {"kdf": value})


def test_recovery_does_not_accept_password_iterations():
    with pytest.raises(ValidationError):
        RecoveryWrappingInput.model_validate(recovery_wrap() | {"iterations": 600_000})


@pytest.mark.parametrize(
    "name", ["pan", "expiry", "cvc", "cvv", "password", "recovery_code", "hvk", "device_key"]
)
def test_plaintext_fields_rejected_at_both_outer_and_nested_boundaries(name):
    payload = initialization()
    with pytest.raises(ValidationError):
        VaultInitialize.model_validate(payload | {name: "PUBLIC SYNTHETIC REJECTION VALUE"})
    payload["member_wrapping"][name] = "PUBLIC SYNTHETIC REJECTION VALUE"
    with pytest.raises(ValidationError):
        VaultInitialize.model_validate(payload)
    with pytest.raises(ValidationError):
        CardEnvelopeInput.model_validate(card_envelope() | {name: "PUBLIC SYNTHETIC VALUE"})


@pytest.mark.parametrize("name", ["member_wrapping", "recovery_wrapping", "key_check"])
def test_initialization_cannot_mix_key_versions(name):
    payload = initialization()
    payload[name]["key_version"] = 2
    with pytest.raises(ValidationError):
        VaultInitialize.model_validate(payload)


@pytest.mark.parametrize("name", ["member_wrapping", "recovery_wrapping"])
def test_initialization_cannot_skip_wrapping_generations(name):
    payload = initialization()
    payload[name]["generation"] = 2
    with pytest.raises(ValidationError):
        VaultInitialize.model_validate(payload)


def test_cross_purpose_nonce_collision_rejected_before_db():
    payload = initialization()
    payload["recovery_wrapping"]["nonce"] = payload["key_check"]["nonce"]
    with pytest.raises(ValidationError):
        VaultInitialize.model_validate(payload)


def test_member_uuid_must_be_canonical_but_python_uuid_instances_work():
    MemberWrappingInput.model_validate(member_wrap(member=UUID(MEMBER)))
    for value in [UUID(MEMBER).hex, "{" + MEMBER + "}", "00000000-0000-4000-8000-00000000000A", 1]:
        with pytest.raises(ValidationError):
            MemberWrappingInput.model_validate(member_wrap(member=value))


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_confirmation_requires_true_boolean_not_truthy_values(value):
    with pytest.raises(ValidationError):
        VaultKeyConfirmation.model_validate({"key_version": 1, "key_check_confirmed": value})


def test_recovery_keeps_key_version_and_distinct_nonces():
    payload = {
        "member_wrapping": member_wrap(),
        "recovery_wrapping": recovery_wrap(),
        "key_check_confirmed": True,
    }
    VaultRecover.model_validate(payload)
    for bad in [recovery_wrap(key_version=2), recovery_wrap(nonce=1)]:
        with pytest.raises(ValidationError):
            VaultRecover.model_validate(payload | {"recovery_wrapping": bad})


def test_rotation_bundle_requires_unique_members_new_key_and_noncolliding_nonces():
    payload = {
        "key_check": key_check(key_version=2),
        "member_wrappings": [
            member_wrap(key_version=2),
            member_wrap(member=OTHER_MEMBER, key_version=2, nonce=4, salt=2),
        ],
        "recovery_wrapping": recovery_wrap(key_version=2),
    }
    VaultRotationPrepare.model_validate(payload)
    duplicate = deepcopy(payload)
    duplicate["member_wrappings"][1]["member_id"] = MEMBER
    collision = deepcopy(payload)
    collision["member_wrappings"][1]["nonce"] = payload["key_check"]["nonce"]
    same_salt = deepcopy(payload)
    same_salt["member_wrappings"][1]["salt"] = payload["member_wrappings"][0]["salt"]
    for bad in [duplicate, collision, same_salt, payload | {"member_wrappings": []}]:
        with pytest.raises(ValidationError):
            VaultRotationPrepare.model_validate(bad)


def test_uninitialized_status_cannot_claim_enrollment_or_key_material():
    payload = {
        "household_id": HOUSEHOLD,
        "initialized": False,
        "id": None,
        "version": None,
        "current_key_version": None,
        "own_membership": "not_enrolled",
        "rotation_required": False,
        "pending_rotation_id": None,
        "members": [],
    }
    VaultStatusResponse.model_validate(payload)
    for extra in [
        {"current_key_version": 1},
        {"own_membership": "active"},
        {"rotation_required": True},
        {"initialized": True},
    ]:
        with pytest.raises(ValidationError):
            VaultStatusResponse.model_validate(payload | extra)


def test_public_schema_retains_exact_lengths_bounds_and_forbids_extra_fields():
    schema = VaultInitialize.model_json_schema()
    member = schema["$defs"]["MemberWrappingInput"]
    assert schema["additionalProperties"] is False and member["additionalProperties"] is False
    assert member["properties"]["wrapped_hvk"]["maxLength"] == 64
    assert member["properties"]["nonce"]["maxLength"] == 16
    assert member["properties"]["iterations"]["minimum"] == 600_000
    assert member["properties"]["iterations"]["maximum"] == 2_000_000
    assert member["properties"]["key_version"]["maximum"] == MAX_SAFE_INTEGER


def test_validation_error_string_omits_raw_input():
    payload = member_wrap() | {"wrapped_hvk": "PUBLIC SYNTHETIC BAD INPUT"}
    with pytest.raises(ValidationError) as error:
        MemberWrappingInput.model_validate(payload)
    assert "PUBLIC SYNTHETIC BAD INPUT" not in str(error.value)


def test_vault_openapi_requires_mutation_headers_and_has_no_retired_blob_route():
    from fastapi import FastAPI

    from sallimbook.vault.router import router

    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    identifiers = []
    for path, operations in schema["paths"].items():
        assert "{key_version}" not in path and "retired" not in path
        for method, operation in operations.items():
            identifiers.append(operation["operationId"])
            if method in {"post", "put", "delete"}:
                headers = {
                    item["name"]: item for item in operation["parameters"] if item["in"] == "header"
                }
                assert headers["Idempotency-Key"]["required"] is True
                if path == "/api/v1/vault/initialize":
                    assert "If-Match" not in headers
                else:
                    assert headers["If-Match"]["required"] is True
    assert len(identifiers) == len(set(identifiers)) == 23
    forbidden = {"pan", "expiry", "cvc", "cvv", "password", "recovery_code", "hvk", "device_key"}
    for definition in schema["components"]["schemas"].values():
        assert not forbidden.intersection(definition.get("properties", {}))


def test_vault_database_constraint_names_do_not_alias_other_unique_indexes():
    import sallimbook.models  # noqa: F401
    from sallimbook.core.database import Base

    names = []
    for table in Base.metadata.tables.values():
        if not (table.name.startswith("vault_") or table.name == "card_secret_envelopes"):
            continue
        names.extend(str(item.name) for item in table.constraints if item.name is not None)
        names.extend(str(item.name) for item in table.indexes)
    assert names and len(names) == len(set(names))
    assert max(map(len, names)) <= 63
