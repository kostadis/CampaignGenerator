#!/usr/bin/env python3
"""Five-pass ensemble fact extractor.

Runs ``extract_facts.py`` five times against the same input, each with a
different lens, then merges the results deterministically.

Passes:

1. ``small``       — generalist prompt at 6,000-char chunks. Catches action
                     granularity (per-attack, per-spell, per-line-of-dialogue
                     detail) that larger chunks blur.
2. ``large``       — generalist prompt at 15,000-char chunks. Catches scene
                     setup, room descriptions, and cross-paragraph relations
                     that small chunks fragment.
3. ``sweep``       — sweep prompt at 15,000-char chunks. Exhaustive
                     proper-noun, object, and monster enumeration that the
                     generalist deprioritizes (Vof Klownits, Sava game,
                     Tongue of Madness, referenced-but-absent NPCs).
4. ``temporal``    — temporal/numeric anchor prompt at 15,000-char chunks.
                     Catches dates, counts, durations, distances, and
                     values that other passes drop ("5th day of 2nd Tenday
                     of Taraskh 1493", "100 feet above the cavern floor",
                     "eight days away via the Darklake").
5. ``interiority`` — character-interiority prompt at 15,000-char chunks.
                     Catches thoughts, feelings, memories, refusals, and
                     mutterings that action-focused passes skip ("Sarith
                     experiences bouts of madness", "Daz refused to wear
                     armor", "Grygum recalled the Giants").

Each pass writes its own ``facts_NNN.json`` cache under
``<workdir>/cache/<pass_name>/``. Re-runs reuse cached chunks, so iterating
on the merge step (or fixing one bad chunk) is cheap.

Merge is deterministic:

- Group facts by (type, normalized subject). Normalization is lowercase
  alphanumerics only, so "Bupido" and "Buppido" cluster together, as do
  "Ilvara's quarters" and "Ilvara’s quarters".
- Within each group, near-duplicate ``fact`` strings (SequenceMatcher
  ratio ≥ threshold) collapse into one entry; we keep the longest
  ``fact`` and the longest ``source_quote``.
- Each merged entry carries a ``passes`` list naming which input passes
  produced it. Facts present in all three passes are higher-confidence;
  facts unique to one pass are the recall-bonus from that lens.

This does NOT do cross-subject normalization (Velkenyvelve ↔
Velkynvelve, Sloopdopblop ↔ Sloobludop). Those phonetic-drift
clusters need a campaign-level name glossary, which is a deliberately
separate step.

Usage:

    python ensemble_extract.py session.md --workdir runs/session_001/

Re-run safely — caches make it cheap.
"""

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path

EXTRACT_SCRIPT = Path(__file__).resolve().parent / "extract_facts.py"

