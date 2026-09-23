#!/usr/bin/env python3
"""Re-ingest the obelisk corpus with provenance node_set tags.

Each tier is its own remember() call because node_set takes one value per call
(remember.py: `return requested_node_set[0]`). Tags make the module/play
distinction queryable: search(node_name=["play_record"]) cannot surface the
module's Cragmaw Castle rescue, which has not happened at this table.
"""
import asyncio, json, os, sys, time
from pathlib import Path

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(line_buffering=True)
import cognee  # noqa: E402
import litellm  # noqa: E402

litellm.request_timeout = 1800
DATASET = "obelisk"
ORDER = ["play_record", "module_canon", "curated_state", "prep_plan", "superseded"]
manifest = json.loads(Path("/home/kostadis/cognee-local/tier_manifest.json").read_text())


async def main():
    for t in ORDER:
        print(f"  {t:<15} {len(manifest[t]):>4} files")
    grand = time.time()
    for tier in ORDER:
        files = manifest[tier]
        if not files:
            continue
        print(f"\n### tier '{tier}': {len(files)} files")
        t0 = time.time()
        try:
            r = await cognee.remember(files, dataset_name=DATASET, self_improvement=False,
                                      data_per_batch=8, node_set=[tier])
            print(f"### tier '{tier}' DONE in {time.time()-t0:.1f}s -> {r}")
        except Exception as e:
            print(f"### tier '{tier}' FAILED after {time.time()-t0:.1f}s: {type(e).__name__}: {e}")
    print(f"\n=== ALL TIERS in {time.time()-grand:.1f}s ===")

asyncio.run(main())
