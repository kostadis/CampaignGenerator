"""Tests for facts_to_state.py — the per-entity fact-aggregation bundler.

Covers the deterministic Stage-1 logic (bundling, chapter ordering, type/floor
selection, render) where the precision lives. No API / no model calls.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import facts_to_state as fts  # noqa: E402
from synthesise_world_state import load_dossiers  # noqa: E402


def _fact(type_, subject, fact, quote="", subjects=None):
    return {"type": type_, "subject": subject, "fact": fact,
            "source_quote": quote, "subjects": subjects or [subject]}


def _bundle(type_, key, items):
    """items = [(chapter, fact_dict, display)]."""
    b = fts.Bundle(type_, key)
    for ch, f, disp in items:
        b.add(ch, f, disp)
    return b


def test_slugify():
    assert fts.slugify("Sarith Kzekarit") == "sarith_kzekarit"
    assert fts.slugify("Ilvara's Quarters!") == "ilvara_s_quarters"
    assert fts.slugify("") == "entity"


def test_chapter_num(tmp_path):
    p = tmp_path / "gen-ch07" / "merged.json"
    p.parent.mkdir()
    assert fts.chapter_num(p) == 7


def test_bundle_orders_by_chapter_and_picks_dominant_display():
    b = _bundle("npc", "daz", [
        (10, _fact("npc", "Daz", "later"), "Daz"),
        (3, _fact("npc", "daz", "earlier"), "Daz"),
        (3, _fact("npc", "Daz", "also early"), "Daz"),
    ])
    order = [ch for ch, _ in b.ordered()]
    assert order == [3, 3, 10]            # chronological, stable within chapter
    assert b.chapters == (3, 10)
    assert b.display == "Daz"             # most common cased form


def test_select_min_facts_only_and_top():
    bundles = {
        "npc\x00daz": _bundle("npc", "daz", [(i, _fact("npc", "Daz", f"f{i}"), "Daz") for i in range(1, 6)]),
        "npc\x00stool": _bundle("npc", "stool", [(1, _fact("npc", "Stool", "x"), "Stool"),
                                                  (2, _fact("npc", "Stool", "y"), "Stool")]),
        "npc\x00bit": _bundle("npc", "bit", [(1, _fact("npc", "Bit", "z"), "Bit")]),
    }
    # min_facts floor drops the 1- and 2-fact entities
    assert [b.display for b in fts.select(bundles, min_facts=3, only=None, top=None)] == ["Daz"]
    # only= matches normalised name
    assert [b.display for b in fts.select(bundles, min_facts=1, only="stool", top=None)] == ["Stool"]
    # top= keeps the densest N (sorted by -count)
    top = fts.select(bundles, min_facts=1, only=None, top=2)
    assert [b.display for b in top] == ["Daz", "Stool"]


def test_render_bundles_groups_and_chapter_tags():
    b = _bundle("thread", "themystery", [
        (4, _fact("thread", "the mystery", "clue A", "quote A"), "the mystery"),
        (9, _fact("thread", "the mystery", "clue B"), "the mystery"),
    ])
    md = fts.render_bundles([b], with_quotes=True)
    assert "## Threads" in md
    assert "### the mystery" in md
    assert "- [ch04] clue A" in md and "- [ch09] clue B" in md
    assert '> "quote A"' in md
    # no-quotes mode omits the blockquote
    assert '>' not in fts.render_bundles([b], with_quotes=False)


def test_load_bundles_groups_across_chapters_with_aliases(tmp_path):
    (tmp_path / "gen-ch01").mkdir()
    (tmp_path / "gen-ch02").mkdir()
    (tmp_path / "gen-ch01" / "merged.json").write_text(json.dumps([
        _fact("npc", "Bupido", "spoke"),          # variant spelling
        _fact("event", "a brawl", "happened"),    # non-stateful type filtered out
    ]), encoding="utf-8")
    (tmp_path / "gen-ch02" / "merged.json").write_text(json.dumps([
        _fact("npc", "Buppido", "left"),
    ]), encoding="utf-8")
    paths = list((tmp_path).glob("gen-ch*/merged.json"))
    aliases = {"Bupido": "Buppido"}              # canonicalise the variant
    bundles = fts.load_bundles(paths, aliases, types=["npc"])
    assert len(bundles) == 1                     # both npc facts in one bundle
    b = next(iter(bundles.values()))
    assert b.display == "Buppido"                # alias-resolved
    assert len(b.facts) == 2
    assert b.chapters == (1, 2)                  # chapter tagging from file path


def test_load_dossiers_filters_by_nfacts(tmp_path):
    (tmp_path / "npc_a.md").write_text("---\nname: A\ntype: npc\nn_facts: 40\n---\n\nbody A",
                                       encoding="utf-8")
    (tmp_path / "npc_b.md").write_text("---\nname: B\ntype: npc\nn_facts: 5\n---\n\nbody B",
                                       encoding="utf-8")
    kept = load_dossiers(list(tmp_path.glob("*.md")), min_facts=20)
    assert [stem for stem, _ in kept] == ["npc_a"]   # only A passes the floor
    assert "body A" in kept[0][1]


def test_known_names_accepts_repeated_flags():
    # The server (server/routers/ensemble.py _cmd_multi) passes each known-names
    # source as its own --known-names flag. nargs="+" alone would keep only the
    # last; action="extend" must accumulate all of them.
    p = fts.build_parser()
    args = p.parse_args(["--corpus", "x", "--known-names", "a.md",
                         "--known-names", "b.json", "--list"])
    assert args.known_names == ["a.md", "b.json"]
    # Single-flag multi-value (CLI style) must still work.
    args = p.parse_args(["--corpus", "x", "--known-names", "a.md", "b.json", "--list"])
    assert args.known_names == ["a.md", "b.json"]
    # Absent -> falsy so the "everything global" path is preserved.
    args = p.parse_args(["--corpus", "x", "--list"])
    assert not args.known_names
