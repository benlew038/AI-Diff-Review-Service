from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"]
    assert isinstance(payload["uptimeSeconds"], int)


def test_spec_endpoint() -> None:
    response = client.get("/spec")
    assert response.status_code == 200
    payload = response.json()
    assert payload["specVersion"] == "1.0"
    assert payload["providers"] == ["mock", "llm"]
    assert payload["limits"]["maxConcurrentJobs"] == 4


def test_spec_reflects_config(monkeypatch) -> None:
    from app.infrastructure.config import Settings

    # Patch the get_settings function in the routes module so /spec reads these values
    monkeypatch.setattr("app.api.routes.get_settings", lambda: Settings(max_payload_bytes=12345, chunk_bytes=54321, max_concurrent_jobs=7, rate_limit_per_minute=99))
    response = client.get("/spec")
    assert response.status_code == 200
    payload = response.json()
    assert payload["limits"]["maxPayloadBytes"] == 12345
    assert payload["limits"]["chunkBytes"] == 54321
    assert payload["limits"]["maxConcurrentJobs"] == 7
    assert payload["limits"]["rateLimitPerMinute"] == 99


def test_review_requires_auth() -> None:
    response = client.post(
        "/v1/reviews",
        json={"diff": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"},
    )
    assert response.status_code == 401
    payload = response.json()
    assert payload["error"]["code"] == "unauthorized"
