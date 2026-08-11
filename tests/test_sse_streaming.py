import asyncio
import json
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.api.routes import _event_stream
from app.application.services.review_service import ReviewService, ReviewWorker, default_review_service
from app.main import app


client = TestClient(app)


def diff_with_findings() -> str:
    return (
        "--- a/b.py\n+++ b/b.py\n@@ -0,0 +1,2 @@\n+console.log('debug')\n+eval(userInput)\n"
        "--- a/a.py\n+++ b/a.py\n@@ -0,0 +1,2 @@\n+// TODO: sort me first\n+const token = 'ABCDEF0123456789'\n"
    )


def chunked_diff_with_same_findings(padding: int = 40000) -> str:
    return (
        f"--- a/a.py\n+++ b/a.py\n@@ -0,0 +1,2 @@\n+// TODO: sort me first\n+{'x' * padding}\n"
        f"--- a/b.py\n+++ b/b.py\n@@ -0,0 +1,2 @@\n+console.log('debug')\n+{'y' * padding}\n"
    )


def parse_sse(text: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in text.strip().split("\n\n"):
        event_type = ""
        payload: dict[str, object] | None = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event_type = line.removeprefix("event: ")
            if line.startswith("data: "):
                payload = json.loads(line.removeprefix("data: "))
        if event_type and payload is not None:
            events.append((event_type, payload))
    return events


def submit_and_process(service: ReviewService, diff: str, *, max_findings: int = 100, provider: str = "mock") -> str:
    result = service.submit_review(diff=diff, provider=provider, max_findings=max_findings, idempotency_key=None)
    ReviewWorker(service).process_job(result["jobId"])
    return result["jobId"]


def stream_job(job_id: str) -> list[tuple[str, dict[str, object]]]:
    with client.stream("GET", f"/v1/reviews/{job_id}/stream", headers={"Authorization": "Bearer test-token"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return parse_sse(response.read().decode("utf-8"))


async def collect_stream(service: ReviewService, job_id: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    async for frame in _event_stream(service, job_id):
        events.extend(parse_sse(frame))
    return events


def public_event_history(service: ReviewService, job_id: str) -> list[tuple[str, dict[str, object]]]:
    return [(event.type, event.payload) for event in service.list_events(job_id)]


def test_stream_endpoint_requires_auth_and_unknown_job_returns_404() -> None:
    assert client.get("/v1/reviews/unknown/stream").status_code == 401
    response = client.get("/v1/reviews/unknown/stream", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 404


def test_stream_endpoint_content_type_and_sse_framing() -> None:
    job_id = submit_and_process(default_review_service, diff_with_findings())

    with client.stream("GET", f"/v1/reviews/{job_id}/stream", headers={"Authorization": "Bearer test-token"}) as response:
        text = response.read().decode("utf-8")

    assert "event: status\n" in text
    assert "data: " in text
    assert text.endswith("\n\n")


def test_successful_event_lifecycle_ordering_and_persistence() -> None:
    job_id = submit_and_process(default_review_service, diff_with_findings())

    events = stream_job(job_id)
    event_types = [event_type for event_type, _ in events]
    finding_payloads = [payload for event_type, payload in events if event_type == "finding"]

    assert event_types == ["status", "status", "finding", "finding", "finding", "finding", "status", "done"]
    assert [payload["status"] for event_type, payload in events if event_type == "status"] == ["queued", "running", "done"]
    assert [(payload["path"], payload["line"], payload["ruleId"]) for payload in finding_payloads] == [
        ("a.py", 1, "MOCK-008"),
        ("a.py", 2, "MOCK-002"),
        ("b.py", 1, "MOCK-007"),
        ("b.py", 2, "MOCK-001"),
    ]
    assert events[-1] == ("done", {"total": 4, "usage": {"inputBytes": len(diff_with_findings().encode("utf-8")), "chunks": 1, "cacheHit": False}})
    assert public_event_history(default_review_service, job_id) == events
    assert [event.sequence for event in default_review_service.list_events(job_id)] == list(range(1, len(events) + 1))


def test_completed_job_replay_is_exact_and_does_not_duplicate_or_regenerate() -> None:
    job_id = submit_and_process(default_review_service, diff_with_findings())
    original_history = public_event_history(default_review_service, job_id)

    first = stream_job(job_id)
    second = stream_job(job_id)

    assert first == original_history
    assert second == original_history
    assert public_event_history(default_review_service, job_id) == original_history


def test_live_client_connected_before_processing_receives_all_events() -> None:
    async def scenario() -> list[tuple[str, dict[str, object]]]:
        service = ReviewService()
        result = service.submit_review(diff=diff_with_findings(), provider="mock", max_findings=100, idempotency_key=None)
        task = asyncio.create_task(collect_stream(service, result["jobId"]))
        await asyncio.sleep(0)
        ReviewWorker(service).process_job(result["jobId"])
        return await task

    events = asyncio.run(scenario())

    assert [event_type for event_type, _ in events] == ["status", "status", "finding", "finding", "finding", "finding", "status", "done"]


def test_live_client_connecting_mid_job_receives_history_plus_future_events() -> None:
    async def scenario() -> list[tuple[str, dict[str, object]]]:
        service = ReviewService()
        result = service.submit_review(diff=diff_with_findings(), provider="mock", max_findings=100, idempotency_key=None)
        job = service.get_job(result["jobId"])
        assert job is not None
        job.mark_running()
        service.job_repository.save(job)
        service.append_event(job.job_id, "status", {"jobId": job.job_id, "status": "running"})
        task = asyncio.create_task(collect_stream(service, job.job_id))
        await asyncio.sleep(0)
        service.append_event(job.job_id, "status", {"jobId": job.job_id, "status": "failed"})
        return await task

    events = asyncio.run(scenario())

    assert events == [
        ("status", {"jobId": events[0][1]["jobId"], "status": "queued"}),
        ("status", {"jobId": events[0][1]["jobId"], "status": "running"}),
        ("status", {"jobId": events[0][1]["jobId"], "status": "failed"}),
    ]


def test_two_live_clients_receive_same_sequence_without_loss_or_duplicates() -> None:
    async def scenario() -> tuple[list[tuple[str, dict[str, object]]], list[tuple[str, dict[str, object]]]]:
        service = ReviewService()
        result = service.submit_review(diff=diff_with_findings(), provider="mock", max_findings=100, idempotency_key=None)
        first = asyncio.create_task(collect_stream(service, result["jobId"]))
        second = asyncio.create_task(collect_stream(service, result["jobId"]))
        await asyncio.sleep(0)
        ReviewWorker(service).process_job(result["jobId"])
        return await first, await second

    first, second = asyncio.run(scenario())

    assert first == second
    assert [event_type for event_type, _ in first].count("done") == 1
    assert len(first) == len(set((event_type, json.dumps(payload, sort_keys=True)) for event_type, payload in first))


def test_failed_job_emits_failed_status_and_no_done_event() -> None:
    job_id = submit_and_process(default_review_service, diff_with_findings(), provider="llm")

    events = stream_job(job_id)

    assert events[-1] == ("status", {"jobId": job_id, "status": "failed"})
    assert "done" not in [event_type for event_type, _ in events]


def test_chunked_and_unchunked_jobs_have_identical_finding_event_sequences() -> None:
    unchunked_job_id = submit_and_process(default_review_service, chunked_diff_with_same_findings(padding=10))
    chunked_job_id = submit_and_process(default_review_service, chunked_diff_with_same_findings(padding=40000))

    unchunked_findings = [payload for event_type, payload in stream_job(unchunked_job_id) if event_type == "finding"]
    chunked_findings = [payload for event_type, payload in stream_job(chunked_job_id) if event_type == "finding"]

    assert unchunked_findings == chunked_findings


def test_max_findings_limits_stream_and_done_total() -> None:
    job_id = submit_and_process(default_review_service, diff_with_findings(), max_findings=2)

    events = stream_job(job_id)

    assert len([event for event in events if event[0] == "finding"]) == 2
    assert events[-1][1]["total"] == 2
