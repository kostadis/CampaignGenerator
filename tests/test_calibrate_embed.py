"""Unit tests for calibrate_embed.py (embed-threshold calibration tool).

Everything here runs against a stubbed `embed_texts` — no network call, no
live endpoint. `spark`/`spark2` on :11434 were confirmed unreachable from the
dev machine when this tool was built, so the live-model measurement this tool
exists to produce could not actually be run; these tests only pin the tool's
own logic (bootstrap band assignment, YAML round-trip, precision/recall/F1
math, threshold recommendation, CLI plumbing).
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipelines.ensemble import calibrate_embed as ce  # noqa: E402


def _fake_embed_from(vecs: dict):
    """Build a stub matching ensemble_merge.embed_texts's signature that
    returns pre-normalized vectors for known texts, keyed by exact text."""
    import numpy as np

    def fake(texts, endpoint, model, batch=256):
        arr = np.asarray([vecs[t] for t in texts], dtype="float32")
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms

    return fake


# ── bootstrap_candidates: band assignment ───────────────────────────────────

def test_bootstrap_candidates_buckets_by_cosine_band():
    np = pytest.importorskip("numpy")

    corpus = [
        {"type": "npc", "fact": "The keeper died."},
        {"type": "npc", "fact": "The keeper has died."},   # near-dup of above
        {"type": "npc", "fact": "A cat meowed softly."},    # unrelated
    ]
    vecs = {
        "The keeper died.": [1.0, 0.0, 0.0],
        "The keeper has died.": [0.999, 0.001, 0.0],   # ~1.0 cosine -> clear_dup
        "A cat meowed softly.": [0.0, 1.0, 0.0],        # orthogonal -> clear_distinct
    }
    fake = _fake_embed_from(vecs)

    candidates = ce.bootstrap_candidates(
        corpus, "http://stub", "stub-model", embed_fn=fake,
        sample_size=10, n_per_band=10,
    )
    assert len(candidates["clear_dup"]) == 1
    assert len(candidates["clear_distinct"]) == 2  # keeper-vs-cat, both pairs
    assert candidates["ambiguous"] == []

    dup_pair = candidates["clear_dup"][0]
    assert {dup_pair["a"], dup_pair["b"]} == {
        "The keeper died.", "The keeper has died."}
    assert dup_pair["type"] == "npc"
    assert dup_pair["cosine"] > 0.99


def test_bootstrap_candidates_never_pairs_across_types():
    """embed merge partitions by type; a bootstrap pair the real merge would
    never compare is useless evidence."""
    np = pytest.importorskip("numpy")
    corpus = [
        {"type": "npc", "fact": "same text"},
        {"type": "monster", "fact": "same text"},
    ]
    vecs = {"same text": [1.0, 0.0]}
    fake = _fake_embed_from(vecs)
    candidates = ce.bootstrap_candidates(
        corpus, "http://stub", "m", embed_fn=fake, sample_size=10, n_per_band=10)
    total = sum(len(v) for v in candidates.values())
    assert total == 0  # each type has only 1 fact -> no pairs possible


def test_bootstrap_candidates_skips_facts_without_text():
    np = pytest.importorskip("numpy")
    corpus = [
        {"type": "npc", "fact": "x"},
        {"type": "npc", "fact": ""},   # no text -> excluded entirely
        {"type": "npc"},               # missing key entirely -> excluded
    ]
    fake = _fake_embed_from({"x": [1.0, 0.0]})
    candidates = ce.bootstrap_candidates(
        corpus, "http://stub", "m", embed_fn=fake, sample_size=10, n_per_band=10)
    total = sum(len(v) for v in candidates.values())
    assert total == 0  # only one usable fact in the type -> no pairs


def test_bootstrap_candidates_respects_n_per_band_cap():
    np = pytest.importorskip("numpy")
    texts = [f"fact {i}" for i in range(8)]
    corpus = [{"type": "npc", "fact": t} for t in texts]
    # All orthogonal-ish but identical-direction vectors -> all clear_dup.
    vecs = {t: [1.0, 0.0] for t in texts}
    fake = _fake_embed_from(vecs)
    candidates = ce.bootstrap_candidates(
        corpus, "http://stub", "m", embed_fn=fake, sample_size=10,
        n_per_band=3, seed=1)
    assert len(candidates["clear_dup"]) == 3  # capped, not all 28 pairs


def test_bootstrap_candidates_seed_is_reproducible():
    np = pytest.importorskip("numpy")
    texts = [f"fact {i}" for i in range(6)]
    corpus = [{"type": "npc", "fact": t} for t in texts]
    vecs = {t: [1.0, 0.0] for t in texts}
    fake = _fake_embed_from(vecs)
    a = ce.bootstrap_candidates(corpus, "http://stub", "m", embed_fn=fake,
                                sample_size=10, n_per_band=3, seed=7)
    b = ce.bootstrap_candidates(corpus, "http://stub", "m", embed_fn=fake,
                                sample_size=10, n_per_band=3, seed=7)
    assert a == b


# ── write_skeleton / load_labeled_pairs round-trip ──────────────────────────

def test_write_skeleton_then_load_all_skipped_as_unlabeled(tmp_path, capsys):
    candidates = {
        "clear_dup": [{"a": "x", "b": "y", "type": "npc", "cosine": 0.99}],
        "ambiguous": [],
        "clear_distinct": [],
    }
    out = tmp_path / "skeleton.yaml"
    ce.write_skeleton(out, Path("corpus.json"), "http://stub", "m", candidates)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "label:" in text
    assert "# Embed-threshold calibration pairs" in text  # header present

    # Every pair is unlabeled -> load_labeled_pairs must skip all of them,
    # not crash, and must exit with the "no usable pairs" error.
    with pytest.raises(SystemExit):
        ce.load_labeled_pairs(out)
    err = capsys.readouterr().err
    assert "no usable labeled pairs" in err


def test_write_skeleton_hand_labeled_round_trips(tmp_path):
    """Simulates a human filling in the labels after --bootstrap, then the
    file being consumed by --pairs."""
    candidates = {
        "clear_dup": [{"a": "Keeper died.", "b": "Keeper has died.",
                       "type": "npc", "cosine": 0.98}],
        "ambiguous": [],
        "clear_distinct": [{"a": "Keeper died.", "b": "A cat meowed.",
                            "type": "npc", "cosine": 0.1}],
    }
    out = tmp_path / "skeleton.yaml"
    ce.write_skeleton(out, Path("corpus.json"), "http://stub", "m", candidates)

    text = out.read_text(encoding="utf-8")
    text = text.replace("label: null", "label: dup", 1)
    text = text.replace("label: null", "label: distinct", 1)
    out.write_text(text, encoding="utf-8")

    pairs = ce.load_labeled_pairs(out)
    assert len(pairs) == 2
    labels = {p["label"] for p in pairs}
    assert labels == {"dup", "distinct"}


# ── load_labeled_pairs: schema tolerance ────────────────────────────────────

def test_load_labeled_pairs_accepts_bare_list(tmp_path):
    yaml_text = """\
