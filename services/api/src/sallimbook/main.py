from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from sallimbook.assets.router import router as assets_router
from sallimbook.config import Settings
from sallimbook.core.database import REQUIRED_SCHEMA_REVISION, make_engine
from sallimbook.core.errors import DomainError, ErrorResponse
from sallimbook.core.http import install_http_contract
from sallimbook.identity.passkeys.router import router as passkey_router
from sallimbook.identity.router import router as identity_router


class HealthResponse(BaseModel):
    status: Literal["ok"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    development = settings.environment in ("development", "test")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.engine = (
            make_engine(settings.database_url.get_secret_value()) if settings.database_url else None
        )
        try:
            yield
        finally:
            if app.state.engine is not None:
                app.state.engine.dispose()

    app = FastAPI(
        title="SallimBook API",
        version="0.1.0",
        docs_url="/api/docs" if development else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if development else None,
        lifespan=lifespan,
        responses={
            code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 422, 429, 500, 503)
        },
    )
    install_http_contract(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "If-Match",
            "Idempotency-Key",
            "X-CSRF-Token",
            "X-Step-Up-Token",
        ],
        expose_headers=["X-Request-ID", "ETag"],
    )

    @app.get("/api/v1/health", response_model=HealthResponse, operation_id="getHealth")
    def health() -> HealthResponse:
        """Process liveness only. Does not imply database readiness."""
        return HealthResponse(status="ok")

    @app.get("/api/v1/ready", response_model=HealthResponse, operation_id="getReadiness")
    def readiness() -> HealthResponse:
        """Database connectivity and the initial schema must both be available."""
        engine = app.state.engine
        if engine is None:
            raise DomainError("DATABASE_UNAVAILABLE", "데이터 저장소를 준비하고 있습니다.", 503)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
                if revision != REQUIRED_SCHEMA_REVISION:
                    raise DomainError(
                        "SCHEMA_UNAVAILABLE", "데이터 저장소를 준비하고 있습니다.", 503
                    )
        except SQLAlchemyError:
            raise DomainError(
                "DATABASE_UNAVAILABLE", "데이터 저장소를 준비하고 있습니다.", 503
            ) from None
        return HealthResponse(status="ok")

    app.include_router(identity_router)
    app.include_router(passkey_router)
    app.include_router(assets_router)
    return app


app = create_app()
