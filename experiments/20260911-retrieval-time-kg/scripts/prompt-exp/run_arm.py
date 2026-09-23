#!/usr/bin/env python3
"""One arm of the extraction-prompt A/B.  usage: run_arm.py A|B"""
import asyncio, os, sys, time
from pathlib import Path

ARM = sys.argv[1]
os.chdir(f"/home/kostadis/cognee-local/prompt-exp/{ARM}")   # picks up this arm's .env
sys.stdout.reconfigure(line_buffering=True)
import cognee  # noqa: E402
import litellm  # noqa: E402
litellm.request_timeout = 1800

ROOT = Path("/home/kostadis/obelisk/obelisk/summaries")
files = sorted({str(p) for pat in ("session_summary.md", "session-summary.md")
                for p in ROOT.rglob(pat)})
CUSTOM = (Path("/home/kostadis/cognee-local/prompt-exp/stripped_prompt.txt").read_text()
          if ARM == "B" else None)


async def main():
    print(f"ARM {ARM}: {'STRIPPED prompt' if CUSTOM else 'DEFAULT prompt'}, {len(files)} files")
    await cognee.add(files, dataset_name="pexp")
    t0 = time.time()
    r = await cognee.cognify(datasets=["pexp"], custom_prompt=CUSTOM)
    print(f"ARM {ARM} COGNIFY DONE in {time.time()-t0:.1f}s")

asyncio.run(main())