- a: "one"
  b: "two"
  label: dup
- a: "three"
  b: "four"
  label: distinct
"""
    p = tmp_path / "pairs.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    pairs = ce.load_labeled_pairs(p)
    assert len(pairs) == 2


def test_load_labeled_pairs_accepts_pairs_key_wrapper(tmp_path):
    yaml_text = """\
model: qwen3-embedding:0.6b
pairs:
  - a: "one"
    b: "two"
    label: dup
"""
    p = tmp_path / "pairs.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    pairs = ce.load_labeled_pairs(p)
    assert len(pairs) == 1


def test_load_labeled_pairs_skips_missing_or_bad_label(tmp_path, capsys):
    yaml_text = """\
pairs:
  - a: "one"
    b: "two"
    label: dup
  - a: "three"
    b: "four"
    label: null
  - a: "five"
    b: "six"
    label: maybe
"""
    p = tmp_path / "pairs.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    pairs = ce.load_labeled_pairs(p)
    assert len(pairs) == 1
    assert "2 pair(s) skipped" in capsys.readouterr().err


def test_load_labeled_pairs_skips_missing_a_or_b(tmp_path, capsys):
    yaml_text = """\
pairs:
  - a: "one"
    label: dup
  - a: "three"
    b: "four"
    label: distinct
