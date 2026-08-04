#!/usr/bin/env python3
"""T053 three-way: Claude pre-fix vs Claude post-fix vs DeepSeek post-fix.

Isolates the confound in D8b. All three scored against the SAME VTT, over the
same 6 scenes, from the same Stage 1 summary, none with --dossier-dir.

If Claude post-fix looks like Claude pre-fix -> the 20% stitching rate is
Claude-the-model, and D1's headline is a model property.
If Claude post-fix looks like DeepSeek     -> the pre-fix code path was
responsible and D1's headline was measuring a bug.
"""
import sys
from pathlib import Path

ROOT = "/home/kroussos/src/CampaignGenerator/.claude/worktrees/dgx-two-phase-extraction"
sys.path.insert(0, ROOT)

from campaignlib.textproc import locate_quote  # noqa: E402
from session_doc.verify_quotes import (  # noqa: E402
    SourceTranscript, Verdict, classify, parse_scene_quotes, read_preserving_newlines,
)

SESS = Path("/home/kroussos/Phandalin/Phandalin/summaries/20260623")
SCRATCH = Path("/tmp/claude-1000/-home-kroussos-src-CampaignGenerator/"
               "1d9a0cda-e7bf-463a-a9a8-4a161baf615b/scratchpad/t047")
VTT = SESS / "GMT20260624-035836_Recording.transcript.cleaned.vtt"

CORPORA = [
    ("Claude PRE-fix  (2026-06-26)", SESS / "scene_extractions_new"),
    ("Claude POST-fix (T053)",       SCRATCH / "scenes_claude_postfix"),
    ("DeepSeek POST-fix",            SCRATCH / "scenes_deepseek"),
]


def decompose(text, haystack, min_words=3):
    w = text.split(); i = segs = orph = 0
    while i < len(w):
        end = 0
        for j in range(len(w), i, -1):
            if j - i < min_words:
                break
            if locate_quote(" ".join(w[i:j]), haystack) is not None:
                end = j; break
        if end:
            segs += 1; i = end
        else:
            orph += 1; i += 1
    return segs, orph


def main():
    tr = SourceTranscript.load(VTT)
    print(f"VTT: {VTT.name} ({len(tr.spoken)} cues)\n")
    hdr = f"{'corpus':<30}{'quotes':>7}{'verbatim':>10}{'%':>6}{'near':>6}{'unver':>7}{'non-contig':>12}{'%':>6}"
    print(hdr); print("-" * len(hdr))
    detail = []
    for name, d in CORPORA:
        if not d.exists():
            print(f"{name:<30}  MISSING {d}"); continue
        counts = {}; unver = []
        n = 0
        for f in sorted(d.glob("*.md")):
            for q in parse_scene_quotes(read_preserving_newlines(f), f):
                fn = classify(q, tr); n += 1
                counts[fn.verdict] = counts.get(fn.verdict, 0) + 1
                if fn.verdict is Verdict.UNVERIFIED:
                    unver.append(fn)
        v = counts.get(Verdict.VERIFIED, 0)
        nr = counts.get(Verdict.NEAR, 0)
        uv = counts.get(Verdict.UNVERIFIED, 0)
        noncontig = n - v
        print(f"{name:<30}{n:>7}{v:>10}{v*100//max(n,1):>5}%{nr:>6}{uv:>7}"
              f"{noncontig:>12}{noncontig*100//max(n,1):>5}%")
        st = inv = other = 0
        for fn in unver:
            s, o = decompose(fn.quote.match_text, tr.haystack)
            if s >= 2 and o <= 2: st += 1
            elif s <= 1 and o > 2: inv += 1
            else: other += 1
        detail.append((name, uv, st, inv, other))

    print("\nunverified, decomposed (T055 discriminator):")
    print(f"{'corpus':<30}{'unver':>7}{'stitched':>10}{'INVENTED':>10}{'unclear':>9}")
    for name, uv, st, inv, other in detail:
        print(f"{name:<30}{uv:>7}{st:>10}{inv:>10}{other:>9}")


if __name__ == "__main__":
    main()
