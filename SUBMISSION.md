# Submission Notes

This repository implements Milestones 1–10 of the AI Diff Review Service. The implementation is intended for single-process evaluation and includes an in-memory rate limiter (Milestone 10).

Project overview

- Asynchronous review pipeline that accepts unified diffs, processes added lines through a provider, and returns structured findings.
- Two providers: `mock` (deterministic, used for scoring) and `llm` (HTTP-based adapter; requires server-side credentials).

Key configuration (environment variables)

- `AUTH_TOKEN` — bearer token for `/v1/*` routes (default: `test-token`)
- `APP_VERSION` — version returned by `/health`
- `MAX_PAYLOAD_BYTES` — max request size (default: 1048576)
- `CHUNK_BYTES` — chunk size for diff chunking (default: 65536)
- `MAX_CONCURRENT_JOBS` — worker concurrency (default: 4)
- `RATE_LIMIT_PER_MINUTE` — submissions/minute for `POST /v1/reviews` (default: 30)
- `RATE_LIMIT_BURST` — extra burst capacity for token-bucket (default: 10)
- `LLM_API_KEY` — server-side LLM API key (optional)
- `LLM_API_URL` — LLM provider HTTP endpoint (optional)
- `LLM_MODEL` — model id passed to the LLM provider (optional)
- `LLM_TIMEOUT_SECONDS` — LLM request timeout (default: 15)

Milestone summary (1–10)

- M1: Public API skeleton (`/health`, `/spec`) and FastAPI scaffolding.
- M2: Bearer authentication and request validation (JSON, payload size, unified-diff validation).
- M3: Job model with in-memory persistence and event sequencing.
- M4: Submission orchestration with idempotency keys and result caching.
- M5: Worker pool, queueing, and concurrency (default 4 workers).
- M6: Unified diff parsing, added-line extraction, and chunking on file boundaries.
- M7: Deterministic `MockProvider` implementing the scoring rules for added lines.
- M8: SSE event streaming with replay from persisted events and multi-client support.
- M9: `LLMProvider` that sends added lines to a configured HTTP endpoint and validates JSON responses.
- M10: POST-only in-memory token-bucket rate limiter, `429`+`Retry-After` behavior, and documentation.

Design decisions

- Keep the core pipeline provider-agnostic: providers return normalized `Finding` objects.
- Persist events and job state in-memory for accurate SSE replay in a single-process evaluation.
- Implement a simple, thread-safe token-bucket rate limiter keyed by bearer token for M10; this meets the assessment requirements while avoiding external infrastructure.

API and auth

- Authentication: `Authorization: Bearer <token>` header required for all `/v1/*` routes. Token must match `AUTH_TOKEN`.
- Error envelope: all non-2xx responses use `{ "error": { "code": "<code>", "message": "<text>" } }`.

Job processing

- Jobs transition: `queued` → `running` → `done` or `failed`.
- Findings are deduplicated by `id`, sorted by `path`, `line`, `ruleId`, and truncated to `maxFindings`.

Testing and verification

- Run the full test suite:

```bash
python -m pytest -q
```

- Current test result (local): `79 passed, 0 failed, 5 warnings`.

Known limitations and deployment assumptions

- In-memory repositories and rate limiter are single-process only. For multi-instance production, a centralized backend (Redis or durable DB) is required for rate limits, idempotency and event persistence.
- `LLMProvider` adapts a generic JSON-based LLM endpoint; exact vendor payloads may need an adapter in production.

How to run

1. Install dependencies: `python -m pip install -r requirements.txt`
2. Run the app: `uvicorn app.main:app --reload`
3. Use the configured bearer token (`AUTH_TOKEN`) when calling `/v1` routes.

AI tools used

- **Codex**: used for generating small, repetitive code patches and unit test scaffolding (examples: test stubs, simple repository updates). Used primarily to speed up routine edits; all Codex outputs were reviewed and adjusted for project conventions.
- **Raptor mini**: used for high-level drafting of documentation text and the README/SUBMISSION narrative. The generated prose was edited for accuracy, security constraints, and to ensure no sensitive keys are exposed.

One AI suggestion that was rejected

- Suggested change: an AI suggestion recommended moving rate-limiting state to Redis (or a database) and adding Docker-based deployment to unify environment configuration. Reason rejected: Redis or Docker were considered out-of-scope and unnecessary for the single-process, in-memory assessment required by the task, so those changes were not applied. The suggestion was valid for production hardening but out-of-scope for this submission.

What I would do next with more time

- Add an optional Redis-backed rate limiter and shared repositories for idempotency and events to support multi-instance deployments.
- Add integration tests exercising a real LLM vendor (behind a mock proxy) to validate vendor-specific payload/response shapes and retry/backoff behavior.
- Add durability for events (append-only log) and background cleanup for old entries.
- Harden observability: structured logging, tracing, and metrics for rate-limits and worker latencies.

Verification notes (how chunking, caching, idempotency, SSE replay were verified)

- Chunking: verified by unit tests that exercise `chunk_diff` on diffs containing multiple files and large files; the `ReviewWorker` uses `chunk_diff(..., max_chunk_bytes=get_settings().chunk_bytes)` so tests that monkeypatch `chunk_bytes` validate chunk boundaries.
- Caching: verified by creating a completed `Job` in the in-memory `job_repository`, saving a mapping in `cache_repository`, then asserting that a subsequent `POST /v1/reviews` with the identical body returns `cacheHit: true` and that the re-used job's `usage.cacheHit` is set to `true` on the stored job (see `tests/test_submission_flow.py::test_post_cache_hit_and_get_reflects_cache_hit`).
- Idempotency: verified by posting twice with the same `Idempotency-Key` but different bodies and asserting a `409` is returned, and by ensuring identical idempotent bodies return the original job id.
- SSE replay: verified by tests that subscribe to `/v1/reviews/{jobId}/stream`, confirm persisted events are replayed in order, and witness live events emitted by the worker after replay ends (see `tests/test_sse_streaming.py`).

