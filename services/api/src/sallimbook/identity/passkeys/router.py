from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import select

from sallimbook.core.authorization import require_recent_login, require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.identity import service as identity
from sallimbook.identity.dependencies import (
    SESSION_COOKIE,
    PrincipalDependency,
    SessionDependency,
    request_source,
    require_native_transport,
    require_web_transport,
)
from sallimbook.identity.passkeys import service
from sallimbook.identity.passkeys.models import AuthCredential
from sallimbook.identity.passkeys.schemas import (
    AssertionVerification,
    CredentialListResponse,
    CredentialResponse,
    LoginOptionsRequest,
    NativeLoginVerification,
    NativeOptionsResponse,
    OptionsResponse,
    RegisterOptionsRequest,
    RegisterVerification,
    StepUpOptionsRequest,
    StepUpResponse,
)
from sallimbook.identity.schemas import NativeTokenResponse, WebLoginResponse

BINDING_COOKIE = "__Host-sallimbook_passkey"
router = APIRouter(prefix="/api/v1", tags=["passkeys"])


def _authenticated_policy(request: Request, principal):
    if principal.transport == "web":
        require_web_transport(request)
    else:
        require_native_transport(request)
    return service.policy_from_settings(
        request.app.state.settings, principal.transport, request.headers.get("origin")
    )


@router.post(
    "/auth/passkeys/register/options",
    response_model=OptionsResponse,
    operation_id="createPasskeyRegistrationOptions",
)
def registration_options(
    payload: RegisterOptionsRequest,
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
):
    return service.registration_options(
        session, principal, payload, _authenticated_policy(request, principal)
    )


@router.post(
    "/auth/passkeys/register/verify",
    response_model=CredentialResponse,
    status_code=201,
    operation_id="verifyPasskeyRegistration",
)
def register_passkey(
    payload: RegisterVerification,
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
):
    return service.register_credential(
        session, principal, payload, _authenticated_policy(request, principal)
    )


@router.post(
    "/auth/web/passkeys/options",
    response_model=OptionsResponse,
    dependencies=[Depends(require_web_transport)],
    operation_id="createWebPasskeyOptions",
)
def web_login_options(
    payload: LoginOptionsRequest, request: Request, response: Response, session: SessionDependency
):
    policy = service.policy_from_settings(
        request.app.state.settings, "web", request.headers.get("origin")
    )
    result = service.login_options(session, payload, policy, request_source(request))
    response.set_cookie(
        BINDING_COOKIE,
        result.device_binding,
        max_age=int(service.CHALLENGE_LIFETIME.total_seconds()),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return result.response


@router.post(
    "/auth/web/passkeys/verify",
    response_model=WebLoginResponse,
    dependencies=[Depends(require_web_transport)],
    operation_id="loginWithWebPasskey",
)
def web_login_verify(
    payload: AssertionVerification, request: Request, response: Response, session: SessionDependency
):
    policy = service.policy_from_settings(
        request.app.state.settings, "web", request.headers.get("origin")
    )
    result = service.verify_login(
        session, payload, policy, request.cookies.get(BINDING_COOKIE), request_source(request)
    )
    response.set_cookie(
        SESSION_COOKIE,
        result.token,
        max_age=int(identity.WEB_ABSOLUTE.total_seconds()),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    response.delete_cookie(BINDING_COOKIE, secure=True, httponly=True, samesite="strict", path="/")
    return WebLoginResponse(
        member=result.member, csrf_token=result.csrf_token, expires_at=result.expires_at
    )


@router.post(
    "/auth/native/passkeys/options",
    response_model=NativeOptionsResponse,
    dependencies=[Depends(require_native_transport)],
    operation_id="createNativePasskeyOptions",
)
def native_login_options(
    payload: LoginOptionsRequest, request: Request, session: SessionDependency
):
    policy = service.policy_from_settings(request.app.state.settings, "native", None)
    result = service.login_options(session, payload, policy, request_source(request))
    return NativeOptionsResponse(
        **result.response.model_dump(), device_binding=result.device_binding
    )


@router.post(
    "/auth/native/passkeys/verify",
    response_model=NativeTokenResponse,
    dependencies=[Depends(require_native_transport)],
    operation_id="loginWithNativePasskey",
)
def native_login_verify(
    payload: NativeLoginVerification, request: Request, session: SessionDependency
):
    policy = service.policy_from_settings(request.app.state.settings, "native", None)
    return service.verify_login(
        session, payload, policy, payload.device_binding.get_secret_value(), request_source(request)
    ).native_tokens


@router.post(
    "/auth/step-up/options", response_model=OptionsResponse, operation_id="createStepUpOptions"
)
def step_up_options(
    payload: StepUpOptionsRequest,
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
):
    return service.step_up_options(
        session, principal, payload, _authenticated_policy(request, principal)
    )


@router.post("/auth/step-up/verify", response_model=StepUpResponse, operation_id="verifyStepUp")
def step_up_verify(
    payload: AssertionVerification,
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
):
    return service.verify_step_up(
        session, principal, payload, _authenticated_policy(request, principal)
    )


@router.get("/auth/passkeys", response_model=CredentialListResponse, operation_id="listPasskeys")
def list_passkeys(
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    query = select(AuthCredential).where(
        AuthCredential.household_id == principal.household_id,
        AuthCredential.user_id == principal.user_id,
        AuthCredential.revoked_at.is_(None),
    )
    if cursor is not None:
        query = query.where(AuthCredential.id < cursor)
    rows = list(session.scalars(query.order_by(AuthCredential.id.desc()).limit(limit + 1)))
    result = CredentialListResponse(
        items=[service.credential_response(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )
    session.commit()
    return result


@router.delete("/auth/passkeys/{credential_id}", status_code=204, operation_id="revokePasskey")
def revoke_passkey(
    credential_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):
    require_recent_login(principal, now=identity.utcnow())
    auth, devices = identity.lock_session_devices(session, principal)
    credential = scoped_entity(session, AuthCredential, credential_id, principal, for_update=True)
    if credential.user_id != principal.user_id:
        raise DomainError("NOT_FOUND", "요청한 항목을 찾을 수 없습니다.", 404)
    require_version(credential, if_match)
    identity.validate_locked_session(
        principal, auth, devices[principal.device_id], recent_login=True
    )
    credential.revoked_at = identity.utcnow()
    session.commit()
    return Response(status_code=204)
