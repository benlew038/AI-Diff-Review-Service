from __future__ import annotations

import asyncio
from collections import defaultdict

from app.domain.models import ReviewEvent


class InMemoryEventBroadcaster:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[ReviewEvent]]] = defaultdict(set)

    def subscribe(self, job_id: str) -> asyncio.Queue[ReviewEvent]:
        queue: asyncio.Queue[ReviewEvent] = asyncio.Queue()
        self._subscribers[job_id].add(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue[ReviewEvent]) -> None:
        subscribers = self._subscribers.get(job_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(job_id, None)

    def publish(self, event: ReviewEvent) -> None:
        for queue in list(self._subscribers.get(event.job_id, ())):
            queue.put_nowait(event)
