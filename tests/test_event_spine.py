"""Event spine store + projections (#213 Phase 2).

The store is derived-but-durable: `update` replaces rows only for chapters
present in the input corpus and preserves everything else — the spine
outlives the gitignored per_chapter/ intermediates. Rows are keyed
(chapter, scene, seq) with quote provenance and Phase-1 lineage.
recent_events.md is a projection; build_recent_events keeps its old CLI as
a wrapper over update+render.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipelines.grounding.event_spine import (  # noqa: E402
    load_store,
    render,
    rows_from_corpus,
    update,
)


def _corpus(dirp: Path, chapter: int, facts: list[dict]) -> Path:
    d = dirp / f"chapter_{chapter:02d}_x"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "merged.json"
    f.write_text(json.dumps(facts))
    return f


def _event(text, scene=None, offset=None, quote="", verified=True, source=None):
    fa = {"type": "event", "subject": "x", "fact": text,
          "source_quote": quote, "quote_verified": verified}
    if scene is not None:
        fa["scene_index"] = scene
    if offset is not None:
        fa["quote_offset"] = offset
    if source:
        fa["source"] = source
    return fa


def test_rows_carry_key_provenance_and_lineage(tmp_path):
    f = _corpus(tmp_path, 40, [
        _event("Orc nine dies.", scene=2, offset=100, quote="The orc was dead",
               source={"kind": "scenes", "session": "20260505"}),
        {"type": "npc", "subject": "Prutha", "fact": "not an event",
         "source_quote": "", "quote_verified": False},
        _event("Table talk about action economy rolled a 3.", scene=1),  # OOC
    ])
    rows = rows_from_corpus(f)
    assert len(rows) == 1
    r = rows[0]
    assert (r["chapter"], r["scene"], r["seq"]) == (40, 2, 100)
    assert r["quote"] == "The orc was dead"
    assert r["source"] == {"kind": "scenes", "session": "20260505"}


def test_unverified_quote_is_not_provenance(tmp_path):
    f = _corpus(tmp_path, 40, [_event("A thing.", quote="fabricated", verified=False)])
    assert rows_from_corpus(f)[0]["quote"] == ""


def test_update_replaces_present_chapters_and_keeps_absent(tmp_path):
    store = tmp_path / "events.jsonl"
    _corpus(tmp_path / "c1", 40, [_event("Old ch40 event.")])
    _corpus(tmp_path / "c1", 41, [_event("Ch41 event.")])
    update([str(tmp_path / "c1" / "*" / "merged.json")], store)
    assert {r["chapter"] for r in load_store(store)} == {40, 41}

    # Re-extract only ch40 — ch41's rows must survive untouched.
    _corpus(tmp_path / "c2", 40, [_event("New ch40 event.", scene=1)])
    update([str(tmp_path / "c2" / "*" / "merged.json")], store)
    rows = load_store(store)
    by = {r["chapter"]: r for r in rows}
    assert len(rows) == 2
    assert by[40]["event"] == "New ch40 event."
    assert by[41]["event"] == "Ch41 event."


def test_store_ordering_chapter_scene_seq(tmp_path):
    store = tmp_path / "events.jsonl"
    _corpus(tmp_path, 40, [
        _event("scene2 late", scene=2, offset=500),
        _event("scene1", scene=1, offset=900),
        _event("scene2 early", scene=2, offset=10),
        _event("unlocated"),
    ])
    update([str(tmp_path / "*" / "merged.json")], store)
    events = [r["event"] for r in load_store(store)]
    assert events == ["scene1", "scene2 early", "scene2 late", "unlocated"]


def test_render_is_projection_with_window(tmp_path):
    store = tmp_path / "events.jsonl"
    for ch in (39, 40, 41):
        _corpus(tmp_path / "c", ch, [_event(f"Chapter {ch} happening.")])
    update([str(tmp_path / "c" / "*" / "merged.json")], store)
    out = tmp_path / "recent_events.md"
    kept, nch = render(store, out, window=2, campaign="TestCampaign")
    text = out.read_text()
    assert (kept, nch) == (2, 2)
    assert "Chapter 39" not in text and "## Chapter 41" in text
    assert "Projection of" in text and "events.jsonl" in text


def test_wrapper_cli_updates_store_and_renders(tmp_path):
    _corpus(tmp_path / "corpus", 40, [_event("Wrapped event.")])
    proc = subprocess.run(
        [sys.executable, str(REPO / "pipelines/grounding/build_recent_events.py"),
         "--corpus", str(tmp_path / "corpus" / "*" / "merged.json"),
         "--output", str(tmp_path / "recent_events.md"),
         "--store", str(tmp_path / "events.jsonl"), "--campaign", "T"],
        capture_output=True, text=True, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "events.jsonl").exists()
    assert "Wrapped event." in (tmp_path / "recent_events.md").read_text()
