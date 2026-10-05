"""Parser tests for summary_native (T006): verbatim ids/bodies, 1-based lines,
and facts-not-raises behaviour on malformed input."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pipelines.summary_native import schema
from pipelines.summary_native.parse import parse_file, parse_text, synopsis_of

FIX = Path(__file__).parent / "fixtures" / "summary_native"


def _p(corpus: str, name: str):
    return parse_file(FIX / corpus / name, FIX)


def test_scene_ids_kept_verbatim():
    pf = _p("clean", "002-the-gate.md")
    assert [s.source_scene_id for s in pf.scenes] == ["002.01", "002.02", "002.03"]
    assert [s.title for s in pf.scenes] == ["Arrival at the Gate", "The Hall of Maps", "A Whispered Warning"]


def test_clean_corpus_has_seven_scenes():
    total = sum(len(_p("clean", n).scenes) for n in ("002-the-gate.md", "003-the-stacks.md", "005-the-door.md"))
    assert total == 7


def test_synopsis_is_h4_verbatim():
    pf = _p("clean", "002-the-gate.md")
    assert pf.scenes[0].synopsis == "Daz acts at the outer gate, changing what the party can do next."


def test_synopsis_joins_multiple_h4_with_slash():
    text = "# Chapter 1\n\n## Scenes\n\n### 001.01 A\n\nprose\n\n#### one\n\n#### two\n"
    assert parse_text(text, "001-x.md").scenes[0].synopsis == "one / two"


def test_synopsis_falls_back_to_first_paragraph_verbatim():
    body = "\nFirst  paragraph, line one.\nline two.\n\nSecond paragraph.\n"
    assert synopsis_of(body) == "First  paragraph, line one.\nline two."


def test_section_bodies_are_exact():
    path = FIX / "clean" / "002-the-gate.md"
    text = path.read_text()
    pf = parse_file(path, FIX)
    lines = text.splitlines(keepends=True)
    for sec in pf.sections:
        start = sec.line  # 1-based heading line -> body starts at 0-based index sec.line
        assert lines[sec.line - 1].startswith(f"## {sec.name}")
        assert sec.body == "".join(lines[start : start + len(sec.body.splitlines(keepends=True))])
    mm = pf.section("Memorable Moments")
    assert mm is not None and mm.body == '\n> "We should not be here, and yet here we are."\n\n'


def test_sections_in_order_with_one_based_lines():
    pf = _p("clean", "002-the-gate.md")
    assert [s.name for s in pf.sections] == ["Scenes", "Memorable Moments", "NPCs", "Locations", "Items", "Spells"]
    assert pf.title_line == 1
    lines = (FIX / "clean" / "002-the-gate.md").read_text().splitlines()
    for sec in pf.sections:
        assert lines[sec.line - 1] == f"## {sec.name}"
    for sc in pf.scenes:
        assert lines[sc.line - 1] == f"### {sc.heading}"
    for e in pf.entities:
        assert lines[e.line - 1] == f"### {e.heading}"


def test_entity_outside_scene_has_no_scene_id():
    pf = _p("clean", "002-the-gate.md")
    assert pf.entities, "fixture should carry entity entries"
    assert all(e.source_scene_id is None for e in pf.entities)
    assert {e.category for e in pf.entities} == {"npc", "location", "item", "spell"}
    npcs = [e.heading for e in pf.entities if e.category == "npc"]
    assert npcs == ["Manshoon"]


def test_prefix_title_and_date():
    pf = _p("clean", "003-the-stacks.md")
    assert (pf.prefix_chapter, pf.title_chapter, pf.date) == (3, 3, "2026-01-17")


def test_paths_are_posix_relative_to_root():
    pf = _p("clean", "002-the-gate.md")
    assert pf.path == "clean/002-the-gate.md"
    assert not pf.path.startswith("/")


def test_no_prefix_and_malformed_do_not_raise():
    pf = _p("multi_error", "session-notes.md")
    assert pf.prefix_chapter is None and pf.title_chapter == 1


def test_missing_title_and_missing_scenes_are_facts():
    pf = _p("multi_error", "011-no-title.md")
    assert pf.title_chapter is None and pf.title_line is None
    assert pf.section("Scenes") is None and pf.scenes == ()


def test_empty_scenes_section_is_present_with_no_entries():
    pf = _p("multi_error", "010-title-mismatch.md")
    sc = pf.section("Scenes")
    assert sc is not None and sc.entries == () and pf.title_chapter == 11 and pf.prefix_chapter == 10


def test_bad_scene_ids_recorded_with_match_flag():
    pf = _p("multi_error", "012-bad-scenes.md")
    ids = [s.source_scene_id for s in pf.scenes]
    assert ids == ["012.01", None, "013.01", "012.02", "012.02"]
    bad = pf.scenes[1]
    assert bad.title == "The Scene Without An Id" and bad.line > 0


def test_unknown_section_preserved():
    pf = _p("multi_error", "012-duplicate.md")
    assert "Foreshadowing" in [s.name for s in pf.sections]


def test_h3_not_matched_as_h2_and_h4_not_as_h3():
    assert schema.H2_RE.match("### x") is None
    assert schema.H3_RE.match("#### x") is None
    assert schema.H4_RE.match("##### x") is None
    assert schema.H2_RE.match("## x") and schema.H3_RE.match("### x") and schema.H4_RE.match("#### x")
    assert schema.TITLE_RE.search("## Chapter 4") is None
    assert schema.TITLE_RE.search("# chapter 12 : x").group(1) == "12"


def test_heading_inside_fence_ignored():
    text = "# Chapter 1\n\n## Scenes\n\n### 001.01 A\n\n```\n## Not A Section\n```\n"
    pf = parse_text(text, "001-x.md")
    assert [s.name for s in pf.sections] == ["Scenes"]


def test_unreadable_file_raises(tmp_path):
    with pytest.raises(OSError):
        parse_file(tmp_path / "nope.md", tmp_path)


def test_real_corpus_parses_if_available():
    """Opt-in smoke test against a real campaign's summaries directory.

    Set ``CG_OOTA_SUMMARIES`` to that directory to run it. It asserts only
    structure that a correct summary always has, never a known defect, so it
    keeps passing after the GM fixes the source files.
    """
    import os

    root = os.environ.get("CG_OOTA_SUMMARIES")
    if not root:
        pytest.skip("CG_OOTA_SUMMARIES not set")
    files = sorted(Path(root).glob("*.md"))
    assert files, f"no summaries in {root}"
    for f in files:
        pf = parse_file(f, Path(root).parent)
        assert pf.prefix_chapter is not None, f.name
        for scene in pf.scenes:
            if scene.source_scene_id is not None:
                assert re.fullmatch(r"\d{3}\.\d{2}", scene.source_scene_id)
