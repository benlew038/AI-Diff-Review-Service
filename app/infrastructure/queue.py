from __future__ import annotations

import asyncio
from typing import Generic, TypeVar

T = TypeVar("T")


class InMemoryQueue(Generic[T]):
    def __init__(self, maxsize: int = 100) -> None:
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=maxsize)

    async def enqueue(self, item: T) -> None:
        await self._queue.put(item)

    async def dequeue(self) -> T | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None

    def qsize(self) -> int:
        return self._queue.qsize()
