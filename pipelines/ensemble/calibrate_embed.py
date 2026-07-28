#!/usr/bin/env python3
"""Calibrate ``ensemble_merge --embed-threshold`` against real fact pairs.

``--embed-threshold 0.93`` was measured on ``nomic-embed-text-v1.5`` (true
duplicates scored ~0.97-0.98, distinct-but-related facts ~0.75-0.78 — 0.93 sits
in the empty gap between them). The embed sidecar has since moved to
``qwen3-embedding:0.6b``, and a three-sample spot check found a true
near-duplicate scoring **0.9103** — *below* 0.93, so it would silently fail to
merge. Three samples is not a calibration; this tool produces one, against
whichever model/endpoint is actually live. It does NOT change the shipped
default — that stays a human decision (see
``docs/design/EnsembleGroundingInvestigation.md``, "Loose ends" #2).

Two modes, corresponding to the human checkpoint the sweep needs upstream of it:

``--bootstrap CORPUS.json --out pairs.yaml``
    Reads a merged ``merged.json`` fact corpus, embeds a sample of facts within
    each ``type`` partition (mirroring how ``ensemble_merge --method embed``
    partitions), and proposes candidate pairs in three cosine bands: near-1.0
    anchors that are probably duplicates, near-0.0 anchors that are probably
    distinct, and an "ambiguous" middle band worth checking by hand. It writes
    a YAML skeleton with every ``label:`` left blank. THE TOOL NEVER LABELS A
    PAIR — a human reads each proposed pair and fills in ``dup`` or
    ``distinct`` before the file is usable by the sweep. This is the
    LLM/algorithm-extracts, human-reviews checkpoint from the repo's
    "LLM renders, humans decide" rule, applied to a non-LLM heuristic: cosine
    similarity is just as capable of being confidently wrong.

``--pairs pairs.yaml``
    Reads a hand-labeled pairs file (schema below), re-embeds every fact text
    (through the SAME seam ``ensemble_merge`` uses, so the measurement matches
    what a real merge run would see), and sweeps a threshold range reporting
    precision/recall/F1 per threshold plus a recommended value. Also reports
    the observed cosine distribution for the ``dup`` and ``distinct`` labels
    (min/median/max) so the "empty gap" argument that justifies a single
    threshold can be re-checked against whichever model is live.

Labeled-pairs YAML schema
--------------------------
Either a bare list of pairs, or a mapping with a ``pairs:`` key (the bootstrap
output uses the mapping form so it can also record what corpus/model produced
it). Each pair is a mapping::

    pairs:
      - a: "The keeper died."
        b: "Keeper has died."
        label: dup            # REQUIRED: dup | distinct
        type: npc              # optional, informational only
        cosine: 0.9612          # optional, informational only — the sweep
                                 # re-embeds and does not trust this value
      - a: "..."
        b: "..."
        label: distinct

Pairs with a missing or unrecognised ``label`` (including the bootstrap's
blank ``label: null`` skeleton entries) are skipped with a warning rather than
erroring the whole file — a partially-labeled file is still useful for a
partial sweep.

Usage::

    # 1. propose candidates from an existing merged.json for hand-labeling
    calibrate_embed --bootstrap docs/ensemble/merged.json --out calib_pairs.yaml

    # 2. (human fills in every `label:` field in calib_pairs.yaml)

    # 3. sweep thresholds against the labeled pairs
    calibrate_embed --pairs calib_pairs.yaml \\
        --embed-endpoint http://spark:11434 --embed-model qwen3-embedding:0.6b
"""

import argparse
import json
import os
import random
import sys
from pathlib import Path
from typing import Any

import campaignlib
from pipelines.ensemble.ensemble_merge import DEFAULT_EMBED_MODEL, embed_texts

# Default cosine bands for --bootstrap, expressed as flags so they can be
# retuned per model without editing code. These are starting points, not
# measurements: the doc's own numbers span duplicate~0.97 (nomic) down to
# duplicate~0.91 (qwen3), so "clear dup" and "ambiguous" must stay adjustable.
DEFAULT_DUP_FLOOR = 0.97
DEFAULT_DISTINCT_CEILING = 0.5
DEFAULT_AMBIGUOUS_LOW = 0.80
DEFAULT_AMBIGUOUS_HIGH = 0.96
DEFAULT_SAMPLE_SIZE = 150
DEFAULT_N_PER_BAND = 15


