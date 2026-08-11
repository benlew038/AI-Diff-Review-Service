import json
from time import sleep

from fastapi.testclient import TestClient

from app.main import app
from app.infrastructure.rate_limiter import default_rate_limiter


client = TestClient(app)


def sample_diff() -> str:
    return "--- a/app.py\n+++ b/app.py\n@@ -0,0 +1 @@\n+print('hi')\n"


def test_post_under_limit(monkeypatch):
    # Configure a permissive rate for the test
    from app.infrastructure.config import Settings
    settings = Settings(
        app_version="0.1.0",
        auth_token="test-token",
        max_payload_bytes=1048576,
        chunk_bytes=65536,
        max_concurrent_jobs=4,
        rate_limit_per_minute=5,
        rate_limit_burst=1,
        rate_limit_backend="memory",
    )
    monkeypatch.setattr("app.infrastructure.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.infrastructure.rate_limiter.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.routes.get_settings", lambda: settings)
    default_rate_limiter.reload_settings()
    default_rate_limiter.reset()

    headers = {"Authorization": "Bearer test-token"}
    r1 = client.post("/v1/reviews", headers=headers, json={"diff": sample_diff()})
    r2 = client.post("/v1/reviews", headers=headers, json={"diff": sample_diff()})

    assert r1.status_code == 202
    assert r2.status_code == 202


def test_exceed_limit_returns_429_and_retry_after(monkeypatch):
    from app.infrastructure.config import Settings
    settings = Settings(
        app_version="0.1.0",
        auth_token="test-token",
        max_payload_bytes=1048576,
        chunk_bytes=65536,
        max_concurrent_jobs=4,
        rate_limit_per_minute=1,
        rate_limit_burst=0,
        rate_limit_backend="memory",
    )
    monkeypatch.setattr("app.infrastructure.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.infrastructure.rate_limiter.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.routes.get_settings", lambda: settings)
    default_rate_limiter.reload_settings()
    default_rate_limiter.reset()

    headers = {"Authorization": "Bearer test-token"}
    r1 = client.post("/v1/reviews", headers=headers, json={"diff": sample_diff()})
    r2 = client.post("/v1/reviews", headers=headers, json={"diff": sample_diff()})

    assert r1.status_code == 202
    assert r2.status_code == 429
    assert "Retry-After" in r2.headers
    payload = r2.json()
    assert payload["error"]["code"] == "rate_limited"


def test_burst_allows_extra_requests(monkeypatch):
    from app.infrastructure.config import Settings
    settings = Settings(
        app_version="0.1.0",
        auth_token="test-token",
        max_payload_bytes=1048576,
        chunk_bytes=65536,
        max_concurrent_jobs=4,
        rate_limit_per_minute=1,
        rate_limit_burst=2,
        rate_limit_backend="memory",
    )
    monkeypatch.setattr("app.infrastructure.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.infrastructure.rate_limiter.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.routes.get_settings", lambda: settings)
    default_rate_limiter.reload_settings()
    default_rate_limiter.reset()

    headers = {"Authorization": "Bearer test-token"}
    results = [client.post("/v1/reviews", headers=headers, json={"diff": sample_diff()}) for _ in range(4)]
    statuses = [r.status_code for r in results]
    # first three allowed (1 + burst 2), fourth should be 429
    assert statuses.count(202) == 3
    assert statuses.count(429) == 1


def test_gets_not_limited(monkeypatch):
    from app.infrastructure.config import Settings
    settings = Settings(
        app_version="0.1.0",
        auth_token="test-token",
        max_payload_bytes=1048576,
        chunk_bytes=65536,
        max_concurrent_jobs=4,
        rate_limit_per_minute=1,
        rate_limit_burst=0,
        rate_limit_backend="memory",
    )
    monkeypatch.setattr("app.infrastructure.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.infrastructure.rate_limiter.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.routes.get_settings", lambda: settings)
    default_rate_limiter.reload_settings()
    default_rate_limiter.reset()

    # multiple health/spec GETs should not be limited
    for _ in range(10):
        r = client.get("/health")
        assert r.status_code == 200
        r = client.get("/spec")
        assert r.status_code == 200


def test_spec_reflects_config(monkeypatch):
    from app.infrastructure.config import Settings
    settings = Settings(
        app_version="0.1.0",
        auth_token="test-token",
        max_payload_bytes=1048576,
        chunk_bytes=65536,
        max_concurrent_jobs=4,
        rate_limit_per_minute=99,
        rate_limit_burst=0,
        rate_limit_backend="memory",
    )
    monkeypatch.setattr("app.infrastructure.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.infrastructure.rate_limiter.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.routes.get_settings", lambda: settings)
    default_rate_limiter.reload_settings()
    default_rate_limiter.reset()

    r = client.get("/spec")
    assert r.status_code == 200
    body = r.json()
    assert body["limits"]["rateLimitPerMinute"] == 99
