from __future__ import annotations

import json
from typing import Any

import httpx

from app.application.providers.provider import Provider
from app.domain.diff_parser import AddedLine
from app.domain.models import Finding
from app.infrastructure.config import get_settings


class LLMProviderError(Exception):
    pass


class LLMProvider(Provider):
    def analyze(self, added_lines: list[AddedLine]) -> list[Finding]:
        settings = get_settings()
        if not settings.llm_api_key or not settings.llm_api_url:
            raise LLMProviderError("missing LLM configuration")

        prompt = self._build_prompt(added_lines)
        response_text = self._send_request(prompt, settings)
        return self._parse_response(response_text)

    def _build_prompt(self, added_lines: list[AddedLine]) -> str:
        lines = []
        for line in added_lines:
            content = json.dumps(line.content, ensure_ascii=False)
            lines.append(
                f"- path: {line.path}\n  line: {line.line}\n  content: {content}"
            )

        lines_text = "\n".join(lines)
        return (
            "You are an AI code reviewer. Analyze only the supplied added lines from a unified diff. "
            "Do not consider removed or context lines.\n\n"
            "Return only a JSON array of findings. Each item must include the following fields: "
            "id, ruleId, path, line, severity, category, title, evidence.\n\n"
            "Added lines:\n"
            f"{lines_text}\n"
        )

    def _send_request(self, prompt: str, settings: Any) -> str:
        payload = {
            "model": settings.llm_model,
            "prompt": prompt,
            "max_tokens": 1500,
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=settings.llm_timeout_seconds)

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(settings.llm_api_url, json=payload, headers=headers)
                response.raise_for_status()
                return response.text
        except httpx.TimeoutException as exc:
            raise LLMProviderError("LLM request timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError("LLM request failed") from exc

    def _parse_response(self, response_text: str) -> list[Finding]:
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise LLMProviderError("LLM response is not valid JSON") from exc

        if not isinstance(data, list):
            raise LLMProviderError("LLM response must be a JSON array")

        findings: list[Finding] = []
        for item in data:
            if not isinstance(item, dict):
                raise LLMProviderError("LLM response array items must be objects")

            required_fields = ["id", "ruleId", "path", "line", "severity", "category", "title", "evidence"]
            for field_name in required_fields:
                if field_name not in item:
                    raise LLMProviderError(f"LLM finding missing required field: {field_name}")

            if not isinstance(item["id"], str):
                raise LLMProviderError("LLM finding.id must be a string")
            if not isinstance(item["ruleId"], str):
                raise LLMProviderError("LLM finding.ruleId must be a string")
            if not isinstance(item["path"], str):
                raise LLMProviderError("LLM finding.path must be a string")
            if not isinstance(item["line"], int):
                raise LLMProviderError("LLM finding.line must be an integer")
            if not isinstance(item["severity"], str):
                raise LLMProviderError("LLM finding.severity must be a string")
            if not isinstance(item["category"], str):
                raise LLMProviderError("LLM finding.category must be a string")
            if not isinstance(item["title"], str):
                raise LLMProviderError("LLM finding.title must be a string")
            if not isinstance(item["evidence"], str):
                raise LLMProviderError("LLM finding.evidence must be a string")

            findings.append(
                Finding(
                    id=item["id"],
                    rule_id=item["ruleId"],
                    path=item["path"],
                    line=item["line"],
                    severity=item["severity"],
                    category=item["category"],
                    title=item["title"],
                    evidence=item["evidence"],
                )
            )

        return findings
