from __future__ import annotations

from typing import Protocol

from app.domain.diff_parser import AddedLine
from app.domain.models import Finding


class Provider(Protocol):
    def analyze(self, added_lines: list[AddedLine]) -> list[Finding]:
        ...
