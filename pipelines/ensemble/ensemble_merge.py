#!/usr/bin/env python3
"""Merge per-pass ensemble outputs into a single deduplicated fact list.

This is the *merge* half of the ensemble pipeline, decoupled from generation
(``ensemble_extract.py``). It reads the ``manifest.json`` that the generator
wrote into a workdir, loads each pass's facts from disk, and merges them — so
you can re-merge an existing generation as many times as you like (subject
merge, then nomic-embedding merge, then a different threshold) WITHOUT
re-extracting anything.

Two merge methods:

- ``subject`` — group by (type, normalized subject), then collapse near-duplicate
  ``fact`` strings within each group (SequenceMatcher ratio ≥ similarity). Keeps
  the longest fact and source_quote. No embed server needed.
- ``embed`` — cluster on embedding cosine of the FACT TEXT, partitioned by
  ``type`` only (subject is NOT part of the key). Catches cross-subject
  duplicates the subject merge cannot (same event under different labels;
  phonetic-variant spellings). Needs an OpenAI-compatible /v1/embeddings server.

Each merged fact carries a ``passes`` list (which lenses produced it) and an
``n_samples`` count (how many sample-runs produced it) — confidence signals for
the human review step. Nothing is auto-filtered: deciding what is in scope is a
precision decision the human makes.

Merge settings come from a flat merge-config YAML (``--config``) and/or CLI
flags. Precedence: explicit CLI flag > ``--config`` value > built-in default.

Usage:

    # merge an existing generation in WORKDIR using a config file
    python ensemble_merge.py --workdir runs/s1 --config merge.yaml

    # or drive it entirely from the CLI (re-merge with a different method)
    python ensemble_merge.py -w runs/s1 --method subject --similarity 0.85
"""

import argparse
import bisect
import json
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import campaignlib
from campaignlib.textproc import (
    chunk_by_scenes,
    chunk_text_with_offsets,
    norm_subject as _norm_subject,
    strip_base64_images,
)


def _fact_key(fact: dict) -> tuple[str, str]:
    return (fact.get("type", ""), _norm_subject(fact.get("subject", "")))


def _facts_similar(a: str, b: str, threshold: float) -> bool:
    if a == b:
        return True
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= threshold


def merge_facts(
    pass_outputs: dict[str, list[dict]], similarity: float
) -> list[dict]:
    """Union facts across passes, group by (type, normalized subject), dedup."""
    groups: dict[tuple[str, str], list[tuple[dict, str]]] = {}
    for pass_name, facts in pass_outputs.items():
        for f in facts:
            groups.setdefault(_fact_key(f), []).append((f, pass_name))

    merged: list[dict] = []
    for items in groups.values():
        kept: list[dict] = []
        for fact, pass_name in items:
            text = fact.get("fact", "")
            quote = fact.get("source_quote", "")
            matched: dict | None = None
            for existing in kept:
                if _facts_similar(existing["fact"], text, similarity):
                    matched = existing
                    break
            if matched is not None:
                if len(text) > len(matched["fact"]):
                    matched["fact"] = text
                if len(quote) > len(matched.get("source_quote", "")):
                    matched["source_quote"] = quote
                    # The flag describes the quote — it travels with it.
                    matched["quote_verified"] = fact.get("quote_verified")
                if pass_name not in matched["passes"]:
                    matched["passes"].append(pass_name)
            else:
                kept.append(
                    {
                        "type": fact.get("type", ""),
                        "subject": fact.get("subject", ""),
                        "fact": text,
                        "source_quote": quote,
                        "quote_verified": fact.get("quote_verified"),
                        "passes": [pass_name],
                    }
                )
        merged.extend(kept)

    # Stable sort for diffability across runs.
    merged.sort(key=lambda f: (f["type"], _norm_subject(f["subject"]), f["fact"]))
    return merged


DEFAULT_EMBED_MODEL = "nomic-ai/nomic-embed-text-v1.5"


