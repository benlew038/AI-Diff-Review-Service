import asyncio

from app.application.services.review_service import ReviewService, ReviewWorker
from app.domain.models import Job
from app.infrastructure.queue import InMemoryQueue


def test_queue_and_worker_process_job() -> None:
    service = ReviewService()
    job = Job.create(provider="mock", max_findings=5, request_fingerprint="abc", diff="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n")
    service.job_repository.save(job)

    queue = InMemoryQueue[str](maxsize=10)
    asyncio.run(queue.enqueue(job.job_id))
    assert queue.qsize() == 1

    worker = ReviewWorker(service)
    worker.process_job(job.job_id)

    updated = service.get_job(job.job_id)
    assert updated is not None
    assert updated.status.value == "done"
