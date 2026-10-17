from pydantic import BaseModel


class FieldError(BaseModel):
    field: str
    code: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    current_version: int | None = None
    fields: list[FieldError] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class DomainError(Exception):
    def __init__(
        self, code: str, message: str, status: int = 422, current_version: int | None = None
    ):
        super().__init__(code)
        self.code = code
        self.safe_message = message
        self.status = status
        self.current_version = current_version
