"""Tests for facts_to_state.py — the per-entity fact-aggregation bundler.

Covers the deterministic Stage-1 logic (bundling, chapter ordering, type/floor
selection, render) where the precision lives. No API / no model calls.
"""
import argparse
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipelines.ensemble import facts_to_state as fts  # noqa: E402
from campaignlib import add_backend_args  # noqa: E402
from campaignlib.registry import load_registry  # noqa: E402
from pipelines.ensemble.synthesise_world_state import (  # noqa: E402
    read_dossiers, split_dossiers,
)


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


def test_select_waives_min_facts_for_known_names():
    bundles = {
        "npc\x00daz": _bundle("npc", "daz", [(i, _fact("npc", "Daz", f"f{i}"), "Daz") for i in range(1, 6)]),
        "npc\x00bit": _bundle("npc", "bit", [(1, _fact("npc", "Bit", "z"), "Bit")]),
        "npc\x00stray": _bundle("npc", "stray", [(1, _fact("npc", "Stray", "z"), "Stray")]),
    }
    # "bit" is a registry/known-names entry with only 1 fact — included anyway.
    # "stray" isn't in known_names — still dropped by the min_facts floor.
    selected = fts.select(bundles, min_facts=3, only=None, top=None,
                          known_names={"bit"})
    assert {b.display for b in selected} == {"Daz", "Bit"}


def test_select_does_not_waive_min_facts_for_excluded_names():
    b = _bundle("npc", "bit", [(1, _fact("npc", "Bit", "z"), "Bit")])
    b.known = False  # forced anonymous via --exclude-names, despite key overlap
    bundles = {"npc\x00bit\x00unknown": b}
    selected = fts.select(bundles, min_facts=3, only=None, top=None,
                          known_names={"bit"})
    assert selected == []


def test_known_only_exempts_occurrence_scoped_types():
    """--known-only strips anonymous npc/faction bundles (generic mob noise),
    but object- and monster-typed bundles are occurrence-scoped: every distinct
    encounter is tracked, so an anonymous (known=False) object or monster bundle
    must survive the filter. Sibling to
    test_select_does_not_waive_min_facts_for_excluded_names."""
    def _anon(type_, key):
        b = _bundle(type_, key, [(1, _fact(type_, key, f"f{i}"), key) for i in range(3)])
        b.known = False
        return b

    bundles = {
        "object\x00spores\x00cave": _anon("object", "spores"),
        "monster\x00gray_ooze\x00sewer": _anon("monster", "gray ooze"),
        "npc\x00bandit\x00road": _anon("npc", "bandit"),
        "faction\x00cult\x00keep": _anon("faction", "cult"),
    }
    selected = fts.select(bundles, min_facts=3, only=None, top=None, known_only=True)
    types = {b.type for b in selected}
    assert types == {"object", "monster"}          # object/monster survive; npc/faction stripped


def test_known_only_exemption_still_respects_min_facts():
    """The occurrence-scoped exemption bypasses the known/anonymous filter only,
    not the --min-facts floor: an anonymous object bundle below the floor is
    still dropped."""
    b = _bundle("object", "spores", [(1, _fact("object", "Spores", "f0"), "Spores")])
    b.known = False
    selected = fts.select({"object\x00spores\x00cave": b},
                          min_facts=3, only=None, top=None, known_only=True)
    assert selected == []


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


def _write_faction_corpus(tmp_path):
    """Two chapters, same FACTION ("Zhentarim"), each with a DIFFERENT dominant
    location — the shape that makes an "unknown" entity fragment into one
    location-scoped bundle per chapter (see load_bundles).

    A non-npc type is deliberate: main's "a named npc is known by default"
    heuristic would otherwise mask this fragmentation for npcs. The
    disagreeing-stores bug is general, so we demonstrate it on a faction,
    where that heuristic does not apply."""
    (tmp_path / "gen-ch01").mkdir()
    (tmp_path / "gen-ch02").mkdir()
    (tmp_path / "gen-ch01" / "merged.json").write_text(json.dumps([
        _fact("faction", "Zhentarim", "held the captives at the outpost"),
        _fact("location", "Velkynvelve", "the outpost holding the captives"),
    ]), encoding="utf-8")
    (tmp_path / "gen-ch02" / "merged.json").write_text(json.dumps([
        _fact("faction", "Zhentarim", "marched its forces east"),
        _fact("location", "Blingdenstone", "the ruined gnome city"),
    ]), encoding="utf-8")
    return list(tmp_path.glob("gen-ch*/merged.json"))


