"""Purpose-specific opaque endpoints; no arbitrary key/version retrieval API."""

from typing import Annotated

from fastapi import APIRouter, Header, Query, Response

from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency
from sallimbook.vault import service
from sallimbook.vault.schemas import (
    CanonicalUUID,
    CardEnvelopeInput,
    CardSecretResponse,
    VaultEmptyMutation,
    VaultInitialize,
    VaultKeyConfirmation,
    VaultMemberRewrap,
    VaultMutationReference,
    VaultOwnWrappingResponse,
    VaultRecover,
    VaultRecoveryResponse,
    VaultRotationCardWrite,
    VaultRotationPrepare,
    VaultRotationResponse,
    VaultRotationStart,
    VaultShareCreate,
    VaultShareListResponse,
    VaultShareWrappingResponse,
    VaultStatusResponse,
)

router = APIRouter(prefix="/api/v1", tags=["vault"])
IfMatch = Annotated[str, Header(alias="If-Match")]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]
StepUpToken = Annotated[str | None, Header(alias="X-Step-Up-Token", max_length=128)]
Limit = Annotated[int, Query(ge=1, le=200)]


def _result(response, result, *, etag=None):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    version = etag if etag is not None else getattr(result, "version", None)
    if version is not None:
        response.headers["ETag"] = f'"{version}"'
    return result


@router.get("/vault/status", response_model=VaultStatusResponse, operation_id="getVaultStatus")
def get_status(principal: PrincipalDependency, session: SessionDependency, response: Response):
    return _result(response, service.get_status(session, principal))


@router.post(
    "/vault/initialize",
    response_model=VaultMutationReference,
    status_code=201,
    operation_id="initializeVault",
)
def initialize(
    payload: VaultInitialize,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    idempotency_key: IdempotencyKey,
    step_up_token: StepUpToken = None,
):
    return _result(
        response,
        service.initialize(
            session,
            principal,
            payload,
            idempotency_key,
            step_up_token=step_up_token,
        ),
    )


