#!/usr/bin/env python3
"""Experiment: does cognify(temporal_cognify=True) give cognee chapter ordering?

The default remember() path produced ZERO Event nodes, so "most recent session"
returned Chapter 8 when 10 and 11 exist. This runs the temporal pipeline instead:
  classify -> chunk -> extract_events_and_timestamps
           -> extract_knowledge_graph_from_events -> add_data_points

temporal_cognify is cognify-only (it is in remember()'s _COGNIFY_ONLY set), and
cognify needs add() to stage the data first.

Isolated root so the working 'obelisk' graph is untouched.
"""
import asyncio, os, sys, time
from pathlib import Path

os.chdir(os.path.dirname(os.path.abspath(__file__)))  # picks up THIS dir's .env
sys.stdout.reconfigure(line_buffering=True)
import cognee  # noqa: E402
import litellm  # noqa: E402

litellm.request_timeout = 1800
DATASET = "obelisk_temporal"
ROOT = Path("/home/kostadis/obelisk/obelisk/summaries")

files = sorted(
    {str(p) for pat in ("session_summary.md", "session-summary.md") for p in ROOT.rglob(pat)}
)


async def main():
    print(f"dataset={DATASET}  files={len(files)}")
    for f in files:
        print(f"   {Path(f).parent.name}/{Path(f).name}  {Path(f).stat().st_size} B")

    t0 = time.time()
    print("\n### add()")
    await cognee.add(files, dataset_name=DATASET)
    print(f"### add done in {time.time()-t0:.1f}s")

    t1 = time.time()
    print("\n### cognify(temporal_cognify=True)")
    r = await cognee.cognify(datasets=[DATASET], temporal_cognify=True)
    print(f"### cognify done in {time.time()-t1:.1f}s -> {r}")
    print(f"\n=== TOTAL {time.time()-t0:.1f}s ===")


asyncio.run(main())
