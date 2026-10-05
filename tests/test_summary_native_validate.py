"""Validation tests for summary_native (T009): a collector, never a raiser."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pipelines.summary_native import schema
from pipelines.summary_native.validate import (
    ChapterRange,
    InputError,
    RangeError,
    scan,
)

FIX = Path(__file__).parent / "fixtures" / "summary_native"


def _scan(corpus, since=None, until=None):
    return scan(FIX / corpus, FIX, since, until)


def _codes(report, **kw):
    return [
        f.code
        for f in report.findings
        if all(getattr(f, k) == v for k, v in kw.items())
    ]


def test_all_errors_one_pass():
    r = _scan("multi_error")
    codes = set(_codes(r))
    for code in (
        schema.NO_NUMERIC_PREFIX,
        schema.DUPLICATE_CHAPTER,
        schema.MISSING_TITLE,
        schema.TITLE_CHAPTER_MISMATCH,
        schema.MISSING_SCENES,
        schema.EMPTY_SCENES,
        schema.BAD_SCENE_ID,
        schema.SCENE_CHAPTER_MISMATCH,
        schema.DUPLICATE_SCENE_ID,
        schema.UNKNOWN_SECTION,
    ):
        assert code in codes, code
    # both errors of the double-error files are in the same report
    f010 = [f.code for f in r.findings if f.file.endswith("010-title-mismatch.md")]
    assert {schema.TITLE_CHAPTER_MISMATCH, schema.EMPTY_SCENES} <= set(f010)
    f011 = [f.code for f in r.findings if f.file.endswith("011-no-title.md")]
    assert {schema.MISSING_TITLE, schema.MISSING_SCENES} <= set(f011)
    assert r.blocking_count >= 9
    assert r.files_failing == 5


def test_title_mismatch_blocks_no_override():
    r = _scan("multi_error")
    (f,) = [x for x in r.findings if x.code == schema.TITLE_CHAPTER_MISMATCH]
    assert f.blocking and f.in_range
    assert f.expected == "# Chapter 10" and f.found == "# Chapter 11"
    assert f.line == 1


def test_scene_chapter_mismatch_blocks():
    r = _scan("multi_error")
    (f,) = [x for x in r.findings if x.code == schema.SCENE_CHAPTER_MISMATCH]
    assert f.blocking and f.found.startswith("013.01")
    assert f.file.endswith("012-bad-scenes.md")


def test_duplicate_chapter_blocks_even_outside_range():
    r = _scan("dup_chapter")
    dups = [f for f in r.findings if f.code == schema.DUPLICATE_CHAPTER]
    assert len(dups) == 2 and all(f.blocking for f in dups)
    # a range that excludes 003 does not unblock it
    r = scan(FIX / "multi_error", FIX, 10, 11)
    outside = [f for f in r.findings if f.code == schema.DUPLICATE_CHAPTER]
    assert outside and all(f.blocking and not f.in_range for f in outside)


def test_out_of_range_errors_listed_not_blocking():
    r = _scan("out_of_range", until=5)
    (f,) = [x for x in r.findings if x.code == schema.TITLE_CHAPTER_MISMATCH]
    assert f.file.endswith("008-late-session.md")
    assert not f.in_range and not f.blocking
    assert r.blocking_count == 0
    # same corpus, range including 008: now it blocks
    assert _scan("out_of_range").blocking_count == 1


def test_range_bound_without_file_refused_lists_present():
    with pytest.raises(RangeError) as e:
        _scan("clean", since=1)
    assert "2, 3, 5" in str(e.value)
    with pytest.raises(RangeError):
        _scan("clean", until=4)


def test_start_after_end_refused():
    with pytest.raises(RangeError):
        _scan("clean", since=5, until=2)


def test_gaps_reported_not_errors():
    r = _scan("clean")
    assert r.range.gaps == [4]
    gap = [f for f in r.findings if f.code == schema.RANGE_GAP]
    assert len(gap) == 1 and not gap[0].blocking and "4" in gap[0].message
    assert r.blocking_count == 0 and _codes(r, blocking=True) == []


def test_clean_corpus_has_no_findings_but_gap():
    r = _scan("clean")
    assert set(_codes(r)) == {schema.RANGE_GAP}
    assert r.files_scanned == 3 and r.range.since == 2 and r.range.until == 5


def test_empty_and_missing_dir_refused(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(InputError):
        scan(tmp_path / "empty", tmp_path, None, None)
    with pytest.raises(InputError):
        scan(tmp_path / "nope", tmp_path, None, None)


def test_ensemble_dir_refused(tmp_path):
    d = tmp_path / "docs" / "ensemble" / "x"
    shutil.copytree(FIX / "clean", d)
    with pytest.raises(InputError):
        scan(d, tmp_path, None, None)


def test_report_md_grouped_by_file_with_summary_counts():
    md = _scan("out_of_range", until=5).to_markdown()
    assert "## Outside range — not blocking" in md
    assert md.index("## Outside range") < md.index("008-late-session.md")
    assert "L1  title-chapter-mismatch" in md
    assert 'expected "# Chapter 8"' in md and 'found "# Chapter 6"' in md
    assert "Blocking problems: 0" in md
    md = _scan("multi_error").to_markdown()
    # each file is a heading, listed once, in chapter order
    heads = [ln for ln in md.splitlines() if ln.startswith("### ")]
    assert len(heads) == len(set(heads))
    names = [h[4:] for h in heads]
    assert names.index(next(n for n in names if "010-" in n)) < names.index(
        next(n for n in names if "011-" in n)
    )
    assert "Files failing: 5" in md


def test_json_matches_report_and_is_deterministic():
    a, b = _scan("multi_error"), _scan("multi_error")
    assert a.to_json() == b.to_json() and a.to_markdown() == b.to_markdown()
    data = json.loads(a.to_json())
    assert data["blocking_count"] == a.blocking_count
    assert len(data["findings"]) == len(a.findings)
    assert {"file", "line", "code", "message", "expected", "found", "blocking", "in_range"} <= set(
        data["findings"][0]
    )
    assert "/home" not in a.to_json()


def test_no_prefix_file_is_in_range_blocking():
    r = _scan("multi_error", since=10, until=12)
    (f,) = [x for x in r.findings if x.code == schema.NO_NUMERIC_PREFIX]
    assert f.in_range and f.blocking


def test_chapter_range_resolve_unset_bounds():
    rng = ChapterRange.resolve([2, 3, 5, 9], None, None)
    assert (rng.since, rng.until, rng.gaps) == (2, 9, [4, 6, 7, 8])
    with pytest.raises(RangeError):
        ChapterRange.resolve([], None, None)


def _mini(tmp_path, files):
    d = tmp_path / "s"
    d.mkdir()
    for name, data in files.items():
        (d / name).write_bytes(data if isinstance(data, bytes) else data.encode())
    return d


_OK = "# Chapter {n}\n\n## Scenes\n\n### {n:03d}.01 One\nSynopsis.\n"


def test_unreadable_file_is_a_finding_not_an_abort(tmp_path):
    d = _mini(
        tmp_path,
        {
            "001-bad.md": b"\xff\xfe\x00bad",
            "002-mismatch.md": _OK.format(n=3),
            "003-ok.md": _OK.format(n=3),
        },
    )
    r = scan(d, tmp_path, None, None)
    codes = {(f.file.rsplit("/", 1)[-1], f.code) for f in r.findings}
    assert ("001-bad.md", schema.UNREADABLE_FILE) in codes
    assert ("002-mismatch.md", schema.TITLE_CHAPTER_MISMATCH) in codes
    (u,) = [f for f in r.findings if f.code == schema.UNREADABLE_FILE]
    assert u.blocking and u.in_range and ("codec" in u.message or "utf" in u.message.lower())
    assert r.files_scanned == 3


def test_unreadable_file_without_prefix_is_in_range(tmp_path):
    d = _mini(tmp_path, {"zz.md": b"\xff\xfe", "002-a.md": _OK.format(n=2)})
    r = scan(d, tmp_path, None, None)
    (u,) = [f for f in r.findings if f.code == schema.UNREADABLE_FILE]
    assert u.in_range and u.blocking


def test_missing_title_found_is_first_h1(tmp_path):
    d = _mini(
        tmp_path,
        {
            "070-a.md": "# Session 2025-04-14\n\n## Scenes\n\n### 070.01 X\nS.\n",
            "071-b.md": "no heading here\n\n## Scenes\n\n### 071.01 X\nS.\n",
        },
    )
    r = scan(d, tmp_path, None, None)
    by = {f.file.rsplit("/", 1)[-1]: f for f in r.findings if f.code == schema.MISSING_TITLE}
    assert by["070-a.md"].found == "# Session 2025-04-14"
    assert by["070-a.md"].expected == "# Chapter 70"
    assert by["071-b.md"].found is None


def test_report_markdown_shape(tmp_path):
    d = _mini(
        tmp_path,
        {
            "070-a.md": "# Session 2025-04-14\n\n## Scenes\n\n### 070.01 X\nS.\n",
            "071-b.md": _OK.format(n=71),
        },
    )
    md = scan(d, tmp_path, None, None).to_markdown()
    lines = md.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("### "):
            assert lines[i - 1] == "", ln
            assert lines[i + 1] == ""
    assert "L-" not in md
    assert 'missing-title  expected "# Chapter 70"  found "# Session 2025-04-14"' in md
    # a line-bearing finding still prints its L token
    (tmp_path / "x").mkdir()
    d2 = _mini(tmp_path / "x", {"002-m.md": _OK.format(n=3)})
    assert "L1  title-chapter-mismatch" in scan(d2, tmp_path, None, None).to_markdown()
