#!/usr/bin/env python3
"""Compare a langextract run against the ensemble's own passes on one chapter.

Row counts are a weak recall proxy -- a harness that splits the same moment
into three rows looks better than one that doesn't. So the primary metric here
is SOURCE COVERAGE: what fraction of the chapter's characters sit inside at
least one quote span. That is harness-neutral and answers "how much of the
chapter did this actually reach".

Reported per side:
  rows       raw row count
  grounded   rows whose quote resolves in the chapter
  coverage   % of chapter chars inside >=1 resolved span
  spans      distinct resolved spans (dedup by (start,end))
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, "/home/kostadis/src/CampaignGenerator")
from campaignlib.textproc import locate_quote  # noqa: E402


def spans_for(rows, doc, quote_key="source_quote"):
    out = []
    for r in rows:
        q = (r.get(quote_key) or "").strip()
        if not q:
            continue
        s = locate_quote(q, doc)
        if s is not None:
            out.append((s, s + len(q)))
    return out


def coverage(spans, n):
    if not spans:
        return 0.0
    merged = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return 100.0 * sum(e - s for s, e in merged) / n


def load(p):
    d = json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    return d if isinstance(d, list) else d.get("facts", [])


def report(label, rows, doc):
    sp = spans_for(rows, doc)
    uniq = len(set(sp))
    print(
        f"  {label:<28} rows {len(rows):>5}   grounded {len(sp):>5} "
        f"({100*len(sp)/max(len(rows),1):>5.1f}%)   spans {uniq:>5}   "
        f"coverage {coverage(sp, len(doc)):>5.1f}%"
    )
    return sp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter_md", type=pathlib.Path)
    ap.add_argument("--lx", type=pathlib.Path, required=True)
    ap.add_argument("--ensemble-dir", type=pathlib.Path, required=True)
    args = ap.parse_args()

    doc = args.chapter_md.read_text(encoding="utf-8")
    print(f"\n=== {args.chapter_md.name}  ({len(doc):,} chars) ===")

    lx_rows = load(args.lx)
    lx_sp = report("langextract (1 pass, 15K)", lx_rows, doc)

    large = args.ensemble_dir / "large.json"
    if large.exists():
        report("ensemble  large lens only", load(large), doc)

    for name in ("small", "sweep", "temporal", "interiority"):
        f = args.ensemble_dir / f"{name}.json"
        if f.exists():
            report(f"ensemble  {name} lens", load(f), doc)

    merged = args.ensemble_dir / "merged.json"
    if merged.exists():
        ens_sp = report("ensemble  5-lens MERGED", load(merged), doc)
        # What did each side reach that the other did not?
        def touched(spans):
            s = set()
            for a, b in spans:
                s.update(range(a, b))
            return s
        lset, eset = touched(lx_sp), touched(ens_sp)
        n = len(doc)
        print(f"\n  chars reached by langextract only : {len(lset - eset):>7,} ({100*len(lset-eset)/n:.1f}%)")
        print(f"  chars reached by ensemble only    : {len(eset - lset):>7,} ({100*len(eset-lset)/n:.1f}%)")
        print(f"  chars reached by both             : {len(lset & eset):>7,} ({100*len(lset&eset)/n:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
