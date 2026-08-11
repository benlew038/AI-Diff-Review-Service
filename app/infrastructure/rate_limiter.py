from __future__ import annotations

import threading
import time
from math import ceil
from typing import Dict

from app.infrastructure.config import get_settings


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"rate limit exceeded; retry after {retry_after_seconds} seconds")
        self.retry_after = retry_after_seconds


class _Bucket:
    def __init__(self, capacity: float, refill_rate_per_second: float) -> None:
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate_per_second
        self.last_ts = time.monotonic()

    def consume(self, amount: float = 1.0) -> int:
        now = time.monotonic()
        elapsed = now - self.last_ts
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_ts = now

        if self.tokens >= amount:
            self.tokens -= amount
            return 0

        needed = amount - self.tokens
        # seconds until enough tokens
        retry_after = ceil(needed / self.refill_rate) if self.refill_rate > 0 else 1
        return retry_after


class InMemoryTokenBucketRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: Dict[str, _Bucket] = {}
        self._init_from_settings()

    def _init_from_settings(self) -> None:
        settings = get_settings()
        per_minute = settings.rate_limit_per_minute
        burst = settings.rate_limit_burst
        self.refill_per_second = per_minute / 60.0
        self.capacity = float(per_minute + burst)

    def consume(self, key: str) -> None:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(capacity=self.capacity, refill_rate_per_second=self.refill_per_second)
                self._buckets[key] = bucket
        retry = bucket.consume(1.0)
        if retry > 0:
            raise RateLimitExceeded(retry)

    def reset(self) -> None:
        with self._lock:
            self._buckets = {}
        # reload settings in case tests monkeypatch get_settings
        self._init_from_settings()

    def reload_settings(self) -> None:
        """Reload rate-limiter configuration from current settings."""
        with self._lock:
            self._init_from_settings()


default_rate_limiter = InMemoryTokenBucketRateLimiter()