def test_legacy_aliases_and_known_names_disagreement_fragments_entity(tmp_path):
    """Two independently hand-curated stores disagreeing IS the fragmentation
    bug: aliases.json canonicalises "Zhentarim" -> "The Black Network", but the
    inventory-derived known_names only knows the bare "Zhentarim" spelling —
    not the alias's canonical form. The canonicalised subject then looks
    "unknown" and gets split into one bundle per chapter's location.

    Demonstrated on a faction, not an npc: main's "named npc is known by
    default" heuristic masks this for npcs, but the disagreement bug is
    general — it bites every type whose canonical form misses known_names."""
    paths = _write_faction_corpus(tmp_path)
    aliases = {"Zhentarim": "The Black Network"}
    known_names = {fts._norm_subject("Zhentarim")}
    bundles = fts.load_bundles(paths, aliases, types=["faction"], known_names=known_names)
    faction_bundles = [b for b in bundles.values() if b.type == "faction"]
    assert len(faction_bundles) == 2                   # fragmented, one per location
    for b in faction_bundles:
        assert getattr(b, "known") is False
        assert b.display.startswith("The Black Network (")
    assert sum(len(b.facts) for b in faction_bundles) == 2  # same 2 facts, just split


def test_registry_aliases_and_known_names_agree_no_fragmentation(tmp_path):
    """Same corpus, same load_bundles code path — only the source differs.
    A registry entity with its alias listed means alias_to_canonical() and
    known_names() can never disagree, so the entity stays one bundle."""
    paths = _write_faction_corpus(tmp_path)
    registry_path = tmp_path / "entity_registry.yaml"
    registry_path.write_text(
        "version: 1\n"
        "entities:\n"
        "  - name: The Black Network\n"
        "    type: faction\n"
        "    aliases: [Zhentarim]\n",
        encoding="utf-8",
    )
    reg = load_registry(registry_path)
    aliases = reg.alias_to_canonical()
    known_names = reg.known_names()
    bundles = fts.load_bundles(paths, aliases, types=["faction"], known_names=known_names)
    faction_bundles = [b for b in bundles.values() if b.type == "faction"]
    assert len(faction_bundles) == 1                   # no fragmentation
    b = faction_bundles[0]
    assert getattr(b, "known") is True
    assert b.display == "The Black Network"
    assert len(b.facts) == 2


def test_spores_object_fragments_per_location_and_survives_known_only(tmp_path):
    """Regression for the object/subject-collision bug shape.

    Two `object` facts share the literal subject "Spores" but occur in
    different chapters with different dominant locations. A registry holds an
    unrelated `event`-typed entity "spores of Zuggtmoy" — mirroring the real
    collision. The event's first token ("spores") must NOT be derived into
    known_names/aliases (registry.py excludes type=="event" from first-token
    derivation), so "Spores" stays anonymous and fragments into one
    location-scoped object bundle per chapter. Both object bundles must then
    survive select(known_only=True), because object is occurrence-scoped."""
    (tmp_path / "gen-ch01").mkdir()
    (tmp_path / "gen-ch02").mkdir()
    (tmp_path / "gen-ch01" / "merged.json").write_text(json.dumps([
        _fact("object", "Spores", "a cluster of spores clung to the wall"),
        _fact("location", "Neverlight Grove", "the myconid colony"),
    ]), encoding="utf-8")
    (tmp_path / "gen-ch02" / "merged.json").write_text(json.dumps([
        _fact("object", "Spores", "spores drifted through the tunnel"),
        _fact("location", "Araumycos", "the vast fungal expanse"),
    ]), encoding="utf-8")
    paths = list(tmp_path.glob("gen-ch*/merged.json"))

    registry_path = tmp_path / "entity_registry.yaml"
    registry_path.write_text(
        "version: 1\n"
        "entities:\n"
        "  - name: spores of Zuggtmoy\n"
        "    type: event\n",
        encoding="utf-8",
    )
    reg = load_registry(registry_path)

    bundles = fts.load_bundles(
        paths, reg.alias_to_canonical(), types=["object", "location"],
        known_names=reg.known_names(),
    )
    object_bundles = [b for b in bundles.values() if b.type == "object"]
    assert len(object_bundles) == 2                     # two separate location-scoped bundles
    assert all(getattr(b, "known") is False for b in object_bundles)
    # distinct location-scoped keys, not one merged bundle
    assert len({k for k, b in bundles.items() if b.type == "object"}) == 2

    # min_facts=1 so the 1-fact-per-location bundles aren't dropped by the floor;
    # the point of this assertion is the known_only exemption, not the floor.
    selected = fts.select(bundles, min_facts=1, only=None, top=None, known_only=True)
    selected_objects = [b for b in selected if b.type == "object"]
    assert len(selected_objects) == 2                   # both survive --known-only