"""
    p = tmp_path / "pairs.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    pairs = ce.load_labeled_pairs(p)
    assert len(pairs) == 1
    assert pairs[0]["label"] == "distinct"


def test_load_labeled_pairs_not_a_list_exits(tmp_path):
    p = tmp_path / "pairs.yaml"
    p.write_text("just: a scalar mapping\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        ce.load_labeled_pairs(p)


def test_load_labeled_pairs_empty_exits(tmp_path):
    p = tmp_path / "pairs.yaml"
    p.write_text("pairs: []\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        ce.load_labeled_pairs(p)


# ── compute_pair_cosines ─────────────────────────────────────────────────────

def test_compute_pair_cosines_matches_known_vectors():
    pairs = [
        {"a": "x", "b": "y", "label": "distinct", "type": None},
        {"a": "x", "b": "x2", "label": "dup", "type": None},
    ]
    vecs = {"x": [1.0, 0.0], "x2": [1.0, 0.0], "y": [0.0, 1.0]}
    fake = _fake_embed_from(vecs)
    scored = ce.compute_pair_cosines(pairs, "http://stub", "m", embed_fn=fake)
    by_label = {p["label"]: p["cosine"] for p in scored}
    assert by_label["distinct"] == pytest.approx(0.0, abs=1e-6)
    assert by_label["dup"] == pytest.approx(1.0, abs=1e-6)


def test_compute_pair_cosines_embeds_each_distinct_text_once():
    """Repeated fact text across pairs (a shared anchor fact, say) should be
    embedded once, not once per pair — cheap and avoids inconsistent vectors
    for the same string within one run."""
    calls = []

    def counting_embed(texts, endpoint, model, batch=256):
        import numpy as np
        calls.append(list(texts))
        vecs = {"x": [1.0, 0.0], "y": [0.0, 1.0], "z": [1.0, 1.0]}
        return np.asarray([vecs[t] for t in texts], dtype="float32")

    pairs = [
        {"a": "x", "b": "y", "label": "distinct", "type": None},
        {"a": "x", "b": "z", "label": "dup", "type": None},
    ]
    ce.compute_pair_cosines(pairs, "http://stub", "m", embed_fn=counting_embed)
    assert len(calls) == 1
    assert sorted(calls[0]) == ["x", "y", "z"]  # 'x' embedded once, not twice


# ── cosine_distribution ──────────────────────────────────────────────────────

def test_cosine_distribution_min_median_max_odd():
    pairs = [{"label": "dup", "cosine": c} for c in [0.9, 0.95, 0.99]]
    dist = ce.cosine_distribution(pairs, "dup")
    assert dist == {"n": 3, "min": 0.9, "median": 0.95, "max": 0.99}


def test_cosine_distribution_median_even_count():
    pairs = [{"label": "dup", "cosine": c} for c in [0.8, 0.9, 0.95, 1.0]]
    dist = ce.cosine_distribution(pairs, "dup")
    assert dist["median"] == pytest.approx((0.9 + 0.95) / 2)


def test_cosine_distribution_none_when_label_absent():
    pairs = [{"label": "dup", "cosine": 0.9}]
    assert ce.cosine_distribution(pairs, "distinct") is None


# ── sweep_thresholds ──────────────────────────────────────────────────────

def test_sweep_thresholds_confusion_counts():
    pairs = [
        {"label": "dup", "cosine": 0.95},
        {"label": "dup", "cosine": 0.85},
        {"label": "distinct", "cosine": 0.80},
        {"label": "distinct", "cosine": 0.60},
    ]
    sweep = ce.sweep_thresholds(pairs, 0.90, 0.90, 0.01)
    assert len(sweep) == 1
    r = sweep[0]
    # threshold 0.90: dup@0.95 predicted dup (tp), dup@0.85 predicted distinct (fn)
    # distinct@0.80 predicted distinct (tn), distinct@0.60 predicted distinct (tn)
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (1, 0, 1, 2)
    assert r["precision"] == 1.0
    assert r["recall"] == 0.5


def test_sweep_thresholds_precision_none_when_nothing_predicted_positive():
    pairs = [{"label": "dup", "cosine": 0.10}, {"label": "distinct", "cosine": 0.05}]
    sweep = ce.sweep_thresholds(pairs, 0.99, 0.99, 0.01)
    r = sweep[0]
    assert r["tp"] == 0 and r["fp"] == 0
    assert r["precision"] is None
    assert r["f1"] == 0.0


def test_sweep_thresholds_covers_full_range_inclusive():
    pairs = [{"label": "dup", "cosine": 0.5}]
    sweep = ce.sweep_thresholds(pairs, 0.0, 0.10, 0.05)
    thresholds = [r["threshold"] for r in sweep]
    assert thresholds == [0.0, 0.05, 0.10]


# ── recommend_threshold ──────────────────────────────────────────────────

def test_recommend_threshold_picks_max_f1():
    sweep = [
        {"threshold": 0.80, "f1": 0.70, "precision": 0.6, "recall": 0.9},
        {"threshold": 0.90, "f1": 0.95, "precision": 0.95, "recall": 0.95},
        {"threshold": 0.95, "f1": 0.60, "precision": 1.0, "recall": 0.4},
    ]
    assert ce.recommend_threshold(sweep)["threshold"] == 0.90


def test_recommend_threshold_ties_break_toward_higher_threshold():
    sweep = [
        {"threshold": 0.80, "f1": 0.90, "precision": 0.9, "recall": 0.9},
        {"threshold": 0.93, "f1": 0.90, "precision": 0.9, "recall": 0.9},
    ]
    assert ce.recommend_threshold(sweep)["threshold"] == 0.93


# ── print_report smoke test ──────────────────────────────────────────────

def test_print_report_names_endpoint_and_model(capsys):
    pairs = [
        {"label": "dup", "cosine": 0.95}, {"label": "distinct", "cosine": 0.3},
    ]
    sweep = ce.sweep_thresholds(pairs, 0.9, 0.9, 0.01)
    recommended = ce.recommend_threshold(sweep)
    ce.print_report("http://spark:11434", "qwen3-embedding:0.6b", pairs, sweep,
                    recommended)
    out = capsys.readouterr().out
    assert "http://spark:11434" in out
    assert "qwen3-embedding:0.6b" in out
    assert "Recommended threshold" in out
    assert "does not change any default" in out


def test_print_report_reports_clean_gap(capsys):
    pairs = [
        {"label": "dup", "cosine": 0.97}, {"label": "dup", "cosine": 0.98},
        {"label": "distinct", "cosine": 0.5}, {"label": "distinct", "cosine": 0.6},
    ]
    sweep = ce.sweep_thresholds(pairs, 0.9, 0.9, 0.01)
    recommended = ce.recommend_threshold(sweep)
    ce.print_report("http://stub", "m", pairs, sweep, recommended)
    out = capsys.readouterr().out
    assert "gap:      0." in out
    assert "NONE" not in out


def test_print_report_reports_no_gap_on_overlap(capsys):
    pairs = [
        {"label": "dup", "cosine": 0.80}, {"label": "distinct", "cosine": 0.85},
    ]
    sweep = ce.sweep_thresholds(pairs, 0.9, 0.9, 0.01)
    recommended = ce.recommend_threshold(sweep)
    ce.print_report("http://stub", "m", pairs, sweep, recommended)
    out = capsys.readouterr().out
    assert "gap:      NONE" in out


# ── load_corpus ──────────────────────────────────────────────────────────

def test_load_corpus_reads_json_list(tmp_path):
    p = tmp_path / "merged.json"
    p.write_text(json.dumps([{"type": "npc", "fact": "x"}]), encoding="utf-8")
    corpus = ce.load_corpus(p)
    assert corpus == [{"type": "npc", "fact": "x"}]


def test_load_corpus_rejects_non_list(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(SystemExit):
        ce.load_corpus(p)


# ── main(): CLI plumbing, exercised end-to-end with a stubbed embed_texts ──

def test_main_requires_exactly_one_of_bootstrap_or_pairs(monkeypatch):
    monkeypatch.setattr(sys, "argv",
                        ["calibrate_embed", "--embed-endpoint", "http://stub"])
    with pytest.raises(SystemExit):
        ce.main()


def test_main_rejects_both_bootstrap_and_pairs(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", [
        "calibrate_embed", "--embed-endpoint", "http://stub",
        "--bootstrap", "x.json", "--pairs", "y.yaml",
    ])
    with pytest.raises(SystemExit):
        ce.main()


def test_main_requires_embed_endpoint(monkeypatch, tmp_path):
    monkeypatch.delenv("EMBED_ENDPOINT", raising=False)
    p = tmp_path / "pairs.yaml"
    p.write_text("pairs:\n  - a: x\n    b: y\n    label: dup\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv",
                        ["calibrate_embed", "--pairs", str(p)])
    with pytest.raises(SystemExit):
        ce.main()


def test_main_bootstrap_requires_out(monkeypatch, tmp_path):
    corpus = tmp_path / "merged.json"
    corpus.write_text(json.dumps([{"type": "npc", "fact": "x"}]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "calibrate_embed", "--embed-endpoint", "http://stub",
        "--bootstrap", str(corpus),
    ])
    with pytest.raises(SystemExit):
        ce.main()


def test_main_bootstrap_end_to_end_writes_skeleton(monkeypatch, tmp_path, capsys):
    corpus_path = tmp_path / "merged.json"
    corpus_path.write_text(json.dumps([
        {"type": "npc", "fact": "Keeper died."},
        {"type": "npc", "fact": "Keeper has died."},
        {"type": "npc", "fact": "A cat meowed."},
    ]), encoding="utf-8")
    out_path = tmp_path / "skeleton.yaml"

    vecs = {
        "Keeper died.": [1.0, 0.0],
        "Keeper has died.": [0.9999, 0.0001],
        "A cat meowed.": [0.0, 1.0],
    }
    monkeypatch.setattr(ce, "embed_texts", _fake_embed_from(vecs))
    monkeypatch.setattr(sys, "argv", [
        "calibrate_embed", "--embed-endpoint", "http://stub",
        "--embed-model", "stub-model",
        "--bootstrap", str(corpus_path), "--out", str(out_path),
        "--sample-size", "10", "--n-per-band", "10",
    ])
    ce.main()

    assert out_path.exists()
    out = capsys.readouterr().out
    assert "http://stub" in out
    assert "stub-model" in out
    assert "Written:" in out


def test_main_pairs_end_to_end_prints_recommendation(monkeypatch, tmp_path, capsys):
    pairs_path = tmp_path / "pairs.yaml"
    pairs_path.write_text("""\
pairs:
  - a: "Keeper died."
    b: "Keeper has died."
    label: dup
  - a: "Keeper died."
    b: "A cat meowed."
    label: distinct
""", encoding="utf-8")

    vecs = {
        "Keeper died.": [1.0, 0.0],
        "Keeper has died.": [0.99, 0.01],
        "A cat meowed.": [0.0, 1.0],
    }
    monkeypatch.setattr(ce, "embed_texts", _fake_embed_from(vecs))
    monkeypatch.setattr(sys, "argv", [
        "calibrate_embed", "--embed-endpoint", "http://stub",
        "--embed-model", "stub-model",
        "--pairs", str(pairs_path),
        "--threshold-min", "0.5", "--threshold-max", "0.99",
        "--threshold-step", "0.1",
    ])
    ce.main()
    out = capsys.readouterr().out
    assert "Recommended threshold" in out
    assert "stub-model" in out
    assert "http://stub" in out
