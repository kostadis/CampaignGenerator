#!/usr/bin/env python3
"""Does a strict system prompt stop the fabrication that filtering could not?

Baseline prompt (cognee default) is:
    "Answer the question using the provided context. Be as brief as possible."
-- which forbids nothing. Both arms use node_name=["play_record"], whose
retrieved context contains ZERO mentions of Cragmaw Castle.
"""
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

Q = "What has happened to Gundren Rockseeker, in order? Where does his thread currently stand?"
FLAGS = ("cragmaw castle", "king grol", "nezznar", "grol")


async def main():
    for label, kw in (("BASELINE  (cognee default prompt)", {}),
                      ("STRICT    (no-outside-knowledge prompt)", {"system_prompt": STRICT})):
        res = await cognee.search(query_text=Q, query_type=SearchType.HYBRID_COMPLETION,
                                  datasets=["obelisk"], node_name=["play_record"], **kw)
        text = (getattr(res[0], "text", None) or str(res[0])) if res else "<no results>"
        print(f"\n{'='*74}\n{label}\n{'-'*74}\n{text.strip()}")
        bad = [f for f in FLAGS if re.search(f, text, re.I)]
        print(f"\n  >> unsupported-term check: {'LEAKED ' + str(bad) if bad else 'CLEAN (none present)'}")
        print(f"  >> says 'not recorded': {'YES' if re.search('not recorded', text, re.I) else 'no'}")

asyncio.run(main())
