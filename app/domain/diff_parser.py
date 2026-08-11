from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


DEFAULT_CHUNK_BYTES = 65536


class InvalidUnifiedDiff(ValueError):
    pass


class DiffLineKind(str, Enum):
    CONTEXT = "context"
    ADDED = "added"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class DiffLine:
    kind: DiffLineKind
    content: str
    old_line_no: int | None
    new_line_no: int | None


@dataclass(frozen=True, slots=True)
class DiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DiffFile:
    path: str
    raw_text: str
    byte_length: int
    hunks: list[DiffHunk] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AddedLine:
    path: str
    line: int
    content: str


@dataclass(frozen=True, slots=True)
class Chunk:
    index: int
    files: list[DiffFile]
    raw_bytes: bytes
    size_bytes: int


_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$")


def parse_unified_diff(diff: str) -> list[DiffFile]:
    raw_lines = diff.splitlines(keepends=True)
    if not raw_lines or not diff.strip():
        raise InvalidUnifiedDiff("diff is empty")

    files: list[DiffFile] = []
    index = 0
    while index < len(raw_lines):
        line = _strip_eol(raw_lines[index])
        if not line:
            raise InvalidUnifiedDiff("unexpected blank line outside a file diff")
        if not line.startswith("--- "):
            raise InvalidUnifiedDiff("expected old file header")

        old_path = _parse_file_header(line, "--- ")
        file_raw_lines = [raw_lines[index]]
        index += 1

        if index >= len(raw_lines):
            raise InvalidUnifiedDiff("missing new file header")
        line = _strip_eol(raw_lines[index])
        if not line.startswith("+++ "):
            raise InvalidUnifiedDiff("missing new file header")

        new_path = _parse_file_header(line, "+++ ")
        path = _normalize_diff_path(new_path if new_path != "/dev/null" else old_path)
        if path == "/dev/null":
            raise InvalidUnifiedDiff("file path cannot be /dev/null on both sides")

        file_raw_lines.append(raw_lines[index])
        index += 1

        hunks: list[DiffHunk] = []
        while index < len(raw_lines):
            line = _strip_eol(raw_lines[index])
            if line.startswith("--- "):
                break
            if not line.startswith("@@ "):
                raise InvalidUnifiedDiff("expected hunk header")

            hunk, index = _parse_hunk(raw_lines, index, file_raw_lines)
            hunks.append(hunk)

        if not hunks:
            raise InvalidUnifiedDiff("file diff must contain at least one hunk")

        raw_text = "".join(file_raw_lines)
        files.append(
            DiffFile(
                path=path,
                raw_text=raw_text,
                byte_length=len(raw_text.encode("utf-8")),
                hunks=hunks,
            )
        )

    return files


def extract_added_lines(file: DiffFile) -> list[AddedLine]:
    added_lines: list[AddedLine] = []
    for hunk in file.hunks:
        for line in hunk.lines:
            if line.kind is DiffLineKind.ADDED:
                if line.new_line_no is None:
                    raise InvalidUnifiedDiff("added line missing new line number")
                added_lines.append(AddedLine(path=file.path, line=line.new_line_no, content=line.content))
    return added_lines


def chunk_diff(files: list[DiffFile], max_chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> list[Chunk]:
    if max_chunk_bytes < 1:
        raise ValueError("max_chunk_bytes must be positive")

    chunks: list[Chunk] = []
    current_files: list[DiffFile] = []
    current_size = 0

    def flush() -> None:
        nonlocal current_files, current_size
        if not current_files:
            return
        raw_bytes = b"".join(file.raw_text.encode("utf-8") for file in current_files)
        chunks.append(Chunk(index=len(chunks), files=list(current_files), raw_bytes=raw_bytes, size_bytes=current_size))
        current_files = []
        current_size = 0

    for file in files:
        if file.byte_length > max_chunk_bytes:
            flush()
            raw_bytes = file.raw_text.encode("utf-8")
            chunks.append(Chunk(index=len(chunks), files=[file], raw_bytes=raw_bytes, size_bytes=file.byte_length))
            continue

        if current_files and current_size + file.byte_length > max_chunk_bytes:
            flush()

        current_files.append(file)
        current_size += file.byte_length

    flush()
    return chunks


def _parse_hunk(raw_lines: list[str], index: int, file_raw_lines: list[str]) -> tuple[DiffHunk, int]:
    header = _strip_eol(raw_lines[index])
    match = _HUNK_HEADER_RE.match(header)
    if match is None:
        raise InvalidUnifiedDiff("malformed hunk header")

    old_start = int(match.group(1))
    old_count = int(match.group(2) or "1")
    new_start = int(match.group(3))
    new_count = int(match.group(4) or "1")

    file_raw_lines.append(raw_lines[index])
    index += 1

    old_line_no = old_start
    new_line_no = new_start
    old_seen = 0
    new_seen = 0
    lines: list[DiffLine] = []

    while index < len(raw_lines):
        raw_line = raw_lines[index]
        line = _strip_eol(raw_line)

        if line.startswith("\\ "):
            file_raw_lines.append(raw_line)
            index += 1
            continue

        if old_seen == old_count and new_seen == new_count:
            break

        if line == "":
            raise InvalidUnifiedDiff("hunk line missing prefix")

        prefix = line[0]
        content = line[1:]

        if prefix == " ":
            lines.append(
                DiffLine(
                    kind=DiffLineKind.CONTEXT,
                    content=content,
                    old_line_no=old_line_no,
                    new_line_no=new_line_no,
                )
            )
            old_line_no += 1
            new_line_no += 1
            old_seen += 1
            new_seen += 1
        elif prefix == "+":
            lines.append(
                DiffLine(
                    kind=DiffLineKind.ADDED,
                    content=content,
                    old_line_no=None,
                    new_line_no=new_line_no,
                )
            )
            new_line_no += 1
            new_seen += 1
        elif prefix == "-":
            lines.append(
                DiffLine(
                    kind=DiffLineKind.REMOVED,
                    content=content,
                    old_line_no=old_line_no,
                    new_line_no=None,
                )
            )
            old_line_no += 1
            old_seen += 1
        else:
            raise InvalidUnifiedDiff("invalid hunk line prefix")

        if old_seen > old_count or new_seen > new_count:
            raise InvalidUnifiedDiff("hunk body exceeds declared line counts")

        file_raw_lines.append(raw_line)
        index += 1

    if old_seen != old_count or new_seen != new_count:
        raise InvalidUnifiedDiff("hunk body does not match declared line counts")

    return DiffHunk(old_start=old_start, old_count=old_count, new_start=new_start, new_count=new_count, lines=lines), index


def _parse_file_header(line: str, marker: str) -> str:
    path = line[len(marker) :].strip()
    if not path:
        raise InvalidUnifiedDiff("file header missing path")
    return path.split("\t", 1)[0].strip()


def _normalize_diff_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    if normalized in {"", "/dev/null"}:
        return normalized
    if normalized.startswith("a/") or normalized.startswith("b/"):
        return normalized[2:]
    return normalized


def _strip_eol(line: str) -> str:
    return line.removesuffix("\n").removesuffix("\r")
