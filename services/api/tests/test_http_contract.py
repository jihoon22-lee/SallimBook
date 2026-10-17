from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from sallimbook.config import Settings
from sallimbook.core.errors import DomainError
from sallimbook.core.types import KrwString
from sallimbook.main import create_app


def test_validation_errors_do_not_echo_inputs():
    app = create_app(Settings(environment="test"))

    class Input(BaseModel):
        amount: KrwString

    @app.post("/test-only/amount")
    def validate_amount(payload: Input):
        return payload

    with TestClient(app) as client:
        response = client.post("/test-only/amount", json={"amount": "synthetic-sensitive-input"})
    assert response.status_code == 422
    assert "synthetic-sensitive-input" not in response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.headers["cache-control"] == "no-store"
    assert str(UUID(response.json()["error"]["request_id"])) == response.headers["x-request-id"]


def test_domain_conflict_is_versioned_and_correlated():
    app = create_app(Settings(environment="test"))

    @app.get("/test-only/conflict")
    def conflict():
        raise DomainError("VERSION_CONFLICT", "다른 기기에서 수정했습니다.", 409, current_version=8)

    with TestClient(app) as client:
        response = client.get("/test-only/conflict")
    assert response.status_code == 409
    assert response.json()["error"]["current_version"] == 8


def test_validation_paths_do_not_echo_dictionary_keys_or_extra_fields():
    app = create_app(Settings(environment="test"))

    class Input(BaseModel):
        model_config = ConfigDict(extra="forbid")
        mapping: dict[str, int]

    @app.post("/test-only/mapping")
    def validate_mapping(payload: Input):
        return payload

    with TestClient(app) as client:
        response = client.post(
            "/test-only/mapping",
            json={"mapping": {"synthetic-sensitive-key": "invalid"}, "synthetic-extra": True},
        )
    assert response.status_code == 422
    assert "synthetic-sensitive-key" not in response.text
    assert "synthetic-extra" not in response.text
    assert all(field["field"] == "body" for field in response.json()["error"]["fields"])


def test_unexpected_error_does_not_log_or_return_exception_text(caplog):
    app = create_app(Settings(environment="test"))

    @app.get("/test-only/failure")
    def failure():
        raise RuntimeError("synthetic-sensitive-parameter")

    with TestClient(app) as client:
        response = client.get("/test-only/failure", headers={"Origin": "http://localhost:18742"})
    assert response.status_code == 500
    assert "synthetic-sensitive-parameter" not in response.text
    assert "synthetic-sensitive-parameter" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:18742"


def test_readiness_without_db_does_not_claim_success():
    with TestClient(create_app(Settings(environment="test", database_url=None))) as client:
        assert client.get("/api/v1/health").status_code == 200
        response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
