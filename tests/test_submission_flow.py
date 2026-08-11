from fastapi.testclient import TestClient

from app.main import app
from app.infrastructure.rate_limiter import default_rate_limiter

client = TestClient(app)


def valid_body(extra: str = "") -> str:
    return (
        '{"diff":"--- a/file.py\\n+++ b/file.py\\n@@ -1 +1 @@\\n-old\\n+new",'
        '"options":{"provider":"mock","maxFindings":100}'
        f"{extra}"
        "}"
    )


def test_submit_review_returns_202_and_creates_job() -> None:
    response = client.post(
        "/v1/reviews",
        headers={"Authorization": "Bearer test-token", "Idempotency-Key": "abc"},
        json={"diff": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"},
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["jobId"]


def test_idempotency_conflict_for_same_key_different_body() -> None:
    first = client.post(
        "/v1/reviews",
        headers={"Authorization": "Bearer test-token", "Idempotency-Key": "same-key"},
        json={"diff": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"},
    )
    assert first.status_code == 202

    second = client.post(
        "/v1/reviews",
        headers={"Authorization": "Bearer test-token", "Idempotency-Key": "same-key"},
        json={"diff": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+other"},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "idempotency_conflict"


def test_idempotency_same_key_byte_identical_body_returns_same_job_id() -> None:
    default_rate_limiter.reset()
    body = valid_body()
    headers = {"Authorization": "Bearer test-token", "Idempotency-Key": "byte-identical", "Content-Type": "application/json"}

    first = client.post("/v1/reviews", headers=headers, content=body)
    second = client.post("/v1/reviews", headers=headers, content=body)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["jobId"] == first.json()["jobId"]


def test_idempotency_same_key_different_unknown_field_returns_409() -> None:
    default_rate_limiter.reset()
    headers = {"Authorization": "Bearer test-token", "Idempotency-Key": "unknown-differs", "Content-Type": "application/json"}

    first = client.post("/v1/reviews", headers=headers, content=valid_body(',"ignored":"one"'))
    second = client.post("/v1/reviews", headers=headers, content=valid_body(',"ignored":"two"'))

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "idempotency_conflict"


def test_idempotency_same_key_different_json_body_returns_409() -> None:
    default_rate_limiter.reset()
    headers = {"Authorization": "Bearer test-token", "Idempotency-Key": "json-differs", "Content-Type": "application/json"}

    first = client.post("/v1/reviews", headers=headers, content=valid_body())
    second = client.post(
        "/v1/reviews",
        headers=headers,
        content='{"diff":"--- a/file.py\\n+++ b/file.py\\n@@ -1 +1 @@\\n-old\\n+other"}',
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "idempotency_conflict"


def test_idempotency_different_key_same_body_remains_valid() -> None:
    default_rate_limiter.reset()
    body = valid_body()

    first = client.post(
        "/v1/reviews",
        headers={"Authorization": "Bearer test-token", "Idempotency-Key": "key-one", "Content-Type": "application/json"},
        content=body,
    )
    second = client.post(
        "/v1/reviews",
        headers={"Authorization": "Bearer test-token", "Idempotency-Key": "key-two", "Content-Type": "application/json"},
        content=body,
    )

    assert first.status_code == 202
    assert second.status_code == 202


def test_unknown_fields_without_idempotency_key_remain_ignored() -> None:
    default_rate_limiter.reset()
    response = client.post(
        "/v1/reviews",
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
        content=valid_body(',"ignored":"still ignored"'),
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"


def test_invalid_diff_returns_422() -> None:
    response = client.post(
        "/v1/reviews",
        headers={"Authorization": "Bearer test-token"},
        json={"diff": "not a diff"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_diff"


def test_post_cache_hit_and_get_reflects_cache_hit() -> None:
    from app.application.services.review_service import default_review_service
    from app.domain.models import Job, Usage
    import hashlib

    # Prepare a completed job in the service repository and cache it
    diff = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"
    provider = "mock"
    max_findings = 100
    fingerprint = hashlib.sha256(f"{diff}\n{provider}\n{max_findings}".encode("utf-8")).hexdigest()

    # Create and mark a job as completed
    job = Job.create(provider=provider, max_findings=max_findings, request_fingerprint=fingerprint, diff=diff)
    job.mark_running()
    job.mark_done(findings=[], usage=Usage(input_bytes=len(diff.encode("utf-8")), chunks=1, cache_hit=False))
    default_review_service.job_repository.save(job)
    default_review_service.cache_repository.save(fingerprint, job.job_id)

    # POST with identical body should report cacheHit true
    response = client.post(
        "/v1/reviews",
        headers={"Authorization": "Bearer test-token"},
        json={"diff": diff, "options": {"provider": provider, "maxFindings": max_findings}},
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["cacheHit"] is True
    cached_job_id = payload["jobId"]

    # GET the job should reflect usage.cacheHit true
    r = client.get(f"/v1/reviews/{cached_job_id}", headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200
    job_payload = r.json()
    assert job_payload["usage"]["cacheHit"] is True