def embed_texts(texts: list[str], endpoint: str, model: str, batch: int = 256):
    """Return an L2-normalised numpy array of embeddings, one row per text.

    Calls an OpenAI-compatible /v1/embeddings server (e.g. vllm-embed on the
    DGX). Normalising up front makes cosine similarity a plain dot product.
    """
    import numpy as np
    from openai import OpenAI

    base = endpoint.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    client = OpenAI(base_url=base, api_key="not-needed")
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch):
        resp = client.embeddings.create(model=model, input=texts[i:i + batch])
        vectors.extend(d.embedding for d in resp.data)
    arr = np.asarray(vectors, dtype="float32")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def merge_facts_embed(
    pass_outputs: dict[str, list[dict]], endpoint: str, model: str,
    threshold: float = 0.94,
) -> list[dict]:
    """Like merge_facts, but cluster on embedding cosine of the FACT TEXT,
    partitioned only by `type` — the subject string is NOT part of the key.

    This catches cross-subject duplicates the SequenceMatcher merge cannot:
    two samples describe the same event under different synthetic subject
    labels ("flee to Darklake tunnel" vs "flee toward Darklake"), or the same
    entity under a phonetic-variant spelling (Velkynvelve / Velkenyvelve).
    Their subject strings differ, so the subject-keyed merge never compares
    their near-identical fact text; cosine similarity does.

    Greedy clustering against each cluster's fixed anchor (the longest fact,
    since we process longest-first). The default 0.94 threshold is calibrated
    on `qwen3-embedding:0.6b` (calibrate_embed sweep, 2026-07-28, issue #197):
    on that model the dup/distinct bands OVERLAP — paraphrase duplicates score
    ~0.91-0.95 while the worst distinct pair (two different in-world dates)
    scores 0.9375 — so no threshold is clean, and 0.94 is the precision-first
    choice: zero false merges on the labeled set, at the cost of missing
    paraphrase dups below it. The threshold is MODEL-SPECIFIC; re-run
    calibrate_embed whenever the embed sidecar changes model.

    Every collapsed variant is preserved on the survivor for human audit:
    `variants` lists the distinct fact strings merged in, `subjects` the
    distinct subject labels. Merging is a scope decision feeding the human
    review step, so nothing is silently discarded — the human can see exactly
    what was collapsed and split it back if a merge was wrong.
    """
    import numpy as np

    # Flatten to (fact_dict, run_key), longest fact first so cluster anchors are
    # the most complete phrasing.
    flat: list[tuple[dict, str]] = []
    for run_key, facts in pass_outputs.items():
        for f in facts:
            flat.append((f, run_key))
    flat.sort(key=lambda fk: -len(fk[0].get("fact", "")))

    by_type: dict[str, list[tuple[dict, str]]] = {}
    for f, run_key in flat:
        by_type.setdefault(f.get("type", ""), []).append((f, run_key))

    merged: list[dict] = []
    for ftype, items in by_type.items():
        texts = [f.get("fact", "") for f, _ in items]
        vecs = embed_texts(texts, endpoint, model) if texts else None
        anchors: list[int] = []          # indices into `items` that seed clusters
        clusters: list[dict] = []        # survivor dicts, parallel to `anchors`
        anchor_vecs = None               # np matrix of anchor embeddings
        for idx, (fact, run_key) in enumerate(items):
            text = fact.get("fact", "")
            quote = fact.get("source_quote", "")
            subj = fact.get("subject", "")
            matched = None
            if anchors:
                sims = anchor_vecs @ vecs[idx]
                best = int(np.argmax(sims))
                if sims[best] >= threshold:
                    matched = clusters[best]
            if matched is not None:
                if run_key not in matched["passes"]:
                    matched["passes"].append(run_key)
                if text and text not in matched["variants"]:
                    matched["variants"].append(text)
                if subj and subj not in matched["subjects"]:
                    matched["subjects"].append(subj)
                if len(quote) > len(matched.get("source_quote", "")):
                    matched["source_quote"] = quote
                    matched["quote_verified"] = fact.get("quote_verified")
            else:
                clusters.append({
                    "type": ftype,
                    "subject": subj,
                    "fact": text,            # anchor = longest, processed first
                    "source_quote": quote,
                    "quote_verified": fact.get("quote_verified"),
                    "passes": [run_key],
                    "variants": [text] if text else [],
                    "subjects": [subj] if subj else [],
                })
                anchors.append(idx)
                row = vecs[idx:idx + 1]
                anchor_vecs = row if anchor_vecs is None else np.vstack([anchor_vecs, row])
        merged.extend(clusters)

    merged.sort(key=lambda f: (f["type"], _norm_subject(f["subject"]), f["fact"]))
    return merged


