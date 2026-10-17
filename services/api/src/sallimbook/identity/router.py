from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import func, select

from sallimbook.core.authorization import require_recent_login, require_version
from sallimbook.core.errors import DomainError
from sallimbook.identity import service
from sallimbook.identity.auth_models import AuthSession, HouseholdMember, RegisteredDevice, User
from sallimbook.identity.dependencies import (
    SESSION_COOKIE,
    PrincipalDependency,
    SessionDependency,
    request_source,
    require_native_transport,
    require_registration_transport,
    require_web_transport,
)
from sallimbook.identity.passkeys.models import StepUpPurpose
from sallimbook.identity.passkeys.service import consume_step_up
from sallimbook.identity.schemas import (
    CsrfResponse,
    DeviceListResponse,
    DeviceResponse,
    InvitationAcceptance,
    InvitationRequest,
    InvitationResponse,
    LoginRequest,
    MemberResponse,
    NativeTokenResponse,
    RefreshRequest,
    WebLoginResponse,
)

router = APIRouter(prefix="/api/v1", tags=["identity"])


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
        member=result.member,
        csrf_token=result.csrf_token,
        expires_at=result.expires_at,
    )


@router.get("/auth/web/csrf", response_model=CsrfResponse, operation_id="renewWebCsrf")
def renew_web_csrf(principal: PrincipalDependency, session: SessionDependency) -> CsrfResponse:
    return CsrfResponse(csrf_token=service.renew_csrf(session, principal))


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
    query = select(RegisteredDevice).where(
        RegisteredDevice.household_id == principal.household_id,
        RegisteredDevice.user_id == principal.user_id,
    )
    if cursor is not None:
        query = query.where(RegisteredDevice.id < cursor)
    rows = list(session.scalars(query.order_by(RegisteredDevice.id.desc()).limit(limit + 1)))
    activity = dict(
        session.execute(
            select(
                AuthSession.device_id,
                func.max(AuthSession.last_seen_at),
            )
            .where(
                AuthSession.household_id == principal.household_id,
                AuthSession.user_id == principal.user_id,
                AuthSession.device_id.in_([device.id for device in rows[:limit]]),
            )
            .group_by(AuthSession.device_id)
        ).all()
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
            )
            for device in rows[:limit]
        ],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )
    session.commit()
    return result


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
