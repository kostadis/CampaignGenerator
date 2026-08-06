"""Excerpt fidelity (Constitution IV), the undecodable branch, and reporting.

**Verbatim is Sacred.** An excerpt is a slice of bytes that were on disk,
decoded — never trimmed, normalised, re-wrapped or "cleaned up". The tests below
compare against the file's own bytes rather than against a hand-copied string,
so a normalisation introduced later cannot be quietly blessed by editing the
expectation to match.

The undecodable branch is not defensive programming. The live corpus contains
Windows `Zone.Identifier` streams and Dropbox attribute files, and rg answers
with base64 `bytes` rather than `text` for those lines. `errors="replace"` would
silently mangle them, which Constitution IV forbids — so they come back flagged
(research D18).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from provenance.scan import (
    ScannerUnavailable,
    available_scanners,
    extract_excerpt,
    scan,
    select_scanner,
)
from provenance.search import SearchRequest, run_search


# ── scanner selection (T039) ─────────────────────────────────────────────────


def test_python_is_always_available() -> None:
    assert "python" in available_scanners()


def test_default_prefers_rg_when_discoverable(rg_or_skip) -> None:
    assert select_scanner(None).name == "rg"


def test_selection_reports_the_implementation_and_its_version() -> None:
    impl = select_scanner("python")
    assert impl.name == "python"
    assert impl.version, "an unreported scanner version is exactly the tribal state VIII forbids"


def test_forcing_an_unavailable_scanner_refuses(monkeypatch) -> None:
    """A silent fallback would make `--scanner rg` a lie the caller cannot detect."""
    monkeypatch.setattr("provenance.scan.shutil.which", lambda _: None)
    with pytest.raises(ScannerUnavailable):
        select_scanner("rg")


def test_an_unknown_scanner_name_refuses() -> None:
    with pytest.raises(ScannerUnavailable):
        select_scanner("grep")


# ── excerpt fidelity ─────────────────────────────────────────────────────────


def test_excerpt_is_the_line_as_written(fixture_workspace: Path) -> None:
    path = fixture_workspace / "alpha" / "docs" / "world_state.md"
    expected = path.read_bytes().split(b"\n")[2].decode("utf-8")
    assert extract_excerpt(path, 3, context_lines=2).text == expected


def test_excerpt_keeps_leading_whitespace(fixture_workspace: Path) -> None:
    """Stripping indentation is a normalisation, and YAML lines carry meaning in it."""
    path = fixture_workspace / "alpha" / "docs" / "corrections.yaml"
    excerpt = extract_excerpt(path, 7, context_lines=0)
    assert excerpt.text.startswith("      subjects:")


def test_context_lines_are_verbatim_and_bounded(fixture_workspace: Path) -> None:
    path = fixture_workspace / "alpha" / "docs" / "world_state.md"
    lines = path.read_text(encoding="utf-8").split("\n")
    excerpt = extract_excerpt(path, 3, context_lines=2)
    assert list(excerpt.before) == lines[0:2]
    assert list(excerpt.after) == lines[3:5]


def test_context_at_the_top_of_a_file_does_not_wrap(fixture_workspace: Path) -> None:
    path = fixture_workspace / "alpha" / "docs" / "world_state.md"
    excerpt = extract_excerpt(path, 1, context_lines=2)
    assert excerpt.before == ()


def test_context_lines_zero_is_honoured(fixture_workspace: Path) -> None:
    path = fixture_workspace / "alpha" / "docs" / "world_state.md"
    excerpt = extract_excerpt(path, 3, context_lines=0)
    assert excerpt.before == () and excerpt.after == ()


# ── the undecodable branch (D18) ─────────────────────────────────────────────


def test_undecodable_line_is_flagged_not_mangled(fixture_workspace: Path) -> None:
    path = fixture_workspace / "alpha" / "docs" / "undecodable.md"
    excerpt = extract_excerpt(path, 3, context_lines=0)
    assert excerpt.encoding == "undecodable"
    # The escaped form is reversible; U+FFFD would not be.
    assert "\\xe9" in excerpt.text
    assert "�" not in excerpt.text


def test_a_decodable_line_says_so(fixture_workspace: Path) -> None:
    path = fixture_workspace / "alpha" / "docs" / "world_state.md"
    assert extract_excerpt(path, 3, context_lines=0).encoding == "utf-8"


def test_an_undecodable_hit_survives_the_whole_pipeline(
    fixture_manifest, fixture_workspace
) -> None:
    response = run_search(
        SearchRequest(query="Silver Lantern", campaigns=["alpha"]),
        fixture_manifest,
        fixture_workspace,
    )
    hit = next(h for h in response.hits if h.path == "docs/undecodable.md")
    assert hit.excerpt_encoding == "undecodable"


# ── scanning ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("scanner", ["python", "rg"])
def test_scan_finds_the_expected_lines(scanner, fixture_manifest, fixture_workspace) -> None:
    if scanner == "rg":
        pytest.importorskip("shutil")
        import shutil

        if shutil.which("rg") is None:
            pytest.skip("ripgrep not on PATH")
    campaign = fixture_manifest.campaigns["alpha"]
    result = scan(
        campaign,
        fixture_workspace / "alpha",
        "Silver Lantern",
        impl=select_scanner(scanner),
    )
    found = {(m.path, m.line) for m in result.matches}
    assert ("docs/world_state.md", 3) in found
    assert ("notes/scratch.md", 3) in found
    assert ("docs/undecodable.md", 3) in found


def test_scan_is_literal_by_default(fixture_manifest, fixture_workspace) -> None:
    """A query is escaped unless --regex; `.` must not match every character."""
    campaign = fixture_manifest.campaigns["alpha"]
    result = scan(
        campaign, fixture_workspace / "alpha", "Silver.Lantern", impl=select_scanner("python")
    )
    assert result.matches == ()


def test_regex_mode_is_opt_in(fixture_manifest, fixture_workspace) -> None:
    campaign = fixture_manifest.campaigns["alpha"]
    result = scan(
        campaign,
        fixture_workspace / "alpha",
        r"Silver\s+Lantern",
        regex=True,
        impl=select_scanner("python"),
    )
    assert result.matches


def test_case_insensitive_by_default(fixture_manifest, fixture_workspace) -> None:
    campaign = fixture_manifest.campaigns["alpha"]
    result = scan(
        campaign, fixture_workspace / "alpha", "silver lantern", impl=select_scanner("python")
    )
    assert result.matches


def test_case_sensitive_is_opt_in(fixture_manifest, fixture_workspace) -> None:
    campaign = fixture_manifest.campaigns["alpha"]
    result = scan(
        campaign,
        fixture_workspace / "alpha",
        "silver lantern",
        case_sensitive=True,
        impl=select_scanner("python"),
    )
    assert result.matches == ()


def test_scan_reports_which_implementation_ran(fixture_manifest, fixture_workspace) -> None:
    campaign = fixture_manifest.campaigns["alpha"]
    result = scan(
        campaign, fixture_workspace / "alpha", "Silver", impl=select_scanner("python")
    )
    assert result.impl.name == "python"
    assert result.impl.version


def test_the_response_names_the_active_scanner(fixture_manifest, fixture_workspace) -> None:
    response = run_search(
        SearchRequest(query="Silver Lantern", campaigns=["alpha"], scanner="python"),
        fixture_manifest,
        fixture_workspace,
    )
    literal = next(b for b in response.backends_consulted if b.name == "literal")
    assert literal.impl == "python"
    assert literal.impl_version
