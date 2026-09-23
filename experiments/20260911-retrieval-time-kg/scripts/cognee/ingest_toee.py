#!/usr/bin/env python3
"""Full ToEE corpus ingest -- the workload validated in the 2026-08-01 retest
(3 grounding docs + 103 NPC dossiers = 106 items).

NOT run automatically. Invoke explicitly:
    cd ~/cognee-local && .venv/bin/python ingest_toee.py
"""
import asyncio, os, time
from pathlib import Path

os.chdir(os.path.dirname(os.path.abspath(__file__)))  # before import cognee (gotcha #2)
import cognee  # noqa: E402
import litellm  # noqa: E402

# 1800 was not enforced on the 2026-09-10 unbounded run: requests reported
# "timeout value=1800.0, time taken=5401.29 seconds" -- 3x over. With bounded
# concurrency nothing should queue that long, and a shorter ceiling surfaces
# trouble sooner. Set AFTER import cognee, not before.
# Restored to 1800: 600 was counterproductive -- it killed calls at the boundary
# and retried them, adding load. Note litellm makes 3 internal attempts before
# raising, so the real ceiling is 3x this value (observed 600 -> 1801s).
litellm.request_timeout = 1800

# vLLM on spark1 runs --max-num-seqs 8. Cognee classifies vLLM as cloud-like
# (llm/config.py:39) and applies no pacing, so the default data_per_batch=20
# documents -- each fanning out over its own chunks -- put ~70 requests on an
# 8-wide server. Queued requests then blew past the client timeout.
# Most of this corpus is 1-2 chunk dossiers, so 8 documents tracks seqs 8.
DATA_PER_BATCH = 8

DOCS = Path("/home/kostadis/src/campaigns/toee/docs")
FILES = [str(DOCS / n) for n in ("campaign_state.md", "party.md", "planning.md")]
FILES += sorted(str(p) for p in (DOCS / "npcs").glob("*.md"))


async def main():
    missing = [f for f in FILES if not Path(f).exists()]
    if missing:
        print(f"WARNING: {len(missing)} missing, skipping: {missing[:3]}")
    files = [f for f in FILES if Path(f).exists()]
    print(f"Ingesting {len(files)} files -> dataset 'toee'\n")

    t0 = time.time()
    result = await cognee.remember(
        files,
        dataset_name="toee",
        self_improvement=False,  # skip the self-improvement loop for a bulk ingest
        data_per_batch=DATA_PER_BATCH,
    )
    print(f"\n{result}   [{time.time() - t0:.1f}s total]")

    # Eval queries from the 2026-08-01 retest, for comparison.
    for q in (
        "Who are the player characters?",
        "What is the current state of the campaign?",
        "Who is the main villain?",
        "Who are the key NPCs?",
        "What factions are in play?",
    ):
        r = await cognee.recall(q, datasets=["toee"])
        text = r[0].text if r else "<no results>"
        print(f"\nQ: {q}\nA: {text.strip()[:600]}")


asyncio.run(main())
