import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException

from sallimbook.core.errors import DomainError, ErrorDetail, ErrorResponse, FieldError

logger = logging.getLogger("sallimbook.requests")


def error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    current_version: int | None = None,
    fields: list[FieldError] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=request.state.request_id,
            current_version=current_version,
            fields=fields,
        )
    )
    return JSONResponse(status_code=status, content=body.model_dump(exclude_none=True))


def install_http_contract(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        try:
            response = await call_next(request)
        except Exception as exc:
            # Never log the exception text/traceback: DB errors may embed input parameters.
            logger.error(
                "request_failed id=%s type=%s", request.state.request_id, type(exc).__name__
            )
            response = error_response(request, 500, "INTERNAL_ERROR", "요청을 처리하지 못했습니다.")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if any(
            item["type"] == "missing" and item["loc"] == ("header", "If-Match")
            for item in exc.errors()
        ):
            return error_response(request, 400, "VERSION_REQUIRED", "수정할 버전을 지정해 주세요.")
        if any(
            item["type"] == "missing" and item["loc"] == ("header", "Idempotency-Key")
            for item in exc.errors()
        ):
            return error_response(
                request, 400, "INVALID_IDEMPOTENCY_KEY", "재시도 식별자를 확인해 주세요."
            )
        fields = [
            # Later loc segments can be submitted dict keys, extra field names,
            # or discriminator values. Return only the framework-owned source.
            FieldError(
                field=item["loc"][0]
                if item["loc"] and item["loc"][0] in {"body", "query", "path", "header", "cookie"}
                else "request",
                code=item["type"],
            )
            for item in exc.errors()
        ]
        return error_response(
            request, 422, "VALIDATION_ERROR", "입력값을 확인해 주세요.", fields=fields
        )

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return error_response(request, exc.status, exc.code, exc.safe_message, exc.current_version)

    @app.exception_handler(StaleDataError)
    async def version_conflict(request: Request, exc: StaleDataError):
        return error_response(request, 409, "VERSION_CONFLICT", "다른 기기에서 수정했습니다.")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        codes = {
            400: ("BAD_REQUEST", "잘못된 요청입니다."),
            401: ("UNAUTHENTICATED", "로그인이 필요합니다."),
            403: ("FORBIDDEN", "허용되지 않은 요청입니다."),
            404: ("NOT_FOUND", "요청한 항목을 찾을 수 없습니다."),
            405: ("METHOD_NOT_ALLOWED", "허용되지 않은 요청 방식입니다."),
            429: ("RATE_LIMITED", "잠시 후 다시 시도해 주세요."),
        }
        code, message = codes.get(
            exc.status_code, ("REQUEST_FAILED", "요청을 처리하지 못했습니다.")
        )
        response = error_response(request, exc.status_code, code, message)
        # Only protocol headers; never echo arbitrary exception detail/headers.
        for name, value in (exc.headers or {}).items():
            if name.lower() in {"allow", "retry-after", "www-authenticate"}:
                response.headers[name] = value
        return response