def test_main_rejects_explicit_registry_combined_with_legacy_aliases(tmp_path, monkeypatch):
    (tmp_path / "gen-ch01").mkdir()
    (tmp_path / "gen-ch01" / "merged.json").write_text("[]", encoding="utf-8")
    registry_path = tmp_path / "entity_registry.yaml"
    registry_path.write_text("version: 1\nentities: []\n", encoding="utf-8")
    argv = [
        "facts_to_state.py",
        "--corpus", str(tmp_path / "gen-ch*" / "merged.json"),
        "--list",
        "--registry", str(registry_path),
        "--aliases", "some_aliases.json",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit):
        fts.main()


def test_dossier_frontmatter_round_trips_into_the_reader(tmp_path):
    """write_dossier emits `n_facts` AND `chapters: lo-hi`; the reader consumes
    both. Issue #194 was exactly this contract half-honoured — the chapter span
    was computed, serialised and then ignored, so a frequency floor stood in for
    a sequence the pipeline already knew. Pinned against real writer output
    rather than hand-rolled frontmatter, so a change to either side breaks here.
    """
    old = _bundle("npc", "bookwyrm", [
        (3, _fact("npc", "Bookwyrm", "early"), "Bookwyrm"),
        (40, _fact("npc", "Bookwyrm", "later"), "Bookwyrm"),
    ])
    debut = _bundle("npc", "moziqodo", [
        (62, _fact("npc", "Moziqodo", "dies in the rotunda"), "Moziqodo"),
    ])
    for b in (old, debut):
        fts.write_dossier(tmp_path, b, "body")

    dossiers, n_missing = read_dossiers(sorted(tmp_path.glob("*.md")))
    assert n_missing == 0
    by_stem = {d.stem: d for d in dossiers}
    assert by_stem["npc_bookwyrm"].n_facts == 2
    assert by_stem["npc_bookwyrm"].last_chapter == 40
    assert by_stem["npc_moziqodo"].last_chapter == 62

    # A one-fact debut in the newest chapter outranks a denser but stale entity.
    recent, background, cutoff = split_dossiers(
        dossiers, background_min_facts=2, recent_window=4)
    assert cutoff == 59
    assert [d.stem for d in recent] == ["npc_moziqodo"]
    assert [d.stem for d in background] == ["npc_bookwyrm"]
    assert "body" in by_stem["npc_moziqodo"].text


# ── --batch (spec 004-claude-api-batch, T021) ────────────────────────────────

def test_batch_flag_wording_matches_registrar():
    """facts_to_state hand-rolls --backend/--endpoints instead of calling
    add_backend_args (it needs a plural --endpoints, which would collide with
    the registrar's singular --endpoint) — but --batch must still be spelled,
    defaulted, and documented identically (FR-001/FR-002), so this syncs the
    two sources of truth directly rather than eyeballing it."""
    registrar_parser = argparse.ArgumentParser()
    registrar_parser.add_argument("--model", default="claude-sonnet-4-6")
    add_backend_args(registrar_parser)
    registrar_action = next(
        a for a in registrar_parser._actions if "--batch" in a.option_strings)

    fts_parser = fts.build_parser()
    fts_action = next(
        a for a in fts_parser._actions if "--batch" in a.option_strings)

    assert fts_action.help == registrar_action.help
    assert fts_action.default == registrar_action.default is False
    assert fts_action.const == registrar_action.const is True  # store_true


