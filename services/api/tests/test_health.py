from fastapi.testclient import TestClient

from sallimbook.config import Settings
from sallimbook.main import create_app


def test_liveness_exposes_only_process_status():
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unlisted_browser_origin_is_not_allowed():
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/v1/health",
            headers={"Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "GET"},
        )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_production_does_not_publish_interactive_api_docs():
    with TestClient(create_app(Settings(environment="production", allowed_origins=[]))) as client:
        for path in ("/api/docs", "/api/openapi.json"):
            assert client.get(path).status_code == 404
