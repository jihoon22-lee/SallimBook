import pytest
from fastapi.testclient import TestClient

from sallimbook.config import Settings
from sallimbook.main import create_app


def test_liveness_exposes_only_process_status():
    with TestClient(create_app(Settings(environment="test", _env_file=None))) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unlisted_browser_origin_is_not_allowed():
    settings = Settings(environment="test", allowed_origins=[], _env_file=None)
    with TestClient(create_app(settings)) as client:
        response = client.options(
            "/api/v1/health",
            headers={"Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "GET"},
        )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_production_does_not_publish_interactive_api_docs():
    settings = Settings(environment="production", allowed_origins=[], _env_file=None)
    with TestClient(create_app(settings)) as client:
        for path in ("/api/docs", "/api/openapi.json"):
            assert client.get(path).status_code == 404


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environments_reject_default_local_browser_origins(environment, monkeypatch):
    monkeypatch.delenv("SALLIMBOOK_ALLOWED_ORIGINS", raising=False)
    settings = Settings(environment=environment, _env_file=None)
    with TestClient(create_app(settings)) as client:
        for origin in ("http://localhost:18742", "http://127.0.0.1:18742"):
            response = client.options(
                "/api/v1/health",
                headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
            )
            assert response.status_code == 400
            assert "access-control-allow-origin" not in response.headers


def test_explicit_production_browser_origin_is_allowed():
    settings = Settings(
        environment="production", allowed_origins=["https://synthetic.invalid"], _env_file=None
    )
    with TestClient(create_app(settings)) as client:
        response = client.options(
            "/api/v1/health",
            headers={
                "Origin": "https://synthetic.invalid", "Access-Control-Request-Method": "GET"
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://synthetic.invalid"
