#!/usr/bin/env python3
"""
Multi-chapter ensemble batch driver.

Runs ensemble.py over every chapter file matching --chapters, one workdir
per chapter under --per-chapter-dir.  Chapters whose merged.json already
exists are skipped — the run is resumable.

After all chapters succeed, the per-chapter merged.json files are
concatenated into --out with a source_chapter field added to each fact for
downstream provenance tracking.

This is the generalised replacement for the campaign-local run.py scripts
that previously lived alongside each campaign's ensemble directory.
"""
import argparse
import glob as glob_module
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_CG_DIR = Path(__file__).parent.resolve()
ENSEMBLE = _CG_DIR / "ensemble.py"


def _build_parser():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--chapters", required=True, metavar="GLOB",
        help="Glob for chapter files, e.g. 'docs/chapters/chapter_*.md'",
    )
    p.add_argument(
        "--per-chapter-dir", default="per_chapter", metavar="DIR",
        help="Root directory for per-chapter workdirs (default: ./per_chapter)",
    )
    p.add_argument(
        "--out", default="merged.json", metavar="FILE",
        help="Combined output path (default: ./merged.json)",
    )
    p.add_argument(
        "--chapter-parallel", type=int, default=3, metavar="N",
        help="Chapters to run concurrently (default: 3)",
    )

    # ensemble.py pass-through flags
    p.add_argument("--plan", metavar="YAML",
                   help="Extract-plan YAML (default: plan.yaml if it exists)")
    p.add_argument("--samples", type=int, metavar="N",
                   help="Self-consistency samples per pass")
    p.add_argument("--endpoints", nargs="+", metavar="URL",
                   help="OpenAI-compatible endpoints")
    p.add_argument("--model", metavar="ID",
                   help="Model id sent to every endpoint")
    p.add_argument("--chunk-parallel", type=int, metavar="N",
                   help="In-flight chunk requests per endpoint (default: ensemble.py default)")
    p.add_argument("--pass-parallel", type=int, metavar="N",
                   help="Passes to run concurrently per chapter (default: one per endpoint)")
    p.add_argument("--skip", action="append", metavar="NAME", default=[],
                   help="Skip a named pass (repeatable)")
    spec = p.add_mutually_exclusive_group()
    spec.add_argument("--speculative", dest="speculative", action="store_true",
                      default=None, help="Enable speculative re-execution")
    spec.add_argument("--no-speculative", dest="speculative", action="store_false",
                      help="Disable speculative re-execution")
    p.add_argument("--unit-timeout", type=int, metavar="SEC",
                   help="Per-unit wall-clock cap in seconds")
    p.add_argument("--unit-retries", type=int, metavar="N",
                   help="Max timeouts per unit before failure")
    p.add_argument("--embed-endpoint", metavar="URL",
                   help="Embedding endpoint for embed-merge")
    p.add_argument("--embed-model", metavar="ID",
                   help="Embedding model id")
    p.add_argument("--embed-threshold", type=float, metavar="COS",
                   help="Embedding cosine threshold override")
    p.add_argument("--method", choices=["subject", "embed"],
                   help="Merge method override")
    p.add_argument("--merge-config", metavar="YAML",
                   help="Merge-config YAML (passed to ensemble.py)")
    return p


def _build_ensemble_cmd(chapter: Path, workdir: Path, args) -> list[str]:
    cmd = [sys.executable, str(ENSEMBLE), str(chapter), "--workdir", str(workdir)]

    plan = args.plan
    if plan is None:
        default_plan = Path("plan.yaml")
        if default_plan.exists():
            plan = str(default_plan)
    if plan:
        cmd += ["--plan", plan]

    if args.endpoints:
        cmd += ["--endpoints"] + args.endpoints
    if args.model:
        cmd += ["--model", args.model]
    if args.samples is not None:
        cmd += ["--samples", str(args.samples)]
    if args.chunk_parallel is not None:
        cmd += ["--chunk-parallel", str(args.chunk_parallel)]
    if args.pass_parallel is not None:
        cmd += ["--pass-parallel", str(args.pass_parallel)]
    for name in args.skip:
        cmd += ["--skip", name]
    if args.speculative is True:
        cmd += ["--speculative"]
    elif args.speculative is False:
        cmd += ["--no-speculative"]
    if args.unit_timeout is not None:
        cmd += ["--unit-timeout", str(args.unit_timeout)]
    if args.unit_retries is not None:
        cmd += ["--unit-retries", str(args.unit_retries)]
    if args.embed_endpoint:
        cmd += ["--embed-endpoint", args.embed_endpoint]
    if args.embed_model:
        cmd += ["--embed-model", args.embed_model]
    if args.embed_threshold is not None:
        cmd += ["--embed-threshold", str(args.embed_threshold)]
    if args.method:
        cmd += ["--method", args.method]
    if args.merge_config:
        cmd += ["--merge-config", args.merge_config]

    return cmd


def main():
    args = _build_parser().parse_args()

    chapters = sorted(Path(p) for p in glob_module.glob(args.chapters))
    if not chapters:
        print(f"No chapter files matched: {args.chapters}", file=sys.stderr)
        sys.exit(1)

    per_chapter_dir = Path(args.per_chapter_dir)
    per_chapter_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out)

    print(f"Chapters:        {len(chapters)}")
    print(f"Per-chapter dir: {per_chapter_dir}")
    print(f"Combined output: {out_path}")
    print()

    print_lock = threading.Lock()

    def run_chapter(chapter: Path) -> tuple[Path, bool]:
        workdir = per_chapter_dir / chapter.stem
        merged = workdir / "merged.json"
        if merged.exists():
            with print_lock:
                print(f"[skip]          {chapter.stem}")
            return chapter, True
        with print_lock:
            print(f"[extract+merge] {chapter.stem}")
        workdir.mkdir(exist_ok=True)
        cmd = _build_ensemble_cmd(chapter, workdir, args)
        result = subprocess.run(cmd)
        ok = result.returncode == 0
        if not ok:
            with print_lock:
                print(f"  ERROR: ensemble failed for {chapter.stem}", file=sys.stderr)
        return chapter, ok

    failed = []
    with ThreadPoolExecutor(max_workers=args.chapter_parallel) as pool:
        futures = {pool.submit(run_chapter, ch): ch for ch in chapters}
        for fut in as_completed(futures):
            chapter, ok = fut.result()
            if not ok:
                failed.append(chapter.stem)

    if failed:
        print(
            f"\n{len(failed)} chapter(s) failed: {', '.join(sorted(failed))}",
            file=sys.stderr,
        )
        print("Fix and re-run; completed chapters will be skipped.", file=sys.stderr)
        sys.exit(1)

    print("\n[combine] Merging per-chapter outputs...")
    all_facts = []
    missing = []
    for chapter in chapters:
        merged = per_chapter_dir / chapter.stem / "merged.json"
        if not merged.exists():
            missing.append(chapter.stem)
            continue
        facts = json.loads(merged.read_text(encoding="utf-8"))
        for fact in facts:
            fact["source_chapter"] = chapter.stem
        all_facts.extend(facts)

    if missing:
        print(
            f"  WARNING: missing merged.json for: {', '.join(missing)}",
            file=sys.stderr,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(all_facts, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[done] {len(all_facts)} facts → {out_path}")


if __name__ == "__main__":
    main()
