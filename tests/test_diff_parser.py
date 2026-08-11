import pytest

from app.application.providers import get_provider
from app.application.services.review_service import ReviewService, ReviewWorker
from app.domain.diff_parser import (
    DEFAULT_CHUNK_BYTES,
    DiffLineKind,
    InvalidUnifiedDiff,
    chunk_diff,
    extract_added_lines,
    parse_unified_diff,
)
from app.domain.models import Job


def file_diff(path: str, content: str) -> str:
    return f"--- a/{path}\n+++ b/{path}\n@@ -0,0 +1 @@\n+{content}\n"


def exact_size_file_diff(path: str, size: int, char: str = "x") -> str:
    prefix = f"--- a/{path}\n+++ b/{path}\n@@ -0,0 +1 @@\n+"
    suffix = "\n"
    content_bytes = size - len(prefix.encode("utf-8")) - len(suffix.encode("utf-8"))
    assert content_bytes >= 0
    return f"{prefix}{char * content_bytes}{suffix}"


def added(files):
    return [line for file in files for line in extract_added_lines(file)]


def test_parse_one_file_one_hunk_with_mixed_line_kinds() -> None:
    files = parse_unified_diff("--- a/app.py\n+++ b/app.py\n@@ -3,3 +3,4 @@\n context\n-old\n+new\n same\n+tail\n")

    assert len(files) == 1
    assert files[0].path == "app.py"
    lines = files[0].hunks[0].lines
    assert [line.kind for line in lines] == [
        DiffLineKind.CONTEXT,
        DiffLineKind.REMOVED,
        DiffLineKind.ADDED,
        DiffLineKind.CONTEXT,
        DiffLineKind.ADDED,
    ]
    assert [(line.line, line.content) for line in extract_added_lines(files[0])] == [(4, "new"), (6, "tail")]


def test_parse_multiple_hunks_and_correct_new_file_line_numbers() -> None:
    files = parse_unified_diff("--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,3 @@\n first\n+inserted\n second\n@@ -10,2 +11,3 @@\n ten\n+eleven\n twelve\n")

    assert [(line.line, line.content) for line in extract_added_lines(files[0])] == [(2, "inserted"), (12, "eleven")]


def test_parse_multiple_files_preserves_file_order() -> None:
    files = parse_unified_diff(file_diff("b.py", "b") + file_diff("a.py", "a"))

    assert [file.path for file in files] == ["b.py", "a.py"]
    assert [(line.path, line.line, line.content) for line in added(files)] == [("b.py", 1, "b"), ("a.py", 1, "a")]


def test_omitted_hunk_counts_default_to_one() -> None:
    files = parse_unified_diff("--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n")

    hunk = files[0].hunks[0]
    assert (hunk.old_count, hunk.new_count) == (1, 1)
    assert [(line.line, line.content) for line in extract_added_lines(files[0])] == [(1, "new")]


def test_plus_plus_plus_header_is_not_added_but_hunk_content_is() -> None:
    files = parse_unified_diff("--- a/app.py\n+++ b/app.py\n@@ -0,0 +1,2 @@\n++++ content\n+literal +++ content\n")

    assert [(line.line, line.content) for line in extract_added_lines(files[0])] == [
        (1, "+++ content"),
        (2, "literal +++ content"),
    ]


def test_new_file_and_deleted_file_dev_null_paths() -> None:
    files = parse_unified_diff(
        "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,2 @@\n+one\n+two\n"
        "--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n"
    )

    assert [file.path for file in files] == ["new.py", "old.py"]
    assert [(line.path, line.line, line.content) for line in added(files)] == [("new.py", 1, "one"), ("new.py", 2, "two")]


def test_malformed_hunk_and_missing_headers_are_rejected() -> None:
    with pytest.raises(InvalidUnifiedDiff):
        parse_unified_diff("--- a/app.py\n+++ b/app.py\n@@ bad @@\n+new\n")

    with pytest.raises(InvalidUnifiedDiff):
        parse_unified_diff("+++ b/app.py\n@@ -0,0 +1 @@\n+new\n")


def test_no_added_lines_path_normalization_and_newline_variants() -> None:
    trailing = parse_unified_diff("--- a/src\\app.py\n+++ b/src\\app.py\n@@ -1 +1 @@\n same\n")
    no_trailing = parse_unified_diff("--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n same")

    assert trailing[0].path == "src/app.py"
    assert extract_added_lines(trailing[0]) == []
    assert extract_added_lines(no_trailing[0]) == []


