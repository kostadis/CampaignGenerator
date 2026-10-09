from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pipelines.summary_native.authority import AuthorityError, SourceRef
from pipelines.summary_native.authority_sources import allowed_summary_path, exact_replace


def _source(path: str, *, anchor: str = "claim-earthstone") -> SourceRef:
    return SourceRef(path=path, anchor=anchor)


def _summary_workspace(tmp_path: Path) -> tuple[Path, Path]:
    summaries = tmp_path / "docs" / "summaries"
    summaries.mkdir(parents=True)
    target = summaries / "chapter-054.md"
    target.write_bytes(b"# Chapter\n\nThe false steward acted.\n")
    return summaries, target


def test_allowed_target_must_be_an_existing_markdown_file_under_summaries_root(tmp_path: Path):
    summaries, target = _summary_workspace(tmp_path)
    assert allowed_summary_path(tmp_path, summaries, _source("docs/summaries/chapter-054.md")) == target

    for path in ("docs/entity_registry.yaml", "docs/summaries/missing.md", "docs/summaries/state/result.md", "docs/summaries/chapter-054.txt"):
        with pytest.raises(AuthorityError, match="AUTH_TARGET_NOT_ALLOWED"):
            allowed_summary_path(tmp_path, summaries, _source(path))


def test_allowed_target_refuses_external_and_symlink_escapes(tmp_path: Path):
    summaries, _ = _summary_workspace(tmp_path)
    external = tmp_path.parent / "outside-authority-summary.md"
    external.write_text("outside")
    (summaries / "linked.md").symlink_to(external)

    with pytest.raises(AuthorityError, match="outside configured summaries root"):
        allowed_summary_path(tmp_path, summaries, _source("docs/summaries/linked.md"))


def test_exact_replace_requires_the_current_whole_file_digest_and_one_span(tmp_path: Path):
    _, target = _summary_workspace(tmp_path)
    original = target.read_bytes()
    before = b"The false steward acted."
    assert exact_replace(target, before, b"The correct actor acted.", expected_file_sha256=hashlib.sha256(original).hexdigest()) == original.replace(before, b"The correct actor acted.", 1)

    with pytest.raises(AuthorityError, match="AUTH_STALE_PROPOSAL"):
        exact_replace(target, before, b"replacement", expected_file_sha256="0" * 64)
    target.write_bytes(b"repeat\nrepeat\n")
    with pytest.raises(AuthorityError, match="AUTH_SPAN_NOT_UNIQUE"):
        exact_replace(target, b"repeat", b"changed")


def test_verbatim_guard_allows_normal_prose_outside_declared_verbatim_section(tmp_path: Path):
    _, target = _summary_workspace(tmp_path)
    target.write_bytes(
        b"## Narrative\n"
        b"The witness called the account verbatim during the hearing.\n"
        b"claim\n\n"
        b"## Verbatim moments\n"
        b"quoted table speech\n"
    )
    original = target.read_bytes()
    assert exact_replace(target, b"claim", b"replacement") == original.replace(b"claim", b"replacement", 1)

    target.write_bytes(b"## Verbatim moments\nclaim\n")
    with pytest.raises(AuthorityError, match="AUTH_VERBATIM_TARGET"):
        exact_replace(target, b"claim", b"replacement")


def test_generated_file_detection_uses_actual_generated_path_semantics(tmp_path: Path):
    summaries, target = _summary_workspace(tmp_path)
    ordinary = summaries / "draft-notes.md"
    ordinary.write_bytes(b"maintained summary")
    assert allowed_summary_path(tmp_path, summaries, _source("docs/summaries/draft-notes.md")) == ordinary

    generated = summaries / "ch002-057" / "state" / "summary.md"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"generated projection")
    with pytest.raises(AuthorityError, match="AUTH_TARGET_NOT_ALLOWED"):
        allowed_summary_path(tmp_path, summaries, _source("docs/summaries/ch002-057/state/summary.md"))

    generated_header = summaries / "chapter-055.md"
    generated_header.write_bytes(b"<!-- generated: summary-native -->\n# Derived projection\n")
    with pytest.raises(AuthorityError, match="AUTH_TARGET_NOT_ALLOWED"):
        allowed_summary_path(tmp_path, summaries, _source("docs/summaries/chapter-055.md"))
