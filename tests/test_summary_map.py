"""Unit + integration tests for pipelines/ensemble/summary_map.py (issue #199).

Deliberately uses synthetic fixtures throughout, never the real OOTA tree —
see the module docstring's "62 chapters, 16 summaries" note for where the
real numbers are validated (manually, read-only, outside this repo).

The regression test at the bottom
(``test_tie_break_never_returns_confidence_below_min_confidence``) captures
a real bug found while calibrating against the actual OOTA corpus: the
tie-break step could swap the winning candidate to one whose OWN score was
below --min-confidence, as long as it was within TIE_EPSILON of a stronger
sibling that had already cleared the bar. That silently contradicted the
entry's own "confidence >= min_confidence" contract. Keep this test failing
if that guard (in propose_for_chapter's `tied = [...]` filter) regresses.
"""

import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipelines.ensemble import summary_map as sm  # noqa: E402


# ── fixture helpers ──────────────────────────────────────────────────────

def _write_chapter(dir_path: Path, name: str, headings: list[tuple[str | None, str]]) -> Path:
    """headings: [(pov_or_None, heading_text), ...] -> '## POV — text' or '## text'."""
    lines = [f"# Chapter {name}", ""]
    for pov, text in headings:
        lines.append(f"## {pov} — {text}" if pov else f"## {text}")
        lines.append("")
        lines.append("Some prose happens here.")
        lines.append("")
    path = dir_path / f"chapter_{name}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_summary(dir_path: Path, scenes: list[str] | None) -> Path:
    """scenes=None writes the unstructured 'Overview / Session Events' shape."""
    dir_path.mkdir(parents=True, exist_ok=True)
    lines = ["# recap", "", "## Summary", "Some summary text.", ""]
    if scenes is not None:
        lines.append("## Scenes")
        for scene in scenes:
            lines += [f"### {scene}", "- a detail", ""]
        lines += ["## Locations", "### Somewhere", ""]
    else:
        lines += [
            "## Overview", "Text.", "",
            "## Session Events", "- something happened", "",
        ]
    path = dir_path / "session-summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ── heading extraction ───────────────────────────────────────────────────

def test_parse_chapter_headings_strips_pov_prefix():
    text = "\n".join([
        "# Chapter 62 The Key is Secured",
        "",
        "## Zalthir — The Aftermath of the Sanctum Attack",
        "prose",
        "## Daz — The Death of Bookwyrm",
        "prose",
    ])
    assert sm.parse_chapter_headings(text) == [
        "The Aftermath of the Sanctum Attack",
        "The Death of Bookwyrm",
    ]


def test_parse_chapter_headings_keeps_plain_headings_verbatim():
    # '## <date>' and other non-POV conventions: kept as-is, not dropped —
    # they simply won't overlap with a summary's scene titles later.
    text = "## 3rd day of the 2nd tenday of Taraskh, 1492\n### Grygum\nprose\n"
    assert sm.parse_chapter_headings(text) == ["3rd day of the 2nd tenday of Taraskh, 1492"]


def test_parse_chapter_headings_ignores_h3_and_h4():
    text = "### Grygum\n#### sub\nprose with no h2 at all\n"
    assert sm.parse_chapter_headings(text) == []


def test_parse_summary_scenes_extracts_ordered_h3_within_scenes_section():
    text = "\n".join([
        "## Summary", "text", "",
        "## Scenes",
        "### Scene One", "- detail", "",
        "### Scene Two", "- detail", "",
        "## Locations",
        "### Not A Scene",
    ])
    assert sm.parse_summary_scenes(text) == ["Scene One", "Scene Two"]


def test_parse_summary_scenes_returns_none_when_no_scenes_section():
    text = "## Overview\ntext\n## Session Events\n- happened\n"
    assert sm.parse_summary_scenes(text) is None


def test_parse_summary_scenes_returns_none_when_scenes_section_empty():
    text = "## Scenes\n\n## Locations\n### Somewhere\n"
    assert sm.parse_summary_scenes(text) is None


# ── similarity / scoring ─────────────────────────────────────────────────

