"""summary_native CLI: validate | build | synth | compare.

Exit codes (contracts/cli.md): 0 ok, 1 blocking validation problems, 2 refusal,
3 incomplete synthesis.
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
from campaignlib import DEFAULT_MODEL, add_backend_args
from campaignlib.api.client import resolve_cli_model
from pipelines.summary_native import compare as compare_mod
from pipelines.summary_native import corpus, schema, synth
from pipelines.summary_native.validate import ValidationRefusal, scan

SUBCOMMANDS = ("validate", "build", "synth", "compare")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="summary_native",
        description="Build grounding-doc drafts directly from reviewed session summaries.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in SUBCOMMANDS:
        p = sub.add_parser(name, help=name)
        if name in ("synth", "compare"):
            p.add_argument("doc", choices=schema.DOCS)
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
        if name == "synth":
            p.add_argument("--world-state", default=None, metavar="FILE", help="GM-reviewed world-state draft to use as context")
            p.add_argument("--campaign-state", default=None, metavar="FILE", help="GM-reviewed campaign-state draft to use as context")
            p.add_argument("--audit", nargs="+", default=None, metavar="FILE",
                           help="tracking/planning/module files treated as questions "
                                "(campaign_state; default grounding.yaml campaign_state.track_files)")
            p.add_argument("--recent-chapters", type=int, default=None,
                           help=f"chapters counted back from the range end (default {schema.DEFAULT_RECENT_CHAPTERS}; 0 = all)")
            p.add_argument("--recurring-min", type=int, default=None,
                           help=f"observations that make an entity recurring (default {schema.DEFAULT_RECURRING_MIN})")
            p.add_argument("--name", nargs="+", default=None, metavar="SUBJECT", help="force-include dossiers by subject")
            p.add_argument("--parts", type=int, default=None,
                           help=f"split the outline into N calls (default {schema.DEFAULT_PARTS} = one call)")
            p.add_argument("--dump-only", action="store_true", help="write prompts and the record; make no model call")
            p.add_argument("--force", action="store_true", help="overwrite an existing draft")
            p.add_argument("--model", default=None, help=f"model id (default: {DEFAULT_MODEL})")
            p.add_argument("--max-tokens", type=int, default=schema.DEFAULT_MAX_TOKENS,
                           help=f"max_tokens per call (default {schema.DEFAULT_MAX_TOKENS})")
            add_backend_args(p)
        if name == "compare":
            p.add_argument("--live", required=True, metavar="FILE", help="the live grounding document to compare against")
    return parser


def _err(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return 2


def _grounding_group(config_file: Path, group: str) -> dict:
    gp = config_file.parent / "grounding.yaml"
    if not gp.is_file():
        return {}
    data = yaml.safe_load(gp.read_text(encoding="utf-8")) or {}
    section = data.get(group) if isinstance(data, dict) else None
    return section if isinstance(section, dict) else {}


def _grounding_section(config_file: Path) -> dict:
    return _grounding_group(config_file, "summary_native")


def _under(root: Path, value: str | Path) -> Path:
    return schema.resolve_under(root, value)


def _sha_if_file(path: Path | None) -> str | None:
    return corpus.sha256_file(path) if path is not None and path.is_file() else None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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
        if args.command in ("validate", "build") and (args.command == "validate" or report.blocking_count):
            report.existing_corpus = corpus.describe_existing(range_dir, report, root)
    except (ValidationRefusal, corpus.CorpusError) as e:
        return _err(str(e))

    return _after_scan(args, root, config_path, cfg, report, range_dir, summaries_dir, registry_path, canon_path)


def _after_scan(args, root, config_path, cfg, report, range_dir, summaries_dir, registry_path, canon_path) -> int:
    if args.command == "synth":
        return _synth(args, root, config_path, cfg, report, range_dir)
    if args.command == "compare":
        return _compare(args, root, range_dir)
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


def _synth(args, root: Path, config_path: Path, cfg: dict, report, range_dir: Path) -> int:
    try:
        args.model = resolve_cli_model(args, legacy_default=DEFAULT_MODEL).effective_model
    except ValueError as e:
        return _err(str(e))
    track = _grounding_group(config_path.expanduser().resolve(), "campaign_state").get("track_files") or []
    return synth.run_synth(
        args,
        root=root,
        range_dir=range_dir,
        report=report,
        audit_default=[str(t) for t in track],
        recent_chapters=_pick(args.recent_chapters, cfg, "recent_chapters", schema.DEFAULT_RECENT_CHAPTERS),
        recurring_min=_pick(args.recurring_min, cfg, "recurring_min", schema.DEFAULT_RECURRING_MIN),
        parts=_pick(args.parts, cfg, "parts", schema.DEFAULT_PARTS),
    )


def _pick(flag, cfg: dict, key: str, default: int) -> int:
    return int(flag if flag is not None else cfg.get(key, default))


def _compare(args, root: Path, range_dir: Path) -> int:
    draft = range_dir / "drafts" / f"{args.doc}.draft.md"
    live = _under(root, args.live)
    for label, p in (("draft", draft), ("live", live)):
        if not p.is_file():
            return _err(f"no {label} file at {p}")
    rep = compare_mod.compare(
        draft.read_text(encoding="utf-8"),
        live.read_text(encoding="utf-8"),
        draft_name=draft.name,
        live_name=live.name,
    )
    out = range_dir / "drafts" / f"{args.doc}.vs-live.diff"
    atomic_write_text(out, rep.diff)
    print(rep.to_text(), end="")
    print(f"diff: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
