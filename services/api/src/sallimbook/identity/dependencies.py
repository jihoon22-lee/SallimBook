import hashlib
import hmac
import ipaddress
import socket
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from sallimbook.core.authorization import Principal
from sallimbook.core.database import get_session
from sallimbook.core.errors import DomainError
from sallimbook.identity.service import authenticate

SESSION_COOKIE = "__Host-sallimbook_session"
NATIVE_HEADER = "X-SallimBook-Native"
SessionDependency = Annotated[Session, Depends(get_session)]


def require_allowed_origin(request: Request, *, required: bool = True) -> None:
    origin = request.headers.get("origin")
    if origin is None and not required:
        return
    if origin is None or origin not in request.app.state.settings.allowed_origins:
        raise DomainError("ORIGIN_REJECTED", "허용되지 않은 요청 출처입니다.", 403)


def _require_json(request: Request) -> None:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise DomainError("JSON_REQUIRED", "JSON 요청 형식을 사용해 주세요.", 400)


def require_web_transport(request: Request) -> None:
    require_allowed_origin(request)
    _require_json(request)
    if "authorization" in request.headers:
        raise DomainError("WRONG_AUTH_TRANSPORT", "인증 경로를 확인해 주세요.", 400)


def require_native_transport(request: Request) -> None:
    """A browser-exclusion transport rule, not proof of device trust or biometrics."""
    if (
        "origin" in request.headers
        or "cookie" in request.headers
        or request.headers.get(NATIVE_HEADER) != "1"
    ):
        raise DomainError("WRONG_AUTH_TRANSPORT", "네이티브 인증 경로를 확인해 주세요.", 403)
    if request.method != "DELETE":
        _require_json(request)


def require_registration_transport(request: Request) -> None:
    if "origin" in request.headers:
        require_web_transport(request)
    else:
        require_native_transport(request)


def get_principal(request: Request, session: SessionDependency) -> Principal:
    cookie = request.cookies.get(SESSION_COOKIE)
    authorization = request.headers.get("authorization")
    if cookie and authorization:
        raise DomainError("AMBIGUOUS_AUTH", "하나의 인증 경로만 사용해 주세요.", 400)
    if authorization:
        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator:
            raise DomainError("UNAUTHENTICATED", "로그인이 필요합니다.", 401)
        return authenticate(session, token, "native")
    if cookie:
        mutation = request.method not in {"GET", "HEAD", "OPTIONS"}
        require_allowed_origin(request, required=mutation)
        return authenticate(
            session,
            cookie,
            "web",
            csrf_token=request.headers.get("X-CSRF-Token"),
            check_csrf=mutation,
        )
    raise DomainError("UNAUTHENTICATED", "로그인이 필요합니다.", 401)


PrincipalDependency = Annotated[Principal, Depends(get_principal)]


def request_source(request: Request) -> str:
    # Trust the ASGI peer only; callers cannot evade throttles with X-Forwarded-For.
    return request.client.host if request.client else "unknown-peer"


def self_setup_identity_allowed(request: Request) -> bool:
    """Trust identity only from the actual isolated Serve/Caddy network peer.

    Serve v1.104.1 removes supplied identity headers before setting its own.
    Caddy binds loopback in that node's namespace; API has no published port and
    Uvicorn must keep --no-proxy-headers. A forwarded IP is never evidence here.
    """
    settings = request.app.state.settings
    expected = settings.self_setup_identity_sha256
    proxy = settings.self_setup_proxy_host
    values = request.headers.getlist("tailscale-user-login")
    if (
        not expected
        or not proxy
        or request.client is None
        or len(values) != 1
        or not values[0]
        or len(values[0]) > 512
        or not values[0].isascii()
        or any(ord(value) < 32 or ord(value) == 127 for value in values[0])
        or "tailscale-funnel-request" in request.headers
    ):
        return False
    try:
        peer = ipaddress.ip_address(request.client.host)
        resolved = {
            ipaddress.ip_address(address[4][0])
            for address in socket.getaddrinfo(proxy, None, type=socket.SOCK_STREAM)
        }
    except OSError, ValueError:
        return False
    if peer not in resolved:
        return False
    return hmac.compare_digest(expected, hashlib.sha256(values[0].encode("ascii")).hexdigest())


def require_self_setup_identity(request: Request) -> None:
    if not self_setup_identity_allowed(request):
        raise DomainError("SETUP_UNAVAILABLE", "이 연결에서는 처음 시작할 수 없습니다.", 403)