# ── bootstrap: propose candidate pairs from a merged.json corpus ────────────

def load_corpus(path: Path) -> list[dict]:
    """Read a merge output (top-level merged.json or a per_chapter one).

    Both shapes are a flat JSON list of fact dicts sharing at least
    ``type``/``subject``/``fact``; the top-level file additionally carries
    ``source_chapter`` and (once #200's re-merge lands) ``quote_offset``.
    Neither field is needed here — only ``type`` and ``fact``.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print(f"Error: {path} is not a JSON list of facts.", file=sys.stderr)
        sys.exit(1)
    return data


def bootstrap_candidates(
    corpus: list[dict],
    endpoint: str,
    model: str,
    embed_fn=None,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    n_per_band: int = DEFAULT_N_PER_BAND,
    dup_floor: float = DEFAULT_DUP_FLOOR,
    distinct_ceiling: float = DEFAULT_DISTINCT_CEILING,
    ambiguous_low: float = DEFAULT_AMBIGUOUS_LOW,
    ambiguous_high: float = DEFAULT_AMBIGUOUS_HIGH,
    seed: int = 0,
) -> dict[str, list[dict]]:
    """Propose candidate pairs in three cosine bands, partitioned by type.

    Partitioning by ``type`` mirrors ``ensemble_merge --method embed``, which
    never compares facts across types — a candidate pair the sweep will never
    actually merge in production isn't useful evidence. Within a type, facts
    are subsampled (seeded, so re-running with the same seed reproduces the
    same skeleton) to keep the O(n^2) pairwise comparison bounded: `npc` alone
    is 5000+ facts in the OOTA corpus, and embedding all of them just to
    bootstrap a calibration file would cost more than the calibration is
    worth.

    Returns ``{"clear_dup": [...], "ambiguous": [...], "clear_distinct": [...]}``,
    each a list of ``{"a", "b", "type", "cosine"}`` dicts, each list capped at
    ``n_per_band`` and shuffled across types for diversity (not sorted to the
    band's extreme, which would just re-propose near-identical pairs from
    whichever type happens to dominate the corpus).
    """
    import numpy as np

    embed_fn = embed_fn or embed_texts
    rng = random.Random(seed)

    by_type: dict[str, list[dict]] = {}
    for f in corpus:
        text = f.get("fact", "")
        if not text:
            continue
        by_type.setdefault(f.get("type", ""), []).append(f)

    candidates: dict[str, list[dict]] = {
        "clear_dup": [], "ambiguous": [], "clear_distinct": [],
    }
    for ftype, facts in sorted(by_type.items()):
        if len(facts) < 2:
            continue
        sample = (facts if len(facts) <= sample_size
                  else rng.sample(facts, sample_size))
        texts = [f["fact"] for f in sample]
        vecs = embed_fn(texts, endpoint, model)
        n = len(sample)
        for i in range(n):
            sims = vecs[i:i + 1] @ vecs[i + 1:n].T if i + 1 < n else None
            if sims is None:
                continue
            sims = np.asarray(sims).reshape(-1)
            for offset, cos in enumerate(sims):
                j = i + 1 + offset
                cos = float(cos)
                pair = {"a": texts[i], "b": texts[j], "type": ftype,
                        "cosine": round(cos, 4)}
                if cos >= dup_floor:
                    candidates["clear_dup"].append(pair)
                elif cos <= distinct_ceiling:
                    candidates["clear_distinct"].append(pair)
                elif ambiguous_low <= cos <= ambiguous_high:
                    candidates["ambiguous"].append(pair)

    for band, pairs in candidates.items():
        rng.shuffle(pairs)
        candidates[band] = pairs[:n_per_band]
    return candidates


def write_skeleton(
    out_path: Path, corpus_path: Path, endpoint: str, model: str,
    candidates: dict[str, list[dict]],
) -> None:
    """Write the bootstrap output as a YAML skeleton with every label blank.

    Uses ``yaml.safe_dump`` for the pair data (never hand-formats fact text
    into YAML — facts routinely contain quotes and colons that are easy to
    get wrong by hand) with a hand-written comment header explaining the
    schema, so opening the file gives instructions before data.
    """
    import yaml

    band_order = ["clear_dup", "ambiguous", "clear_distinct"]
    all_pairs = []
    for band in band_order:
        for p in candidates.get(band, []):
            all_pairs.append({
                "band": band,
                "type": p["type"],
                "cosine": p["cosine"],
                "a": p["a"],
                "b": p["b"],
                "label": None,  # dup | distinct — the human fills this in.
            })

    doc = {
        "source_corpus": str(corpus_path),
        "embed_endpoint": endpoint,
        "embed_model": model,
        "pairs": all_pairs,
    }

    header = f"""\
