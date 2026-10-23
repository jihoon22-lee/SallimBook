from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import func, select

from sallimbook.core.authorization import require_recent_login, require_version
from sallimbook.core.errors import DomainError
from sallimbook.core.pagination import keyset_page
from sallimbook.identity import service
from sallimbook.identity.auth_models import AuthSession, HouseholdMember, RegisteredDevice, User
from sallimbook.identity.dependencies import (
    SESSION_COOKIE,
    PrincipalDependency,
    SessionDependency,
    request_source,
    require_native_transport,
    require_registration_transport,
    require_self_setup_identity,
    require_web_transport,
    self_setup_identity_allowed,
)
from sallimbook.identity.passkeys.models import StepUpPurpose
from sallimbook.identity.passkeys.service import consume_step_up
from sallimbook.identity.schemas import (
    ConnectionCodeResponse,
    ConnectionRequest,
    CsrfResponse,
    DeviceListResponse,
    DeviceResponse,
    InvitationAcceptance,
    InvitationRequest,
    InvitationResponse,
    LoginRequest,
    MemberResponse,
    NativeTokenResponse,
    PasswordChangeRequest,
    ReauthenticationRequest,
    RefreshRequest,
    RevokedDevicesResponse,
    SetupRequest,
    SetupStatusResponse,
    WebLoginResponse,
)

router = APIRouter(prefix="/api/v1", tags=["identity"])


def _web_session_response(response: Response, result: service.LoginResult) -> WebLoginResponse:
    response.set_cookie(
        SESSION_COOKIE,
        result.token,
        max_age=int(service.WEB_ABSOLUTE.total_seconds()),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return WebLoginResponse(
        member=result.member, csrf_token=result.csrf_token, expires_at=result.expires_at
    )


@router.get(
    "/household/setup", response_model=SetupStatusResponse, operation_id="getHouseholdSetup"
)
def get_household_setup(
    request: Request, response: Response, session: SessionDependency
) -> SetupStatusResponse:
    response.headers["Cache-Control"] = "no-store"
    return SetupStatusResponse(
        available=(self_setup_identity_allowed(request) and service.setup_available(session))
    )


@router.post(
    "/auth/web/setup",
    response_model=WebLoginResponse,
    status_code=201,
    dependencies=[Depends(require_web_transport), Depends(require_self_setup_identity)],
    operation_id="setupHouseholdWeb",
)
def setup_household_web(
    payload: SetupRequest,
    request: Request,
    response: Response,
    session: SessionDependency,
) -> WebLoginResponse:
    return _web_session_response(
        response,
        service.setup_household(
            session,
            payload,
            request_source(request),
            "web",
        ),
    )


@router.post(
    "/auth/native/setup",
    response_model=NativeTokenResponse,
    status_code=201,
    dependencies=[Depends(require_native_transport), Depends(require_self_setup_identity)],
    operation_id="setupHouseholdNative",
)
def setup_household_native(
    payload: SetupRequest,
    request: Request,
    session: SessionDependency,
) -> NativeTokenResponse:
    return service.setup_household(
        session, payload, request_source(request), "native"
    ).native_tokens


@router.post(
    "/auth/web/connect",
    response_model=WebLoginResponse,
    status_code=201,
    dependencies=[Depends(require_web_transport)],
    operation_id="connectHouseholdWeb",
)
def connect_household_web(
    payload: ConnectionRequest,
    request: Request,
    response: Response,
    session: SessionDependency,
) -> WebLoginResponse:
    return _web_session_response(
        response,
        service.connect_household(
            session,
            payload,
            request_source(request),
            "web",
        ),
    )


@router.post(
    "/auth/native/connect",
    response_model=NativeTokenResponse,
    status_code=201,
    dependencies=[Depends(require_native_transport)],
    operation_id="connectHouseholdNative",
)
def connect_household_native(
    payload: ConnectionRequest,
    request: Request,
    session: SessionDependency,
) -> NativeTokenResponse:
    return service.connect_household(
        session, payload, request_source(request), "native"
    ).native_tokens


@router.post(
    "/household/connection-code",
    response_model=ConnectionCodeResponse,
    status_code=201,
    operation_id="createHouseholdConnectionCode",
)
def create_household_connection_code(
    principal: PrincipalDependency,
    session: SessionDependency,
    step_up_token: Annotated[str | None, Header(alias="X-Step-Up-Token", max_length=128)] = None,
) -> ConnectionCodeResponse:
    return service.create_connection_code(session, principal, step_up_token=step_up_token)


@router.post(
    "/auth/web/login",
    response_model=WebLoginResponse,
    dependencies=[Depends(require_web_transport)],
    operation_id="loginWeb",
)
def login_web(
    payload: LoginRequest, request: Request, response: Response, session: SessionDependency
) -> WebLoginResponse:
    result = service.login(session, payload, request_source(request), "web")
    return _web_session_response(response, result)


@router.get("/auth/web/csrf", response_model=CsrfResponse, operation_id="renewWebCsrf")
def renew_web_csrf(principal: PrincipalDependency, session: SessionDependency) -> CsrfResponse:
    return CsrfResponse(csrf_token=service.renew_csrf(session, principal))


@router.post(
    "/auth/password",
    response_model=RevokedDevicesResponse,
    dependencies=[Depends(require_registration_transport)],
    operation_id="changePassword",
)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
) -> RevokedDevicesResponse:
    return service.change_password(session, principal, payload, request_source(request))


