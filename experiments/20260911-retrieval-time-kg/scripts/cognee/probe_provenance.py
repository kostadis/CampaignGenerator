#!/usr/bin/env python3
"""The provenance test.

Gundren's rescue at Cragmaw Castle is MODULE canon (name_glossary.md:
"co-administers the mine after rescue"). It has NOT happened at this table --
his last appearance in the play record is session 7, and Ch.10-11 show the party
still hunting for the castle's location.

Untagged, cognee reported the rescue as history. If node_set tagging works,
filtering to 'play_record' should make that claim unreachable.

node_name filtering is a search() parameter, not recall().
"""
import asyncio, os, sys
os.chdir("/home/kostadis/cognee-local")
sys.stdout.reconfigure(line_buffering=True)
import cognee  # noqa: E402
from cognee.modules.search.types import SearchType  # noqa: E402

Q = "What has happened to Gundren Rockseeker, in order? Where does his thread currently stand?"


def show(label, res):
    print(f"\n{'='*74}\n{label}\n{'-'*74}")
    if not res:
        print("<no results>"); return
    r = res[0]
    print(getattr(r, "text", None) or getattr(r, "value", None) or str(r))


async def main():
    for label, kwargs in (
        ("A) play_record ONLY  (should NOT contain a Cragmaw rescue)",
         dict(node_name=["play_record"])),
        ("B) module_canon ONLY (this is where the rescue lives)",
         dict(node_name=["module_canon"])),
        ("C) unfiltered        (the original failure)",
         dict()),
    ):
        try:
            res = await cognee.search(query_text=Q, query_type=SearchType.HYBRID_COMPLETION,
                                      datasets=["obelisk"], **kwargs)
            show(label, res)
        except Exception as e:
            print(f"\n{label}\n  FAILED: {type(e).__name__}: {str(e)[:300]}")

asyncio.run(main())
