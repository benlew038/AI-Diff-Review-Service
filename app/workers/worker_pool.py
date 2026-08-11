from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.application.services.review_service import ReviewWorker, ReviewService, default_review_service
from app.infrastructure.config import get_settings
from app.infrastructure.queue import InMemoryQueue

logger = logging.getLogger(__name__)


class WorkerPool:
    def __init__(self, *, service: ReviewService, worker_count: int = 4, queue_size: int = 100) -> None:
        self.service = service
        self.worker_count = worker_count
        self.queue = InMemoryQueue[str](maxsize=queue_size)
        self._tasks: list[asyncio.Task[Any]] = []
        self._stopped = False

    async def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [asyncio.create_task(self._run_worker(i)) for i in range(self.worker_count)]

    async def stop(self) -> None:
        self._stopped = True
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def enqueue_job(self, job_id: str) -> None:
        await self.queue.enqueue(job_id)

    async def _run_worker(self, worker_index: int) -> None:
        worker = ReviewWorker(self.service)
        while not self._stopped:
            job_id = await self.queue.dequeue()
            if job_id is None:
                await asyncio.sleep(0.01)
                continue
            logger.info("worker %s processing job %s", worker_index, job_id)
            worker.process_job(job_id)


default_worker_pool = WorkerPool(
    service=default_review_service,
    worker_count=get_settings().max_concurrent_jobs,
)
