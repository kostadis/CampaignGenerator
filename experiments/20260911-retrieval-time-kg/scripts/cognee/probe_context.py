#!/usr/bin/env python3
"""What did RETRIEVAL actually return, before the LLM wrote anything?

only_context=True returns the retrieved context with no completion.
query_type is pinned because unspecified hybrid may defer to GRAPH_COMPLETION.
"""
import asyncio, os, re, sys
os.chdir("/home/kostadis/cognee-local")
sys.stdout.reconfigure(line_buffering=True)
import cognee  # noqa: E402
from cognee.modules.search.types import SearchType  # noqa: E402

Q = "What has happened to Gundren Rockseeker, in order? Where does his thread currently stand?"
PROBES = ("cragmaw castle", "king grol", "nezznar", "rescue", "co-administers")


async def main():
    for label, kw in (("play_record", dict(node_name=["play_record"])),
                      ("module_canon", dict(node_name=["module_canon"])),
                      ("unfiltered", dict())):
        res = await cognee.search(query_text=Q, query_type=SearchType.HYBRID_COMPLETION,
                                  datasets=["obelisk"], only_context=True, **kw)
        text = "\n".join(str(getattr(r, "text", None) or getattr(r, "value", None) or r)
                         for r in (res or []))
        print(f"\n{'='*74}\n{label.upper()}  — retrieved context: {len(text)} chars\n{'-'*74}")
        for p in PROBES:
            hits = [m.start() for m in re.finditer(p, text, re.I)]
            print(f"  {p:<16} {len(hits):>3} occurrence(s)")
        # show the sentences that mention Gundren AND castle
        for sent in re.split(r"(?<=[.!?])\s+", text):
            if re.search("gundren", sent, re.I) and re.search("castle|grol", sent, re.I):
                print(f"    >> {sent.strip()[:220]}")

asyncio.run(main())
