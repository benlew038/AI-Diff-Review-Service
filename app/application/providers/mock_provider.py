from __future__ import annotations

import re
from typing import Iterable

from app.domain.diff_parser import AddedLine
from app.domain.models import Finding


CREDENTIAL_RE = re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_-]{16,}['\"]", re.IGNORECASE)
PROMPT_INJECTION_RE = re.compile(r"ignore previous instructions|disregard all prior|you are now", re.IGNORECASE)
SQL_KEYWORDS_RE = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b")
CATCH_LINE_RE = re.compile(r"\bcatch\b")
STRICT_NULL_RE = re.compile(r"(?<![=!])==\s*null|(?<![!])!=(?!=)\s*null")
JSON_DEEP_CLONE_RE = re.compile(r"JSON\.parse\(JSON\.stringify\(")
CONSOLE_LOG_RE = re.compile(r"console\.log\(")
TODO_FIXME_RE = re.compile(r"TODO|FIXME")


RULES: list[tuple[str, str, str, str, str]] = [
    ("MOCK-001", "critical", "security", "eval usage", "eval("),
    ("MOCK-002", "critical", "security", "hardcoded credential", "credential"),
    ("MOCK-003", "high", "security", "SQL string concatenation", "sql_concat"),
    ("MOCK-004", "high", "correctness", "swallowed exception", "catch_empty"),
    ("MOCK-005", "medium", "correctness", "loose null comparison", "null_comparison"),
    ("MOCK-006", "medium", "performance", "deep-clone via JSON", "deep_clone"),
    ("MOCK-007", "low", "style", "console.log left in", "console_log"),
    ("MOCK-008", "low", "style", "unresolved marker", "todo_fixme"),
    ("MOCK-INJ", "critical", "security", "prompt-injection content", "prompt_injection"),
]


class MockProvider:
    def analyze(self, added_lines: list[AddedLine]) -> list[Finding]:
        findings: list[Finding] = []
        for index, line in enumerate(added_lines):
            findings.extend(self._findings_for_line(line, added_lines, index))
        return findings

    def _findings_for_line(self, line: AddedLine, added_lines: list[AddedLine], index: int) -> list[Finding]:
        findings: list[Finding] = []
        if "eval(" in line.content:
            findings.append(self._build_finding(line, "MOCK-001", "critical", "security", "eval usage"))
        if CREDENTIAL_RE.search(line.content):
            findings.append(self._build_finding(line, "MOCK-002", "critical", "security", "hardcoded credential"))
        if self._is_sql_string_concatenation(line.content):
            findings.append(self._build_finding(line, "MOCK-003", "high", "security", "SQL string concatenation"))
        if self._is_empty_catch_line(line, added_lines, index):
            findings.append(self._build_finding(line, "MOCK-004", "high", "correctness", "swallowed exception"))
        if STRICT_NULL_RE.search(line.content):
            findings.append(self._build_finding(line, "MOCK-005", "medium", "correctness", "loose null comparison"))
        if JSON_DEEP_CLONE_RE.search(line.content):
            findings.append(self._build_finding(line, "MOCK-006", "medium", "performance", "deep-clone via JSON"))
        if CONSOLE_LOG_RE.search(line.content):
            findings.append(self._build_finding(line, "MOCK-007", "low", "style", "console.log left in"))
        if TODO_FIXME_RE.search(line.content):
            findings.append(self._build_finding(line, "MOCK-008", "low", "style", "unresolved marker"))
        if PROMPT_INJECTION_RE.search(line.content):
            findings.append(self._build_finding(line, "MOCK-INJ", "critical", "security", "prompt-injection content"))
        return findings

    def _is_sql_string_concatenation(self, content: str) -> bool:
        if "+" not in content:
            return False
        return bool(SQL_KEYWORDS_RE.search(content))

    def _is_empty_catch_line(self, line: AddedLine, added_lines: list[AddedLine], index: int) -> bool:
        cleaned = line.content.strip()
        if not CATCH_LINE_RE.search(cleaned):
            return False
        if cleaned.endswith("{}"):
            return True
        if cleaned.endswith(") {}"):
            return True
        if cleaned.endswith("{"):
            if index + 1 >= len(added_lines):
                return False
            next_line = added_lines[index + 1]
            return (
                next_line.path == line.path
                and next_line.line == line.line + 1
                and next_line.content.strip() == "}"
            )
        return False

    def _build_finding(
        self,
        line: AddedLine,
        rule_id: str,
        severity: str,
        category: str,
        title: str,
    ) -> Finding:
        return Finding(
            id=f"{rule_id}:{line.path}:{line.line}",
            rule_id=rule_id,
            path=line.path,
            line=line.line,
            severity=severity,
            category=category,
            title=title,
            evidence=line.content,
        )
