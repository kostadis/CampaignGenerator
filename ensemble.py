#!/usr/bin/env python3
"""Driver: run the ensemble generation, then the merge, in one command.

This is the convenient all-in-one entrypoint. It subprocesses the two halves
of the pipeline (mirroring how ``ensemble_extract.py`` subprocesses
``extract_facts.py``):

1. ``ensemble_extract.py`` — generation. Runs the passes, writes per-pass
   ``*.json`` + ``manifest.json`` into the workdir.
2. ``ensemble_merge.py`` — merge. Reads the manifest, writes ``merged.json``.

The two phases stay decoupled: extraction is configured by an extract-plan YAML
(``--plan``, passes + documents) and merging by a separate merge-config YAML
(``--merge-config``, method + settings). After a run you can re-merge the same
generation directly:

    python ensemble_merge.py --workdir WORKDIR --method subject

Usage:

    python ensemble.py session.md --workdir runs/s1
    python ensemble.py --workdir runs/s1 --plan extract.yaml --merge-config merge.yaml \\
        --endpoints http://192.168.1.147:8001/v1 http://192.168.1.69:8001/v1
"""

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXTRACT = HERE / "ensemble_extract.py"
MERGE = HERE / "ensemble_merge.py"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run ensemble generation (ensemble_extract.py) then merge "
            "(ensemble_merge.py) in one command. Extraction and merge are "
            "configured by separate YAMLs (--plan vs --merge-config)."
        )
    )
    # Shared / generation
    parser.add_argument("input", nargs="?",
                        help="Default input text file (optional when --plan "
                             "gives every pass its own 'document').")
    parser.add_argument("--workdir", "-w", required=True, metavar="DIR",
                        help="Working directory for per-pass outputs, manifest, "
                             "and merged.json.")
    parser.add_argument("--plan", metavar="YAML",
                        help="Extract-plan YAML (passes + documents). Passed to "
                             "ensemble_extract.py.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve and print the extract plan only; skip "
                             "generation and merge.")
    parser.add_argument("--samples", type=int, default=1, metavar="N",
                        help="Self-consistency samples per pass (default 1).")
    parser.add_argument("--endpoints", nargs="+", metavar="URL",
                        help="OpenAI-compatible endpoints to fan across "
                             "concurrently (default: $DGX_ENDPOINT).")
    parser.add_argument("--chunk-parallel", type=int, default=4, metavar="N",
                        help="In-flight chunk requests per endpoint (default 4, "
                             "matching the Sparks' vLLM --max-num-seqs; 1 = old "
                             "sequential behaviour).")
    parser.add_argument("--model", default=None, metavar="ID",
                        help="Model id sent to every endpoint (default: $DGX_MODEL).")
    parser.add_argument("--skip", action="append", default=[], metavar="NAME",
                        help="Skip a named pass (can repeat).")
    parser.add_argument("--speculative", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="Speculative straggler re-execution (default ON, "
                             "needs 2+ endpoints).")
    parser.add_argument("--spec-min-age", type=float, default=60.0, metavar="SEC",
                        help="Min age before a unit is speculatively duplicated "
                             "(default 60).")
    parser.add_argument("--unit-timeout", type=float, default=600.0, metavar="SEC",
                        help="Per-unit wall-clock cap (default 600; 0 disables).")
    parser.add_argument("--unit-retries", type=int, default=3, metavar="N",
                        help="Max timeouts per unit before it fails (default 3).")
    # Merge
    parser.add_argument("--merge-config", metavar="YAML",
                        help="Merge-config YAML (method + settings). Passed to "
                             "ensemble_merge.py as --config.")
    parser.add_argument("--method", choices=["subject", "embed"], default=None,
                        help="Merge method override (subject|embed).")
    parser.add_argument("--similarity", type=float, default=None, metavar="RATIO",
                        help="Subject-merge similarity threshold override.")
    parser.add_argument("--embed-endpoint", default=None, metavar="URL",
                        help="Embedding endpoint override for the embed merge.")
    parser.add_argument("--embed-model", default=None, metavar="ID",
                        help="Embedding model override.")
    parser.add_argument("--embed-threshold", type=float, default=None, metavar="COS",
                        help="Embedding cosine threshold override.")
    args = parser.parse_args()

    # ── Phase 1: generation ──────────────────────────────────────────────────
    extract_cmd = [sys.executable, str(EXTRACT), "--workdir", args.workdir]
    if args.input:
        extract_cmd.insert(2, args.input)          # positional after script path
    if args.plan:
        extract_cmd += ["--plan", args.plan]
    if args.dry_run:
        extract_cmd += ["--dry-run"]
    extract_cmd += ["--samples", str(args.samples)]
    if args.endpoints:
        extract_cmd += ["--endpoints", *args.endpoints]
    extract_cmd += ["--chunk-parallel", str(args.chunk_parallel)]
    if args.model:
        extract_cmd += ["--model", args.model]
    for s in args.skip:
        extract_cmd += ["--skip", s]
    if not args.speculative:
        extract_cmd += ["--no-speculative"]
    extract_cmd += ["--spec-min-age", str(args.spec_min_age)]
    extract_cmd += ["--unit-timeout", str(args.unit_timeout)]
    extract_cmd += ["--unit-retries", str(args.unit_retries)]

    print(f"[ensemble] generation: {' '.join(extract_cmd)}", flush=True)
    rc = subprocess.run(extract_cmd).returncode
    if rc != 0:
        print(f"[ensemble] generation failed (exit {rc}); not merging.",
              file=sys.stderr)
        sys.exit(rc)
    if args.dry_run:
        return  # nothing generated; nothing to merge

    # ── Phase 2: merge ───────────────────────────────────────────────────────
    merge_cmd = [sys.executable, str(MERGE), "--workdir", args.workdir]
    if args.merge_config:
        merge_cmd += ["--config", args.merge_config]
    if args.method:
        merge_cmd += ["--method", args.method]
    if args.similarity is not None:
        merge_cmd += ["--similarity", str(args.similarity)]
    if args.embed_endpoint:
        merge_cmd += ["--embed-endpoint", args.embed_endpoint]
    if args.embed_model:
        merge_cmd += ["--embed-model", args.embed_model]
    if args.embed_threshold is not None:
        merge_cmd += ["--embed-threshold", str(args.embed_threshold)]

    print(f"\n[ensemble] merge: {' '.join(merge_cmd)}", flush=True)
    rc = subprocess.run(merge_cmd).returncode
    if rc != 0:
        print(f"[ensemble] merge failed (exit {rc}).", file=sys.stderr)
        sys.exit(rc)


if __name__ == "__main__":
    main()
