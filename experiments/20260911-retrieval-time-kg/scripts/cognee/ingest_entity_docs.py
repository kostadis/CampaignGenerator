#!/usr/bin/env python3
"""Ingest the 253 per-entity docs into the play_record tier."""
import asyncio, os, sys, time
from pathlib import Path
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(line_buffering=True)
import cognee  # noqa: E402
import litellm  # noqa: E402

litellm.request_timeout = 1800
files = sorted(str(p) for p in Path("/home/kostadis/cognee-local/entity_docs").glob("*.md"))


async def main():
    print(f"### entity docs: {len(files)} files, "
          f"{sum(Path(f).stat().st_size for f in files)/1024:.1f} KB")
    t0 = time.time()
    r = await cognee.remember(files, dataset_name="obelisk", self_improvement=False,
                              data_per_batch=8, node_set=["play_record"])
    print(f"### DONE in {time.time()-t0:.1f}s -> {r}")

asyncio.run(main())
