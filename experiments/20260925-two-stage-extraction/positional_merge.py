#!/usr/bin/env python3
"""Measure what a positional signal would change in the ensemble subject merge.

The ensemble already stamps `quote_offset` (ensemble_merge.py:318) using the
same `campaignlib.textproc.locate_quote` the merge's own `quote_offset()` calls
-- but the merge DECISION never reads it. Grouping is (type, normalized
subject) and dedup inside a group is SequenceMatcher over the `fact` prose.

So two error directions are open, and this script counts both against the real
algorithm rather than arguing about them:

  MISSED  two facts in one group describing the same moment -- their quotes
          land on overlapping spans -- that stay separate because the prose
          differs. Costs the reviewer a duplicate row.

  UNSAFE  two facts whose prose is similar enough to collapse but whose quotes
          land on DISJOINT spans. Two different moments merged into one row.
          Costs a fact.

Nothing here writes to the campaign. Baseline is regenerated from the pass
files with the shipped merge_facts(), so the comparison is same-settings.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, "/home/kostadis/src/CampaignGenerator")

from campaignlib.textproc import locate_quote  # noqa: E402
from pipelines.ensemble.ensemble_merge import (  # noqa: E402
    _facts_similar,
    _fact_key,
)

# The manifests were written on a host where this repo lived under a different
# home. Same tree, different mount point -- see CLAUDE.md on the cross-machine
# split. Remap rather than rewrite the manifests.
HOME_REMAP = ("/home/kroussos/", "/home/kostadis/")


def resolve_doc(path_str: str) -> pathlib.Path:
    p = pathlib.Path(path_str.replace(*HOME_REMAP))
    return p


def span_of(fact: dict, doc: str) -> tuple[int, int] | None:
    """(start, end) of a fact's source_quote in doc, or None if unlocatable.

    End is start + len(quote); locate_quote's whitespace tolerance means the
    real matched span can differ by a few chars, which is immaterial at the
    granularity of "is this the same moment".
    """
    q = fact.get("source_quote") or ""
    if not q:
        return None
    s = locate_quote(q, doc)
    if s is None:
        return None
    return (s, s + len(q))


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def analyse_chapter(workdir: pathlib.Path, similarity: float) -> dict | None:
    manifest_path = workdir / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    doc_path = resolve_doc(manifest.get("default_input", ""))
    if not doc_path.exists():
        return {"workdir": workdir.name, "error": f"document missing: {doc_path}"}
    doc = doc_path.read_text(encoding="utf-8")

    # Load every pass output exactly as ensemble_merge would.
    pass_outputs: dict[str, list[dict]] = {}
    for p in manifest.get("passes", []):
        for out in p.get("outputs", []):
            f = workdir / out["file"]
            if f.exists():
                pass_outputs[out["key"]] = json.loads(f.read_text(encoding="utf-8"))

    n_raw = sum(len(v) for v in pass_outputs.values())
    if not n_raw:
        return {"workdir": workdir.name, "error": "no pass facts"}

    # Group exactly as merge_facts does.
    groups: dict[tuple[str, str], list[tuple[dict, str]]] = {}
    for pass_name, facts in pass_outputs.items():
        for fct in facts:
            if isinstance(fct, dict):
                groups.setdefault(_fact_key(fct), []).append((fct, pass_name))

    located = 0
    n_facts = 0
    missed: list[dict] = []
    unsafe: list[dict] = []
    merged_rows = 0

    for items in groups.values():
        # Replay the shipped greedy dedup, tracking which raw facts landed in
        # each output row so a row's constituents can be span-checked.
        kept: list[dict] = []  # each: {"fact":str, "members":[(fact,pass)]}
        for fct, pass_name in items:
            n_facts += 1
            text = fct.get("fact", "")
            matched = None
            for existing in kept:
                if _facts_similar(existing["fact"], text, similarity):
                    matched = existing
                    break
            if matched is not None:
                matched["members"].append((fct, pass_name))
                if len(text) > len(matched["fact"]):
                    matched["fact"] = text
            else:
                kept.append({"fact": text, "members": [(fct, pass_name)]})
        merged_rows += len(kept)

        # Spans for everything in this group.
        spans: dict[int, tuple[int, int] | None] = {}
        for fct, _ in items:
            sp = span_of(fct, doc)
            spans[id(fct)] = sp
            if sp is not None:
                located += 1

        # UNSAFE: a surviving row whose own members sit on disjoint spans.
        for row in kept:
            sps = [spans[id(f)] for f, _ in row["members"]]
            sps = [s for s in sps if s is not None]
            if len(sps) < 2:
                continue
            if any(not overlaps(x, y) for i, x in enumerate(sps) for y in sps[i + 1:]):
                unsafe.append(
                    {
                        "chapter": workdir.name,
                        "fact": row["fact"][:150],
                        "spans": sorted(sps),
                        "passes": sorted({p for _, p in row["members"]}),
                        "quotes": [
                            (f.get("source_quote") or "")[:90] for f, _ in row["members"]
                        ],
                    }
                )

        # MISSED: two SEPARATE rows in this group whose spans overlap.
        for i, ra in enumerate(kept):
            for rb in kept[i + 1:]:
                sa = [spans[id(f)] for f, _ in ra["members"]]
                sb = [spans[id(f)] for f, _ in rb["members"]]
                sa = [s for s in sa if s]
                sb = [s for s in sb if s]
                if any(overlaps(x, y) for x in sa for y in sb):
                    missed.append(
                        {
                            "chapter": workdir.name,
                            "a": ra["fact"][:130],
                            "b": rb["fact"][:130],
                            "quote_a": (ra["members"][0][0].get("source_quote") or "")[:90],
                            "quote_b": (rb["members"][0][0].get("source_quote") or "")[:90],
                            "span_a": sa[0],
                            "span_b": sb[0],
                        }
                    )

    return {
        "workdir": workdir.name,
        "raw_facts": n_facts,
        "merged_rows": merged_rows,
        "located": located,
        "missed": missed,
        "unsafe": unsafe,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("per_chapter_root", type=pathlib.Path)
    ap.add_argument("--similarity", type=float, default=0.85)
    ap.add_argument("--dump", type=pathlib.Path)
    args = ap.parse_args()

    dirs = sorted(d for d in args.per_chapter_root.iterdir() if d.is_dir())
    tot_raw = tot_rows = tot_loc = 0
    all_missed: list[dict] = []
    all_unsafe: list[dict] = []
    errors = []

    for d in dirs:
        r = analyse_chapter(d, args.similarity)
        if r is None:
            continue
        if "error" in r:
            errors.append((d.name, r["error"]))
            continue
        tot_raw += r["raw_facts"]
        tot_rows += r["merged_rows"]
        tot_loc += r["located"]
        all_missed += r["missed"]
        all_unsafe += r["unsafe"]

    print(f"chapters analysed : {len(dirs) - len(errors)} of {len(dirs)}")
    if errors:
        print(f"  skipped         : {len(errors)}  e.g. {errors[0]}")
    print(f"raw pass facts    : {tot_raw:,}")
    print(f"merged rows       : {tot_rows:,}  (current subject merge @ {args.similarity})")
    pct = 100 * tot_loc / tot_raw if tot_raw else 0
    print(f"quotes locatable  : {tot_loc:,} / {tot_raw:,}  ({pct:.1f}%)  <- positional signal coverage")
    print()
    print(f"MISSED merges     : {len(all_missed):,} pairs  "
          f"(separate rows, overlapping source spans)")
    print(f"UNSAFE merges     : {len(all_unsafe):,} rows   "
          f"(collapsed rows whose members sit on disjoint spans)")

    if all_missed:
        print("\n--- MISSED sample ---")
        for m in all_missed[:4]:
            print(f"[{m['chapter']}]")
            print(f"   A {m['span_a']} {m['a']!r}")
            print(f"   B {m['span_b']} {m['b']!r}")
            print(f"   quote A: {m['quote_a']!r}")
            print(f"   quote B: {m['quote_b']!r}\n")
    if all_unsafe:
        print("--- UNSAFE sample ---")
        for u in all_unsafe[:4]:
            print(f"[{u['chapter']}] passes={u['passes']} spans={u['spans']}")
            print(f"   kept fact: {u['fact']!r}")
            for q in u["quotes"]:
                print(f"   quote: {q!r}")
            print()

    if args.dump:
        args.dump.write_text(
            json.dumps({"missed": all_missed, "unsafe": all_unsafe}, indent=2),
            encoding="utf-8",
        )
        print(f"-> {args.dump}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
