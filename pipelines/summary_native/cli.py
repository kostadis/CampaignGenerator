"""summary_native CLI: validate | build (synth and compare are stubs for now).

Exit codes (contracts/cli.md): 0 ok, 1 blocking validation problems, 2 refusal.
Config is resolved AFTER ``parse_args`` because ``find_default_config`` raises.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from campaignlib.config import ConfigLocationError, campaign_root_for_config, find_default_config
from campaignlib.registry import resolve_registry_arg
from campaignlib.util import atomic_write_text
from pipelines.summary_native import corpus, schema
from pipelines.summary_native.validate import ValidationRefusal, scan

SUBCOMMANDS = ("validate", "build", "synth", "compare")
IMPLEMENTED = ("validate", "build")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="summary_native",
        description="Build grounding-doc drafts directly from reviewed session summaries.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in SUBCOMMANDS:
        p = sub.add_parser(name, help=name if name in IMPLEMENTED else f"{name} (not implemented yet)")
        if name not in IMPLEMENTED:
            continue
        p.add_argument("--summaries-dir", default=None, help="directory of structured summaries (*.md)")
        p.add_argument("--since", type=int, default=None, help="first chapter (inclusive)")
        p.add_argument("--until", type=int, default=None, help="last chapter (inclusive)")
        p.add_argument("--out-root", default=None, help=f"output root (default {schema.DEFAULT_OUT_ROOT})")
        p.add_argument("--registry", default=None, help="entity registry (default: auto-discover)")
        p.add_argument("--canon", default=None, help="not-a-duplicate rulings (default <out-root>/canon.yaml)")
        p.add_argument("--dup-threshold", type=float, default=None, help="possible-duplicate similarity ratio")
        p.add_argument("--config", default=None)
        if name == "build":
            p.add_argument("--force", action="store_true", help="rewrite an existing corpus")
    return parser


def _err(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return 2


def _grounding_section(config_file: Path) -> dict:
    gp = config_file.parent / "grounding.yaml"
    if not gp.is_file():
        return {}
    data = yaml.safe_load(gp.read_text(encoding="utf-8")) or {}
    section = data.get("summary_native") if isinstance(data, dict) else None
    return section if isinstance(section, dict) else {}


def _under(root: Path, value: str | Path) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else root / p


def _sha_if_file(path: Path | None) -> str | None:
    return corpus.sha256_file(path) if path is not None and path.is_file() else None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command not in IMPLEMENTED:
        print(f"summary_native {args.command}: not implemented yet", file=sys.stderr)
        return 2

    try:
        config_path = Path(args.config) if args.config else Path(find_default_config())
        root = campaign_root_for_config(config_path)
    except ConfigLocationError as e:
        return _err(str(e))
    cfg = _grounding_section(config_path.expanduser().resolve())

    summaries = args.summaries_dir or cfg.get("summaries_dir")
    if not summaries:
        return _err(
            "no summaries directory: pass --summaries-dir or set "
            "grounding.yaml summary_native.summaries_dir"
        )
    out_root = _under(root, args.out_root or cfg.get("out_root") or schema.DEFAULT_OUT_ROOT)
    # Accepted and recorded now; used by duplicate detection (US3).
    dup_threshold = (
        args.dup_threshold
        if args.dup_threshold is not None
        else float(cfg.get("dup_threshold", schema.DEFAULT_DUP_THRESHOLD))
    )
    del dup_threshold

    try:
        registry, _, _ = resolve_registry_arg(args.registry, False, parser)
    except SystemExit:
        return 2
    registry_path = _under(root, registry) if registry else None
    canon_path = _under(root, args.canon) if args.canon else out_root / "canon.yaml"

    summaries_dir = _under(root, summaries)
    try:
        report = scan(summaries_dir, root, args.since, args.until)
        rng = report.range
        range_dir = out_root / f"ch{rng.since:03d}-{rng.until:03d}"
        corpus.check_not_foreign(range_dir)
        if args.command == "build" and not report.blocking_count:
            corpus.check_build_allowed(range_dir, args.force)  # pure; build_corpus guards once
        if args.command == "validate" or report.blocking_count:
            report.existing_corpus = corpus.describe_existing(range_dir, report, root)
    except (ValidationRefusal, corpus.CorpusError) as e:
        return _err(str(e))

    range_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(range_dir / "validation_report.md", report.to_markdown())
    atomic_write_text(range_dir / "validation_report.json", report.to_json())
    print(report.to_markdown(), end="")
    if report.blocking_count:
        return 1
    if args.command == "validate":
        return 0

    try:
        corpus.build_corpus(
            summaries_dir,
            root,
            report,
            range_dir,
            force=args.force,
            registry_sha256=_sha_if_file(registry_path),
            canon_sha256=_sha_if_file(canon_path),
        )
    except corpus.CorpusError as e:
        return _err(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