@router.get(
    "/vault/wrappings/me",
    response_model=VaultOwnWrappingResponse,
    operation_id="getOwnVaultWrapping",
)
def get_own_wrapping(
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    result = service.get_own_wrapping(session, principal)
    return _result(response, result, etag=result.wrapping.version)


@router.put(
    "/vault/wrappings/me",
    response_model=VaultMutationReference,
    operation_id="rewrapOwnVaultKey",
)
def rewrap_member(
    payload: VaultMemberRewrap,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
    step_up_token: StepUpToken = None,
):
    return _result(
        response,
        service.rewrap_member(
            session,
            principal,
            payload,
            if_match,
            idempotency_key,
            step_up_token=step_up_token,
        ),
    )


@router.get(
    "/vault/recovery-wrap",
    response_model=VaultRecoveryResponse,
    operation_id="getVaultRecoveryWrapping",
)
def get_recovery_wrapping(
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    step_up_token: StepUpToken = None,
):
    return _result(
        response,
        service.get_recovery_wrapping(
            session,
            principal,
            step_up_token=step_up_token,
        ),
    )


@router.post("/vault/recover", response_model=VaultMutationReference, operation_id="recoverVault")
def recover(
    payload: VaultRecover,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
    step_up_token: StepUpToken = None,
):
    """If-Match is the vault status version; replace both wrapping generations atomically."""
    return _result(
        response,
        service.recover(
            session,
            principal,
            payload,
            if_match,
            idempotency_key,
            step_up_token=step_up_token,
        ),
    )


@router.post(
    "/vault/members/{member_id}/revoke",
    response_model=VaultMutationReference,
    operation_id="revokeVaultMember",
)
def revoke_member(
    member_id: CanonicalUUID,
    payload: VaultEmptyMutation,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
    step_up_token: StepUpToken = None,
):
    return _result(
        response,
        service.revoke_member(
            session,
            principal,
            member_id,
            if_match,
            idempotency_key,
            step_up_token=step_up_token,
        ),
    )


@router.post(
    "/vault/shares",
    response_model=VaultMutationReference,
    status_code=201,
    operation_id="createVaultShare",
)
def create_share(
    payload: VaultShareCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
    step_up_token: StepUpToken = None,
):
    """If-Match is the vault status version; target identity is inside its wrapping."""
    return _result(
        response,
        service.create_share(
            session,
            principal,
            payload,
            if_match,
            idempotency_key,
            step_up_token=step_up_token,
        ),
    )


@router.get(
    "/vault/shares",
    response_model=VaultShareListResponse,
    operation_id="listVaultShares",
    description=(
        "본인 관련 공유 이력을 생성 시각·ID 내림차순으로 조회합니다. "
        "cursor는 직전 페이지 마지막 공유 ID이며 현재 가계와 참여자 범위에서 확인합니다."
    ),
)
def list_shares(
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    cursor: CanonicalUUID | None = None,
    limit: Limit = 50,
):
    return _result(response, service.list_shares(session, principal, cursor=cursor, limit=limit))


@router.get(
    "/vault/shares/{offer_id}/wrapping",
    response_model=VaultShareWrappingResponse,
    operation_id="getVaultShareWrapping",
)
def get_share_wrapping(
    offer_id: CanonicalUUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    step_up_token: StepUpToken = None,
):
    result = service.get_share_wrapping(session, principal, offer_id, step_up_token=step_up_token)
    return _result(response, result, etag=result.offer.version)


@router.post(
    "/vault/shares/{offer_id}/accept",
    response_model=VaultMutationReference,
    operation_id="acceptVaultShare",
)
def accept_share(
    offer_id: CanonicalUUID,
    payload: VaultKeyConfirmation,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
    step_up_token: StepUpToken = None,
):
    return _result(
        response,
        service.accept_share(
            session,
            principal,
            offer_id,
            payload,
            if_match,
            idempotency_key,
            step_up_token=step_up_token,
        ),
    )


@router.post(
    "/vault/shares/{offer_id}/cancel",
    response_model=VaultMutationReference,
    operation_id="cancelVaultShare",
)
def cancel_share(
    offer_id: CanonicalUUID,
    payload: VaultEmptyMutation,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
    step_up_token: StepUpToken = None,
):
    return _result(
        response,
        service.cancel_share(
            session,
            principal,
            offer_id,
            if_match,
            idempotency_key,
            step_up_token=step_up_token,
        ),
    )


@router.get(
    "/cards/{card_id}/secret-envelope",
    response_model=CardSecretResponse,
    operation_id="getCardSecretEnvelope",
)
def get_card_secret(
    card_id: CanonicalUUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    result = service.get_card_secret(session, principal, card_id)
    return _result(response, result, etag=result.card_version)


@router.put(
    "/cards/{card_id}/secret-envelope",
    response_model=VaultMutationReference,
    operation_id="writeCardSecretEnvelope",
)
def write_card_secret(
    card_id: CanonicalUUID,
    payload: CardEnvelopeInput,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    """If-Match is the card metadata version; the supplied last four changes atomically."""
    return _result(
        response,
        service.write_card_secret(
            session,
            principal,
            card_id,
            payload,
            if_match,
            idempotency_key,
        ),
    )


@router.delete(
    "/cards/{card_id}/secret-envelope",
    response_model=VaultMutationReference,
    operation_id="deleteCardSecretEnvelope",
)
def delete_card_secret(
    card_id: CanonicalUUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    """Irreversibly purge online ciphertext across every key version; keep nonce history."""
    return _result(
        response,
        service.delete_card_secret(
            session,
            principal,
            card_id,
            if_match,
            idempotency_key,
        ),
    )


@router.post(
    "/vault/rotations",
    response_model=VaultMutationReference,
    status_code=201,
    operation_id="startVaultRotation",
)
def start_rotation(
    payload: VaultRotationStart,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
    step_up_token: StepUpToken = None,
):
    return _result(
        response,
        service.start_rotation(
            session,
            principal,
            payload,
            if_match,
            idempotency_key,
            step_up_token=step_up_token,
        ),
    )


@router.get(
    "/vault/rotations/{rotation_id}",
    response_model=VaultRotationResponse,
    operation_id="getVaultRotation",
)
def get_rotation(
    rotation_id: CanonicalUUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    return _result(response, service.get_rotation(session, principal, rotation_id))


@router.post(
    "/vault/rotations/{rotation_id}/prepare",
    response_model=VaultMutationReference,
    operation_id="prepareVaultRotation",
)
def prepare_rotation(
    rotation_id: CanonicalUUID,
    payload: VaultRotationPrepare,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
    step_up_token: StepUpToken = None,
):
    return _result(
        response,
        service.prepare_rotation(
            session,
            principal,
            rotation_id,
            payload,
            if_match,
            idempotency_key,
            step_up_token=step_up_token,
        ),
    )


@router.put(
    "/vault/rotations/{rotation_id}/cards/{card_id}",
    response_model=VaultMutationReference,
    operation_id="stageVaultRotationCard",
)
def stage_card(
    rotation_id: CanonicalUUID,
    card_id: CanonicalUUID,
    payload: VaultRotationCardWrite,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
    step_up_token: StepUpToken = None,
):
    """If-Match is the rotation version, shared by every staged write and finalization."""
    return _result(
        response,
        service.stage_card(
            session,
            principal,
            rotation_id,
            card_id,
            payload,
            if_match,
            idempotency_key,
            step_up_token=step_up_token,
        ),
    )


@router.get(
    "/vault/rotations/{rotation_id}/cards/{card_id}",
    response_model=CardSecretResponse,
    operation_id="getStagedVaultCard",
)
def get_staged_card(
    rotation_id: CanonicalUUID,
    card_id: CanonicalUUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    return _result(response, service.get_staged_card(session, principal, rotation_id, card_id))


@router.get(
    "/vault/rotations/{rotation_id}/wrappings/me",
    response_model=VaultOwnWrappingResponse,
    operation_id="getOwnStagedVaultWrapping",
)
def get_staged_wrapping(
    rotation_id: CanonicalUUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    return _result(response, service.get_staged_wrapping(session, principal, rotation_id))


@router.post(
    "/vault/rotations/{rotation_id}/finalize",
    response_model=VaultMutationReference,
    operation_id="finalizeVaultRotation",
)
def finalize_rotation(
    rotation_id: CanonicalUUID,
    payload: VaultKeyConfirmation,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
    step_up_token: StepUpToken = None,
):
    return _result(
        response,
        service.finalize_rotation(
            session,
            principal,
            rotation_id,
            payload,
            if_match,
            idempotency_key,
            step_up_token=step_up_token,
        ),
    )


@router.post(
    "/vault/rotations/{rotation_id}/abort",
    response_model=VaultMutationReference,
    operation_id="abortVaultRotation",
)
def abort_rotation(
    rotation_id: CanonicalUUID,
    payload: VaultEmptyMutation,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
    step_up_token: StepUpToken = None,
):
    return _result(
        response,
        service.abort_rotation(
            session,
            principal,
            rotation_id,
            if_match,
            idempotency_key,
            step_up_token=step_up_token,
        ),
    )