def test_heading_similarity_identical_text_is_perfect():
    assert sm.heading_similarity("The Death of Bookwyrm", "The Death of Bookwyrm") == 1.0


def test_heading_similarity_ignores_case_and_punctuation():
    assert sm.heading_similarity("The Death of Bookwyrm!", "the death of bookwyrm") == 1.0


def test_heading_similarity_unrelated_text_is_low():
    assert sm.heading_similarity("The Death of Bookwyrm", "Fungus Among Us") < 0.4


def test_score_overlap_empty_inputs_score_zero():
    assert sm.score_overlap([], ["Scene"]) == (0.0, [])
    assert sm.score_overlap(["Heading"], None) == (0.0, [])
    assert sm.score_overlap(["Heading"], []) == (0.0, [])


def test_score_overlap_perfect_match():
    overlap, matched = sm.score_overlap(
        ["The Aftermath of the Sanctum Attack", "The Death of Bookwyrm"],
        ["The Aftermath of the Sanctum Attack", "The Death of Bookwyrm", "Aftermath and Strategy"],
    )
    assert overlap == 1.0
    assert len(matched) == 2
    assert all(m["score"] == 1.0 for m in matched)
    assert matched[0]["summary_scene"] == "The Aftermath of the Sanctum Attack"


# ── chapter index / summary date parsing ─────────────────────────────────

def test_chapter_index_from_filename():
    assert sm.chapter_index_from_filename(Path("chapter_62_the_key_is_secured.md")) == 62
    assert sm.chapter_index_from_filename(Path("chapter_01_intro.md")) == 1
    assert sm.chapter_index_from_filename(Path("prologue.md")) is None


def test_summary_date_from_dirname_valid():
    assert sm.summary_date_from_dirname("20260720") == date(2026, 7, 20)


def test_summary_date_from_dirname_rejects_non_date_suffix():
    # The real OOTA tree has summaries/old/20260404.old/ — a superseded
    # duplicate whose dirname the ^\d{8}$ pattern must NOT match.
    assert sm.summary_date_from_dirname("20260404.old") is None


def test_summary_date_from_dirname_rejects_invalid_calendar_date():
    assert sm.summary_date_from_dirname("20261332") is None  # month 13, day 32


def test_summary_date_from_dirname_rejects_non_numeric():
    assert sm.summary_date_from_dirname("old") is None


# ── discovery (file-based) ────────────────────────────────────────────────

def test_discover_chapters_sorted_and_parsed(tmp_path):
    chapters_dir = tmp_path / "chapters"
    chapters_dir.mkdir()
    _write_chapter(chapters_dir, "02_b", [(None, "Second")])
    _write_chapter(chapters_dir, "01_a", [("Grygum", "First")])
    chapters = sm.discover_chapters(str(chapters_dir / "chapter_*.md"))
    assert [c.path.name for c in chapters] == ["chapter_01_a.md", "chapter_02_b.md"]
    assert chapters[0].index == 1
    assert chapters[0].headings == ["First"]


def test_discover_summaries_walks_nested_old_directory(tmp_path):
    summaries_dir = tmp_path / "summaries"
    _write_summary(summaries_dir / "20260720", scenes=["Scene A"])
    _write_summary(summaries_dir / "old" / "20260518", scenes=["Scene B"])
    _write_summary(summaries_dir / "old" / "20260404.old", scenes=None)

    summaries = sm.discover_summaries(summaries_dir)
    ids = {s.summary_id for s in summaries}
    assert len(summaries) == 3
    assert str(summaries_dir / "20260720") in ids
    assert str(summaries_dir / "old" / "20260518") in ids
    assert str(summaries_dir / "old" / "20260404.old") in ids

    by_id = {s.summary_id: s for s in summaries}
    dotted = by_id[str(summaries_dir / "old" / "20260404.old")]
    assert dotted.dir_date is None          # unparseable dirname
    assert dotted.structured is False        # scenes=None fixture

    dated = by_id[str(summaries_dir / "20260720")]
    assert dated.dir_date == date(2026, 7, 20)
    assert dated.structured is True


