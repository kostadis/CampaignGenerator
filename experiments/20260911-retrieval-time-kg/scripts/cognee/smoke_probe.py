#!/usr/bin/env python3
"""One-doc end-to-end smoke test for the local Spark-backed cognee.

Validates endpoint/config before committing to a long ingest. Per gotcha #2 in
~/src/dgx-fun/cognee-dgx-setup-guide.md, chdir happens BEFORE `import cognee`
so the .env in this directory is the one that loads.
"""
import asyncio, os, sys, time

os.chdir(os.path.dirname(os.path.abspath(__file__)))
import cognee  # noqa: E402

DOC = sys.argv[1] if len(sys.argv) > 1 else "/home/kostadis/src/campaigns/toee/docs/npcs/magda.md"
QUESTION = sys.argv[2] if len(sys.argv) > 2 else "Who is Magda and what is she like?"


async def main():
    print(f"LLM      : {os.environ.get('LLM_MODEL')} @ {os.environ.get('LLM_ENDPOINT')}")
    print(f"EMBED    : {os.environ.get('EMBEDDING_MODEL')} @ {os.environ.get('EMBEDDING_ENDPOINT')}")
    print(f"DATA_ROOT: {os.environ.get('DATA_ROOT_DIRECTORY')}\n")

    t0 = time.time()
    result = await cognee.remember(DOC, dataset_name="smoke", self_improvement=False)
    print(f"\nremember(): {result}   [{time.time() - t0:.1f}s]\n")

    t1 = time.time()
    answer = await cognee.recall(QUESTION, datasets=["smoke"])
    print(f"recall({QUESTION!r})  [{time.time() - t1:.1f}s]:\n{answer}")


asyncio.run(main())
