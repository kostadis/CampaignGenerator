#!/usr/bin/env python3
"""Emit a triage-candidates queue from the session summaries ALONE.

Why this exists
---------------
``registry triage-candidates`` picks its corpus in ``_gather_triage_sources``
with a *presence* test::

    has_ensemble = any(next(campaign_dir.glob(p), None) is not None
                       for p in _MERGED_JSON_GLOBS)

A campaign with a 7-chapter ensemble and 51 chapters on disk therefore has its
whole summary corpus masked: the ensemble wins the test, and the remaining 44
chapters' proper nouns are never candidates. Worse, when the lineage gate is
closed (no ``summary_map.yaml``) that ensemble was itself extracted from chapter
prose — so the registry ends up sourced from the artifact you are rewriting.

This reads ``docs/summaries/*.md`` and nothing else. No chapters, no scene
extractions, no ensemble.

Two signals, tagged per candidate so the high-confidence set can be walked first:

``heading``   a ``###`` entry under ``## NPCs`` / ``## Locations`` / ``## Items``.
              An authored heading is an ASSERTION that something is an entity;
              the tokenizer only guesses that a capitalised token might be.
``mention``   ``spell_canon.proper_noun_counts`` over the ``## Scenes`` body —
              the same tokenizer ``triage-candidates`` uses, same min-len.

Everything downstream is the real library: ``norm_subject``, ``known_names``
(incl. ``party.yaml``), the ``difflib`` near-miss, and the suppression of pairs
already settled by a GM ``distinct`` / ``rejected_aliases`` ruling. Only the
corpus differs, so the output drops straight into the ``entity-triage`` skill.

Writes a queue JSON. Never touches the registry.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

CG = Path("/home/kostadis/src/CampaignGenerator")
if str(CG) not in sys.path:
    sys.path.insert(0, str(CG))

from entity_registry import spell_canon                                    # noqa: E402
from entity_registry.registry import (                                     # noqa: E402
    _best_near_miss, _registry_catalog, _suppressed_pairs,
)
from campaignlib.party import load_pc_names                                # noqa: E402
from campaignlib.registry import load_registry                             # noqa: E402
from campaignlib.textproc import norm_subject                              # noqa: E402

STATE_SECTIONS = ("NPCs", "Locations", "Items")


def sections(text: str) -> dict[str, str]:
    out, cur, buf = {}, None, []
    for ln in text.splitlines():
        m = re.match(r"^##\s+(?!#)(.*)$", ln)
        if m:
            if cur:
                out[cur] = "\n".join(buf)
            cur, buf = m.group(1).strip(), []
        elif cur is not None:
            buf.append(ln)
    if cur:
        out[cur] = "\n".join(buf)
    return out


def headings(body: str) -> list[str]:
    return [m.group(1).strip() for m in
            re.finditer(r"^###\s+(?!#)(.*)$", body or "", re.M)]


def canon_head(t: str) -> str:
    """'Wick *(Chapter 7 - carried forward)*' -> 'Wick'."""
    return re.sub(r"\s*[*(].*$", "", t).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("campaign_dir", type=Path)
    ap.add_argument("--summaries", default="docs/summaries",
                    help="relative to campaign_dir (default: docs/summaries)")
    ap.add_argument("--out", type=Path, default=None, help="queue JSON path (default: stdout)")
    ap.add_argument("--min-len", type=int, default=spell_canon.DEFAULT_MIN_LEN)
    ap.add_argument("--min-count", type=int, default=1,
                    help="applies to MENTION candidates only; a heading is one "
                         "authored assertion and is never dropped for rarity")
    ap.add_argument("--state", type=Path, default=None,
                    help="prior .entity_triage_state.json, to report overlap "
                         "(the skill does the subtraction itself)")
    args = ap.parse_args()

    cdir = args.campaign_dir.resolve()
    reg_path = cdir / "docs" / "entity_registry.yaml"
    if not reg_path.is_file():
        print(f"Error: no registry at {reg_path}", file=sys.stderr)
        return 1
    reg = load_registry(reg_path)

    sdir = cdir / args.summaries
    files = sorted(sdir.glob("*.md"))
    if not files:
        print(f"Error: no summaries under {sdir}", file=sys.stderr)
        return 1

    head_count: Counter = Counter()
    ment_count: Counter = Counter()
    srcs: dict[str, set[str]] = defaultdict(set)
    display: dict[str, str] = {}

    for f in files:
        secs = sections(f.read_text(encoding="utf-8"))
        for sec in STATE_SECTIONS:
            for h in headings(secs.get(sec, "")):
                h = canon_head(h)
                if not h:
                    continue
                k = norm_subject(h)
                head_count[k] += 1
                srcs[k].add(f.name)
                display.setdefault(k, h)
        scenes = secs.get("Scenes", "")
        if scenes:
            for surface, n in spell_canon.proper_noun_counts(scenes, args.min_len).items():
                k = norm_subject(surface)
                ment_count[k] += n
                srcs[k].add(f.name)
                display.setdefault(k, surface)

    known = reg.known_names(extra=load_pc_names(cdir))
    catalog = _registry_catalog(reg)
    suppressed = _suppressed_pairs(reg)

    candidates = []
    for k in set(head_count) | set(ment_count):
        if k in known:
            continue
        h, m = head_count.get(k, 0), ment_count.get(k, 0)
        if not h and m < args.min_count:
            continue
        signal = "both" if h and m else ("heading" if h else "mention")
        candidates.append({
            "surface": display[k],
            "norm": k,
            "count": h + m,
            "sources": sorted(srcs[k]),
            "near_miss": _best_near_miss(reg, k, catalog, suppressed),
            "signal": signal,
            "heading_count": h,
            "mention_count": m,
        })

    rank = {"heading": 0, "both": 1, "mention": 2}
    candidates.sort(key=lambda c: (rank[c["signal"]], -c["count"], c["surface"]))

    payload = {
        "campaign": reg.campaign,
        "generated_from": [f"{args.summaries}/*.md (headings under "
                           f"{'/'.join(STATE_SECTIONS)}; proper nouns in ## Scenes)"],
        "candidates": candidates,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)

    by = Counter(c["signal"] for c in candidates)
    hints = sum(1 for c in candidates if c["near_miss"])
    print(f"\n{len(files)} summaries scanned", file=sys.stderr)
    print(f"{len(candidates)} candidate(s): "
          f"{by['heading']} heading, {by['both']} both, {by['mention']} mention-only; "
          f"{hints} with near-miss hint(s)", file=sys.stderr)
    if args.state and args.state.is_file():
        st = json.loads(args.state.read_text(encoding="utf-8"))
        prior = {e["norm"] for e in st.get("ignored", []) + st.get("deferred", [])
                 if e.get("norm")}
        hit = sum(1 for c in candidates if c["norm"] in prior)
        print(f"{hit} already ruled in {args.state.name} "
              f"(the skill subtracts these at load)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