def load_manifest(workdir: Path) -> dict:
    """Read the generator's manifest.json from a workdir, or exit with help."""
    manifest_path = workdir / "manifest.json"
    if not manifest_path.exists():
        print(f"Error: no manifest.json in {workdir}. Run ensemble_extract.py "
              f"against this workdir first (it writes the manifest the merge "
              f"step consumes).", file=sys.stderr)
        sys.exit(1)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_pass_outputs(workdir: Path, manifest: dict) -> dict[str, list[dict]]:
    """Build {provenance_key: facts} from the manifest's per-pass output files.

    Keys are f"{name}#{k}" (carrying the sample index) so the n_samples collapse
    downstream works identically to the original all-in-one path.
    """
    pass_outputs: dict[str, list[dict]] = {}
    for p in manifest.get("passes", []):
        for o in p.get("outputs", []):
            fpath = workdir / o["file"]
            if not fpath.exists():
                print(f"Error: manifest lists {o['file']} for pass "
                      f"{p['name']!r}, but it's missing from {workdir}.",
                      file=sys.stderr)
                sys.exit(1)
            pass_outputs[o["key"]] = json.loads(fpath.read_text(encoding="utf-8"))
    if not pass_outputs:
        print(f"Error: manifest in {workdir} lists no pass outputs.",
              file=sys.stderr)
        sys.exit(1)
    return pass_outputs


def quote_offset(quote: str, document: str) -> int | None:
    """Character offset of ``quote`` in ``document``, or None if not found.

    ``extract_facts.verify_quotes`` already locates every quote — it just asks
    ``q in chunk`` and keeps only the boolean. Finding it costs the same as
    testing for it, and the position is the one thing that says WHEN a fact
    happened inside a chapter (issue #195). Without it the pipeline has to infer
    ordering it was handed for free: the cache keeps chunk order only in a
    filename, and ``merge_facts`` sorts alphabetically by (type, subject, fact).

    Whitespace-tolerant, mirroring ``verify_quotes``' own fallback: the extract
    prompts demand verbatim substrings, but a reflowed line break inside an
    otherwise exact quote shouldn't lose the position. Runs of whitespace in the
    quote match runs of whitespace in the document.
    """
    if not quote:
        return None
    i = document.find(quote)
    if i >= 0:
        return i
    tokens = quote.split()
    if not tokens:
        return None
    pattern = re.compile(r"\s+".join(re.escape(t) for t in tokens))
    m = pattern.search(document)
    return m.start() if m else None


def load_document(manifest: dict) -> str | None:
    """Source text the passes were extracted from, for quote positioning.

    Every pass in a run reads the same document in practice, but the manifest
    records it per pass, so prefer the first pass's ``document`` and fall back
    to ``default_input``. Returns None (rather than exiting) when the path is
    absent or unreadable: a corpus extracted elsewhere, or a campaign that has
    since moved, must still merge — it just merges without offsets.
    """
    candidates = [p.get("document") for p in manifest.get("passes", [])]
    candidates.append(manifest.get("default_input"))
    for c in candidates:
        if not c:
            continue
        try:
            return Path(c).expanduser().read_text(encoding="utf-8")
        except OSError:
            continue
    return None


