"""Tests for the deterministic (no-API) parts of synthesise_world_state.py.

The Claude synthesis call is not exercised here; these guard the
render/grounding layer — the LLM-pipeline checkpoint where atomic facts are
grouped into structured input by code, not by a model.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import synthesise_world_state as sws  # noqa: E402


def _fact(t, subject, fact, quote=""):
    return {"type": t, "subject": subject, "fact": fact, "source_quote": quote}


def test_render_groups_by_type_and_subject():
    facts = [
        _fact("npc", "Daz", "Daz casts Mind Sliver."),
        _fact("npc", "Daz", "Daz falls unconscious."),
        _fact("location", "Velkynvelve", "Velkynvelve is a drow outpost."),
    ]
    out = sws.render_facts(facts, aliases={}, with_quotes=False)
    assert "## NPCs" in out
    assert "## Locations" in out
    assert "**Daz**" in out
    # Both Daz facts land under the one subject header.
    assert out.count("**Daz**") == 1
    assert "- Daz casts Mind Sliver." in out
    assert "- Daz falls unconscious." in out


def test_render_orders_types_per_TYPE_ORDER():
    facts = [
        _fact("thread", "mystery", "An unresolved question."),
        _fact("npc", "Daz", "Daz acts."),
    ]
    out = sws.render_facts(facts, aliases={}, with_quotes=False)
    # npc precedes thread regardless of input order.
    assert out.index("## NPCs") < out.index("## Threads & Mysteries")


def test_render_quotes_toggle():
    facts = [_fact("npc", "Daz", "Daz casts a spell.", quote="Daz speaks the incantation")]
    with_q = sws.render_facts(facts, aliases={}, with_quotes=True)
    without_q = sws.render_facts(facts, aliases={}, with_quotes=False)
    assert '> "Daz speaks the incantation"' in with_q
    assert ">" not in without_q


def test_render_collapses_quote_whitespace():
    facts = [_fact("npc", "Daz", "Daz acts.", quote="line one\n  line two")]
    out = sws.render_facts(facts, aliases={}, with_quotes=True)
    assert '> "line one line two"' in out


def test_render_applies_aliases():
    facts = [
        _fact("npc", "Bupido", "Bupido fires a crossbow."),
        _fact("npc", "Buppido", "Buppido misses."),
    ]
    out = sws.render_facts(facts, aliases={"Buppido": "Buppido", "Bupido": "Buppido"},
                           with_quotes=False)
    assert out.count("**Buppido**") == 1
    assert "**Bupido**" not in out


def test_render_skips_empty_fact_text():
    facts = [_fact("npc", "Daz", "  "), _fact("npc", "Daz", "Daz acts.")]
    out = sws.render_facts(facts, aliases={}, with_quotes=False)
    assert out.count("- ") == 1


def test_unknown_type_sorts_after_known(tmp_path):
    facts = [_fact("npc", "Daz", "Daz acts."), _fact("weird", "x", "Odd.")]
    out = sws.render_facts(facts, aliases={}, with_quotes=False)
    assert out.index("## NPCs") < out.index("## Weird")


def test_load_party_names(tmp_path):
    p = tmp_path / "party.yaml"
    p.write_text(
        "characters:\n- name: Zalthir\n  sheet: z.md\n- name: Daz\n  sheet: d.md\n",
        encoding="utf-8",
    )
    assert sws.load_party_names(p) == ["Zalthir", "Daz"]


def test_load_party_names_missing_file():
    assert sws.load_party_names(Path("/nonexistent/party.yaml")) == []


def test_load_aliases_flat_map(tmp_path):
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps({"Buppido": ["Bupido", "Bupiddo"]}), encoding="utf-8")
    flat = sws.load_aliases(p)
    assert flat["Bupido"] == "Buppido"
    assert flat["Buppido"] == "Buppido"  # canonical self-maps


def test_session_label_prefers_parent_dir(tmp_path):
    d = tmp_path / "gen-ch02"
    d.mkdir()
    merged = d / "merged.json"
    merged.write_text("[]", encoding="utf-8")
    assert sws.session_label(merged) == "gen-ch02"
    other = tmp_path / "extract_004.json"
    other.write_text("[]", encoding="utf-8")
    assert sws.session_label(other) == "extract_004"


def test_session_index_orders_numerically(tmp_path):
    # chapter_2 must sort before chapter_10 (numeric, not lexical).
    paths = [tmp_path / f"chapter_{n}.json" for n in (10, 2, 3)]
    for p in paths:
        p.write_text("[]", encoding="utf-8")
    ordered = sorted(paths, key=sws.session_index)
    assert [p.stem for p in ordered] == ["chapter_2", "chapter_3", "chapter_10"]


def test_session_index_numberless_sorts_last(tmp_path):
    numbered = tmp_path / "chapter_05.json"
    numberless = tmp_path / "prologue.json"
    for p in (numbered, numberless):
        p.write_text("[]", encoding="utf-8")
    ordered = sorted([numberless, numbered], key=sws.session_index)
    assert [p.stem for p in ordered] == ["chapter_05", "prologue"]


def test_session_dates_keeps_real_drops_placeholders():
    facts = [
        {"type": "date", "subject": "4th day of the 2nd Tenday of Taraskh 1493",
         "fact": "x"},
        {"type": "date", "subject": "session date", "fact": "y"},
        {"type": "date", "subject": "4th day of the 2nd Tenday of Taraskh 1493",
         "fact": "dup"},
        {"type": "npc", "subject": "Daz", "fact": "not a date"},
    ]
    assert sws.session_dates(facts) == ["4th day of the 2nd Tenday of Taraskh 1493"]


def test_session_dates_empty_when_none():
    assert sws.session_dates([{"type": "npc", "subject": "Daz", "fact": "x"}]) == []


def test_expand_globs_dedups_and_sorts(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    fa = tmp_path / "a" / "merged.json"
    fb = tmp_path / "b" / "merged.json"
    fa.write_text("[]", encoding="utf-8")
    fb.write_text("[]", encoding="utf-8")
    pat = str(tmp_path / "*" / "merged.json")
    # Passing the same glob twice must not duplicate.
    out = sws.expand_globs([pat, pat])
    assert out == sorted([fa.resolve(), fb.resolve()])
