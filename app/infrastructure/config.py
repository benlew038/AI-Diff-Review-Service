from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os


@dataclass(frozen=True)
class Settings:
    app_version: str = "0.1.0"
    auth_token: str = "test-token"
    max_payload_bytes: int = 1048576
    chunk_bytes: int = 65536
    max_concurrent_jobs: int = 4
    rate_limit_per_minute: int = 30
    rate_limit_burst: int = 10
    rate_limit_backend: str = "memory"
    llm_api_key: str | None = None
    llm_api_url: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: int = 15


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_version=os.getenv("APP_VERSION", "0.1.0"),
        auth_token=os.getenv("AUTH_TOKEN", "test-token"),
        max_payload_bytes=int(os.getenv("MAX_PAYLOAD_BYTES", "1048576")),
        chunk_bytes=int(os.getenv("CHUNK_BYTES", "65536")),
        max_concurrent_jobs=int(os.getenv("MAX_CONCURRENT_JOBS", "4")),
        rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "30")),
        rate_limit_burst=int(os.getenv("RATE_LIMIT_BURST", "10")),
        rate_limit_backend=os.getenv("RATE_LIMIT_BACKEND", "memory"),
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_api_url=os.getenv("LLM_API_URL"),
        llm_model=os.getenv("LLM_MODEL"),
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "15")),
    )
