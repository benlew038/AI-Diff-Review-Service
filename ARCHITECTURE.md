# Architecture Blueprint v2 for the AI Diff Review Service

## 1. Purpose

This document is the reviewed and refined version of the system design for the service described in [CANDIDATE-TASK.md](CANDIDATE-TASK.md). It preserves the original architecture direction but tightens the design around contract compliance, operational safety, and implementation realism.

---

## 2. Architecture review summary

The first-pass design was directionally correct, but several areas needed tightening to avoid implementation drift, hidden coupling, and contract failures during scoring.

### Review findings and accepted improvements

| Area | Issue identified | Why it matters | Consequence if unaddressed | Smallest improvement |
|---|---|---|---|---|
| Contract compliance | The design did not explicitly tie each component to the published contract. | The service is contract-driven; missing explicit mapping creates accidental drift. | Wrong status codes, wrong payload shapes, and failed scoring. | Add a contract compliance checklist and validate each response shape at the API boundary. |
| Missing edge cases | The design did not enumerate malformed diff shapes, empty added-line cases, and provider-selection edge cases. | The task is intentionally strict and includes subtle invalid-input cases. | Unexpected 500s or incorrect 422 handling. | Add explicit validation rules for empty diffs, whitespace-only diffs, no-added-line diffs, and unsupported provider values. |
| Hidden assumptions | The design assumed a simple diff parser and provider interface without defining boundary conditions. | Diff parsing is the most failure-prone part of the system. | Bad line numbers, incorrect chunking, and lost findings. | Define parser assumptions explicitly and keep line-number semantics centralized. |
| Data model completeness | The design did not include request fingerprints, event sequence numbers, and durable idempotency/cache records. | These are essential for correctness and replay. | Duplicate jobs, inconsistent cache behavior, broken replay. | Add explicit persistence models for request fingerprint, event sequence, and cache/idempotency records. |
| State machine correctness | The prior design used state names but did not define atomic transition rules or invariants well enough. | Transition errors are a common source of race conditions. | Jobs can become stuck or inconsistent. | Add atomic transition rules and define terminal-state guards. |
| Race conditions | The design did not address simultaneous submissions with the same idempotency key. | This is a real production issue and a likely hidden test case. | Duplicate work or conflicting job identities. | Use a create-or-return pattern with transaction-safe reservation. |
| Concurrency | The design mentioned worker concurrency but did not formalize queueing semantics or backpressure. | The contract requires four concurrent workers and a fifth job that should not fail. | Queue starvation or worker overload. | Define bounded queue depth and a worker pool that preserves queue order and avoid unbounded fan-out. |
| Cache consistency | The design did not define the exact cache key or whether cache results depend on provider, options, or job metadata. | Cache correctness is subtle and must be deterministic. | Cached results may be reused incorrectly. | Make the cache key canonical and include provider plus effective options. |
| Idempotency correctness | The design did not specify behavior for repeated submissions after a failed job or for requests with no idempotency key. | This matters for both correctness and interview defensibility. | Duplicate work or an inconsistent client experience. | Define idempotency as “same key + same canonical body => same job,” regardless of terminal state, while keeping cache separate. |
| SSE replay correctness | The design mentioned replay but not sequencing, persistence semantics, or reconnect behavior. | Replay is explicitly tested and easy to implement incorrectly. | Clients see inconsistent streams or missing events. | Persist event history with sequence numbers and replay from the beginning of the job event log. |
| Chunking edge cases | The design mentioned file-boundary chunking but not exact size semantics or zero-length edge cases. | Chunking bugs are among the highest-risk areas. | Findings may be duplicated or dropped. | Define chunking rules precisely around exact boundary sizes and empty chunks. |
| Failure recovery | The design did not define what happens after a crash during processing. | A worker crash can leave jobs stuck in running. | Jobs hang indefinitely and fail scoring. | Add recovery logic that re-queues in-progress jobs after restart. |
| Repository boundaries | The design had repositories conceptually, but not enough separation across job data, events, idempotency, and cache. | Hidden coupling can emerge quickly. | Hard-to-test and hard-to-maintain persistence layer. | Split repositories by concern and keep them behind narrow interfaces. |
| Service boundaries | The design did not fully isolate submission, worker orchestration, and streaming concerns. | Cross-service coupling creates brittle code. | Refactors become difficult later. | Define explicit service interfaces for submission, processing, and stream replay. |
| Provider abstraction quality | The provider interface was under-specified and could easily leak domain concerns. | A weak abstraction causes the mock and LLM paths to drift. | The llm path becomes inconsistent and hard to test. | Define a provider contract that returns normalized findings and usage but does not know about HTTP, jobs, or storage. |
| Event persistence | The design mentioned event history but not atomicity or deduplication of event writes. | Stream replay requires fidelity. | Replayed events may be incomplete or out of order. | Use append-only event writes with sequence numbers and atomic commit semantics. |
| Error taxonomy | The design did not define how provider failures map to the published error envelope or how unsupported provider values should be treated. | The contract is strict about error codes. | A subtle mismatch can fail scoring even if the core logic works. | Define error mapping at the API layer and keep domain errors normalized before the API responds. |
| Testing completeness | The design listed milestone tests but did not define the acceptance test matrix for the scoring contract. | The scoring checklist is broad and important. | Implementation may pass happy-path checks but fail hidden contract tests. | Add a test matrix that directly mirrors the scoring surface. |
| Operational concerns | The design mentioned logging and metrics but not configuration discipline, secrets handling, or startup readiness checks. | Production-grade design must be observable and safe. | Hard-to-debug deployments and fragile local setup. | Introduce structured logging, metrics, config validation, and a startup health gate. |

