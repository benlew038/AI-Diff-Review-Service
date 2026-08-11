from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from app.domain.diff_parser import InvalidUnifiedDiff, chunk_diff, extract_added_lines, parse_unified_diff
from app.domain.models import Finding, Job, JobStatus, ReviewEvent, Usage
from app.application.providers import get_provider
from app.infrastructure.config import get_settings
from app.infrastructure.repositories import InMemoryCacheRepository, InMemoryEventRepository, InMemoryIdempotencyRepository, InMemoryJobRepository
from app.infrastructure.streaming import InMemoryEventBroadcaster
from app.shared.errors import ApiError, ErrorCode


@dataclass(slots=True)
class ReviewService:
    job_repository: InMemoryJobRepository = field(default_factory=InMemoryJobRepository)
    idempotency_repository: InMemoryIdempotencyRepository = field(default_factory=InMemoryIdempotencyRepository)
    cache_repository: InMemoryCacheRepository = field(default_factory=InMemoryCacheRepository)
    event_repository: InMemoryEventRepository = field(default_factory=InMemoryEventRepository)
    event_broadcaster: InMemoryEventBroadcaster = field(default_factory=InMemoryEventBroadcaster)

    def submit_review(
        self,
        *,
        diff: str,
        provider: str,
        max_findings: int,
        idempotency_key: str | None,
        idempotency_body_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        canonical_fingerprint = self._canonical_request_fingerprint(diff=diff, provider=provider, max_findings=max_findings)
        idempotency_fingerprint = idempotency_body_fingerprint or canonical_fingerprint

        if idempotency_key:
            record = self.idempotency_repository.get_record(idempotency_key)
            if record is not None:
                previous_fingerprint, previous_job_id = record
                if previous_fingerprint == idempotency_fingerprint:
                    existing = self.job_repository.get(previous_job_id)
                    if existing is not None:
                        return {"jobId": existing.job_id, "cacheHit": False, "newJob": False}
                raise ApiError(ErrorCode.IDEMPOTENCY_CONFLICT, "idempotency key reused with a different body")

        cached = self.cache_repository.get(canonical_fingerprint)
        if cached is not None:
            # Mark the referenced job as a cache hit so GET results consistently report cacheHit
            existing_job = self.job_repository.get(cached["jobId"]) if cached.get("jobId") else None
            if existing_job is not None:
                if existing_job.usage is not None:
                    existing_job.usage.cache_hit = True
                else:
                    # Create minimal usage record indicating cache hit
                    existing_job.usage = Usage(input_bytes=len(diff.encode("utf-8")), chunks=0, cache_hit=True)
                self.job_repository.save(existing_job)
            if idempotency_key:
                self.idempotency_repository.save(idempotency_key, idempotency_fingerprint, cached["jobId"])
            return {"jobId": cached["jobId"], "cacheHit": True, "newJob": False}

        job = Job.create(provider=provider, max_findings=max_findings, request_fingerprint=canonical_fingerprint, diff=diff)
        self.job_repository.save(job)
        self.append_event(job.job_id, "status", {"jobId": job.job_id, "status": JobStatus.QUEUED.value})
        if idempotency_key:
            self.idempotency_repository.save(idempotency_key, idempotency_fingerprint, job.job_id)
        return {"jobId": job.job_id, "cacheHit": False, "newJob": True}

    def get_job(self, job_id: str) -> Job | None:
        return self.job_repository.get(job_id)

    def append_event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> ReviewEvent:
        event = self.event_repository.append(job_id=job_id, event_type=event_type, payload=payload)
        self.event_broadcaster.publish(event)
        return event

    def list_events(self, job_id: str) -> list[ReviewEvent]:
        return self.event_repository.list_for_job(job_id)

    def reset(self) -> None:
        self.job_repository = InMemoryJobRepository()
        self.idempotency_repository = InMemoryIdempotencyRepository()
        self.cache_repository = InMemoryCacheRepository()
        self.event_repository = InMemoryEventRepository()
        self.event_broadcaster = InMemoryEventBroadcaster()

    def is_unified_diff(self, diff: str) -> bool:
        try:
            parse_unified_diff(diff)
        except InvalidUnifiedDiff:
            return False
        return True

    def _canonical_request_fingerprint(self, *, diff: str, provider: str, max_findings: int) -> str:
        payload = f"{diff}\n{provider}\n{max_findings}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


default_review_service = ReviewService()


class ReviewWorker:
    service: ReviewService

    def __init__(self, service: ReviewService) -> None:
        self.service = service

    def process_job(self, job_id: str) -> None:
        job = self.service.get_job(job_id)
        if job is None:
            return
        if job.status is JobStatus.DONE or job.status is JobStatus.FAILED:
            return
        job.mark_running()
        self.service.job_repository.save(job)
        self.service.append_event(job.job_id, "status", {"jobId": job.job_id, "status": JobStatus.RUNNING.value})
        try:
            files = parse_unified_diff(job.diff)
            chunks = chunk_diff(files, max_chunk_bytes=get_settings().chunk_bytes)
            provider = get_provider(job.provider)
            findings: list[Finding] = []
            for chunk in chunks:
                added_lines = [line for file in chunk.files for line in extract_added_lines(file)]
                findings.extend(provider.analyze(added_lines))
            unique_findings = {finding.id: finding for finding in findings}
            sorted_findings = sorted(unique_findings.values(), key=lambda finding: (finding.path, finding.line, finding.rule_id))
            truncated_findings = sorted_findings[: job.max_findings]
            job.mark_done(
                findings=truncated_findings,
                usage=Usage(input_bytes=len(job.diff.encode("utf-8")), chunks=len(chunks), cache_hit=False),
            )
            self.service.job_repository.save(job)
            for finding in truncated_findings:
                self.service.append_event(job.job_id, "finding", finding.to_public_dict())
            self.service.append_event(job.job_id, "status", {"jobId": job.job_id, "status": JobStatus.DONE.value})
            if job.usage is not None:
                self.service.append_event(
                    job.job_id,
                    "done",
                    {"total": len(truncated_findings), "usage": job.usage.to_public_dict()},
                )
            self.service.cache_repository.save(job.request_fingerprint, job.job_id)
        except Exception as exc:  # pragma: no cover - defensive fallback
            job.mark_failed(str(exc))
            self.service.job_repository.save(job)
            self.service.append_event(job.job_id, "status", {"jobId": job.job_id, "status": JobStatus.FAILED.value})
