from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(slots=True)
class Usage:
    input_bytes: int
    chunks: int
    cache_hit: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {"inputBytes": self.input_bytes, "chunks": self.chunks, "cacheHit": self.cache_hit}


@dataclass(slots=True)
class Finding:
    id: str
    rule_id: str
    path: str
    line: int
    severity: str
    category: str
    title: str
    evidence: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ruleId": self.rule_id,
            "path": self.path,
            "line": self.line,
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class ReviewEvent:
    job_id: str
    sequence: int
    type: str
    payload: dict[str, Any]
    timestamp: str


@dataclass(slots=True)
class Job:
    job_id: str
    status: JobStatus
    provider: str
    max_findings: int
    request_fingerprint: str
    diff: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    usage: Usage | None = None
    findings: list[Finding] = field(default_factory=list)
    version: int = 1

    @classmethod
    def create(cls, *, provider: str, max_findings: int, request_fingerprint: str, diff: str) -> "Job":
        now = cls._timestamp()
        return cls(
            job_id=str(uuid4()),
            status=JobStatus.QUEUED,
            provider=provider,
            max_findings=max_findings,
            request_fingerprint=request_fingerprint,
            diff=diff,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _timestamp() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def mark_running(self) -> None:
        if self.status not in {JobStatus.QUEUED}:
            return
        self.status = JobStatus.RUNNING
        self.started_at = self._timestamp()
        self.updated_at = self._timestamp()

    def mark_done(self, *, findings: list[Finding], usage: Usage) -> None:
        if self.status is not JobStatus.RUNNING:
            return
        self.status = JobStatus.DONE
        self.findings = findings
        self.usage = usage
        self.completed_at = self._timestamp()
        self.updated_at = self._timestamp()

    def mark_failed(self, error_message: str) -> None:
        if self.status is not JobStatus.RUNNING:
            return
        self.status = JobStatus.FAILED
        self.error_message = error_message
        self.completed_at = self._timestamp()
        self.updated_at = self._timestamp()

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jobId": self.job_id,
            "status": self.status.value,
            "usage": self.usage.to_public_dict() if self.usage is not None else {"inputBytes": 0, "chunks": 0, "cacheHit": False},
        }
        if self.findings:
            payload["findings"] = [finding.to_public_dict() for finding in self.findings]
        return payload
