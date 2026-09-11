#!/usr/bin/env python3
"""Obelisk corpus ingest.

Three groups, run as stages into ONE dataset ('obelisk'):
  1. session summaries  -- both spellings: session_summary.md AND session-summary.md
                           (8 dirs use the hyphen, 3 use the underscore)
  2. docs/**/*.md
  3. the file refs.yaml points at, resolved through refs.local.yaml roots

Stages give incremental results and isolate a failure to one group instead of
losing the whole run. Same dataset, so recall() sees all of it.

    cd ~/cognee-local && .venv/bin/python ingest_obelisk.py
"""
import asyncio, os, sys, time
from pathlib import Path

os.chdir(os.path.dirname(os.path.abspath(__file__)))  # before import cognee (gotcha #2)
sys.stdout.reconfigure(line_buffering=True)  # stage lines must hit the log immediately
import cognee  # noqa: E402
import litellm  # noqa: E402

litellm.request_timeout = 1800  # litellm makes 3 internal attempts: real ceiling is 3x
DATA_PER_BATCH = 8              # vLLM on spark1 runs --max-num-seqs 8
DATASET = "obelisk"

ROOT = Path("/home/kostadis/obelisk/obelisk")

# Excluded by request 2026-09-10: 620 KB, half the docs stage on its own.
EXCLUDE = {ROOT / "docs" / "background" / "obelisk.md"}

# Restrict stages for a resumed run, e.g. OBELISK_STAGES=docs,refs
ONLY = {s.strip() for s in os.environ.get("OBELISK_STAGES", "").split(",") if s.strip()}


def summaries():
    out = set()
    for pattern in ("session_summary.md", "session-summary.md"):
        out.update(str(p) for p in (ROOT / "summaries").rglob(pattern))
    return sorted(out)


def docs():
    return sorted(str(p) for p in (ROOT / "docs").rglob("*.md") if p not in EXCLUDE)


def notes():
    """notes/**/*.md only. The 3 non-markdown files there are tooling state
    (.scrub_state.json, .vtt_spell_pass_state.json, mempalace.yaml), not
    campaign content -- ingesting them injects junk entities."""
    return sorted(str(p) for p in (ROOT / "notes").rglob("*.md"))


def refs():
    """Resolve refs.yaml entries against refs.local.yaml roots."""
    import yaml

    spec = yaml.safe_load((ROOT / "config" / "refs.yaml").read_text()) or {}
    local = yaml.safe_load((ROOT / "config" / "refs.local.yaml").read_text()) or {}
    roots = local.get("roots", {})

    resolved, missing = [], []
    for ref in spec.get("refs", []):
        rel = ref.get("rpglib")
        library = ref.get("library")
        root = roots.get(f"rpg_library_{library}")
        if not (rel and root):
            missing.append(f"unresolvable ref: {ref}")
            continue
        path = Path(root) / rel
        (resolved if path.exists() else missing).append(str(path))
    for m in missing:
        print(f"  !! {m}")
    return resolved


STAGES = [("summaries", summaries()), ("docs", docs()), ("notes", notes()), ("refs", refs())]
if ONLY:
    STAGES = [(n, f) for n, f in STAGES if n in ONLY]


async def main():
    print(f"dataset={DATASET}  data_per_batch={DATA_PER_BATCH}\n")
    for name, files in STAGES:
        total = sum(Path(f).stat().st_size for f in files)
        print(f"  {name:10} {len(files):4d} files  {total/1024:9.1f} KB")
    print()

    grand = time.time()
    for name, files in STAGES:
        if not files:
            print(f"\n### {name}: nothing to do, skipping")
            continue
        print(f"\n### stage '{name}': {len(files)} files")
        t0 = time.time()
        try:
            r = await cognee.remember(
                files,
                dataset_name=DATASET,
                self_improvement=False,
                data_per_batch=DATA_PER_BATCH,
            )
            print(f"### stage '{name}' DONE in {time.time()-t0:.1f}s -> {r}")
        except Exception as e:
            print(f"### stage '{name}' FAILED after {time.time()-t0:.1f}s: {type(e).__name__}: {e}")
    print(f"\n=== ALL STAGES in {time.time()-grand:.1f}s ===")

    for q in (
        "What is the Obelisk?",
        "Who are the player characters?",
        "What happened in the most recent session?",
        "What factions are in Phandalin?",
    ):
        try:
            r = await cognee.recall(q, datasets=[DATASET])
            print(f"\nQ: {q}\nA: {(r[0].text.strip() if r else '<no results>')[:700]}")
        except Exception as e:
            print(f"\nQ: {q}\nA: FAILED {type(e).__name__}: {e}")


asyncio.run(main())
