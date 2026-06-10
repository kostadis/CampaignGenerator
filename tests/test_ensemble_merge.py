"""Unit tests for ensemble_merge.py.

Cover the deterministic merge logic and the manifest-driven loading that the
decoupled merge step relies on. The embedding path is exercised with a stubbed
`embed_texts` so no embed server is needed.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ensemble_merge as em  # noqa: E402


# ── subject-keyed merge ──────────────────────────────────────────────────────

def test_merge_facts_dedups_within_subject_and_unions_passes():
    pass_outputs = {
        "a#1": [{"type": "npc", "subject": "Daz", "fact": "Daz is brave.",
                 "source_quote": "q1"}],
        "b#1": [
            {"type": "npc", "subject": "Daz", "fact": "Daz is brave.",
             "source_quote": "q1-longer"},
            {"type": "event", "subject": "Fight", "fact": "A fight happened.",
             "source_quote": ""},
        ],
    }
    merged = em.merge_facts(pass_outputs, similarity=0.85)
    by = {(f["type"], f["subject"]): f for f in merged}
    assert len(merged) == 2

    daz = by[("npc", "Daz")]
    assert daz["fact"] == "Daz is brave."
    assert daz["source_quote"] == "q1-longer"          # longest quote kept
    assert set(daz["passes"]) == {"a#1", "b#1"}         # provenance unioned

    assert by[("event", "Fight")]["passes"] == ["b#1"]


def test_merge_facts_quote_verified_travels_with_kept_quote():
    # The flag describes the quote, so when a longer quote replaces a shorter
    # one its verification status must replace too — in both directions.
    pass_outputs = {
        "a#1": [{"type": "npc", "subject": "Daz", "fact": "Daz is brave.",
                 "source_quote": "short", "quote_verified": True}],
        "b#1": [{"type": "npc", "subject": "Daz", "fact": "Daz is brave.",
                 "source_quote": "much longer stitched quote",
                 "quote_verified": False}],
    }
    merged = em.merge_facts(pass_outputs, similarity=0.85)
    assert len(merged) == 1
    assert merged[0]["source_quote"] == "much longer stitched quote"
    assert merged[0]["quote_verified"] is False


def test_merge_facts_keeps_distinct_facts_under_threshold():
    pass_outputs = {"a#1": [
        {"type": "npc", "subject": "Daz", "fact": "Daz is brave.", "source_quote": ""},
        {"type": "npc", "subject": "Daz", "fact": "Daz likes cheese.", "source_quote": ""},
    ]}
    merged = em.merge_facts(pass_outputs, similarity=0.85)
    assert len(merged) == 2


def test_merge_facts_keeps_longest_fact_when_collapsing():
    pass_outputs = {
        "a#1": [{"type": "npc", "subject": "Daz", "fact": "Daz is very very brave",
                 "source_quote": ""}],
        "b#1": [{"type": "npc", "subject": "Daz", "fact": "Daz is very very brave.",
                 "source_quote": ""}],
    }
    merged = em.merge_facts(pass_outputs, similarity=0.85)
    assert len(merged) == 1
    assert merged[0]["fact"] == "Daz is very very brave."   # the longer one


def test_merge_facts_is_sorted_deterministically():
    pass_outputs = {"a#1": [
        {"type": "npc", "subject": "Zed", "fact": "z", "source_quote": ""},
        {"type": "event", "subject": "Alpha", "fact": "a", "source_quote": ""},
        {"type": "npc", "subject": "Abe", "fact": "b", "source_quote": ""},
    ]}
    merged = em.merge_facts(pass_outputs, similarity=0.85)
    keys = [(f["type"], f["subject"]) for f in merged]
    # sorted by (type, normalized subject, fact)
    assert keys == [("event", "Alpha"), ("npc", "Abe"), ("npc", "Zed")]


# ── embedding merge (stubbed embed server) ───────────────────────────────────

def test_merge_facts_embed_clusters_cross_subject(monkeypatch):
    np = pytest.importorskip("numpy")
    # Same vector for the two "same event under different subject labels"; an
    # orthogonal vector for the unrelated fact.
    vecs = {
        "The keeper died.": [1.0, 0.0, 0.0],
        "Keeper has died.": [1.0, 0.0, 0.0],
        "A cat meowed.":    [0.0, 1.0, 0.0],
    }

    def fake_embed(texts, endpoint, model, batch=256):
        return np.asarray([vecs[t] for t in texts], dtype="float32")

    monkeypatch.setattr(em, "embed_texts", fake_embed)

    pass_outputs = {
        "a#1": [
            {"type": "npc", "subject": "Keeper", "fact": "The keeper died.",
             "source_quote": "short"},
            {"type": "npc", "subject": "Cat", "fact": "A cat meowed.",
             "source_quote": ""},
        ],
        "b#1": [
            {"type": "npc", "subject": "Janussi", "fact": "Keeper has died.",
             "source_quote": "a longer quote"},
        ],
    }
    merged = em.merge_facts_embed(pass_outputs, "http://stub", "stub-model",
                                  threshold=0.93)
    assert len(merged) == 2                              # keeper+janussi collapse; cat separate

    big = max(merged, key=lambda f: len(f["variants"]))
    assert set(big["variants"]) == {"The keeper died.", "Keeper has died."}
    assert set(big["subjects"]) == {"Keeper", "Janussi"}
    assert set(big["passes"]) == {"a#1", "b#1"}
    assert big["source_quote"] == "a longer quote"      # longest quote kept

    small = min(merged, key=lambda f: len(f["variants"]))
    assert small["variants"] == ["A cat meowed."]


def test_merge_facts_embed_keeps_distinct_below_threshold(monkeypatch):
    np = pytest.importorskip("numpy")
    vecs = {"x": [1.0, 0.0], "y": [0.0, 1.0]}

    def fake_embed(texts, endpoint, model, batch=256):
        return np.asarray([vecs[t] for t in texts], dtype="float32")

    monkeypatch.setattr(em, "embed_texts", fake_embed)
    pass_outputs = {"a#1": [
        {"type": "npc", "subject": "A", "fact": "x", "source_quote": ""},
        {"type": "npc", "subject": "B", "fact": "y", "source_quote": ""},
    ]}
    merged = em.merge_facts_embed(pass_outputs, "http://stub", "m", threshold=0.93)
    assert len(merged) == 2


# ── manifest / pass-output loading ───────────────────────────────────────────

def test_load_manifest_missing_exits(tmp_path):
    with pytest.raises(SystemExit):
        em.load_manifest(tmp_path)


def test_load_pass_outputs_roundtrip(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(
        [{"type": "npc", "subject": "X", "fact": "f", "source_quote": ""}]))
    manifest = {"version": 1, "samples": 1, "passes": [
        {"name": "a", "outputs": [{"key": "a#1", "file": "a.json", "n_facts": 1}]}]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    m = em.load_manifest(tmp_path)
    po = em.load_pass_outputs(tmp_path, m)
    assert list(po.keys()) == ["a#1"]
    assert po["a#1"][0]["subject"] == "X"


def test_load_pass_outputs_missing_file_exits(tmp_path):
    manifest = {"passes": [
        {"name": "a", "outputs": [{"key": "a#1", "file": "missing.json"}]}]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(SystemExit):
        em.load_pass_outputs(tmp_path, em.load_manifest(tmp_path))