def test_batch_defaults_false_and_toggles_on():
    p = fts.build_parser()
    args = p.parse_args(["--corpus", "x", "--list"])
    assert args.batch is False
    args = p.parse_args(["--corpus", "x", "--list", "--batch"])
    assert args.batch is True


# ── check_batch_backend: fires once, up front, before any work ───────────────

def test_check_batch_backend_noop_when_batch_absent():
    ns = argparse.Namespace(batch=False, backend="dgx")
    fts.check_batch_backend(ns)  # must not raise regardless of backend


def test_check_batch_backend_allows_anthropic(monkeypatch):
    monkeypatch.delenv("CG_BACKEND", raising=False)
    ns = argparse.Namespace(batch=True, backend="anthropic")
    fts.check_batch_backend(ns)  # must not raise


@pytest.mark.parametrize("backend", ["dgx", "openrouter", "claude-code"])
def test_check_batch_backend_rejects_non_anthropic(backend, monkeypatch):
    monkeypatch.delenv("CG_BACKEND", raising=False)
    ns = argparse.Namespace(batch=True, backend=backend)
    with pytest.raises(SystemExit) as exc_info:
        fts.check_batch_backend(ns)
    msg = str(exc_info.value)
    assert "--batch requires the Claude API backend (--backend anthropic)" in msg
    assert f"backend '{backend}' has no batch support" in msg


def test_check_batch_backend_rejects_via_cg_backend_env(monkeypatch):
    """--backend anthropic (the default) + CG_BACKEND=openrouter must still
    be rejected — env-driven resolution, not just the explicit flag."""
    monkeypatch.setenv("CG_BACKEND", "openrouter")
    ns = argparse.Namespace(batch=True, backend="anthropic")
    with pytest.raises(SystemExit) as exc_info:
        fts.check_batch_backend(ns)
    assert "backend 'openrouter' has no batch support" in str(exc_info.value)


def test_main_rejects_batch_before_any_corpus_or_client_work(tmp_path, monkeypatch):
    """End-to-end: --batch + a non-anthropic backend must abort before
    expand_globs (corpus loading) or client construction — not merely before
    the worker threads. Trips an assertion if either runs."""
    def _boom_globs(*a, **kw):
        raise AssertionError("expand_globs must not run before the --batch rejection")

    def _boom_client(*a, **kw):
        raise AssertionError("client_from_args must not run before the --batch rejection")

    monkeypatch.setattr(fts, "expand_globs", _boom_globs)
    monkeypatch.setattr(fts, "client_from_args", _boom_client)
    monkeypatch.delenv("CG_BACKEND", raising=False)
    monkeypatch.setattr(sys, "argv", [
        "facts_to_state.py",
        "--corpus", str(tmp_path / "gen-ch*" / "merged.json"),
        "--out-dir", str(tmp_path / "out"),
        "--backend", "dgx",
        "--batch",
    ])
    with pytest.raises(SystemExit) as exc_info:
        fts.main()
    assert "backend 'dgx' has no batch support" in str(exc_info.value)


# ── batch aggregation path: grouped submission + partial failure ────────────

def _write_two_npc_corpus(tmp_path):
    (tmp_path / "gen-ch01").mkdir()
    (tmp_path / "gen-ch01" / "merged.json").write_text(json.dumps([
        _fact("npc", "Alpha", "did a thing"),
        _fact("npc", "Beta", "did another thing"),
    ]), encoding="utf-8")
    return tmp_path


class FakeRunBatch:
    """Records the single grouped call and returns caller-controlled records."""

    def __init__(self, records_by_id):
        self.calls = []
        self.records_by_id = records_by_id

    def __call__(self, client, requests, **kwargs):
        self.calls.append({"client": client, "requests": requests, "kwargs": kwargs})
        return {r["custom_id"]: self.records_by_id[r["custom_id"]] for r in requests}