---

## 3. Architectural principles retained from v1

The overall architecture remains:

1. Separate ingress, orchestration, domain logic, and persistence.
2. Use an asynchronous job-based review pipeline.
3. Keep the review engine provider-agnostic.
4. Persist enough state for replay and recovery.
5. Keep idempotency and caching explicit and distinct.
6. Prefer deterministic behavior over cleverness.

---

## 4. Architecture Decision Records (ADR) v2

### ADR-001: Use an asynchronous job-based architecture
Status: Accepted

Decision: The service will accept review requests over HTTP and process them asynchronously through jobs.

Rationale: The contract requires state transitions, SSE streaming, and latency-sensitive processing. An async model is the clearest fit.

### ADR-002: Keep HTTP concerns out of the core domain engine
Status: Accepted

Decision: HTTP handlers will perform validation and translation only. The review engine will operate on domain objects and not depend on FastAPI, request objects, or response formatting.

Rationale: This preserves a clean boundary and makes the engine easier to test.

### ADR-003: Use a provider abstraction with normalized output
Status: Accepted

Decision: Providers will implement a common contract that accepts a normalized review request and returns normalized findings plus usage metadata.

Rationale: The mock provider and LLM provider must share the same pipeline semantics, event behavior, and persistence rules.

### ADR-004: Persist job state, findings, and SSE events durably
Status: Accepted

Decision: The service will store job state, findings, and event history durably so that replay, lookup, and recovery work after restarts.

Rationale: Replay correctness and recovery are explicit contract requirements.

### ADR-005: Treat chunking as a first-class domain module
Status: Accepted

Decision: Diff parsing and chunk construction will be implemented in a dedicated module that owns boundary rules and line-number semantics.

Rationale: Chunking correctness is a major risk area and should not be hidden inside providers.

### ADR-006: Separate idempotency and caching explicitly
Status: Accepted

Decision: Idempotency will protect against duplicate submissions using the same key and body, while caching will protect against recomputing identical review work for a canonical request fingerprint.

Rationale: These are related but not interchangeable concerns.

### ADR-007: Use a bounded worker pool and a queue with backpressure
Status: Accepted

Decision: The worker pool will be capped at the required concurrency target and will use a bounded queue so that a fifth request is queued rather than failed.

Rationale: This matches the contract and prevents runaway memory growth under load.

### ADR-008: Recover in-progress jobs after crashes
Status: Accepted

Decision: Jobs that are in queued or running state when the process stops will be re-queued or re-evaluated on restart.

Rationale: The service must not leave jobs stuck in a non-terminal state after an unexpected failure.

### ADR-009: Normalize all domain errors before API response construction
Status: Accepted

Decision: Domain and infrastructure failures will be converted into normalized application errors before the API layer formats the public response envelope.

Rationale: This prevents leaking internal failures and keeps the error contract consistent.

---

## 5. Recommended implementation stack

The reference stack remains:

