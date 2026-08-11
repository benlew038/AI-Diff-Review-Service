import json
import hashlib
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from app.application.services.review_service import ReviewService, default_review_service
from app.domain.models import ReviewEvent
from app.infrastructure.config import get_settings
from app.shared.errors import ApiError, ErrorCode
from app.workers.worker_pool import default_worker_pool
from app.infrastructure.rate_limiter import default_rate_limiter

router = APIRouter()


def get_review_service() -> ReviewService:
    return default_review_service


def require_bearer_token(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(ErrorCode.UNAUTHORIZED, "missing or invalid bearer token")

    token = authorization.split(" ", 1)[1]
    if token != get_settings().auth_token:
        raise ApiError(ErrorCode.UNAUTHORIZED, "missing or invalid bearer token")


@router.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "version": get_settings().app_version, "uptimeSeconds": 0}


@router.get("/spec")
def spec() -> dict[str, object]:
    return {
        "specVersion": "1.0",
        "providers": ["mock", "llm"],
        "limits": {
            "maxPayloadBytes": get_settings().max_payload_bytes,
            "chunkBytes": get_settings().chunk_bytes,
            "maxConcurrentJobs": get_settings().max_concurrent_jobs,
            "rateLimitPerMinute": get_settings().rate_limit_per_minute,
        },
    }


@router.post("/v1/reviews", status_code=202)
async def submit_review(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    review_service: ReviewService = Depends(get_review_service),
) -> dict[str, object]:
    require_bearer_token(authorization)
    # Apply POST-only rate limiting per bearer token
    token = authorization.split(" ", 1)[1]
    default_rate_limiter.consume(token)

    try:
        body_bytes = await request.body()
    except UnicodeDecodeError:
        raise ApiError(ErrorCode.INVALID_JSON, "request body must be valid JSON")

    # Enforce overall JSON request body size (in bytes) per settings
    if len(body_bytes) > get_settings().max_payload_bytes:
        raise ApiError(ErrorCode.PAYLOAD_TOO_LARGE, "payload exceeds size limit")

    try:
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else None
    except json.JSONDecodeError:
        raise ApiError(ErrorCode.INVALID_JSON, "request body must be valid JSON")

    if payload is None:
        raise ApiError(ErrorCode.INVALID_JSON, "request body must be valid JSON")
    if not isinstance(payload, dict):
        raise ApiError(ErrorCode.INVALID_JSON, "request body must be an object")

    diff_value = payload.get("diff")
    if not isinstance(diff_value, str) or not diff_value.strip():
        raise ApiError(ErrorCode.INVALID_DIFF, "diff is required")

    options = payload.get("options")
    if options is not None and not isinstance(options, dict):
        raise ApiError(ErrorCode.INVALID_JSON, "options must be an object")

    provider = (options or {}).get("provider", "mock") if isinstance(options, dict) else "mock"
    if provider not in {"mock", "llm"}:
        raise ApiError(ErrorCode.INVALID_JSON, "unknown provider")

    max_findings = (options or {}).get("maxFindings", 100) if isinstance(options, dict) else 100
    if not isinstance(max_findings, int) or max_findings < 1:
        raise ApiError(ErrorCode.INVALID_JSON, "maxFindings must be a positive integer")

    if not review_service.is_unified_diff(diff_value):
        raise ApiError(ErrorCode.INVALID_DIFF, "diff is not a unified diff")

    result = review_service.submit_review(
        diff=diff_value,
        provider=provider,
        max_findings=max_findings,
        idempotency_key=idempotency_key,
        idempotency_body_fingerprint=hashlib.sha256(body_bytes).hexdigest(),
    )
    if result.get("newJob", False):
        await default_worker_pool.enqueue_job(result["jobId"])
    return {"jobId": result["jobId"], "status": "queued", "cacheHit": result.get("cacheHit", False)}


@router.get("/v1/reviews/{job_id}")
def get_review(job_id: str, authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, object]:
    require_bearer_token(authorization)

    service = default_review_service
    job = service.get_job(job_id)
    if job is None:
        raise ApiError(ErrorCode.NOT_FOUND, "job not found")

    return job.to_public_dict()


@router.get("/v1/reviews/{job_id}/stream")
def stream_review(job_id: str, authorization: str | None = Header(default=None, alias="Authorization")) -> StreamingResponse:
    require_bearer_token(authorization)

    service = default_review_service
    job = service.get_job(job_id)
    if job is None:
        raise ApiError(ErrorCode.NOT_FOUND, "job not found")

    return StreamingResponse(_event_stream(service, job_id), media_type="text/event-stream")


async def _event_stream(service: ReviewService, job_id: str) -> AsyncIterator[str]:
    subscriber = service.event_broadcaster.subscribe(job_id)
    last_sequence = 0
    try:
        for event in service.list_events(job_id):
            last_sequence = event.sequence
            yield _format_sse(event)
            if _is_terminal_event(event):
                return

        while True:
            event = await subscriber.get()
            if event.sequence <= last_sequence:
                continue
            last_sequence = event.sequence
            yield _format_sse(event)
            if _is_terminal_event(event):
                return
    finally:
        service.event_broadcaster.unsubscribe(job_id, subscriber)


def _format_sse(event: ReviewEvent) -> str:
    payload = json.dumps(event.payload, separators=(",", ":"))
    return f"event: {event.type}\ndata: {payload}\n\n"


def _is_terminal_event(event: ReviewEvent) -> bool:
    if event.type == "done":
        return True
    return event.type == "status" and event.payload.get("status") == "failed"
