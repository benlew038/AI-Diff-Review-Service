# AI Diff Review Service

This repository implements an asynchronous AI-backed code diff review service and a deterministic `mock` provider. It includes Milestones 1–10 of the assessment (single-process/in-memory implementation).

What this service provides

- Public endpoints: `/health`, `/spec` (public); authenticated review API under `/v1`.
- Submission flow: `POST /v1/reviews` accepts a unified diff and returns a queued job id (`202`).
- Idempotency and caching: byte-identical requests are cached and idempotency keys are supported.
- Background processing: bounded worker pool (configurable concurrency) processes jobs asynchronously.
- Providers: `mock` (deterministic rule engine) and `llm` (HTTP-based LLM adapter).
- SSE streaming: `GET /v1/reviews/{jobId}/stream` replays persisted events and streams live events.
- Rate limiting (Milestone 10): POST-only in-memory token-bucket limiter, configurable via environment variables.

High-level architecture

- API layer (FastAPI): request validation, auth, and error envelope mapping.
- Application services: submission, idempotency, cache, and job orchestration.
- Worker layer: `ReviewWorker` and `WorkerPool` process jobs concurrently and emit events.
- Providers: pluggable `Provider` interface with `MockProvider` and `LLMProvider` implementations.
- Persistence: in-memory repositories for jobs, events, idempotency and cache (suitable for single-process evaluation).

Requirements / prerequisites

- Python 3.11+ (a virtual environment is recommended)
- Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run locally (development):

```bash
uvicorn app.main:app --reload
```

Run tests (from project root):

```bash
python -m pytest -q
```

Configuration (environment variables)

The service uses environment variables (see `app/infrastructure/config.py`). Important variables:

- `AUTH_TOKEN` — bearer token required for all `/v1/*` routes (default: `test-token`)
- `APP_VERSION` — version returned by `/health`
- `MAX_PAYLOAD_BYTES` — maximum allowed request payload bytes (default: 1048576)
- `CHUNK_BYTES` — chunk size for diff chunking (default: 65536)
- `MAX_CONCURRENT_JOBS` — worker pool size (default: 4)
- `RATE_LIMIT_PER_MINUTE` — submissions/minute for `POST /v1/reviews` (default: 30)
- `RATE_LIMIT_BURST` — extra burst capacity applied to token-bucket (default: 10)
- `RATE_LIMIT_BACKEND` — limiter backend (default: `memory`)
- `LLM_API_KEY` — server-side API key for LLM provider (optional)
- `LLM_API_URL` — HTTP endpoint for LLM provider (optional)
- `LLM_MODEL` — model identifier passed to the LLM provider (optional)
- `LLM_TIMEOUT_SECONDS` — request timeout for LLM calls (default: 15)

Security note

- LLM credentials (`LLM_API_KEY`, etc.) are server-side environment variables and must never be accepted from clients. Clients only send the bearer token in `Authorization: Bearer <token>` and review `options` in the request body.

Authentication

- All `/v1/*` routes require the header `Authorization: Bearer <token>`. The token must match `AUTH_TOKEN` configured on the server. Missing or incorrect tokens return a `401` error envelope.

API endpoints (summary)

- `GET /health` — public; returns `{status, version, uptimeSeconds}`
- `GET /spec` — public; returns machine-readable spec including `providers` and limits (reads runtime config)
- `POST /v1/reviews` — authenticated; request: `{"diff": "<unified diff>", "options": {"provider": "mock"|"llm", "maxFindings": <int>}}`; returns `202` with `{jobId, status: queued, cacheHit}` or `429` when rate limited
- `GET /v1/reviews/{jobId}` — authenticated; job status and findings when done
- `GET /v1/reviews/{jobId}/stream` — authenticated; SSE stream of job events (status, finding, done)

Providers

- `mock` — deterministic rule engine that inspects added lines only and emits findings per the spec.
- `llm` — sends added lines to a configured HTTP LLM endpoint. LLM provider validates JSON response and maps items into `Finding` objects. The LLM path requires `LLM_API_KEY`, `LLM_API_URL`, and `LLM_MODEL` configured on the server.

Rate limiting details (Milestone 10)

- Applied only to `POST /v1/reviews`, keyed by bearer token.
- Configured by `RATE_LIMIT_PER_MINUTE` (default 30) and `RATE_LIMIT_BURST` (default 10).
- When exceeded: returns HTTP `429` with error envelope `{ "error": { "code": "rate_limited", "message": "rate limit exceeded" } }` and a `Retry-After: <seconds>` response header.
- The implementation uses a thread-safe in-memory token-bucket; it is suitable for single-process evaluation. Multi-instance deployments require a centralized backend (e.g., Redis) — see notes below.

SSE streaming and replay

- All job events are persisted in an in-memory event repository with sequence numbers.
- `GET /v1/reviews/{jobId}/stream` replays the persisted event history and then streams new events in order. Multiple clients can subscribe and receive identical sequences.

Job lifecycle

- `queued` → `running` → (`done` | `failed`).
- Jobs are processed by the worker pool; findings are deduplicated by `id`, sorted by `path`, `line`, `ruleId`, then truncated by `maxFindings`.

Known limitations

- The current implementation uses in-memory repositories and an in-memory rate limiter; these are suitable for single-process evaluation but are not distributed. For production or multi-instance deployments, run a central store (Redis) for rate limiting and durable persistence.

Test status

- Full test suite: `79 passed, 0 failed, 5 warnings` (local run).

"# Xsolla" 
