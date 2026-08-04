#!/usr/bin/env python3
"""Prototype: split `unverified` into STITCHED vs INVENTED, deterministically.

Discovered by the T047 calibration (research.md D8b). The shipped report calls a
quote "Likely stitched" when it contains `...` — a heuristic that only fires when
the model was honest enough to write the ellipsis. This decides it mechanically
instead, with no model and no threshold:

    Greedily consume the quote left-to-right, taking the LONGEST prefix that is a
    contiguous span of the transcript, then continue from where that ran out.

    segments == 1, no orphans   -> verbatim (already `verified`)
    segments >= 2, few orphans  -> STITCHED   — every word is real, the JOIN is
                                   invented. Fix by splitting into two quotes.
    segments <= 1, many orphans -> INVENTED   — words that are not on the tape at
                                   all. Fix by deleting.

Measured on session 20260623 (see calibration/*.tsv for the corpora):

    DeepSeek (12 unverified):  9 stitched, 0 invented, 3 other
    Claude   (31 unverified): 16 stitched, 6 invented, 9 other

That DeepSeek produced ZERO quotes with unmatchable content is the single most
surprising number in the calibration — the model the feature was built to police
does not, in Stage 2, invent words at all. It joins real ones badly.

Why this matters more than the similarity score: the two classes need OPPOSITE
repairs, and the score cannot tell them apart (a stitch of two real spans can
score anywhere). "Split this" and "delete this" is an instruction; "0.63" is not.

NOT WIRED IN — proposed as T055. Run standalone:

    python segment_decomposition.py --vtt X.cleaned.vtt --scenes DIR
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "/home/kroussos/src/CampaignGenerator/.claude/worktrees/dgx-two-phase-extraction")

from campaignlib.textproc import locate_quote  # noqa: E402
from session_doc.verify_quotes import (  # noqa: E402
    SourceTranscript, Verdict, classify, parse_scene_quotes,
    parse_summary_quotes, read_preserving_newlines,
)

MIN_SEGMENT_WORDS = 3


def decompose(match_text: str, haystack: str,
              min_words: int = MIN_SEGMENT_WORDS) -> tuple[int, int]:
    """Return (contiguous transcript spans, words matched to nothing)."""
    words = match_text.split()
    i = segments = orphans = 0
    while i < len(words):
        end = 0
        for j in range(len(words), i, -1):
            if j - i < min_words:
                break
            if locate_quote(" ".join(words[i:j]), haystack) is not None:
                end = j
                break
        if end:
            segments += 1
            i = end
        else:
            orphans += 1
            i += 1
    return segments, orphans


def label(segments: int, orphans: int) -> str:
    if segments >= 2 and orphans <= 2:
        return "STITCHED"
    if segments <= 1 and orphans > 2:
        return "INVENTED"
    return "unclear"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vtt", required=True)
    ap.add_argument("--scenes")
    ap.add_argument("--summary")
    args = ap.parse_args()

    tr = SourceTranscript.load(Path(args.vtt))
    quotes = []
    if args.summary:
        p = Path(args.summary)
        quotes += parse_summary_quotes(read_preserving_newlines(p), p)
    if args.scenes:
        for f in sorted(Path(args.scenes).glob("*.md")):
            quotes += parse_scene_quotes(read_preserving_newlines(f), f)

    tally: dict[str, int] = {}
    for q in quotes:
        finding = classify(q, tr)
        if finding.verdict is not Verdict.UNVERIFIED:
            continue
        segs, orph = decompose(finding.quote.match_text, tr.haystack)
        kind = label(segs, orph)
        tally[kind] = tally.get(kind, 0) + 1
        print(f"{kind:<9} segs={segs} orphans={orph}  {q.text[:80]}")

    print("\n" + "  ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