PASSES = [
    {"name": "small",       "chunk_size": 6000,  "agent": "extract_facts"},
    {"name": "large",       "chunk_size": 15000, "agent": "extract_facts"},
    {"name": "sweep",       "chunk_size": 15000, "agent": "extract_facts_sweep"},
    {"name": "temporal",    "chunk_size": 15000, "agent": "extract_facts_temporal"},
    {"name": "interiority", "chunk_size": 15000, "agent": "extract_facts_interiority"},
]


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
                if pass_name not in matched["passes"]:
                    matched["passes"].append(pass_name)
            else:
                kept.append(
                    {
                        "type": fact.get("type", ""),
                        "subject": fact.get("subject", ""),
                        "fact": text,
                        "source_quote": quote,
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
            else:
                clusters.append({
                    "type": ftype,
                    "subject": subj,
                    "fact": text,            # anchor = longest, processed first
                    "source_quote": quote,
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


def run_unit(
    input_path: Path, pass_spec: dict, k: int, samples: int, workdir: Path,
    endpoint: str | None, model: str | None,
) -> tuple[str, list[dict] | None, str | None]:
    """Run ONE (lens, sample) unit on `endpoint`. Returns (key, facts, error).

    `key` is f"{lens}#{k}". On success `error` is None; on failure `facts` is
    None and `error` describes it. A completed, parseable unit output is reused
    verbatim, so an interrupted/resumed run skips finished units instantly.
    Each sample has its own cache dir so a resume does not collapse the samples
    into one identical cached result.
    """
    name = pass_spec["name"]
    single = samples == 1
    output_path = workdir / (f"{name}.json" if single else f"{name}.s{k}.json")
    extract_dir = workdir / "cache" / (name if single else f"{name}/s{k}")
    extract_dir.mkdir(parents=True, exist_ok=True)
    key = f"{name}#{k}"
    label = name if single else f"{name} s{k}"

    if output_path.exists():
        try:
            facts = json.loads(output_path.read_text(encoding="utf-8"))
            print(f"  [cached] {label:20s} {len(facts):>3} facts")
            return key, facts, None
        except json.JSONDecodeError:
            pass  # corrupt/partial — regenerate below

    cmd = [
        sys.executable,
        str(EXTRACT_SCRIPT),
        str(input_path),
        "--output", str(output_path),
        "--extract-dir", str(extract_dir),
        "--chunk-size", str(pass_spec["chunk_size"]),
        "--agent", pass_spec["agent"],
    ]
    if endpoint:
        cmd += ["--dgx-endpoint", endpoint]
    if model:
        cmd += ["--model", model]

    where = endpoint or "default endpoint"
    print(f"  [start ] {label:20s} -> {where}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n    ".join((result.stderr or "").strip().splitlines()[-3:])
        return key, None, (
            f"pass {name!r} sample {k} on {where} failed (exit "
            f"{result.returncode}); fix the failing chunk in {extract_dir} "
            f"and re-run.\n    {tail}"
        )
    try:
        facts = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return key, None, f"pass {name!r} sample {k}: cannot read {output_path}: {e}"
    print(f"  [done  ] {label:20s} {len(facts):>3} facts  ({where})")
    return key, facts, None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the 5-lens ensemble extraction plan "
            "(small/large/sweep/temporal/interiority), optionally with "
            "self-consistency samples and fanned across multiple endpoints "
            "concurrently, then deterministically merge with subject "
            "clustering and near-duplicate fact dedup."
        )
    )
    parser.add_argument("input",
                        help="Input text file (session summary, chapter, ...)")
    parser.add_argument("--workdir", "-w", required=True, metavar="DIR",
                        help="Working directory for per-pass outputs and caches.")
    parser.add_argument("--similarity", type=float, default=0.85, metavar="RATIO",
                        help="Fact-text similarity threshold for within-group "
                             "dedup (0..1, default 0.85). Higher = stricter, "
                             "more duplicates retained; lower = looser, more "
                             "collapsed.")
    parser.add_argument("--skip", action="append", default=[], metavar="NAME",
                        choices=[p["name"] for p in PASSES],
                        help="Skip a named pass (can repeat). Useful when "
                             "iterating on prompt fixes for one lens.")
    parser.add_argument("--samples", type=int, default=1, metavar="N",
                        help="Self-consistency: run each pass N times and union "
                             "the results (default 1). Extraction is "
                             "nondeterministic (no fixed temperature/seed), so "
                             "re-sampling recovers facts a single run misses. "
                             "Each merged fact gains 'n_samples' = how many "
                             "sample-runs produced it — a confidence signal for "
                             "the human review step; nothing is auto-filtered.")
    parser.add_argument("--endpoints", nargs="+", metavar="URL",
                        help="One or more OpenAI-compatible endpoints to fan the "
                             "work across CONCURRENTLY (one in-flight unit per "
                             "endpoint, work-stealing from a shared queue for "
                             "balance). Example: --endpoints "
                             "http://192.168.1.147:8001/v1 "
                             "http://192.168.1.69:8001/v1 runs the ensemble across "
                             "both DGX Sparks. Default: a single endpoint from "
                             "$DGX_ENDPOINT (else extract_facts.py's built-in "
                             "default). All endpoints MUST serve the same --model.")
    parser.add_argument("--model", default=None, metavar="ID",
                        help="Model id sent to every endpoint (default: $DGX_MODEL, "
                             "else extract_facts.py's default). All endpoints must "
                             "serve this same model id, since the merge treats "
                             "their facts uniformly.")
    parser.add_argument("--embed-endpoint", default=os.environ.get("EMBED_ENDPOINT"),
                        metavar="URL",
                        help="OpenAI-compatible /v1/embeddings endpoint (e.g. "
                             "vllm-embed at http://192.168.1.147:8000). When set, "
                             "facts are merged by embedding cosine of the fact TEXT "
                             "(partitioned by type only), catching cross-subject "
                             "duplicates the default subject-keyed merge misses "
                             "(same event under different labels; phonetic-variant "
                             "spellings). Default ($EMBED_ENDPOINT, else unset): use "
                             "the subject-keyed SequenceMatcher merge — no embed "
                             "server needed.")
    parser.add_argument("--embed-model", default=os.environ.get("EMBED_MODEL", DEFAULT_EMBED_MODEL),
                        metavar="ID", help=f"Embedding model id (default: "
                             f"$EMBED_MODEL or {DEFAULT_EMBED_MODEL}).")
    parser.add_argument("--embed-threshold", type=float, default=0.93, metavar="COS",
                        help="Cosine threshold for the embedding merge (default "
                             "0.93). Measured separation: true duplicates ~0.97-0.98, "
                             "distinct-but-related facts ~0.75-0.78 — 0.93 sits in "
                             "the empty gap. Lower = more aggressive collapsing "
                             "(risk of merging distinct facts); higher = stricter.")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Error: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    workdir = Path(args.workdir).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    active_passes = [p for p in PASSES if p["name"] not in args.skip]
    if not active_passes:
        print("Error: no passes selected (all skipped).", file=sys.stderr)
        sys.exit(1)

    print(f"Input:    {input_path}")
    print(f"Workdir:  {workdir}")
    print(f"Passes:   {', '.join(p['name'] for p in active_passes)}")
    if args.skip:
        print(f"Skipped:  {', '.join(args.skip)}")
    if args.samples > 1:
        print(f"Samples:  {args.samples} per pass (self-consistency union)")

    # Resolve the endpoint pool. One endpoint → the old sequential behaviour;
    # several → units fan out concurrently (one in-flight unit per endpoint,
    # pulled work-stealing from a shared queue, so a faster/free box grabs the
    # next unit instead of idling). [None] means "no explicit endpoint" — each
    # extract_facts.py falls back to $DGX_ENDPOINT or its own default.
    endpoints = args.endpoints if args.endpoints else [os.environ.get("DGX_ENDPOINT")]
    model = args.model or os.environ.get("DGX_MODEL")

    units = [(p, k) for p in active_passes for k in range(1, args.samples + 1)]
    print(f"Endpoints: {', '.join(e or 'default' for e in endpoints)}")
    print(f"Units:    {len(units)} ({len(active_passes)} passes x {args.samples} "
          f"sample(s)) across {len(endpoints)} endpoint(s)")
    print("=" * 70)

    work = queue.Queue()
    for u in units:
        work.put(u)
    results: dict[str, list[dict]] = {}
    errors: list[str] = []
    lock = threading.Lock()

    def worker(endpoint: str | None) -> None:
        while True:
            try:
                pass_spec, k = work.get_nowait()
            except queue.Empty:
                return
            try:
                key, facts, err = run_unit(
                    input_path, pass_spec, k, args.samples, workdir, endpoint, model)
            except Exception as e:  # a worker must never die silently
                key, facts, err = f"{pass_spec['name']}#{k}", None, repr(e)
            with lock:
                if err:
                    errors.append(err)
                else:
                    results[key] = facts
            work.task_done()

    t0 = time.time()
    threads = [threading.Thread(target=worker, args=(ep,), daemon=True)
               for ep in endpoints]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - t0

    if errors:
        print(f"\n{len(errors)} unit(s) failed:", file=sys.stderr)
        for e in errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    pass_outputs = results
    print(f"\nExtraction wall-clock: {elapsed:.0f}s across {len(endpoints)} endpoint(s)")

    print("\n" + "=" * 70)
    if args.embed_endpoint:
        print(f"Merging (embedding cosine, threshold {args.embed_threshold}, "
              f"{args.embed_endpoint})...")
        merged = merge_facts_embed(pass_outputs, args.embed_endpoint,
                                   args.embed_model, args.embed_threshold)
    else:
        print("Merging (subject-keyed SequenceMatcher)...")
        merged = merge_facts(pass_outputs, args.similarity)

    # merge_facts tracks provenance per sample-run key ("sweep#1", "sweep#3").
    # Collapse those back to clean lens names and record how many independent
    # sample-runs produced each fact. n_samples is a confidence signal for the
    # human review step — we deliberately do NOT drop low-agreement facts, since
    # deciding what is in scope is a precision decision the human makes.
    for f in merged:
        runs = f["passes"]
        f["n_samples"] = len(runs)
        f["passes"] = sorted({p.split("#")[0] for p in runs})

    merged_path = workdir / "merged.json"
    merged_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")

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

    print(f"\nPer-lens facts (raw, summed over samples): {counts_by_lens}")
    print(f"Total merged (unique): {len(merged)}")
    print(f"By type:               {dict(sorted(counts_by_type.items()))}")
    if args.samples > 1:
        print(f"Agreement (n_samples -> #facts): {dict(sorted(agree_hist.items()))}")
    print(f"Pass coverage:")
    for combo, n in sorted(pass_combo_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {combo:30s} {n}")
    print(f"\nWritten: {merged_path}")


if __name__ == "__main__":
    main()