def _succeeded(text):
    return {"status": "succeeded", "text": text, "stop_reason": "end_turn",
            "error": None, "usage": None}


def _errored(error):
    return {"status": "errored", "text": None, "stop_reason": None,
            "error": error, "usage": None}


def test_batch_mode_groups_per_unit_calls_into_one_submission(tmp_path, monkeypatch):
    _write_two_npc_corpus(tmp_path)
    out_dir = tmp_path / "out"
    fake_run_batch = FakeRunBatch({
        "npc_alpha": _succeeded("ALPHA DOSSIER BODY"),
        "npc_beta": _succeeded("BETA DOSSIER BODY"),
    })
    monkeypatch.setattr(fts, "run_batch", fake_run_batch)
    monkeypatch.setattr(fts, "client_from_args", lambda *a, **kw: "FAKE_CLIENT")
    monkeypatch.setattr(sys, "argv", [
        "facts_to_state.py",
        "--corpus", str(tmp_path / "gen-ch*" / "merged.json"),
        "--out-dir", str(out_dir),
        "--min-facts", "1",
        "--batch",
    ])
    fts.main()

    # One grouped submission, one request per unit (not one call per entity).
    assert len(fake_run_batch.calls) == 1
    requests = fake_run_batch.calls[0]["requests"]
    assert {r["custom_id"] for r in requests} == {"npc_alpha", "npc_beta"}
    assert fake_run_batch.calls[0]["client"] == "FAKE_CLIENT"

    assert (out_dir / "npc_alpha.md").read_text(encoding="utf-8").strip().endswith(
        "ALPHA DOSSIER BODY")
    assert (out_dir / "npc_beta.md").read_text(encoding="utf-8").strip().endswith(
        "BETA DOSSIER BODY")


def test_batch_mode_partial_failure_writes_successes_and_exits_nonzero(
    tmp_path, monkeypatch, capsys
):
    _write_two_npc_corpus(tmp_path)
    out_dir = tmp_path / "out"
    fake_run_batch = FakeRunBatch({
        "npc_alpha": _succeeded("ALPHA DOSSIER BODY"),
        "npc_beta": _errored("boom"),
    })
    monkeypatch.setattr(fts, "run_batch", fake_run_batch)
    monkeypatch.setattr(fts, "client_from_args", lambda *a, **kw: "FAKE_CLIENT")
    monkeypatch.setattr(sys, "argv", [
        "facts_to_state.py",
        "--corpus", str(tmp_path / "gen-ch*" / "merged.json"),
        "--out-dir", str(out_dir),
        "--min-facts", "1",
        "--batch",
    ])
    with pytest.raises(SystemExit) as exc_info:
        fts.main()
    assert exc_info.value.code != 0

    # Successful item's dossier is written; the errored one's is not.
    assert (out_dir / "npc_alpha.md").exists()
    assert not (out_dir / "npc_beta.md").exists()

    stderr = capsys.readouterr().err
    assert "FAILED npc_beta: errored boom" in stderr


def test_batch_mode_all_cached_submits_nothing(tmp_path, monkeypatch):
    """Resumable behavior carries over to batch mode: entities whose dossier
    already exists on disk are excluded from the request set, same as the
    threaded path's skip-if-exists check — an empty todo list must not call
    run_batch at all (submit_batch raises on an empty requests list)."""
    _write_two_npc_corpus(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    (out_dir / "npc_alpha.md").write_text("already here", encoding="utf-8")
    (out_dir / "npc_beta.md").write_text("already here", encoding="utf-8")

    def _boom(*a, **kw):
        raise AssertionError("run_batch must not be called when nothing is missing")

    monkeypatch.setattr(fts, "run_batch", _boom)
    monkeypatch.setattr(fts, "client_from_args", lambda *a, **kw: "FAKE_CLIENT")
    monkeypatch.setattr(sys, "argv", [
        "facts_to_state.py",
        "--corpus", str(tmp_path / "gen-ch*" / "merged.json"),
        "--out-dir", str(out_dir),
        "--min-facts", "1",
        "--batch",
    ])
    fts.main()  # must return normally, not raise


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