@router.post(
    "/auth/web/reauthenticate",
    response_model=MemberResponse,
    dependencies=[Depends(require_web_transport)],
    operation_id="reauthenticateWeb",
)
def reauthenticate_web(
    payload: ReauthenticationRequest,
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
) -> MemberResponse:
    if principal.transport != "web":
        raise DomainError("WRONG_AUTH_TRANSPORT", "인증 경로를 확인해 주세요.", 403)
    return service.reauthenticate(session, principal, payload, request_source(request))


@router.post("/auth/web/logout", status_code=204, operation_id="logoutWeb")
def logout_web(principal: PrincipalDependency, session: SessionDependency) -> Response:
    if principal.transport != "web":
        raise DomainError("WRONG_AUTH_TRANSPORT", "인증 경로를 확인해 주세요.", 403)
    service.logout(session, principal)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return response


@router.post(
    "/auth/native/login",
    response_model=NativeTokenResponse,
    dependencies=[Depends(require_native_transport)],
    operation_id="loginNative",
)
def login_native(
    payload: LoginRequest, request: Request, session: SessionDependency
) -> NativeTokenResponse:
    return service.login(session, payload, request_source(request), "native").native_tokens


@router.post(
    "/auth/native/refresh",
    response_model=NativeTokenResponse,
    dependencies=[Depends(require_native_transport)],
    operation_id="refreshNative",
)
def refresh_native(
    payload: RefreshRequest, request: Request, session: SessionDependency
) -> NativeTokenResponse:
    return service.rotate_refresh(
        session, payload.refresh_token.get_secret_value(), request_source(request)
    )


@router.post(
    "/auth/native/reauthenticate",
    response_model=MemberResponse,
    dependencies=[Depends(require_native_transport)],
    operation_id="reauthenticateNative",
)
def reauthenticate_native(
    payload: ReauthenticationRequest,
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
) -> MemberResponse:
    if principal.transport != "native":
        raise DomainError("WRONG_AUTH_TRANSPORT", "인증 경로를 확인해 주세요.", 403)
    return service.reauthenticate(session, principal, payload, request_source(request))


@router.post(
    "/auth/native/logout",
    status_code=204,
    dependencies=[Depends(require_native_transport)],
    operation_id="logoutNative",
)
def logout_native(principal: PrincipalDependency, session: SessionDependency) -> Response:
    if principal.transport != "native":
        raise DomainError("WRONG_AUTH_TRANSPORT", "인증 경로를 확인해 주세요.", 403)
    service.logout(session, principal)
    return Response(status_code=204)


@router.post(
    "/auth/invitations/accept",
    response_model=MemberResponse,
    status_code=201,
    dependencies=[Depends(require_registration_transport)],
    operation_id="acceptInvitation",
)
def accept_invitation(
    payload: InvitationAcceptance, request: Request, session: SessionDependency
) -> MemberResponse:
    return service.accept_invitation(session, payload, request_source(request))


@router.get("/me", response_model=MemberResponse, operation_id="getCurrentMember")
def get_me(principal: PrincipalDependency, session: SessionDependency) -> MemberResponse:
    user = session.get(User, principal.user_id)
    member = session.get(HouseholdMember, principal.member_id)
    result = service.member_response(user, member)
    session.commit()
    return result


