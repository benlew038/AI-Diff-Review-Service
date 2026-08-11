from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.domain.models import Job, ReviewEvent


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def save(self, job: Job) -> None:
        self._jobs[job.job_id] = job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)


class InMemoryIdempotencyRepository:
    def __init__(self) -> None:
        self._records: dict[str, tuple[str, str]] = {}

    def save(self, idempotency_key: str, body_fingerprint: str, job_id: str) -> None:
        self._records[idempotency_key] = (body_fingerprint, job_id)

    def get_record(self, idempotency_key: str) -> tuple[str, str] | None:
        return self._records.get(idempotency_key)

    def get_job(self, idempotency_key: str) -> str | None:
        record = self._records.get(idempotency_key)
        if record is None:
            return None
        return record[1]

    def exists_with_different_body(self, idempotency_key: str, body_fingerprint: str) -> bool:
        record = self._records.get(idempotency_key)
        if record is None:
            return False
        return record[0] != body_fingerprint


class InMemoryCacheRepository:
    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}

    def save(self, canonical_fingerprint: str, job_id: str) -> None:
        self._entries[canonical_fingerprint] = {"jobId": job_id}

    def get(self, canonical_fingerprint: str) -> dict[str, Any] | None:
        return self._entries.get(canonical_fingerprint)


class InMemoryEventRepository:
    def __init__(self) -> None:
        self._events: dict[str, list[ReviewEvent]] = {}
        self._lock = Lock()

    def append(self, *, job_id: str, event_type: str, payload: dict[str, Any]) -> ReviewEvent:
        with self._lock:
            events = self._events.setdefault(job_id, [])
            event = ReviewEvent(
                job_id=job_id,
                sequence=len(events) + 1,
                type=event_type,
                payload=payload,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            events.append(event)
            return event

    def list_for_job(self, job_id: str) -> list[ReviewEvent]:
        with self._lock:
            return list(self._events.get(job_id, []))
