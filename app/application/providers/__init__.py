from __future__ import annotations

from app.application.providers.llm_provider import LLMProvider
from app.application.providers.mock_provider import MockProvider
from app.application.providers.provider import Provider


def get_provider(provider_name: str) -> Provider:
    if provider_name == "mock":
        return MockProvider()
    if provider_name == "llm":
        return LLMProvider()
    raise ValueError(f"unsupported provider: {provider_name}")
