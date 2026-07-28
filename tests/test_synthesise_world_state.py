"""Tests for the deterministic (no-API) parts of synthesise_world_state.py.

The Claude synthesis call is not exercised here (except in the --batch
section below); these guard the render/grounding layer — the LLM-pipeline
checkpoint where atomic facts are grouped into structured input by code, not
by a model.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipelines.ensemble import synthesise_world_state as sws  # noqa: E402


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


# ── Dossier scope: recency, not frequency (issue #194) ──────────────────────
#
# The floor used to apply to every dossier, so it deleted the newest chapter's
# entities on every run — a debuting entity has the fewest facts by
# construction. These pin the corrected contract: recency scopes the floor.


def _dossier(tmp_path, stem, n_facts, chapters="1-1", body="body"):
    """Write a facts_to_state-shaped dossier and return its path."""
    p = tmp_path / f"{stem}.md"
    fm = f"---\nname: {stem}\ntype: npc\nn_facts: {n_facts}\n"
    if chapters is not None:
        fm += f"chapters: {chapters}\n"
    p.write_text(fm + "---\n\n" + body + "\n", encoding="utf-8")
    return p


def _split(tmp_path, specs, background_min_facts, recent_window):
    paths = [_dossier(tmp_path, s, n, c) for s, n, c in specs]
    dossiers, n_missing = sws.read_dossiers(paths)
    recent, background, cutoff = sws.split_dossiers(
        dossiers, background_min_facts, recent_window)
    return ([d.stem for d in recent], [d.stem for d in background],
            cutoff, n_missing)


def test_read_dossiers_parses_both_frontmatter_fields(tmp_path):
    p = _dossier(tmp_path, "npc_moziqodo", 1, "62-62")
    dossiers, n_missing = sws.read_dossiers([p])
    assert n_missing == 0
    assert dossiers[0].n_facts == 1
    assert dossiers[0].last_chapter == 62


def test_recent_entity_survives_below_the_floor(tmp_path):
    # The OOTA regression verbatim: Moziqodo debuts in ch62 with a single fact
    # and a floor of 10. Before the fix he was silently dropped, and
    # world_state.md reported the Chapter-61 world stamped "Chapter 62".
    recent, background, _cutoff, _ = _split(
        tmp_path,
        [("npc_moziqodo", 1, "62-62"), ("npc_bookwyrm", 40, "3-40")],
        background_min_facts=10, recent_window=4)
    assert "npc_moziqodo" in recent
    assert background == ["npc_bookwyrm"]


def test_old_and_sparse_entity_is_dropped(tmp_path):
    # The floor's real job — one-scene noise in the deep past — still works.
    # npc_current anchors `latest` at 62; without it the "old" entities would
    # themselves be the newest thing in the corpus and correctly count as recent.
    recent, background, _cutoff, _ = _split(
        tmp_path,
        [("npc_current", 5, "62-62"), ("npc_walk_on", 1, "3-3"),
         ("npc_recurring", 40, "3-40")],
        background_min_facts=10, recent_window=4)
    assert recent == ["npc_current"]
    assert background == ["npc_recurring"]
    assert "npc_walk_on" not in recent + background


def test_window_zero_keeps_everything(tmp_path):
    # 0 = every chapter is recent, so the floor applies to nothing — the same
    # sense as build_recent_events.py --window 0.
    recent, background, cutoff, _ = _split(
        tmp_path,
        [("npc_walk_on", 1, "3-3"), ("npc_recurring", 40, "3-40")],
        background_min_facts=10, recent_window=0)
    assert cutoff is None
    assert sorted(recent) == ["npc_recurring", "npc_walk_on"]
    assert background == []


def test_missing_chapters_line_keeps_everything_and_is_counted(tmp_path):
    # Recency could not be read, so nothing is deleted on the strength of it.
    paths = [_dossier(tmp_path, "npc_a", 1, chapters=None),
             _dossier(tmp_path, "npc_b", 2, chapters=None)]
    dossiers, n_missing = sws.read_dossiers(paths)
    recent, background, _cutoff = sws.split_dossiers(dossiers, 10, 4)
    assert n_missing == 2
    assert sorted(d.stem for d in recent) == ["npc_a", "npc_b"]
    assert background == []


def test_cutoff_is_relative_to_the_latest_chapter_present(tmp_path):
    _r, _b, cutoff, _ = _split(
        tmp_path, [("npc_a", 1, "1-62")], background_min_facts=10, recent_window=4)
    assert cutoff == 59


def test_recent_sorts_newest_first_background_densest_first(tmp_path):
    recent, background, _cutoff, _ = _split(
        tmp_path,
        [("npc_old_dense", 90, "2-10"), ("npc_old_denser", 99, "2-9"),
         ("npc_ch60", 5, "60-60"), ("npc_ch62", 1, "62-62")],
        background_min_facts=10, recent_window=4)
    assert recent == ["npc_ch62", "npc_ch60"]        # newest touched leads
    assert background == ["npc_old_denser", "npc_old_dense"]  # densest leads


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


# ── --batch: routes the synthesis call through run_single_batch ─────────────
# Single-call CLI per contracts/cli-batch-flag.md: the render/grouping above
# is deterministic (no LLM); only the final synthesis call is batchable.

class FakeStreamAPI:
    def __init__(self):
        self.calls = []

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model, "kwargs": kwargs})
        return "## NPCs\n\n**Daz**\n"


class FakeRunSingleBatch:
    def __init__(self):
        self.calls = []

    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens})
        return "## NPCs\n\n**Daz** (batched)\n"


class FailingRunSingleBatch:
    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        raise RuntimeError("batch item 'single' did not succeed: status=errored error=boom")


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(sws, "stream_api", fake)
    monkeypatch.setattr(sws, "client_from_args", lambda *a, **kw: None)
    return fake


@pytest.fixture
def fake_run_single_batch(monkeypatch):
    fake = FakeRunSingleBatch()
    monkeypatch.setattr(sws, "run_single_batch", fake)
    monkeypatch.setattr(sws, "client_from_args", lambda *a, **kw: None)
    return fake


def _write_corpus(tmp_path: Path) -> Path:
    p = tmp_path / "merged.json"
    p.write_text(json.dumps([
        {"type": "npc", "subject": "Daz", "fact": "Daz acts.", "source_quote": ""},
    ]), encoding="utf-8")
    return p


def test_default_path_uses_stream_api_unchanged(monkeypatch, fake_stream_api, tmp_path):
    corpus = _write_corpus(tmp_path)
    output = tmp_path / "world_state.md"
    monkeypatch.setattr(sys, "argv", [
        "synthesise_world_state.py", "--corpus", str(corpus), "--output", str(output),
    ])
    sws.main()

    assert len(fake_stream_api.calls) == 1
    assert fake_stream_api.calls[0]["kwargs"].get("max_tokens") == 16000  # default --max-tokens
    assert output.exists()


def test_batch_flag_routes_through_run_single_batch(monkeypatch, fake_run_single_batch, tmp_path):
    corpus = _write_corpus(tmp_path)
    output = tmp_path / "world_state.md"
    monkeypatch.setattr(sys, "argv", [
        "synthesise_world_state.py", "--corpus", str(corpus), "--output", str(output),
        "--batch",
    ])
    sws.main()

    assert len(fake_run_single_batch.calls) == 1
    assert fake_run_single_batch.calls[0]["max_tokens"] == 16000
    assert "(batched)" in output.read_text(encoding="utf-8")


def test_batch_flag_honors_custom_max_tokens(monkeypatch, fake_run_single_batch, tmp_path):
    corpus = _write_corpus(tmp_path)
    output = tmp_path / "world_state.md"
    monkeypatch.setattr(sys, "argv", [
        "synthesise_world_state.py", "--corpus", str(corpus), "--output", str(output),
        "--batch", "--max-tokens", "32000",
    ])
    sws.main()

    assert fake_run_single_batch.calls[0]["max_tokens"] == 32000


def test_batch_failure_exits_nonzero(monkeypatch, tmp_path, capsys):
    corpus = _write_corpus(tmp_path)
    output = tmp_path / "world_state.md"
    monkeypatch.setattr(sws, "run_single_batch", FailingRunSingleBatch())
    monkeypatch.setattr(sws, "client_from_args", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", [
        "synthesise_world_state.py", "--corpus", str(corpus), "--output", str(output),
        "--batch",
    ])

    with pytest.raises(SystemExit) as exc_info:
        sws.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Error: batch item failed:" in err
    assert not output.exists()