def test_chunk_under_exact_and_above_default_threshold() -> None:
    under = parse_unified_diff(exact_size_file_diff("under.py", DEFAULT_CHUNK_BYTES - 1))
    exact = parse_unified_diff(exact_size_file_diff("exact.py", DEFAULT_CHUNK_BYTES))
    above = parse_unified_diff(exact_size_file_diff("above.py", DEFAULT_CHUNK_BYTES + 1))

    assert [chunk.size_bytes for chunk in chunk_diff(under)] == [DEFAULT_CHUNK_BYTES - 1]
    assert [chunk.size_bytes for chunk in chunk_diff(exact)] == [DEFAULT_CHUNK_BYTES]
    above_chunks = chunk_diff(above)
    assert len(above_chunks) == 1
    assert above_chunks[0].size_bytes == DEFAULT_CHUNK_BYTES + 1


def test_chunk_multiple_files_crossing_threshold_only_on_file_boundaries() -> None:
    files = parse_unified_diff(file_diff("one.py", "1" * 10) + file_diff("two.py", "2" * 10) + file_diff("three.py", "3" * 10))
    first_size = files[0].byte_length
    second_size = files[1].byte_length
    chunks = chunk_diff(files, max_chunk_bytes=first_size + second_size)

    assert [[file.path for file in chunk.files] for chunk in chunks] == [["one.py", "two.py"], ["three.py"]]
    assert [chunk.index for chunk in chunks] == [0, 1]
    assert chunks[0].raw_bytes == (files[0].raw_text + files[1].raw_text).encode("utf-8")


def test_single_file_larger_than_threshold_is_own_chunk_and_order_is_preserved() -> None:
    files = parse_unified_diff(file_diff("small-a.py", "a") + file_diff("large.py", "L" * 40) + file_diff("small-b.py", "b"))
    chunks = chunk_diff(files, max_chunk_bytes=files[0].byte_length + 1)

    assert [[file.path for file in chunk.files] for chunk in chunks] == [["small-a.py"], ["large.py"], ["small-b.py"]]
    assert chunks[1].size_bytes == files[1].byte_length


def test_chunking_uses_utf8_bytes_not_character_count() -> None:
    files = parse_unified_diff(file_diff("unicode.py", "ééé"))
    chunk = chunk_diff(files, max_chunk_bytes=files[0].byte_length)[0]

    assert len(files[0].raw_text) < files[0].byte_length
    assert chunk.size_bytes == len(chunk.raw_bytes)


def test_parser_output_and_added_lines_are_independent_of_chunk_grouping() -> None:
    files = parse_unified_diff(file_diff("a.py", "alpha") + file_diff("b.py", "beta"))
    one_chunk = chunk_diff(files, max_chunk_bytes=sum(file.byte_length for file in files))
    two_chunks = chunk_diff(files, max_chunk_bytes=files[0].byte_length)

    assert [(line.path, line.line, line.content) for line in added(one_chunk[0].files)] == [
        ("a.py", 1, "alpha"),
        ("b.py", 1, "beta"),
    ]
    assert [(line.path, line.line, line.content) for chunk in two_chunks for line in added(chunk.files)] == [
        ("a.py", 1, "alpha"),
        ("b.py", 1, "beta"),
    ]


def test_review_worker_uses_parser_chunker_and_original_input_bytes() -> None:
    diff = exact_size_file_diff("a.py", 40000) + exact_size_file_diff("b.py", 40000)
    service = ReviewService()
    job = Job.create(provider="mock", max_findings=10, request_fingerprint="abc", diff=diff)
    service.job_repository.save(job)

    ReviewWorker(service).process_job(job.job_id)

    updated = service.get_job(job.job_id)
    assert updated is not None
    assert updated.status.value == "done"
    assert updated.usage is not None
    assert updated.usage.input_bytes == len(diff.encode("utf-8"))
    assert updated.usage.chunks == 2
    assert updated.findings == []


def test_mock_findings_are_identical_for_chunked_and_unchunked_processing() -> None:
    diff = (
        file_diff("a.py", "eval(x)")
        + file_diff("b.py", "const apiKey = 'ABCDEFGHIJKLMNOP' + eval(userInput)")
        + file_diff("c.py", "console.log('debug')")
    )
    files = parse_unified_diff(diff)
    all_in_one = _process_findings(files, chunk_bytes=sum(file.byte_length for file in files), max_findings=2)
    chunked = _process_findings(files, chunk_bytes=files[0].byte_length, max_findings=2)

    assert all_in_one == chunked
    assert [finding.id for finding in all_in_one] == [finding.id for finding in chunked]
    assert len(all_in_one) == len(chunked)


def _process_findings(files, chunk_bytes: int, max_findings: int) -> list[Job]:
    chunks = chunk_diff(files, max_chunk_bytes=chunk_bytes)
    provider = get_provider("mock")
    findings = []
    for chunk in chunks:
        added_lines = [line for file in chunk.files for line in extract_added_lines(file)]
        findings.extend(provider.analyze(added_lines))
    unique_findings = {finding.id: finding for finding in findings}
    sorted_findings = sorted(unique_findings.values(), key=lambda finding: (finding.path, finding.line, finding.rule_id))
    return sorted_findings[:max_findings]