- Runtime: Python 3.11+
- Web framework: FastAPI
- Async runtime: asyncio
- Worker model: bounded async worker pool with a durable queue abstraction
- Persistence: PostgreSQL for durable state and event logs
- Cache/queue acceleration: Redis
- Deployment: single service with worker processes behind a reverse proxy or tunnel

This stack remains appropriate because it supports async processing, durable job state, and a clean service boundary without over-engineering the solution.

---

## 6. Contract compliance model

The implementation should explicitly map the system to the published contract.

### Public routes

- GET /health returns status, version, and uptimeSeconds.
- GET /spec returns a machine-readable payload with the declared limits.
- All /v1 routes require bearer auth.

### Request validation

- POST /v1/reviews must reject oversized payloads with 413.
- Invalid JSON must return 400.
- Missing, empty, or non-unified diffs must return 422.
- Unknown body fields must be ignored rather than rejected.

### Response and envelope rules

- Successful submission returns 202 with jobId and queued status.
- Job status retrieval returns the required schema.
- SSE responses use text/event-stream and emit status, finding, and done events in order.
- Non-2xx responses use the required error envelope.

### Behavioral invariants

- The declared spec limits must match actual behavior.
- Jobs up to 64 KiB must reach done within 30 seconds.
- GET requests are not rate limited.
- POST requests are rate limited.
- A fifth concurrent job must not fail.

---

## 7. High-level architecture v2

The service remains a layered system with five major concerns:

1. Ingress layer
   - request parsing
   - auth enforcement
   - validation
   - error envelope mapping

2. Application services
   - submission orchestration
   - idempotency handling
   - review orchestration
   - cache resolution
   - event publication

3. Domain engine
   - diff parsing
   - chunk generation
   - provider execution
   - finding normalization
   - ordering and deduplication

4. Persistence layer
   - job repository
   - finding repository
   - event repository
   - idempotency repository
   - cache repository

5. Worker layer
   - consumes queued jobs
   - updates job state
   - persists results
   - emits events

### Service boundaries

- API service handles transport concerns only.
- Submission service creates and resolves jobs.
- Review service orchestrates the processing pipeline.
- Worker service executes jobs independently of the API process.
- Stream service replays and publishes event history.

These boundaries are important because they avoid combining HTTP, worker, and domain logic in one module.

---

## 8. Complete request lifecycle v2

### Submission flow

1. The client sends POST /v1/reviews with a bearer token.
2. The API layer validates size, JSON, and authentication.
3. The submission service canonicalizes the body into a request fingerprint.
4. The submission service checks the idempotency record:
   - same key + same canonical body -> return the existing job
   - same key + different canonical body -> return 409
5. The submission service checks the content cache:
   - cache hit -> reuse the existing result and return cacheHit=true
   - cache miss -> create a new job
6. A new job enters queued state and is persisted.
7. The worker pool receives the job and begins processing.

### Processing flow

1. The worker moves the job to running and emits a status event.
2. The review pipeline parses the diff into a normalized structure.
3. The diff is chunked only on file boundaries.
4. Each chunk is passed to the selected provider.
5. Provider output is normalized into findings and usage metrics.
6. Findings are merged, sorted, deduplicated, and truncated.
7. The job is persisted as done or failed.
8. Stream events are emitted for every state change and finding discovery.

### Observation flow

1. A client can poll the job status endpoint.
2. A client can open a stream endpoint to receive live events.
3. If the job is already done, the stream replays the full event history from the beginning.
4. The stream closes after the done event.

---

## 9. Processing pipeline v2

The processing pipeline is now explicitly defined as:

1. Normalize request payload
2. Validate shape and parse the diff
3. Resolve or create a job
4. Persist job metadata and queue it
5. Worker marks the job running and emits a status event
6. Parse diff into file-aware diff units
7. Chunk the diff only on file boundaries
8. Invoke the selected provider per chunk
9. Normalize provider output
10. Merge findings and compute usage
11. Sort, deduplicate, and truncate findings
12. Persist final result and emit a done event
13. On provider or processing failure, persist a failed state and emit an error event

### Pipeline invariants

- Findings must always be returned in canonical order.
- Deduplication must happen after aggregation and before truncation.
- Chunking must never change the final finding set.
- Jobs must not remain in running state after a crash unless recovery is in progress.
- Event sequence numbers must strictly increase.

---

## 10. Internal package and module structure v2

