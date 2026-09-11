#!/usr/bin/env python3
"""Baseline vs strict system prompt, on a given question."""
import asyncio, os, re, sys
os.chdir("/home/kostadis/cognee-local")
sys.stdout.reconfigure(line_buffering=True)
import cognee  # noqa: E402
from cognee.modules.search.types import SearchType  # noqa: E402

STRICT = """You are answering questions about an in-progress tabletop campaign from its play record.

RULES, in priority order:
1. Use ONLY the provided context. You may have prior knowledge of published
   adventures; that knowledge is NOT evidence about this campaign and must never
   appear in your answer.
2. If the context does not state something, write "Not recorded" for that point.
   Never fill a gap with what is typical, likely, or canonical elsewhere.
3. Do not infer outcomes. If the context shows a goal or a plan but not its
   result, say the result is not recorded.
4. Distinguish what is established from what characters believe or intend. Use
   "the record shows" for events and "X says/believes" for claims.
5. Prefer an incomplete answer over a complete-sounding one. An unresolved thread
   left visibly unresolved is correct; a tidy ending is a failure."""

Q = sys.argv[1]
FLAGS = ("cragmaw castle", "king grol", "nezznar", "wave echo cave", "thundertree")

ARMS = [
    ("BASELINE + play_record", dict(node_name=["play_record"]), {}),
    ("STRICT   + play_record", dict(node_name=["play_record"]), {"system_prompt": STRICT}),
    ("STRICT   + unfiltered",  dict(),                          {"system_prompt": STRICT}),
]


async def main():
    print(f"QUESTION: {Q}")
    for label, filt, pr in ARMS:
        res = await cognee.search(query_text=Q, query_type=SearchType.HYBRID_COMPLETION,
                                  datasets=["obelisk"], **filt, **pr)
        text = (getattr(res[0], "text", None) or str(res[0])) if res else "<no results>"
        print(f"\n{'='*74}\n{label}\n{'-'*74}\n{text.strip()}")
        bad = [f for f in FLAGS if re.search(f, text, re.I)]
        print(f"\n  >> flagged terms: {bad if bad else 'none'}")
        print(f"  >> hedges ('not recorded'/'unknown'/'believes'): "
              f"{'YES' if re.search(r'not recorded|unknown|believe|speculat', text, re.I) else 'no'}")

asyncio.run(main())
