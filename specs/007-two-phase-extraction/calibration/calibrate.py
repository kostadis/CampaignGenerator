#!/usr/bin/env python3
"""T047 — threshold calibration support.

Dumps EVERY quote's similarity score so the near/unverified boundary can be
chosen from a distribution instead of a preference, and sweeps candidate
thresholds to show what each would cost in findings.

This decides nothing. It surfaces candidates with their evidence; where the
boundary goes is the GM's call (Constitution II).

    python calibrate.py --vtt X.vtt --scenes DIR [--summary FILE] --label deepseek
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve()
for p in (Path("/home/kroussos/src/CampaignGenerator/.claude/worktrees/dgx-two-phase-extraction"),):
    sys.path.insert(0, str(p))

from session_doc.verify_quotes import (  # noqa: E402
    SourceTranscript, Verdict, classify, parse_scene_quotes,
    parse_summary_quotes, read_preserving_newlines,
)


def collect(vtt: Path, summary: Path | None, scenes: Path | None):
    tr = SourceTranscript.load(vtt)
    findings = []
    if summary and summary.exists():
        text = read_preserving_newlines(summary)
        findings += [(summary.name, classify(q, tr)) for q in parse_summary_quotes(text, summary)]
    if scenes and scenes.exists():
        for f in sorted(scenes.glob("*.md")):
            text = read_preserving_newlines(f)
            findings += [(f.name, classify(q, tr)) for q in parse_scene_quotes(text, f)]
    return tr, findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vtt", required=True)
    ap.add_argument("--summary")
    ap.add_argument("--scenes")
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", help="TSV of every scored quote")
    args = ap.parse_args()

    tr, findings = collect(
        Path(args.vtt),
        Path(args.summary) if args.summary else None,
        Path(args.scenes) if args.scenes else None,
    )
    if not findings:
        print("no quotes parsed — nothing to calibrate", file=sys.stderr)
        return 2

    counts = {v: 0 for v in Verdict}
    for _, f in findings:
        counts[f.verdict] += 1
    total = len(findings)

    print(f"\n=== {args.label} | {total} quotes | VTT: {Path(args.vtt).name} ===")
    for v in Verdict:
        if counts[v]:
            print(f"  {v.value:<12} {counts[v]:>4}  ({counts[v] * 100 // total}%)")

    # Only SCORED quotes (near/unverified) have a threshold-sensitive verdict;
    # verbatim matches and exempt/unscored ones never move.
    scored = sorted(
        [(f.score, name, f) for name, f in findings if f.score is not None],
        key=lambda t: t[0],
    )
    print(f"\n  scored (threshold-sensitive): {len(scored)} of {total}")
    if not scored:
        return 0

    print("\n  --- threshold sweep: how many quotes land in 'unverified' ---")
    print("   thresh   unverified   near")
    for t in (0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95):
        u = sum(1 for s, _, _ in scored if s < t)
        print(f"    {t:.2f}      {u:>5}      {len(scored) - u:>4}")

    print("\n  --- 25 lowest-scoring quotes (most likely fabricated) ---")
    for s, name, f in scored[:25]:
        q = f.quote.text.replace("\n", " ")[:88]
        near = (f.nearest_line or "")[:88]
        print(f"\n   score {s:.3f}  [{name}]")
        print(f"     quote : {q}")
        print(f"     vtt   : {near}")

    if args.out:
        lines = ["score\tverdict\tfile\tquote\tnearest_vtt_line"]
        for s, name, f in scored:
            q = f.quote.text.replace("\t", " ").replace("\n", " ")
            n = (f.nearest_line or "").replace("\t", " ").replace("\n", " ")
            lines.append(f"{s:.4f}\t{f.verdict.value}\t{name}\t{q}\t{n}")
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n  wrote {args.out} ({len(scored)} scored rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