The module layout remains layered, but the interfaces are now more explicit.

### Suggested structure

- api/
  - routes/
  - middleware/
  - serializers/
  - error_handlers/

- application/
  - services/
  - use_cases/
  - orchestration/

- domain/
  - models/
  - value_objects/
  - rules/
  - events/
  - services/

- infrastructure/
  - persistence/
    - job_repository.py
    - finding_repository.py
    - event_repository.py
    - idempotency_repository.py
    - cache_repository.py
  - queue/
  - workers/
  - providers/
  - streaming/

- workers/
  - worker_pool.py
  - job_worker.py

- shared/
  - config/
  - errors/
  - logging/
  - metrics/
  - time/
  - utils/

### Dependency rules

- api depends on application.
- application depends on domain and infrastructure interfaces.
- domain does not depend on API, storage, or framework code.
- infrastructure depends on domain contracts.
- workers depend on application and infrastructure.

This boundary keeps the business logic testable and reduces coupling to the transport layer.

---

## 11. Core domain models v2

### ReviewRequest
Fields:
- diff
- provider
- maxFindings
- idempotencyKey
- canonicalFingerprint
- createdAt

Responsibilities:
- canonicalize the request for caching and idempotency
- validate request shape
- normalize provider selection

### Job
Fields:
- jobId
- status
- provider
- requestFingerprint
- createdAt
- updatedAt
- startedAt
- completedAt
- errorMessage
- usage
- findings
- version

Responsibilities:
- represent lifecycle state
- preserve processing progress and final outcome
- ensure only one terminal transition is applied

### Finding
Fields:
- id
- ruleId
- path
- line
- severity
- category
- title
- evidence

Responsibilities:
- represent normalized findings
- participate in ordering and deduplication

### Chunk
Fields:
- chunkIndex
- filePath
- startOffset
- endOffset
- content
- addedLines
- lineOffset

Responsibilities:
- preserve boundary semantics
- keep track of line-number context for added lines

### ReviewEvent
Fields:
- jobId
- sequenceNumber
- eventType
- payload
- createdAt

Responsibilities:
- preserve stream order and replayability

### IdempotencyRecord
Fields:
- idempotencyKey
- canonicalBodyFingerprint
- jobId
- status
- createdAt

Responsibilities:
- ensure same-key same-body submissions resolve to the same job
- cause a conflict when the body changes

### CacheEntry
Fields:
- requestFingerprint
- provider
- maxFindings
- resultSnapshot
- usage
- createdAt

Responsibilities:
- reuse completed results for identical requests

### Relationships

- One Job has many Findings.
- One Job has many ReviewEvents.
- One Job has many Chunks.
- One IdempotencyRecord points to one Job.
- One CacheEntry may be reused by many identical requests.

---

## 12. State machine and invariants v2

### Job state machine

States:
- queued
- running
- done
- failed

Transitions:
- queued -> running
- queued -> failed
- running -> done
- running -> failed

Invariants:
- A job must have exactly one terminal state.
- A job can transition from queued to running at most once.
- A terminal state must be persisted atomically.
- Findings and usage may only be persisted once the job reaches a terminal state.

### Idempotency state machine

States:
- pending
- reserved
- completed
- conflicted

Transitions:
- pending -> reserved
- reserved -> completed
- reserved -> conflicted

Invariants:
- The same idempotency key must never point to two different jobs.
- A key reused with a different canonical body must produce conflict.
- A completed or failed job must remain addressable by the original idempotency record.

### Event stream invariants

- Sequence numbers increase monotonically.
- Events are appended atomically.
- Replay must start from the earliest persisted event for the job.
- A done event must be emitted exactly once.

---

## 13. Cross-cutting concerns v2

### Authentication

- All /v1 routes require bearer auth.
- Missing or invalid tokens return 401 with the standard envelope.
- Public routes remain /health and /spec.

### Caching

- The cache key is the canonical request fingerprint plus effective provider and maxFindings.
- Cache hits should not re-run work and should return cacheHit=true.
- The cached result should be immutable once stored for that fingerprint.

### Idempotency

- Idempotency uses the client-supplied key plus the canonical request fingerprint.
- The same key and same fingerprint return the same jobId.
- The same key and different fingerprint return 409.
- The original job remains authoritative even if it ends in failed state.

### Chunking