def test_discover_summaries_recognises_duplicate_dates(tmp_path):
    # OOTA has both summaries/20260504/ and summaries/old/20260504/ — two
    # distinct files sharing one calendar date. Both must survive discovery
    # as separate entries (never silently merged/dropped).
    summaries_dir = tmp_path / "summaries"
    _write_summary(summaries_dir / "20260504", scenes=["A"])
    _write_summary(summaries_dir / "old" / "20260504", scenes=["A"])
    summaries = sm.discover_summaries(summaries_dir)
    assert len(summaries) == 2
    assert {s.summary_id for s in summaries} == {
        str(summaries_dir / "20260504"), str(summaries_dir / "old" / "20260504"),
    }
    assert sum(1 for s in summaries if s.dir_date == date(2026, 5, 4)) == 2


# ── expected-index interpolation (date-proximity signal) ─────────────────

def test_build_expected_index_map_interpolates_by_rank():
    early = sm.SummaryInfo(path=Path("a"), summary_id="a", dir_date=date(2026, 1, 1))
    late = sm.SummaryInfo(path=Path("b"), summary_id="b", dir_date=date(2026, 12, 1))
    expected = sm.build_expected_index_map([early, late], num_chapters=11)
    assert expected["a"] == 1.0
    assert expected["b"] == 11.0


def test_build_expected_index_map_needs_two_dated_summaries():
    only_one = sm.SummaryInfo(path=Path("a"), summary_id="a", dir_date=date(2026, 1, 1))
    assert sm.build_expected_index_map([only_one], num_chapters=10) == {}
    undated = sm.SummaryInfo(path=Path("a"), summary_id="a", dir_date=None)
    assert sm.build_expected_index_map([undated, undated], num_chapters=10) == {}


# ── propose_for_chapter ────────────────────────────────────────────────────

def _summary(summary_id, scenes, dir_date=None, structured=None):
    return sm.SummaryInfo(
        path=Path(summary_id) / "session-summary.md",
        summary_id=summary_id,
        dir_date=dir_date,
        scenes=scenes,
        structured=(scenes is not None) if structured is None else structured,
    )


def test_propose_for_chapter_confident_match():
    # Synthetic analog of the real acceptance case: chapter_62's six
    # headings ARE summaries/20260720's scenes 3-8 verbatim, POV stripped.
    chapter = sm.ChapterInfo(
        path=Path("chapter_62_the_key_is_secured.md"),
        index=62,
        headings=["The Aftermath of the Sanctum Attack", "The Death of Bookwyrm"],
    )
    summaries = [
        _summary("summaries/old/20260629", ["Unrelated Scene"], date(2026, 6, 29)),
        _summary(
            "summaries/20260720",
            ["A Recap", "Chaos", "The Aftermath of the Sanctum Attack", "The Death of Bookwyrm"],
            date(2026, 7, 20),
        ),
    ]
    entry = sm.propose_for_chapter(chapter, summaries, expected_index={}, min_confidence=0.75)
    assert entry["chapter"] == "chapter_62_the_key_is_secured.md"
    assert entry["summary"] == "summaries/20260720"
    assert entry["confidence"] == 1.0
    assert entry["approved"] is False
    assert entry["evidence"]["method"] == "scene_heading_overlap"
    assert len(entry["evidence"]["matched"]) == 2


def test_propose_for_chapter_no_confident_match_stays_null():
    chapter = sm.ChapterInfo(
        path=Path("chapter_01_exploring_the_prison.md"), index=1,
        headings=["3rd day of the 2nd tenday of Taraskh, 1492"],
    )
    summaries = [_summary("summaries/20260720", ["The Death of Bookwyrm"], date(2026, 7, 20))]
    entry = sm.propose_for_chapter(chapter, summaries, expected_index={}, min_confidence=0.75)
    assert entry["summary"] is None
    assert entry["confidence"] == 0.0
    assert entry["approved"] is False
    assert entry["evidence"]["method"] == "none"
    # Below-threshold candidate is surfaced for a human, never proposed.
    assert entry["evidence"]["best_scored_candidate"]["summary"] == "summaries/20260720"


