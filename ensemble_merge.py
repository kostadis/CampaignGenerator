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
import json
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path


def _norm_subject(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


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
    threshold: float = 0.93,
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
    since we process longest-first). The default 0.93 threshold sits in the
    empirically-measured empty gap between true duplicates (~0.97-0.98) and
    distinct-but-related facts (~0.75-0.78), so distinct facts are NOT merged.

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
                             "0.93). True duplicates ~0.97-0.98, distinct-but-"
                             "related ~0.75-0.78 — 0.93 sits in the empty gap.")
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
    embed_threshold = float(_resolve(args.embed_threshold, "embed_threshold", 0.93))
    similarity = float(_resolve(args.similarity, "similarity", 0.85))
    method = _resolve(args.method, "method", None) or (
        "embed" if embed_endpoint else "subject")
    if method == "embed" and not embed_endpoint:
        print("Error: merge method 'embed' needs an embed endpoint "
              "(--embed-endpoint, config embed_endpoint, or $EMBED_ENDPOINT).",
              file=sys.stderr)
        sys.exit(1)

    manifest = load_manifest(workdir)
    samples = int(manifest.get("samples", 1))
    pass_outputs = load_pass_outputs(workdir, manifest)
    output_path = (Path(args.output).expanduser().resolve()
                   if args.output else workdir / "merged.json")

    print(f"Workdir:  {workdir}")
    print(f"Passes:   {len(manifest.get('passes', []))} "
          f"({len(pass_outputs)} sample-run output(s))")
    if method == "embed":
        print(f"Merge:    embedding cosine / nomic ({embed_endpoint}, "
              f"model {embed_model}, threshold {embed_threshold})")
    else:
        print(f"Merge:    subject-keyed SequenceMatcher (similarity {similarity})")
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

    output_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")

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
    if samples > 1:
        print(f"Agreement (n_samples -> #facts): {dict(sorted(agree_hist.items()))}")
    print("Pass coverage:")
    for combo, n in sorted(pass_combo_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {combo:30s} {n}")
    print(f"\nWritten: {output_path}")


if __name__ == "__main__":
    main()
