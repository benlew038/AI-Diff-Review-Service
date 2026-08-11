import asyncio
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.application.providers.llm_provider import LLMProvider, LLMProviderError
from app.application.services.review_service import ReviewService, ReviewWorker, default_review_service
from app.domain.diff_parser import AddedLine
from app.domain.models import Job
from app.main import app
from app.application.providers import get_provider


client = TestClient(app)


def submit_and_process_llm(service: ReviewService, diff: str, *, max_findings: int = 100) -> str:
    result = service.submit_review(diff=diff, provider="llm", max_findings=max_findings, idempotency_key=None)
    ReviewWorker(service).process_job(result["jobId"])
    return result["jobId"]


def diff_with_llm_findings() -> str:
    return "--- a/app.py\n+++ b/app.py\n@@ -0,0 +1,2 @@\n+eval(x)\n+console.log('debug')\n"


def test_llm_provider_selected_in_api(monkeypatch) -> None:
    settings = type("S", (), {"llm_api_key": "key", "llm_api_url": "https://example.com/api", "llm_model": "model", "llm_timeout_seconds": 1})()
    monkeypatch.setattr("app.application.providers.llm_provider.get_settings", lambda: settings)
    monkeypatch.setattr(LLMProvider, "_send_request", lambda self, prompt, settings: json.dumps([]))
    response = client.post(
        "/v1/reviews",
        headers={"Authorization": "Bearer test-token"},
        json={"diff": diff_with_llm_findings(), "options": {"provider": "llm"}},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"


def test_llm_job_fails_when_provider_errors(monkeypatch) -> None:
    service = ReviewService()
    settings = type("S", (), {"llm_api_key": "key", "llm_api_url": "https://example.com/api", "llm_model": "model", "llm_timeout_seconds": 1})()
    monkeypatch.setattr("app.application.providers.llm_provider.get_settings", lambda: settings)
    monkeypatch.setattr(LLMProvider, "_send_request", lambda self, prompt, settings: (_ for _ in ()).throw(LLMProviderError("LLM failed")))

    job_id = submit_and_process_llm(service, diff_with_llm_findings())
    job = service.get_job(job_id)
    assert job is not None
    assert job.status.value == "failed"


def test_llm_successful_job_uses_existing_sort_and_truncation(monkeypatch) -> None:
    service = ReviewService()
    settings = type("S", (), {"llm_api_key": "key", "llm_api_url": "https://example.com/api", "llm_model": "model", "llm_timeout_seconds": 1})()
    monkeypatch.setattr("app.application.providers.llm_provider.get_settings", lambda: settings)

    response_json = json.dumps([
        {"id": "LLM-001:app.py:1", "ruleId": "LLM-001", "path": "app.py", "line": 1, "severity": "high", "category": "security", "title": "eval usage", "evidence": "eval(x)"},
        {"id": "LLM-002:app.py:2", "ruleId": "LLM-002", "path": "app.py", "line": 2, "severity": "low", "category": "style", "title": "console usage", "evidence": "console.log('debug')"},
    ])
    monkeypatch.setattr(LLMProvider, "_send_request", lambda self, prompt, settings: response_json)

    job_id = submit_and_process_llm(service, diff_with_llm_findings(), max_findings=1)
    job = service.get_job(job_id)
    assert job is not None
    assert job.status.value == "done"
    assert len(job.findings) == 1
    assert job.findings[0].id == "LLM-001:app.py:1"


def test_llm_does_not_accept_client_api_key(monkeypatch) -> None:
    response = client.post(
        "/v1/reviews",
        headers={"Authorization": "Bearer test-token"},
        json={
            "diff": diff_with_llm_findings(),
            "options": {"provider": "llm", "apiKey": "client-provided-key"},
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