- Chunks are created only on file boundaries.
- A file larger than 64 KiB may itself remain a single chunk.
- Chunk boundaries are determined before provider execution.
- Chunking must preserve the exact final finding set relative to an unchunked run.

### SSE replay

- Events must be persisted before they are emitted to avoid partial replay.
- Replay should read events from the beginning of the job event log.
- The stream should be deterministic and should not depend on when the client connects.

### Ordering and deduplication

- Findings are sorted by path, line, ruleId.
- Deduplication occurs by finding id.
- maxFindings truncation is applied after sorting and deduplication.

### Concurrency

- The worker pool size is fixed to four workers.
- A fifth job is queued rather than failed.
- A bounded queue prevents unbounded memory growth.
- Provider execution should be isolated from event emission to avoid partial state corruption.

### Error handling

- Validation errors return the appropriate 4xx with the standard envelope.
- Provider failures become failed jobs with a clear message.
- Unexpected internal failures are converted to the standard internal error envelope at the API boundary.
- Worker crashes should be recoverable through job re-queueing on startup.

---

## 14. Testing strategy v2

### Contract test matrix

The test suite should directly mirror the scoring contract:

- auth on all /v1 routes
- health and spec payload correctness
- invalid JSON and invalid diff handling
- payload size enforcement
- idempotency and cache behavior
- SSE replay semantics
- chunking correctness
- provider rule correctness
- rate limiting behavior
- concurrency behavior
- llm failure behavior

### Milestone-level testing plan

1. Milestone 1: smoke tests for health/spec and app startup
2. Milestone 2: validation and auth tests
3. Milestone 3: repository and state transition tests
4. Milestone 4: idempotency and caching integration tests
5. Milestone 5: concurrency and worker tests
6. Milestone 6: parser and chunking regression tests
7. Milestone 7: deterministic mock-provider fixture tests
8. Milestone 8: SSE event history and replay tests
9. Milestone 9: llm provider failure and graceful degradation tests
10. Milestone 10: burst rate limiting and full lifecycle tests

### Additional recommended tests

- property tests for diff parsing edge cases
- regression tests for ordering and deduplication across chunk boundaries
- restart-recovery tests to ensure queued/running jobs re-enter the queue safely

---

## 15. Operational concerns v2

### Configuration

- Use environment-based configuration for provider credentials and runtime toggles.
- Fail fast at startup if required configuration is missing.
- Keep the spec limits in a single source of truth so the API and implementation cannot drift.

### Logging

- Use structured logs with jobId, provider, status, and error code.
- Log state transitions and processing failures without exposing secrets.

### Metrics

- Track request counts, queue depth, worker utilization, processing latency, cache hit rate, idempotency conflicts, SSE replay counts, and provider failures.

### Observability

- Add startup health checks and a readiness signal.
- Ensure that logs and metrics are sufficient to debug a failed job without reading the database manually.

---

## 16. Risks, trade-offs, and future extensibility

### Main risks

- Chunking correctness remains the highest-risk functional area.
- SSE replay can fail silently if event order is not preserved.
- Idempotency and caching can conflict if their semantics are not separated.
- Worker crashes can leave jobs stuck if recovery is not implemented.

### Trade-offs

- Durability adds complexity but is necessary for correctness.
- A layered design is slightly heavier than a simple script, but it is far easier to defend and evolve.
- A bounded queue is simpler and safer than an unbounded one under burst conditions.

### Extensibility

The design can evolve to support:
- additional providers
- richer finding schemas
- webhooks and external notifications
- multi-tenant authorization
- more advanced observability and tracing

The provider abstraction and explicit service boundaries are the main enablers of this extensibility.

---

## 17. Final implementation blueprint

The implementation should proceed in the same milestone order as before, but each milestone should now be guided by the stricter invariants in this document:

1. Build the public API contract.
2. Add validation and authentication.
3. Introduce durable job state.
4. Add submission orchestration, idempotency, and cache handling.
5. Implement bounded workers and concurrency.
6. Build the diff parser and chunking module.
7. Implement the deterministic mock provider and result normalization.
8. Add SSE event persistence and replay.
9. Add the LLM provider abstraction and graceful failure handling.
10. Harden rate limiting, recovery, metrics, and deployment readiness.

This v2 design remains faithful to the original architecture while making the implementation materially safer, more testable, and more likely to satisfy the scoring contract without hidden surprises.