def test_propose_for_chapter_unstructured_summary_never_wins():
    chapter = sm.ChapterInfo(
        path=Path("chapter_x.md"), index=1, headings=["The Death of Bookwyrm"],
    )
    summaries = [_summary("summaries/old/20260413", scenes=None, dir_date=date(2026, 4, 13))]
    entry = sm.propose_for_chapter(chapter, summaries, expected_index={}, min_confidence=0.75)
    assert entry["summary"] is None
    assert entry["evidence"]["best_scored_candidate"] is None  # 0.0 never counts as "scored"


def test_tie_break_prefers_nearest_position_among_genuine_ties():
    chapter = sm.ChapterInfo(path=Path("chapter_09.md"), index=9, headings=["h"])
    # score_overlap is patched below to key off each summary's (distinct)
    # scenes list, so the "content" here is just a distinguishing label.
    far = _summary("far", ["scene_far"], date(2026, 1, 1))
    near = _summary("near", ["scene_near"], date(2026, 1, 1))
    scores = {"scene_far": 0.80, "scene_near": 0.78}

    orig = sm.score_overlap
    try:
        sm.score_overlap = lambda h, s: (
            (scores[s[0]], [{"chapter_heading": h[0], "summary_scene": s[0], "score": scores[s[0]]}])
            if s else (0.0, [])
        )
        expected_index = {"far": 50.0, "near": 9.0}  # "near" sits exactly on chapter 9
        entry = sm.propose_for_chapter(
            chapter, [far, near], expected_index=expected_index, min_confidence=0.5,
        )
    finally:
        sm.score_overlap = orig

    # "far" has the higher raw score (0.80 > 0.78) but both clear
    # min_confidence and are within TIE_EPSILON (0.02 apart) — proximity
    # picks "near".
    assert entry["summary"] == "near"
    assert entry["confidence"] == 0.78
    assert "tie_break" in entry["evidence"]


def test_tie_break_never_returns_confidence_below_min_confidence():
    """Regression test for the bug found calibrating against real OOTA data.

    A weak candidate must never win just because it happens to fall within
    TIE_EPSILON of a stronger sibling that already cleared min_confidence —
    if the weak candidate's OWN score is below the bar, it must be excluded
    from the tie-break pool entirely, even if it is closer by position.
    """
    chapter = sm.ChapterInfo(path=Path("chapter_23.md"), index=23, headings=["h"])
    strong = _summary("strong", ["s"], date(2026, 1, 1))
    weak = _summary("weak", ["s"], date(2026, 1, 1))
    strong.scenes, weak.scenes = ["scene_strong"], ["scene_weak"]
    scores = {"scene_strong": 0.52, "scene_weak": 0.48}  # 0.04 apart: "tied" by TIE_EPSILON=0.05

    orig = sm.score_overlap
    try:
        sm.score_overlap = lambda h, s: (
            (scores[s[0]], [{"chapter_heading": h[0], "summary_scene": s[0], "score": scores[s[0]]}])
            if s else (0.0, [])
        )
        # "weak" sits exactly on the chapter's position — if the guard were
        # missing, position proximity would swap the winner to "weak" and
        # report confidence 0.48 despite --min-confidence 0.5.
        expected_index = {"strong": 1.0, "weak": 23.0}
        entry = sm.propose_for_chapter(
            chapter, [strong, weak], expected_index=expected_index, min_confidence=0.5,
        )
    finally:
        sm.score_overlap = orig

    assert entry["summary"] == "strong"
    assert entry["confidence"] == 0.52
    assert entry["confidence"] >= 0.5


# ── load_approved (preserve-on-rerun) ────────────────────────────────────

def test_load_approved_filters_to_approved_rows_only(tmp_path):
    path = tmp_path / "summary_map.yaml"
    path.write_text(yaml.safe_dump({
        "entries": [
            {"chapter": "chapter_01.md", "approved": True, "summary": "s1"},
            {"chapter": "chapter_02.md", "approved": False, "summary": "s2"},
            {"chapter": "chapter_03.md", "summary": None},  # no approved key at all
        ]
    }), encoding="utf-8")
    approved = sm.load_approved(path)
    assert set(approved) == {"chapter_01.md"}
    assert approved["chapter_01.md"]["summary"] == "s1"