# Embed-threshold calibration pairs — bootstrapped candidates for hand-labeling.
#
# For EVERY pair below, set `label: dup` or `label: distinct` based on your
# own reading of the two fact texts. The `band`/`cosine` fields say where the
# bootstrap sampled the pair from ({DEFAULT_DUP_FLOOR:.2f}+ = clear_dup,
# {DEFAULT_AMBIGUOUS_LOW:.2f}-{DEFAULT_AMBIGUOUS_HIGH:.2f} = ambiguous, <={DEFAULT_DISTINCT_CEILING:.2f} = clear_distinct)
# — they are NOT a suggested answer. A pair left unlabeled (the `label`
# field blank) is skipped by the sweep with a warning, so an incomplete pass
# is still usable.
#
# Then run:
#   calibrate_embed --pairs {out_path.name} \\
#       --embed-endpoint {endpoint} --embed-model {model}
#
"""
    body = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True,
                          default_flow_style=False, width=88)
    campaignlib.atomic_write_text(out_path, header + body)


# ── labeled-pairs loading ────────────────────────────────────────────────────

def load_labeled_pairs(path: Path) -> list[dict]:
    """Load a labeled-pairs YAML (see module docstring for the schema).

    Accepts a bare list or a ``{"pairs": [...]}`` mapping (the bootstrap
    output uses the mapping form to also carry provenance). Pairs missing a
    recognised ``label`` (blank bootstrap skeletons included) are dropped
    with a stderr count rather than erroring — a partially-labeled file
    should still sweep against what IS labeled.
    """
    import yaml

    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = loaded.get("pairs", loaded) if isinstance(loaded, dict) else loaded
    if not isinstance(items, list):
        print(f"Error: {path} does not contain a list of pairs (or a "
              f"'pairs:' key holding one). See calibrate_embed --help for "
              f"the schema.", file=sys.stderr)
        sys.exit(1)

    pairs: list[dict] = []
    skipped = 0
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            skipped += 1
            continue
        label = item.get("label")
        if label not in ("dup", "distinct"):
            skipped += 1
            continue
        a, b = item.get("a"), item.get("b")
        if not a or not b:
            print(f"Warning: pair #{i} has label {label!r} but is missing "
                  f"'a' or 'b' text — skipped.", file=sys.stderr)
            skipped += 1
            continue
        pairs.append({"a": a, "b": b, "label": label, "type": item.get("type")})

    if skipped:
        print(f"Note: {skipped} pair(s) skipped (missing or unlabeled — "
              f"still 'label: null' or similar). {len(pairs)} usable.",
              file=sys.stderr)
    if not pairs:
        print(f"Error: no usable labeled pairs in {path}. Every pair needs "
              f"'a', 'b', and 'label: dup' or 'label: distinct'.",
              file=sys.stderr)
        sys.exit(1)
    return pairs


# ── measurement: embed the pairs, sweep thresholds ──────────────────────────

def compute_pair_cosines(
    pairs: list[dict], endpoint: str, model: str, embed_fn=None,
) -> list[dict]:
    """Embed every distinct fact text once, return pairs with a ``cosine`` key.

    ``embed_fn`` defaults to ``ensemble_merge.embed_texts`` — the SAME seam a
    real merge run calls — resolved at call time (not bound into the default
    argument) so tests can either monkeypatch the module-level name (as
    ``test_ensemble_merge.py`` does for ``ensemble_merge``) or pass a fake
    function directly; either way no network call happens in a test.
    """
    embed_fn = embed_fn or embed_texts

    texts: list[str] = []
    index: dict[str, int] = {}
    for p in pairs:
        for text in (p["a"], p["b"]):
            if text not in index:
                index[text] = len(texts)
                texts.append(text)

    vecs = embed_fn(texts, endpoint, model)

    out = []
    for p in pairs:
        va = vecs[index[p["a"]]]
        vb = vecs[index[p["b"]]]
        cos = float(va @ vb)
        out.append({**p, "cosine": cos})
    return out


def cosine_distribution(pairs: list[dict], label: str) -> dict[str, Any] | None:
    """min/median/max cosine among pairs carrying the given label, or None."""
    vals = sorted(p["cosine"] for p in pairs if p["label"] == label)
    if not vals:
        return None
    n = len(vals)
    median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    return {"n": n, "min": vals[0], "median": median, "max": vals[-1]}


def sweep_thresholds(
    pairs: list[dict], threshold_min: float, threshold_max: float,
    threshold_step: float,
) -> list[dict]:
    """Score every threshold in [min, max] (inclusive) at the given step.

    ``dup`` is the positive class: a fact pair whose cosine clears the
    threshold is predicted a merge. Precision/recall/F1 are computed directly
    against the human labels — no smoothing, so a threshold with zero
    predicted positives reports precision as None (undefined) rather than a
    misleading 0 or 1.
    """
    results = []
    n_steps = max(0, round((threshold_max - threshold_min) / threshold_step))
    for i in range(n_steps + 1):
        t = round(threshold_min + i * threshold_step, 10)
        tp = fp = fn = tn = 0
        for p in pairs:
            predicted_dup = p["cosine"] >= t
            actual_dup = p["label"] == "dup"
            if predicted_dup and actual_dup:
                tp += 1
            elif predicted_dup and not actual_dup:
                fp += 1
            elif not predicted_dup and actual_dup:
                fn += 1
            else:
                tn += 1
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        if precision is not None and recall is not None and (precision + recall) > 0:
            f1 = 2 * precision * recall / (precision + recall)
        else:
            f1 = 0.0
        results.append({
            "threshold": t, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": f1,
        })
    return results


def recommend_threshold(sweep: list[dict]) -> dict:
    """Highest-F1 threshold; ties broken toward the HIGHER threshold.

    A tie means multiple thresholds separate the labeled set equally well on
    this sample. Preferring the higher one biases toward precision — fewer
    false merges — which matches the whole point of a merge threshold: an
    over-eager merge silently discards a fact (issue #197's failure mode),
    while an under-eager one just leaves two facts unmerged for a human to
    notice and merge by hand. Erring toward "review more" over "merge wrongly"
    is the safer default when the evidence doesn't clearly prefer one value.
    """
    best = max(sweep, key=lambda r: (r["f1"], r["threshold"]))
    return best


# ── reporting ─────────────────────────────────────────────────────────────

def _fmt(x) -> str:
    return f"{x:.3f}" if isinstance(x, float) else ("—" if x is None else str(x))


def print_report(
    endpoint: str, model: str, pairs: list[dict], sweep: list[dict],
    recommended: dict,
) -> None:
    n_dup = sum(1 for p in pairs if p["label"] == "dup")
    n_distinct = sum(1 for p in pairs if p["label"] == "distinct")

    print(f"Endpoint: {endpoint}")
    print(f"Model:    {model}")
    print(f"Pairs:    {len(pairs)} labeled ({n_dup} dup, {n_distinct} distinct)")
    print("=" * 70)

    dup_dist = cosine_distribution(pairs, "dup")
    distinct_dist = cosine_distribution(pairs, "distinct")
    print("Cosine distribution:")
    if dup_dist:
        print(f"  dup:      n={dup_dist['n']:<4} min={dup_dist['min']:.4f}  "
              f"median={dup_dist['median']:.4f}  max={dup_dist['max']:.4f}")
    else:
        print("  dup:      (no labeled dup pairs)")
    if distinct_dist:
        print(f"  distinct: n={distinct_dist['n']:<4} min={distinct_dist['min']:.4f}  "
              f"median={distinct_dist['median']:.4f}  max={distinct_dist['max']:.4f}")
    else:
        print("  distinct: (no labeled distinct pairs)")
    if dup_dist and distinct_dist:
        gap = dup_dist["min"] - distinct_dist["max"]
        if gap > 0:
            print(f"  gap:      {gap:.4f} wide — distinct.max "
                  f"{distinct_dist['max']:.4f} < dup.min {dup_dist['min']:.4f} "
                  f"(a threshold anywhere in this range separates the labels "
                  f"cleanly)")
        else:
            print(f"  gap:      NONE — distinct.max {distinct_dist['max']:.4f} "
                  f">= dup.min {dup_dist['min']:.4f} (overlap of {-gap:.4f}; "
                  f"no single threshold separates the labels cleanly on this "
                  f"sample)")
    print()

    print(f"{'threshold':>9}  {'precision':>9}  {'recall':>9}  {'f1':>6}  "
          f"{'tp':>4}  {'fp':>4}  {'fn':>4}  {'tn':>4}")
    for r in sweep:
        marker = " *" if r["threshold"] == recommended["threshold"] else ""
        print(f"{r['threshold']:>9.3f}  {_fmt(r['precision']):>9}  "
              f"{_fmt(r['recall']):>9}  {r['f1']:>6.3f}  {r['tp']:>4}  "
              f"{r['fp']:>4}  {r['fn']:>4}  {r['tn']:>4}{marker}")

    print()
    print(f"Recommended threshold: {recommended['threshold']:.3f}  "
          f"(F1={recommended['f1']:.3f}, precision="
          f"{_fmt(recommended['precision'])}, recall={_fmt(recommended['recall'])})")
    print("This tool does not change any default — --embed-threshold 0.93 "
          "stays the shipped value everywhere until a human edits it "
          "(docs/design/EnsembleGroundingInvestigation.md, 'Loose ends' #2).")


# ── CLI ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="calibrate_embed",
        description=(
            "Calibrate ensemble_merge's --embed-threshold against real fact "
            "pairs, for whichever embedding model/endpoint is actually live. "
            "Two modes: --bootstrap proposes candidate pairs from a "
            "merged.json corpus for hand-labeling; --pairs sweeps thresholds "
            "against a hand-labeled pairs file. See the module docstring "
            "(pipelines/ensemble/calibrate_embed.py) for the labeled-pairs "
            "YAML schema. Never changes the shipped 0.93 default — that "
            "stays a human decision."
        ),
    )
    parser.add_argument("--bootstrap", metavar="MERGED_JSON",
                        help="Propose candidate pairs from this merged.json "
                             "(or a per_chapter merged.json) for hand-"
                             "labeling; writes to --out and exits. Mutually "
                             "exclusive with --pairs.")
    parser.add_argument("--pairs", metavar="YAML",
                        help="Hand-labeled pairs file to sweep thresholds "
                             "against (see module docstring for schema). "
                             "Mutually exclusive with --bootstrap.")
    parser.add_argument("--out", "-o", metavar="YAML",
                        help="Where --bootstrap writes the labeling "
                             "skeleton. Required with --bootstrap.")

    embed = parser.add_argument_group(
        "embed endpoint (mirrors ensemble_merge's flags — measure against "
        "the SAME endpoint a real merge run would use)")
    embed.add_argument("--embed-endpoint", default=None, metavar="URL",
                        help="OpenAI-compatible /v1/embeddings endpoint "
                             "(e.g. http://spark:11434). Default: "
                             "$EMBED_ENDPOINT. Required (one way or another) "
                             "for both modes.")
    embed.add_argument("--embed-model", default=None, metavar="ID",
                        help=f"Embedding model id (default: $EMBED_MODEL or "
                             f"{DEFAULT_EMBED_MODEL} — same fallback chain "
                             f"as ensemble_merge).")

    boot = parser.add_argument_group("--bootstrap tuning")
    boot.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE,
                       metavar="N",
                       help=f"Max facts sampled per type before computing "
                            f"pairwise cosines (default {DEFAULT_SAMPLE_SIZE}"
                            f"; a type with more facts is randomly "
                            f"subsampled — the OOTA corpus has 5000+ npc "
                            f"facts alone, too many to embed all-pairs).")
    boot.add_argument("--n-per-band", type=int, default=DEFAULT_N_PER_BAND,
                       metavar="N",
                       help=f"Max candidate pairs proposed per cosine band "
                            f"(default {DEFAULT_N_PER_BAND}).")
    boot.add_argument("--dup-floor", type=float, default=DEFAULT_DUP_FLOOR,
                       metavar="COS",
                       help=f"Cosine at/above which a pair is a 'clear_dup' "
                            f"anchor candidate (default {DEFAULT_DUP_FLOOR}).")
    boot.add_argument("--distinct-ceiling", type=float,
                       default=DEFAULT_DISTINCT_CEILING, metavar="COS",
                       help=f"Cosine at/below which a pair is a "
                            f"'clear_distinct' anchor candidate (default "
                            f"{DEFAULT_DISTINCT_CEILING}).")
    boot.add_argument("--ambiguous-low", type=float,
                       default=DEFAULT_AMBIGUOUS_LOW, metavar="COS",
                       help=f"Lower bound of the 'ambiguous' band (default "
                            f"{DEFAULT_AMBIGUOUS_LOW}) — the pairs most "
                            f"worth a human's time, since they're the ones "
                            f"near any plausible threshold.")
    boot.add_argument("--ambiguous-high", type=float,
                       default=DEFAULT_AMBIGUOUS_HIGH, metavar="COS",
                       help=f"Upper bound of the 'ambiguous' band (default "
                            f"{DEFAULT_AMBIGUOUS_HIGH}).")
    boot.add_argument("--seed", type=int, default=0, metavar="N",
                       help="Random seed for sampling/shuffling (default 0) "
                            "— same seed + same corpus reproduces the same "
                            "skeleton.")

    sweep_grp = parser.add_argument_group("--pairs sweep tuning")
    sweep_grp.add_argument("--threshold-min", type=float, default=0.50,
                            metavar="COS",
                            help="Lowest threshold to test (default 0.50).")
    sweep_grp.add_argument("--threshold-max", type=float, default=0.99,
                            metavar="COS",
                            help="Highest threshold to test (default 0.99).")
    sweep_grp.add_argument("--threshold-step", type=float, default=0.01,
                            metavar="COS",
                            help="Step size between tested thresholds "
                                 "(default 0.01).")

    args = parser.parse_args()

    if bool(args.bootstrap) == bool(args.pairs):
        print("Error: pass exactly one of --bootstrap or --pairs.",
              file=sys.stderr)
        sys.exit(1)

    embed_endpoint = args.embed_endpoint or os.environ.get("EMBED_ENDPOINT")
    embed_model = (args.embed_model or os.environ.get("EMBED_MODEL")
                  or DEFAULT_EMBED_MODEL)
    if not embed_endpoint:
        print("Error: no embed endpoint resolved. Pass --embed-endpoint or "
              "set $EMBED_ENDPOINT (same as ensemble_merge).",
              file=sys.stderr)
        sys.exit(1)

    if args.bootstrap:
        if not args.out:
            print("Error: --bootstrap requires --out YAML (where to write "
                  "the labeling skeleton).", file=sys.stderr)
            sys.exit(1)
        corpus_path = Path(args.bootstrap).expanduser().resolve()
        out_path = Path(args.out).expanduser().resolve()
        corpus = load_corpus(corpus_path)

        print(f"Endpoint: {embed_endpoint}")
        print(f"Model:    {embed_model}")
        print(f"Corpus:   {corpus_path} ({len(corpus)} facts)")
        print("=" * 70)

        candidates = bootstrap_candidates(
            corpus, embed_endpoint, embed_model,
            sample_size=args.sample_size, n_per_band=args.n_per_band,
            dup_floor=args.dup_floor, distinct_ceiling=args.distinct_ceiling,
            ambiguous_low=args.ambiguous_low, ambiguous_high=args.ambiguous_high,
            seed=args.seed,
        )
        total = sum(len(v) for v in candidates.values())
        for band in ("clear_dup", "ambiguous", "clear_distinct"):
            print(f"  {band:16s} {len(candidates[band])} candidate pair(s)")
        write_skeleton(out_path, corpus_path, embed_endpoint, embed_model,
                       candidates)
        print(f"\nWritten: {out_path} ({total} pairs, every label blank — "
              f"fill in 'dup' or 'distinct' by hand, then re-run with "
              f"--pairs {out_path}).")
        return

    pairs_path = Path(args.pairs).expanduser().resolve()
    labeled = load_labeled_pairs(pairs_path)
    scored = compute_pair_cosines(labeled, embed_endpoint, embed_model)
    sweep = sweep_thresholds(scored, args.threshold_min, args.threshold_max,
                             args.threshold_step)
    if not sweep:
        print("Error: empty threshold sweep — check --threshold-min/-max/"
              "-step.", file=sys.stderr)
        sys.exit(1)
    recommended = recommend_threshold(sweep)
    print_report(embed_endpoint, embed_model, scored, sweep, recommended)


if __name__ == "__main__":
    main()