def stamp_offsets(merged: list[dict], document: str | None) -> int:
    """Stamp ``quote_offset`` on each fact; returns how many got a real one.

    Facts whose quote can't be located keep ``quote_offset: None`` rather than a
    fake 0 — an unlocatable quote is usually a fabricated or ``...``-stitched
    one (the same signal ``quote_verified`` carries), and sorting those to
    position zero would put the least trustworthy facts first.
    """
    located = 0
    for f in merged:
        off = quote_offset(f.get("source_quote") or "", document) if document else None
        f["quote_offset"] = off
        if off is not None:
            located += 1
    return located


def reference_chunking(manifest: dict) -> tuple[int | None, bool]:
    """The (chunk_size, structural) pair used to derive ``scene_index``.

    Mirrors ``load_document``'s own precedent: prefer the FIRST pass's
    config. Every pass reads the same document in practice, but they can be
    extracted at different chunk sizes (the 5 built-in lenses deliberately
    are — 6,000 vs 15,000 chars) and, with issue #202's ``--scene-chunks``,
    can differ on ``structural`` too. Picking one reference pass rather than
    trying to reconcile five is a scope decision, not a bug: when
    ``--scene-chunks`` is applied uniformly (the expected use — see
    ``ensemble_extract --scene-chunks``), every opted-in pass produces
    IDENTICAL scene boundaries anyway, since structural splitting is
    header-driven, not size-driven — they only diverge on the sub-split of
    an oversized scene, which is bounded by each pass's own chunk_size.

    Returns ``(None, False)`` when the manifest lists no passes at all (e.g.
    ``{}``, matching ``load_document``'s handling of the same input) so the
    caller degrades to stamping ``scene_index: None`` everywhere rather than
    raising.
    """
    passes = manifest.get("passes") or []
    if not passes:
        return None, False
    p0 = passes[0]
    return p0.get("chunk_size"), bool(p0.get("structural", False))


def scene_boundaries(
    document: str, chunk_size: int, structural: bool
) -> tuple[list[int], str]:
    """Reproduce ``prepare_chunks``' chunk boundaries for a single-document
    (no ``--split-chapters``) extraction, so a fact's quote can be mapped back
    to the chunk it came from.

    Applies the identical base64-image-strip + BOM-lstrip ``prepare_chunks``
    applies before chunking, and the identical structural-vs-character-count
    decision. Returns ``(sorted chunk start offsets, the stripped text)`` —
    callers MUST locate a fact's quote against the returned STRIPPED text, not
    the raw ``document`` passed in (or the raw text used by ``quote_offset``
    for the separate ``quote_offset`` field above): if the source document
    ever contains a leading BOM or an embedded base64 image block, the
    stripped text's coordinates shift relative to the raw document's, and
    bisecting a raw-document offset against stripped-text boundaries would be
    silently wrong. Locating independently against the SAME stripped text
    sidesteps that entirely (see ``stamp_scene_index``).
    """
    stripped = strip_base64_images(document).lstrip("﻿")
    if structural:
        result = chunk_by_scenes(stripped, chunk_size)
        if result is not None:
            scenes, _convention = result
            return [off for off, _ in scenes], stripped
    scenes = chunk_text_with_offsets(stripped, chunk_size)
    return [off for off, _ in scenes], stripped


def stamp_scene_index(
    merged: list[dict], document: str | None, chunk_size: int | None,
    structural: bool,
) -> int:
    """Stamp ``scene_index`` (the containing chunk's 0-based index) on each
    fact; returns how many got a real one.

    Complementary to ``quote_offset`` (issue #200): the offset gives WHERE
    within the chapter a fact happened, ``scene_index`` gives WHICH scene it
    happened in — the natural join key for a future narrative-per-scene pass
    (issue #202) and for scoping a bundle to the scenes it actually touches.

    Degrades exactly like ``stamp_offsets``: no document, or no chunk_size on
    the manifest's reference pass (an ancient corpus, or one with no passes
    at all), stamps ``scene_index: None`` everywhere rather than a fake 0 —
    the same backward-compatibility contract ``facts_to_state._narrative_key``
    already honours for a missing ``quote_offset``. An individual fact whose
    quote can't be located gets ``None`` too, independently of whether its
    ``quote_offset`` (against the raw document) was found — see
    ``scene_boundaries`` for why the two are located separately.
    """
    if document is None or not chunk_size:
        for f in merged:
            f["scene_index"] = None
        return 0
    starts, stripped = scene_boundaries(document, chunk_size, structural)
    located = 0
    for f in merged:
        q = f.get("source_quote") or ""
        off = quote_offset(q, stripped) if q else None
        if off is None:
            f["scene_index"] = None
            continue
        f["scene_index"] = max(bisect.bisect_right(starts, off) - 1, 0)
        located += 1
    return located


