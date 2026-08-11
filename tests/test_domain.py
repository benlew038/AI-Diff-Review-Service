from app.domain.models import Finding, Job, JobStatus, Usage


def test_job_state_transitions() -> None:
    job = Job.create(provider="mock", max_findings=5, request_fingerprint="abc", diff="diff")
    assert job.status is JobStatus.QUEUED

    job.mark_running()
    assert job.status is JobStatus.RUNNING

    job.mark_done(findings=[Finding(id="x", rule_id="R1", path="a.py", line=1, severity="low", category="style", title="t", evidence="e")], usage=Usage(input_bytes=3, chunks=1, cache_hit=False))
    assert job.status is JobStatus.DONE


def test_job_failure_transition() -> None:
    job = Job.create(provider="mock", max_findings=1, request_fingerprint="abc", diff="diff")
    job.mark_running()
    job.mark_failed("boom")
    assert job.status is JobStatus.FAILED
    assert job.error_message == "boom"
