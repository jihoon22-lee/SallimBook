from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sallimbook.config import Settings


class HealthResponse(BaseModel):
    status: Literal["ok"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    development = settings.environment in ("development", "test")
    app = FastAPI(
        title="SallimBook API",
        version="0.1.0",
        docs_url="/api/docs" if development else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if development else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/v1/health", response_model=HealthResponse, operation_id="getHealth")
    def health() -> HealthResponse:
        """Process liveness only. Does not imply database readiness."""
        return HealthResponse(status="ok")

    return app


app = create_app()