def test_load_approved_missing_file_returns_empty(tmp_path):
    assert sm.load_approved(tmp_path / "does_not_exist.yaml") == {}


# ── main() end-to-end ─────────────────────────────────────────────────────

def _campaign_fixture(tmp_path):
    chapters_dir = tmp_path / "docs" / "chapters"
    chapters_dir.mkdir(parents=True)
    _write_chapter(chapters_dir, "01_intro", [("Grygum", "Waking Up"), ("Zalthir", "First Blood")])
    _write_chapter(chapters_dir, "02_unrelated", [(None, "2026-01-01")])
    summaries_dir = tmp_path / "summaries"
    _write_summary(summaries_dir / "20260101", scenes=["Waking Up", "First Blood", "Aftermath"])
    _write_summary(summaries_dir / "old" / "20251201", scenes=None)
    out_path = tmp_path / "docs" / "ensemble" / "summary_map.yaml"
    argv = [
        "summary_map",
        "--chapters-glob", str(chapters_dir / "chapter_*.md"),
        "--summaries-dir", str(summaries_dir),
        "--out", str(out_path),
    ]
    return chapters_dir, summaries_dir, out_path, argv


def test_main_writes_expected_mapping(tmp_path, monkeypatch):
    _, summaries_dir, out_path, argv = _campaign_fixture(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)
    sm.main()

    data = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert data["stats"]["chapters_found"] == 2
    assert data["stats"]["summaries_found"] == 2
    assert data["stats"]["summaries_structured"] == 1
    assert data["stats"]["summaries_unstructured"] == 1
    assert data["stats"]["chapters_proposed"] == 1
    assert data["stats"]["chapters_unmatched"] == 1

    entries = {e["chapter"]: e for e in data["entries"]}
    intro = entries["chapter_01_intro.md"]
    assert intro["summary"] == str(summaries_dir / "20260101")
    assert intro["confidence"] == 1.0
    assert intro["approved"] is False
    assert entries["chapter_02_unrelated.md"]["summary"] is None


def test_main_preserves_approved_row_and_force_discards_it(tmp_path, monkeypatch):
    _, _, out_path, argv = _campaign_fixture(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)
    sm.main()

    data = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    for e in data["entries"]:
        if e["chapter"] == "chapter_01_intro.md":
            e["approved"] = True
            e["confidence"] = 0.01  # deliberately wrong, to prove it round-trips verbatim
            e["evidence"] = {"human_note": "GM confirmed by hand"}
    out_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "argv", argv)
    sm.main()
    data2 = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    intro2 = next(e for e in data2["entries"] if e["chapter"] == "chapter_01_intro.md")
    assert intro2["approved"] is True
    assert intro2["confidence"] == 0.01
    assert intro2["evidence"] == {"human_note": "GM confirmed by hand"}
    assert data2["stats"]["chapters_preserved_approved"] == 1

    monkeypatch.setattr(sys, "argv", argv + ["--force"])
    sm.main()
    data3 = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    intro3 = next(e for e in data3["entries"] if e["chapter"] == "chapter_01_intro.md")
    assert intro3["approved"] is False
    assert intro3["confidence"] == 1.0
    assert data3["stats"]["chapters_preserved_approved"] == 0


def test_main_drops_orphaned_approval_for_renamed_chapter(tmp_path, monkeypatch, capsys):
    chapters_dir, summaries_dir, out_path, argv = _campaign_fixture(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)
    sm.main()

    data = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    for e in data["entries"]:
        if e["chapter"] == "chapter_01_intro.md":
            e["approved"] = True
    out_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )

    # Rename the chapter file on disk so it no longer matches the approved
    # row's key.
    (chapters_dir / "chapter_01_intro.md").rename(chapters_dir / "chapter_01_intro_renamed.md")

    monkeypatch.setattr(sys, "argv", argv)
    sm.main()
    captured = capsys.readouterr()
    assert "no longer match a discovered chapter file" in captured.err

    data2 = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    chapters_out = {e["chapter"] for e in data2["entries"]}
    assert "chapter_01_intro.md" not in chapters_out
    assert "chapter_01_intro_renamed.md" in chapters_out