def stamp_lineage(merged: list[dict], workdir: Path) -> dict | None:
    """Stamp per-fact source lineage from the workdir's lineage.json.

    ensemble_batch writes lineage.json at ladder-decision time (issue #213
    Phase 1: kind scenes|summary|chapter, session, inputs, reason). Each fact
    gets a lean ``source: {kind[, session]}`` — the full decision detail
    stays in lineage.json. Returns the loaded lineage dict, or None when the
    file is absent (manual ensemble.py run, pre-Phase-1 workdir) or
    malformed — in which case nothing is stamped: absent provenance must
    read as absent, never be guessed.
    """
    lineage_file = workdir / "lineage.json"
    if not lineage_file.exists():
        return None
    try:
        lineage = json.loads(lineage_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(lineage, dict) or not lineage.get("kind"):
        return None
    stamp = {"kind": lineage["kind"]}
    if lineage.get("session"):
        stamp["session"] = lineage["session"]
    for f in merged:
        f["source"] = dict(stamp)
    return lineage


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Merge the per-pass outputs of an ensemble generation (read from "
            "the workdir's manifest.json) into a single deduplicated fact list. "
            "Decoupled from generation: re-run it freely with different methods "
            "or thresholds against the same per-pass outputs."
        )
    )
    parser.add_argument("--workdir", "-w", required=True, metavar="DIR",
                        help="Generation workdir containing manifest.json and the "
                             "per-pass *.json outputs.")
    parser.add_argument("--config", metavar="YAML",
                        help="Merge-config YAML (flat mapping of merge settings: "
                             "method, embed_endpoint, embed_model, "
                             "embed_threshold, similarity). A 'merge:' wrapper key "
                             "is also accepted. CLI flags override these.")
    parser.add_argument("--method", choices=["subject", "embed"], default=None,
                        help="Merge method. 'subject' = group by (type, subject) "
                             "then SequenceMatcher dedup; 'embed' = nomic "
                             "embedding-cosine clustering partitioned by type. "
                             "Default: 'embed' if an embed endpoint is resolved, "
                             "else 'subject'.")
    parser.add_argument("--similarity", type=float, default=None, metavar="RATIO",
                        help="Subject-merge fact-text similarity threshold (0..1, "
                             "default 0.85). Higher = stricter / more duplicates "
                             "retained.")
    parser.add_argument("--embed-endpoint", default=None, metavar="URL",
                        help="OpenAI-compatible /v1/embeddings endpoint for the "
                             "embed merge (e.g. http://192.168.1.147:8000). "
                             "Default: $EMBED_ENDPOINT.")
    parser.add_argument("--embed-model", default=None, metavar="ID",
                        help=f"Embedding model id (default: $EMBED_MODEL or "
                             f"{DEFAULT_EMBED_MODEL}).")
    parser.add_argument("--embed-threshold", type=float, default=None, metavar="COS",
                        help="Cosine threshold for the embedding merge (default "
                             "0.94, calibrated on qwen3-embedding:0.6b — "
                             "precision-first: zero false merges on the labeled "
                             "set. Model-specific; recalibrate with "
                             "calibrate_embed if the embed model changes.)")
    parser.add_argument("--output", "-o", default=None, metavar="FILE",
                        help="Where to write merged.json (default: "
                             "<workdir>/merged.json).")
    args = parser.parse_args()

    workdir = Path(args.workdir).expanduser().resolve()
    if not workdir.is_dir():
        print(f"Error: workdir not found: {workdir}", file=sys.stderr)
        sys.exit(1)

    # Merge-config file: load the flat mapping (tolerate a 'merge:' wrapper).
    cfg: dict = {}
    if args.config:
        import yaml
        cfg_path = Path(args.config).expanduser().resolve()
        loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        cfg = loaded.get("merge", loaded) if isinstance(loaded, dict) else {}

    # Precedence: explicit CLI flag > --config value > built-in default.
    def _resolve(cli, key, default):
        if cli is not None:
            return cli
        if key in cfg and cfg[key] is not None:
            return cfg[key]
        return default

    embed_endpoint = _resolve(args.embed_endpoint, "embed_endpoint",
                              os.environ.get("EMBED_ENDPOINT"))
    embed_model = _resolve(args.embed_model, "embed_model",
                           os.environ.get("EMBED_MODEL", DEFAULT_EMBED_MODEL))
    embed_threshold = float(_resolve(args.embed_threshold, "embed_threshold", 0.94))
    similarity = float(_resolve(args.similarity, "similarity", 0.85))
    chosen_method = _resolve(args.method, "method", None)
    method = chosen_method or ("embed" if embed_endpoint else "subject")
    if method == "embed" and not embed_endpoint:
        print("Error: merge method 'embed' needs an embed endpoint "
              "(--embed-endpoint, config embed_endpoint, or $EMBED_ENDPOINT).",
              file=sys.stderr)
        sys.exit(1)
    # A degradation must not look like a decision. Falling back to `subject`
    # because no embed endpoint resolved is materially weaker — `subject`
    # partitions on (type, subject), so facts filed under different subjects are
    # never compared, and a whole class of cross-subject duplicate and
    # contradiction is invisible by construction (issue #197, and the mechanism
    # behind #195). Warn only when the fallback is IMPLICIT: an explicit
    # `--method subject` (or a config key) is a considered choice, and nagging
    # considered choices is how warnings get tuned out.
    implicit_fallback = method == "subject" and chosen_method is None
    if implicit_fallback:
        print(
            "Warning: merging with 'subject' because no embed endpoint was "
            "resolved. The 'embed' merge is stronger — it clusters on fact-text "
            "similarity across subjects, which 'subject' cannot do at all. "
            "Enable it with --embed-endpoint URL, an embed_endpoint key in "
            "--config, or $EMBED_ENDPOINT. Pass --method subject to choose this "
            "deliberately and silence this warning.",
            file=sys.stderr,
        )

    manifest = load_manifest(workdir)
    samples = int(manifest.get("samples", 1))
    pass_outputs = load_pass_outputs(workdir, manifest)
    output_path = (Path(args.output).expanduser().resolve()
                   if args.output else workdir / "merged.json")

    print(f"Workdir:  {workdir}")
    print(f"Passes:   {len(manifest.get('passes', []))} "
          f"({len(pass_outputs)} sample-run output(s))")
    if method == "embed":
        # Don't name a model in the label — this said "nomic" for months after
        # the embed sidecar became Qwen (2026-06-30), and the threshold below is
        # MODEL-SPECIFIC: 0.94 was calibrated on qwen3-embedding:0.6b
        # (calibrate_embed, 2026-07-28; the nomic-era value was 0.93). A
        # different embedding model has a different similarity distribution and
        # needs its own threshold. Print what is actually being used and let it
        # speak for itself.
        print(f"Merge:    embedding cosine ({embed_endpoint}, "
              f"model {embed_model}, threshold {embed_threshold})")
    else:
        origin = " [fallback — no embed endpoint]" if implicit_fallback else ""
        print(f"Merge:    subject-keyed SequenceMatcher "
              f"(similarity {similarity}){origin}")
    print("=" * 70)

    if method == "embed":
        merged = merge_facts_embed(pass_outputs, embed_endpoint,
                                   embed_model, embed_threshold)
    else:
        merged = merge_facts(pass_outputs, similarity)

    # Provenance is tracked per sample-run key ("sweep#1", "sweep#3"). Collapse
    # those to clean lens names and record n_samples = how many independent
    # sample-runs produced each fact (a confidence signal for human review; we
    # deliberately do NOT drop low-agreement facts).
    for f in merged:
        runs = f["passes"]
        f["n_samples"] = len(runs)
        f["passes"] = sorted({p.split("#")[0] for p in runs})

    # WHEN each fact happened inside the chapter (issue #195). Done here rather
    # than in extract_facts.verify_quotes so it lands on corpora that are
    # already extracted: re-merging is free (the per-lens JSON is on disk),
    # re-extracting is hours of local-LLM time. The merged file keeps its
    # alphabetical sort for diffability — consumers re-order by this field.
    document = load_document(manifest)
    located = stamp_offsets(merged, document)

    # WHICH scene each fact happened in (issue #202), complementary to the
    # offset above: offsets give position, scene indices give grouping — the
    # join key a future narrative-per-scene pass consumes. Same "done at
    # merge time" reasoning as quote_offset above.
    scene_chunk_size, scene_structural = reference_chunking(manifest)
    scene_located = stamp_scene_index(merged, document, scene_chunk_size, scene_structural)

    # WHICH artifact the facts were extracted from (issue #213 Phase 1).
    # ensemble_batch writes lineage.json at decision time; stamping the kind
    # onto every fact lets downstream consumers (facts_to_state bundles, the
    # Phase-5 verifier) pick the right ground truth per claim. Absent file —
    # a manual ensemble.py run, or a pre-Phase-1 workdir — stamps nothing.
    lineage = stamp_lineage(merged, workdir)
    if lineage:
        print(f"Lineage:  {lineage['kind']}"
              + (f" (session {lineage['session']})" if lineage.get("session") else ""))

    campaignlib.atomic_write_json(output_path, merged)  # FR-014: atomic publish

    counts_by_lens: dict[str, int] = {}
    for key, facts in pass_outputs.items():
        lens = key.split("#")[0]
        counts_by_lens[lens] = counts_by_lens.get(lens, 0) + len(facts)
    counts_by_type: dict[str, int] = {}
    pass_combo_counts: dict[str, int] = {}
    agree_hist: dict[int, int] = {}
    for f in merged:
        counts_by_type[f["type"]] = counts_by_type.get(f["type"], 0) + 1
        combo = "+".join(f["passes"])
        pass_combo_counts[combo] = pass_combo_counts.get(combo, 0) + 1
        agree_hist[f["n_samples"]] = agree_hist.get(f["n_samples"], 0) + 1

    verified = sum(1 for f in merged if f.get("quote_verified"))

    print(f"\nPer-lens facts (raw, summed over samples): {counts_by_lens}")
    print(f"Total merged (unique): {len(merged)}")
    print(f"By type:               {dict(sorted(counts_by_type.items()))}")
    print(f"Quotes verified:       {verified}/{len(merged)} "
          f"({len(merged) - verified} unverified — review those first)")
    if document is None:
        print("Quote offsets:         none — the manifest's source document "
              "could not be read, so facts carry no within-chapter order.",
              file=sys.stderr)
    else:
        print(f"Quote offsets:         {located}/{len(merged)} located "
              f"(within-chapter event order)")
    if document is None or not scene_chunk_size:
        print("Scene index:           none — no source document or no "
              "chunk_size on the manifest's reference pass.", file=sys.stderr)
    else:
        mode = "structural" if scene_structural else "character-count"
        print(f"Scene index:           {scene_located}/{len(merged)} located "
              f"({mode} chunking, size {scene_chunk_size:,})")
    if samples > 1:
        print(f"Agreement (n_samples -> #facts): {dict(sorted(agree_hist.items()))}")
    print("Pass coverage:")
    for combo, n in sorted(pass_combo_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {combo:30s} {n}")
    print(f"\nWritten: {output_path}")


if __name__ == "__main__":
    main()