@router.get(
    "/household/members", response_model=list[MemberResponse], operation_id="listHouseholdMembers"
)
def get_members(principal: PrincipalDependency, session: SessionDependency) -> list[MemberResponse]:
    rows = session.execute(
        select(User, HouseholdMember)
        .select_from(User)
        .join(HouseholdMember)
        .where(
            HouseholdMember.household_id == principal.household_id,
            HouseholdMember.status == "active",
            User.disabled_at.is_(None),
        )
        .order_by(HouseholdMember.slot)
    )
    result = [service.member_response(user, member) for user, member in rows]
    session.commit()
    return result


@router.post(
    "/household/invitations",
    response_model=InvitationResponse,
    status_code=201,
    operation_id="createPartnerInvitation",
)
def create_invitation(
    payload: InvitationRequest,
    principal: PrincipalDependency,
    session: SessionDependency,
    step_up_token: Annotated[str | None, Header(alias="X-Step-Up-Token", max_length=128)] = None,
) -> InvitationResponse:
    return service.create_partner_invitation(
        session, principal, payload, step_up_token=step_up_token
    )


@router.get("/devices", response_model=DeviceListResponse, operation_id="listDevices")
def get_devices(
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DeviceListResponse:
    now = service.utcnow()
    cutoff = now - service.DEVICE_LIST_IDLE
    used_recently = (
        select(AuthSession.id)
        .where(
            AuthSession.household_id == RegisteredDevice.household_id,
            AuthSession.device_id == RegisteredDevice.id,
            AuthSession.last_seen_at > cutoff,
        )
        .exists()
    )
    query = select(RegisteredDevice).where(
        RegisteredDevice.household_id == principal.household_id,
        RegisteredDevice.user_id == principal.user_id,
        (RegisteredDevice.status != "active")
        | (RegisteredDevice.last_seen_at > cutoff)
        | used_recently,
    )
    rows, next_cursor = keyset_page(
        session,
        query,
        model=RegisteredDevice,
        household_id=principal.household_id,
        keys=(RegisteredDevice.created_at,),
        cursor=cursor,
        limit=limit,
        cursor_where=(RegisteredDevice.user_id == principal.user_id,),
    )
    activity = dict(
        session.execute(
            select(
                AuthSession.device_id,
                func.max(AuthSession.last_seen_at),
            )
            .where(
                AuthSession.household_id == principal.household_id,
                AuthSession.user_id == principal.user_id,
                AuthSession.device_id.in_([device.id for device in rows]),
            )
            .group_by(AuthSession.device_id)
        ).all()
    )
    live = set(
        session.scalars(
            select(AuthSession.device_id).where(
                AuthSession.household_id == principal.household_id,
                AuthSession.user_id == principal.user_id,
                AuthSession.device_id.in_([device.id for device in rows]),
                service.live_session(now),
            )
        )
    )
    result = DeviceListResponse(
        items=[
            DeviceResponse(
                id=device.id,
                label=device.label,
                platform=device.platform,
                status=device.status,
                last_seen_at=max(device.last_seen_at, activity.get(device.id, device.last_seen_at)),
                version=device.version,
                current=device.id == principal.device_id,
                login_state=(
                    "revoked"
                    if device.status == "revoked"
                    else "active"
                    if device.id in live
                    else "expired"
                ),
            )
            for device in rows
        ],
        next_cursor=next_cursor,
    )
    session.commit()
    return result


@router.post(
    "/devices/revoke-others",
    response_model=RevokedDevicesResponse,
    dependencies=[Depends(require_registration_transport)],
    operation_id="revokeOtherDevices",
)
def revoke_other_devices(
    payload: ReauthenticationRequest,
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
) -> RevokedDevicesResponse:
    # One route for both transports: Origin+CSRF for cookies, the native header for bearer.
    return service.revoke_other_devices(session, principal, payload, request_source(request))


@router.delete("/devices/{device_id}", status_code=204, operation_id="revokeDevice")
def revoke_device(
    device_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    step_up_token: Annotated[str | None, Header(alias="X-Step-Up-Token", max_length=128)] = None,
) -> Response:
    if step_up_token is None:
        require_recent_login(principal, now=service.utcnow())
    auth, devices = service.lock_session_devices(
        session, principal, additional_device_ids=(device_id,)
    )
    device = devices[device_id]
    require_version(device, if_match)
    if step_up_token is None:
        service.validate_locked_session(
            principal, auth, devices[principal.device_id], recent_login=True
        )
    else:
        consume_step_up(session, principal, step_up_token, StepUpPurpose.DEVICE_REVOKE, device.id)
    service.revoke_device(session, principal, device)
    return Response(status_code=204)
