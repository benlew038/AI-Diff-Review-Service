import json
from unittest.mock import patch

import pytest

from app.application.providers.llm_provider import LLMProvider, LLMProviderError
from app.domain.diff_parser import AddedLine
from app.infrastructure.config import get_settings


class DummySettings:
    llm_api_key = "test-key"
    llm_api_url = "https://example.com/api"
    llm_model = "test-model"
    llm_timeout_seconds = 1


def test_get_provider_llm_is_available() -> None:
    from app.application.providers import get_provider

    provider = get_provider("llm")
    assert isinstance(provider, LLMProvider)


def test_llm_analyze_parses_valid_json_response(monkeypatch) -> None:
    provider = LLMProvider()
    added_lines = [AddedLine(path="app.py", line=1, content="eval(x)")]
    response = json.dumps([
        {
            "id": "LLM-001:app.py:1",
            "ruleId": "LLM-001",
            "path": "app.py",
            "line": 1,
            "severity": "high",
            "category": "security",
            "title": "eval usage",
            "evidence": "eval(x)",
        }
    ])

    monkeypatch.setattr("app.application.providers.llm_provider.get_settings", lambda: DummySettings())
    monkeypatch.setattr(LLMProvider, "_send_request", lambda self, prompt, settings: response)

    findings = provider.analyze(added_lines)
    assert len(findings) == 1
    assert findings[0].id == "LLM-001:app.py:1"
    assert findings[0].path == "app.py"
    assert findings[0].evidence == "eval(x)"


def test_llm_analyze_handles_empty_findings(monkeypatch) -> None:
    provider = LLMProvider()
    added_lines = [AddedLine(path="app.py", line=1, content="console.log('debug')")]

    monkeypatch.setattr("app.application.providers.llm_provider.get_settings", lambda: DummySettings())
    monkeypatch.setattr(LLMProvider, "_send_request", lambda self, prompt, settings: json.dumps([]))

    findings = provider.analyze(added_lines)
    assert findings == []


@pytest.mark.parametrize("response_text", ["not json", "{\"id\": 1}"])
def test_llm_invalid_json_raises(response_text, monkeypatch) -> None:
    provider = LLMProvider()
    added_lines = [AddedLine(path="app.py", line=1, content="eval(x)")]

    monkeypatch.setattr("app.application.providers.llm_provider.get_settings", lambda: DummySettings())
    monkeypatch.setattr(LLMProvider, "_send_request", lambda self, prompt, settings: response_text)

    with pytest.raises(LLMProviderError):
        provider.analyze(added_lines)


def test_llm_response_not_array_raises(monkeypatch) -> None:
    provider = LLMProvider()
    added_lines = [AddedLine(path="app.py", line=1, content="eval(x)")]

    monkeypatch.setattr("app.application.providers.llm_provider.get_settings", lambda: DummySettings())
    monkeypatch.setattr(LLMProvider, "_send_request", lambda self, prompt, settings: json.dumps({"id": "x"}))

    with pytest.raises(LLMProviderError):
        provider.analyze(added_lines)


def test_llm_missing_required_field_raises(monkeypatch) -> None:
    provider = LLMProvider()
    added_lines = [AddedLine(path="app.py", line=1, content="eval(x)")]

    monkeypatch.setattr("app.application.providers.llm_provider.get_settings", lambda: DummySettings())
    monkeypatch.setattr(
        LLMProvider,
        "_send_request",
        lambda self, prompt, settings: json.dumps([{"id": "LLM-001", "ruleId": "LLM-001"}]),
    )

    with pytest.raises(LLMProviderError):
        provider.analyze(added_lines)


def test_llm_invalid_field_type_raises(monkeypatch) -> None:
    provider = LLMProvider()
    added_lines = [AddedLine(path="app.py", line=1, content="eval(x)")]

    monkeypatch.setattr("app.application.providers.llm_provider.get_settings", lambda: DummySettings())
    monkeypatch.setattr(
        LLMProvider,
        "_send_request",
        lambda self, prompt, settings: json.dumps([
            {
                "id": "LLM-001",
                "ruleId": "LLM-001",
                "path": "app.py",
                "line": "1",
                "severity": "high",
                "category": "security",
                "title": "eval usage",
                "evidence": "eval(x)",
            }
        ]),
    )

    with pytest.raises(LLMProviderError):
        provider.analyze(added_lines)


def test_llm_missing_configuration_raises(monkeypatch) -> None:
    provider = LLMProvider()
    added_lines = [AddedLine(path="app.py", line=1, content="eval(x)")]

    settings = DummySettings()
    settings.llm_api_key = None
    monkeypatch.setattr("app.application.providers.llm_provider.get_settings", lambda: settings)

    with pytest.raises(LLMProviderError):
        provider.analyze(added_lines)


def test_llm_api_failure_raises(monkeypatch) -> None:
    provider = LLMProvider()
    added_lines = [AddedLine(path="app.py", line=1, content="eval(x)")]

    monkeypatch.setattr("app.application.providers.llm_provider.get_settings", lambda: DummySettings())
    def raise_error(self, prompt, settings):
        raise LLMProviderError("LLM request failed")
    monkeypatch.setattr(LLMProvider, "_send_request", raise_error)

    with pytest.raises(LLMProviderError):
        provider.analyze(added_lines)
