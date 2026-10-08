"""summary_native CLI: validate | build | extract | audit | synth | annotate | compare | npc-link | npc-draft | npc-compose | npc-verify | npc-publish.

Exit codes (contracts/cli.md): 0 ok, 1 blocking validation problems, 2 refusal,
3 incomplete synthesis, 4 model call failed, 5 npc-verify found a failing draft.
Config is resolved AFTER ``parse_args`` because ``find_default_config`` raises.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from campaignlib.config import ConfigLocationError, campaign_root_for_config, find_default_config
from campaignlib.players_config import PLAYERS_CONFIG_FILENAME, load_players_config
from campaignlib.registry import load_registry
from campaignlib.util import atomic_write_text
from campaignlib import DEFAULT_MODEL, add_backend_args
from campaignlib.api.client import resolve_cli_model
from pipelines.summary_native import annotate, audit
from pipelines.summary_native import compare as compare_mod
from pipelines.summary_native import corpus, duplicates, extract, npc_authored, npc_compose, npc_config, npc_draft, npc_forms, npc_link
from pipelines.summary_native import npc_publish, npc_verify, parse, resolve, schema, synth
from pipelines.summary_native.freshness import check_fresh
from pipelines.summary_native.validate import ValidationRefusal, scan

SUBCOMMANDS = ("validate", "build", "extract", "audit", "synth", "annotate", "compare", "npc-link", "npc-draft", "npc-compose", "npc-verify", "npc-publish", "check-pointers")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="summary_native",
        description="Build grounding-doc drafts directly from reviewed session summaries.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in SUBCOMMANDS:
        p = sub.add_parser(name, help=name)
        if name == "check-pointers":
            p.add_argument("document", help="promoted world_state file (or its draft)")
            p.add_argument("--config", default=None)
            continue
        if name in ("synth", "compare"):
            p.add_argument("doc", choices=schema.DOCS)
        if name == "annotate":
            p.add_argument("doc", choices=schema.STATE_DOCS)
            p.add_argument("--dry-run", action="store_true", help="print the hits, write nothing")
        p.add_argument("--summaries-dir", default=None, help="directory of structured summaries (*.md)")
        p.add_argument("--since", type=int, default=None, help="first chapter (inclusive)")
        p.add_argument("--until", type=int, default=None, help="last chapter (inclusive)")
        p.add_argument("--out-root", default=None, help=f"output root (default {schema.DEFAULT_OUT_ROOT})")
        p.add_argument("--registry", default=None, help="entity registry file or campaign dir (default: grounding.yaml summary_native.registry, else auto-discover)")
        p.add_argument("--canon", default=None, help="not-a-duplicate rulings (default: grounding.yaml summary_native.canon_file, else <out-root>/canon.yaml)")
        p.add_argument("--dup-threshold", type=float, default=None, help="possible-duplicate similarity ratio")
        p.add_argument("--config", default=None)
        if name == "build":
            p.add_argument("--force", action="store_true", help="rewrite an existing corpus")
        if name == "audit":
            p.add_argument("--track-file", metavar="FILE", action="append", default=None,
                           help="tracking file (repeatable; same spelling as campaign_state --track-file; "
                                "default: grounding.yaml campaign_state.track_files)")
            p.add_argument("--candidates", type=_positive_int, default=schema.DEFAULT_AUDIT_CANDIDATES, metavar="N",
                           help=f"max candidate chapters per item (default {schema.DEFAULT_AUDIT_CANDIDATES})")
        if name == "extract":
            p.add_argument("--chunk-chars", type=int, default=None,
                           help="chunk size limit in characters "
                                f"(default: grounding.yaml summary_native.extract.chunk_chars, else {schema.DEFAULT_CHUNK_CHARS})")
        if name in ("extract", "audit"):
            p.add_argument("--max-tokens", type=int, default=schema.DEFAULT_MAX_TOKENS,
                           help=f"max_tokens per call (default {schema.DEFAULT_MAX_TOKENS})")
            p.add_argument("--dump-only", action="store_true",
                           help="write prompts and the run record; make no model call")
            p.add_argument("--force", action="store_true",
                           help="re-run every call, ignoring cache keys")
            p.add_argument("--model", default=None,
                           help="model id (default: grounding.yaml summary_native.extract.model, "
                                f"else {schema.DEFAULT_DRAFT_MODEL})")
            # no parser default: precedence is flag > grounding.yaml summary_native.extract.backend > schema
            add_backend_args(p, default_backend=None)
            # Same spelling and meaning as facts_to_state --endpoints and extract_facts --parallel.
            # Endpoints are machine wiring: never read from grounding.yaml.
            p.add_argument("--endpoints", nargs="+", default=None, metavar="URL",
                           help="Multiple OpenAI-compatible endpoints sharing one queue of chunks "
                                "(one worker per endpoint, work-stealing). --backend dgx only; "
                                "all must serve --model, checked before any call.")
            p.add_argument("--parallel", type=_positive_int, default=schema.DEFAULT_EXTRACT_PARALLEL, metavar="N",
                           help="Concurrent in-flight chunk requests per endpoint (default %(default)s; 1 = sequential).")
        if name.startswith("npc-") or name == "synth":
            p.add_argument("--npc-root", default=None,
                           help="NPC output root (default: npc_dossiers.yaml npc_root, else "
                                f"{schema.DEFAULT_NPC_ROOT})"
                                + ("; world_state only: where draft verifications and the publish log are read, "
                                   "to explain a missing dossier" if name == "synth" else ""))
        if name == "npc-link":
            p.add_argument("--force", action="store_true",
                           help="rewrite existing evidence/ and link_manifest.json for the range")
        if name == "npc-draft":
            p.add_argument("--name", nargs="+", default=None, metavar="NAME", help="narrow to these global NPCs")
            p.add_argument("--all", action="store_true",
                           help="every global NPC with evidence in range (exclusive with the narrowing flags)")
            p.add_argument("--recent-chapters", type=int, default=None,
                           help="narrow: NPCs seen in the last N chapters of the range (031 rules)")
            p.add_argument("--recurring-min", type=int, default=None,
                           help="narrow: NPCs with at least N entries (031 rules)")
            p.add_argument("--dump-only", action="store_true", help="write prompts, selection and record; make no model call")
            p.add_argument("--force", action="store_true", help="re-draft even when the draft key is unchanged")
            p.add_argument("--model", default=None,
                           help=f"model id (default: npc_dossiers.yaml draft.model, else {schema.DEFAULT_DRAFT_MODEL}; "
                                f"{DEFAULT_MODEL} when --backend differs from the default backend)")
            p.add_argument("--max-tokens", type=int, default=schema.DEFAULT_MAX_TOKENS,
                           help=f"max_tokens per call (default {schema.DEFAULT_MAX_TOKENS})")
            p.add_argument("--mode", choices=schema.DRAFT_MODES, default=None,
                           help=f"drafting mode (default: npc_dossiers.yaml draft.mode, else {schema.DEFAULT_DRAFT_MODE})")
            p.add_argument("--chunk-chars", type=int, default=None,
                           help="chunked mode: chunk size limit in characters "
                                f"(default: npc_dossiers.yaml draft.chunk_chars, else {schema.DEFAULT_CHUNK_CHARS})")
            # no parser default: precedence is flag > npc_dossiers.yaml draft.backend > schema
            add_backend_args(p, default_backend=None)
        if name == "npc-verify":
            p.add_argument("--name", nargs="+", default=None, metavar="NAME", help="limit to these NPCs")
        if name == "npc-publish":
            p.add_argument("--name", nargs="+", action="extend", default=None, metavar="NAME", help="publish these NPCs")
            p.add_argument("--all", dest="all_", action="store_true", help="every NPC with a GM dossier in range")
            p.add_argument("--authored-all", action="store_true", help="every hand-built authored/<slug>.md")
            p.add_argument("--source", choices=npc_publish.SOURCES, default=None,
                           help="which source to publish when both a GM dossier and a hand-built file exist")
            p.add_argument("--force", action="store_true", help="publish despite a failed verification or a hand-edited target")
        if name == "npc-compose":
            p.add_argument("--name", nargs="+", default=None, metavar="NAME", help="compose GM dossiers for these NPCs")
            p.add_argument("--init", nargs="+", default=None, metavar="NAME",
                           help="create an empty authored file for each name; composes nothing")
        if name == "synth":
            p.add_argument("--world-state", default=None, metavar="FILE", help="GM-reviewed world-state draft to use as context")
            p.add_argument("--campaign-state", default=None, metavar="FILE", help="GM-reviewed campaign-state draft to use as context")
            p.add_argument("--party-config", default=None, metavar="FILE",
                           help="party roster (party; default <config>/party.yaml)")
            p.add_argument("--planning-config", default=None, metavar="FILE",
                           help="tracked NPCs/factions and arc scores (planning; default <config>/planning.yaml)")
            p.add_argument("--audit", nargs="+", default=None, metavar="FILE",
                           help="retired for campaign_state (the audit is `summary_native audit`); "
                                "refused for every document")
            p.add_argument("--recent-chapters", type=int, default=None,
                           help=f"chapters counted back from the range end (default {schema.DEFAULT_RECENT_CHAPTERS}; 0 = all); "
                                "party, planning and world_state's Key NPCs; refused for campaign_state")
            p.add_argument("--recurring-min", type=int, default=None,
                           help=f"observations that make an entity recurring (default {schema.DEFAULT_RECURRING_MIN}); "
                                "party, planning and world_state's Key NPCs; refused for campaign_state")
            p.add_argument("--name", nargs="+", default=None, metavar="SUBJECT",
                           help="force-include dossiers by subject (party, planning; world_state: force-include "
                                "these global NPCs in Key NPCs); refused for campaign_state")
            p.add_argument("--fallback-npc-lines", action="store_true",
                           help="world_state only: when a selected NPC has no published, verified dossier, write a "
                                f"code-built line {schema.KEY_NPC_FALLBACK_MARK} instead of refusing "
                                "(per run; never read from config)")
            p.add_argument("--parts", type=int, default=None,
                           help=f"split the outline into N calls (party and planning; default {schema.DEFAULT_PARTS} = one call; "
                                "refused for world_state and campaign_state, which write one call per section)")
            p.add_argument("--dump-only", action="store_true", help="write prompts and the record; make no model call")
            p.add_argument("--force", action="store_true", help="overwrite an existing draft")
            p.add_argument("--model", default=None,
                           help=f"model id (default: {DEFAULT_MODEL}; world_state and campaign_state: "
                                f"grounding.yaml summary_native.prose.model, else {schema.DEFAULT_PROSE_MODEL})")
            p.add_argument("--max-tokens", type=int, default=schema.DEFAULT_MAX_TOKENS,
                           help=f"max_tokens per call (default {schema.DEFAULT_MAX_TOKENS})")
            # no parser default: world_state/campaign_state resolve flag > grounding.yaml summary_native.prose > schema.
            # None behaves as "anthropic" everywhere else (client_from_args, resolve_cli_model), so party and planning are unchanged.
            add_backend_args(p, default_backend=None)
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
    if args.command == "check-pointers":
        from pipelines.summary_native.pointers import check_paths
        document = _under(root, args.document)
        problems = check_paths(document, root)
        if problems:
            return _err("\n".join(problems))
        print(f"All reading-contract pointers resolve: {document}")
        return 0
    cfg = _grounding_section(config_path.expanduser().resolve())

    summaries = args.summaries_dir or cfg.get("summaries_dir")
    if not summaries:
        return _err(
            "no summaries directory: pass --summaries-dir or set "
            "grounding.yaml summary_native.summaries_dir"
        )
    out_root = _under(root, args.out_root or cfg.get("out_root") or schema.DEFAULT_OUT_ROOT)
    dup_threshold = (
        args.dup_threshold
        if args.dup_threshold is not None
        else float(cfg.get("dup_threshold", schema.DEFAULT_DUP_THRESHOLD))
    )

    registry_path = None
    if args.command != "compare":  # synth hashes the registry for its staleness check
        try:
            registry_path = resolve.resolve_registry_path(root, args.registry, cfg)
        except resolve.PathRefusal as e:
            return _err(str(e))
    try:
        canon_path = resolve.resolve_canon_path(root, out_root, args.canon, cfg)
    except resolve.PathRefusal as e:
        return _err(str(e))
    reg_obj = None
    if registry_path is not None and args.command in ("validate", "build", "npc-link", "npc-draft", "npc-compose", "npc-verify", "npc-publish"):
        try:
            reg_obj = load_registry(registry_path)
        except Exception as e:  # yaml.YAMLError, KeyError, AttributeError, TypeError, ValueError, OSError
            return _err(f"invalid entity registry {registry_path}: {type(e).__name__}: {e}")
    try:
        rulings = duplicates.load_rulings(canon_path)
    except (duplicates.RulingsError, ValueError, OSError) as e:
        return _err(str(e))
    grouper = duplicates.make_grouper(reg_obj)

    summaries_dir = _under(root, summaries)
    try:
        report = scan(
            summaries_dir, root, args.since, args.until,
            registry=reg_obj, rulings=rulings, dup_threshold=dup_threshold,
        )
        rng = report.range
        range_dir = out_root / f"ch{rng.since:03d}-{rng.until:03d}"
        corpus.check_not_foreign(range_dir)
        if args.command == "build" and not report.blocking_count:
            corpus.check_build_allowed(range_dir, args.force)  # pure; build_corpus guards once
        if args.command in ("validate", "build") and (args.command == "validate" or report.blocking_count):
            report.existing_corpus = corpus.describe_existing(range_dir, report, root)
    except (ValidationRefusal, corpus.CorpusError) as e:
        return _err(str(e))

    return _after_scan(args, root, config_path, cfg, report, range_dir, summaries_dir, registry_path, canon_path, grouper)


def _after_scan(args, root, config_path, cfg, report, range_dir, summaries_dir, registry_path, canon_path, grouper) -> int:
    if args.command == "extract":
        return _extract(args, root, config_path, cfg, report, range_dir, summaries_dir, registry_path)
    if args.command == "audit":
        return _audit(args, root, config_path, cfg, report, range_dir, summaries_dir, registry_path)
    if args.command == "synth":
        return _synth(args, root, config_path, cfg, report, range_dir, registry_path, summaries_dir)
    if args.command == "annotate":
        return annotate.run_annotate(
            args, range_dir=range_dir, summaries_dir=summaries_dir, registry_path=registry_path,
            players_path=_players_path(config_path),
        )
    if args.command == "compare":
        return _compare(args, root, range_dir)
    if args.command in ("npc-draft", "npc-compose", "npc-verify", "npc-publish"):
        return _npc_stage(args, root, config_path, cfg, report, range_dir, registry_path, canon_path)
    if args.command == "npc-link":
        return _npc_link(args, root, config_path, report, range_dir, summaries_dir, registry_path, canon_path)
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
            grouper=grouper,
            registry_sha256=_sha_if_file(registry_path),
            canon_sha256=_sha_if_file(canon_path),
        )
    except corpus.CorpusError as e:
        return _err(str(e))
    return 0


def _npc_config(config_path: Path):
    """``<config>/npc_dossiers.yaml`` through the one strict model (npc_config.py).

    Raises ``ValueError`` for malformed YAML, an unknown key or an invalid value.
    """
    return npc_config.load_npc_dossiers_config(config_path.expanduser().resolve().parent / npc_config.NPC_DOSSIERS_CONFIG_FILENAME)


def _npc_root(args, root: Path, config_path: Path) -> Path:
    """``--npc-root`` > ``npc_dossiers.yaml npc_root`` > the schema default (the model's default)."""
    return _under(root, args.npc_root or _npc_config(config_path).npc_root)


def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return n


def _resolve_draft_args(args, config_path: Path) -> None:
    """Fill backend, model, mode and chunk size: flag > ``npc_dossiers.yaml draft:`` > schema.

    The schema model belongs to the schema backend. A different ``--backend`` with no ``--model``
    falls back to the command-wide default model rather than sending a Spark model id elsewhere.
    """
    draft = _npc_config(config_path).draft
    args.backend = args.backend or draft.backend
    legacy = (draft.effective_model() if args.backend == draft.backend else None) or DEFAULT_MODEL
    args.model = resolve_cli_model(args, legacy_default=legacy).effective_model
    args.mode = args.mode or draft.mode
    args.chunk_chars = args.chunk_chars if args.chunk_chars is not None else draft.chunk_chars
    if args.chunk_chars < 1:
        raise ValueError("--chunk-chars must be a positive integer")


def _npc_link(args, root: Path, config_path: Path, report, range_dir: Path, summaries_dir: Path,
              registry_path, canon_path) -> int:
    """npc-link: deterministic, no model (contracts/cli.md)."""
    if report.blocking_count:
        print(report.to_markdown(), end="", file=sys.stderr)
        print("validation has blocking problems; fix the summaries, then build --force", file=sys.stderr)
        return 1
    try:
        manifest = corpus.load_manifest(range_dir, require_complete=True)
    except corpus.CorpusError as e:
        return _err(f"{e}; run `summary_native build`")
    stale = check_fresh(report, range_dir, root, manifest, registry_path)
    if stale:
        return _err(stale)

    rng = report.range
    try:
        out_dir = _npc_root(args, root, config_path) / f"ch{rng.since:03d}-{rng.until:03d}"
    except ValueError as e:
        return _err(str(e))
    existing = out_dir / npc_link.LINK_MANIFEST
    if existing.is_file():
        try:
            kind = json.loads(existing.read_text(encoding="utf-8")).get("kind")
        except (OSError, ValueError):
            kind = None
        if kind != "npc_link":
            return _err(f"{out_dir}: {npc_link.LINK_MANIFEST} is not an npc_link manifest; refusing to overwrite it")
        if not args.force:
            return _err(f"{out_dir}: linked output already exists; pass --force to rewrite it")
    elif (out_dir / npc_link.EVIDENCE_DIR).is_dir() and any((out_dir / npc_link.EVIDENCE_DIR).iterdir()) and not args.force:
        return _err(f"{out_dir}: evidence/ already exists without a link manifest; pass --force to rewrite it")

    try:
        reg_obj = load_registry(registry_path) if registry_path is not None else None
        rulings = duplicates.load_rulings(canon_path)
        wordlist, wordlist_sha = npc_forms.load_wordlist()
        players = load_players_config(config_path.expanduser().resolve().parent / PLAYERS_CONFIG_FILENAME)
        index = npc_forms.build_form_index(
            reg_obj, npc_forms.read_corpus_dossiers(range_dir), wordlist, rulings, players
        )
        files = [parse.parse_file(p, root) for p in sorted(report.input_files)]
        result = npc_link.link_with_findings(files, range_dir, index)
    except npc_forms.LinkRefusal as e:
        return _err(str(e))
    except (duplicates.RulingsError, corpus.CorpusError, ValueError, OSError) as e:
        return _err(str(e))

    npc_link.write_link_outputs(
        out_dir,
        result.dossiers,
        result.findings,
        {
            "range": {"since": rng.since, "until": rng.until},
            "corpus_manifest_sha256": corpus.sha256_file(range_dir / "manifest.json"),
            "registry_sha256": _sha_if_file(registry_path),
            "canon_sha256": _sha_if_file(canon_path),
            "wordlist_sha256": wordlist_sha,
            "players_sha256": _sha_if_file(config_path.expanduser().resolve().parent / PLAYERS_CONFIG_FILENAME),
        },
        result.counts,
    )
    c = result.counts
    print(f"NPCs linked: {c['npcs']}")
    print(f"scenes linked: {c['scenes']}")
    print(f"moments linked: {c['moments']}")
    print(f"withheld forms: {c['ambiguous']} ambiguous, {c['generic_unruled']} generic (unruled), "
          f"{c['generic_never']} generic (ruled never)")
    print(f"evidence: {schema.display_path(out_dir / npc_link.EVIDENCE_DIR, root)}")
    if c["ambiguous"] or c["generic_unruled"]:
        print(
            f"warning: {c['ambiguous']} ambiguous, {c['generic_unruled']} generic (unruled) name forms "
            f"withheld from linking — see {schema.display_path(out_dir / npc_link.LINK_REPORT_MD, root)}",
            file=sys.stderr,
        )
    return 0


def _npc_stage(args, root: Path, config_path: Path, cfg: dict, report, range_dir: Path, registry_path, canon_path) -> int:
    """npc-draft and npc-compose (contracts/cli.md)."""
    rng = report.range
    try:
        npc_range_dir = _npc_root(args, root, config_path) / f"ch{rng.since:03d}-{rng.until:03d}"
    except ValueError as e:
        return _err(str(e))
    try:
        reg_obj = load_registry(registry_path) if registry_path is not None else None
    except Exception as e:  # noqa: BLE001 - same breadth as main()
        return _err(f"invalid entity registry {registry_path}: {type(e).__name__}: {e}")
    registry_npcs = tuple(e.name for e in reg_obj.entities if e.type == "npc") if reg_obj else ()
    aliases = {
        a.casefold(): e.name for e in (reg_obj.entities if reg_obj else ()) if e.type == "npc" for a in e.aliases
    }
    if args.command == "npc-compose":
        return _npc_compose(args, root, report, npc_range_dir, registry_npcs)
    if args.command == "npc-publish":
        return _npc_publish(args, root, report, npc_range_dir, aliases, registry_npcs)
    if args.command == "npc-verify":
        return _npc_verify(args, root, report, npc_range_dir, aliases)
    try:
        _resolve_draft_args(args, config_path)
    except ValueError as e:
        return _err(str(e))
    return npc_draft.run_draft(
        args,
        root=root,
        range_dir=range_dir,
        npc_range_dir=npc_range_dir,
        report=report,
        registry_path=registry_path,
        canon_path=canon_path,
        players_path=config_path.expanduser().resolve().parent / PLAYERS_CONFIG_FILENAME,
        registry_npcs=registry_npcs,
        registry_aliases=aliases,
        recent_chapters=args.recent_chapters,
        recurring_min=args.recurring_min,
        # flag > npc_dossiers.yaml > schema (grounding.yaml summary_native belongs to 031's synth)
        default_recent=_npc_config(config_path).recent_chapters,
        default_recurring=_npc_config(config_path).recurring_min,
    )


def _npc_verify(args, root: Path, report, npc_range_dir: Path, aliases: dict[str, str]) -> int:
    """npc-verify: deterministic, never edits a draft (contracts/cli.md). Exit 5 on any failure."""
    if report.blocking_count:
        print(report.to_markdown(), end="", file=sys.stderr)
        print("validation has blocking problems; fix the summaries, then build --force", file=sys.stderr)
        return 1
    draft_dir = npc_range_dir / npc_draft.DRAFT_DIR
    evidence = {e.stem: e for e in npc_link.read_evidence_files(npc_range_dir)}
    drafted = sorted(
        p.stem for p in draft_dir.glob("*.md")
        if not p.name.endswith((".incomplete.md", ".verify.md")) and p.stem in evidence
    ) if draft_dir.is_dir() else []
    by_subject = {e.subject.casefold(): e.stem for e in evidence.values()}
    stems = drafted
    if args.name:
        stems = []
        for name in args.name:
            key = name.strip().casefold()
            stem = by_subject.get(key) or by_subject.get(aliases.get(key, "").casefold())
            if stem is None:
                return _err(f"--name {name}: no evidence for this NPC in range")
            if stem not in drafted:
                return _err(f"--name {name}: no draft dossier in range; run `summary_native npc-draft`")
            if stem not in stems:
                stems.append(stem)
    if not stems:
        return _err("no draft dossiers in range; run `summary_native npc-draft`")
    try:
        manuals = {
            stem: npc_authored.load_manual(
                npc_compose.authored_path_for(root, evidence[stem].subject), evidence[stem].subject)
            for stem in stems
        }
        ctx = npc_verify.load_context(root, report)
    except (npc_authored.AuthoredError, ValueError, OSError) as e:
        return _err(str(e))
    failed = 0
    totals = {k: 0 for k in npc_verify.FAIL_CODES}
    for stem in stems:
        ev = evidence[stem]
        result = npc_verify.verify_draft(draft_dir, stem, ev.subject, ev, manuals[stem], ctx)
        print(f"{ev.subject}: {result.summary_line()}")
        for m in result.manual:
            if not m.cited:
                print(f'warning: {ev.subject}: manual edit {m.n} dropped \u2014 "{m.text}"', file=sys.stderr)
        failed += 0 if result.passed else 1
        for k in totals:
            totals[k] += result.counts.get(k, 0)
    print(f"verified {len(stems)} drafts: {len(stems) - failed} pass, {failed} fail"
          + ("" if not failed else " (" + ", ".join(f"{k} {n}" for k, n in totals.items() if n) + ")"))
    return schema.EXIT_VERIFY_FAILED if failed else 0


def _npc_publish(args, root: Path, report, npc_range_dir: Path, aliases: dict[str, str], registry_npcs) -> int:
    """npc-publish: deterministic, explicit selection, the only writer of docs/npcs/<slug>.md."""
    if report.blocking_count:
        print(report.to_markdown(), end="", file=sys.stderr)
        print("validation has blocking problems; fix the summaries, then build --force", file=sys.stderr)
        return 1
    try:
        results = npc_publish.publish(
            root, npc_range_dir, names=args.name or (), all_=args.all_, authored_all=args.authored_all,
            source=args.source, force=args.force, aliases=aliases, registry_npcs=registry_npcs,
        )
    except npc_publish.PublishRefusal as e:
        return _err(str(e))
    for r in results:
        print(r.line())
    return 0 if all(r.published for r in results) else 2


def _npc_compose(args, root: Path, report, npc_range_dir: Path, registry_npcs) -> int:
    if report.blocking_count:
        print(report.to_markdown(), end="", file=sys.stderr)
        print("validation has blocking problems; fix the summaries, then build --force", file=sys.stderr)
        return 1
    if args.init:
        if args.name:
            return _err("--init composes nothing; do not combine it with --name")
        known = {s.casefold(): s for s in npc_compose.known_npcs(npc_range_dir).values()}
        known.update({n.casefold(): n for n in registry_npcs})
        subjects, failed = [], False
        for name in args.init:
            subject = known.get(name.strip().casefold())
            if subject is None:
                print(f"Error: {name}: not a known NPC (no evidence in this range, not a registry NPC)", file=sys.stderr)
                failed = True
            else:
                subjects.append(subject)
        for subject, error in npc_compose.init(root, subjects):
            if error:
                print(f"Error: {error}", file=sys.stderr)
                failed = True
            else:
                print(f"created {schema.display_path(npc_compose.authored_path_for(root, subject), root)}")
        return 2 if failed else 0
    try:
        results = npc_compose.compose_many(root, npc_range_dir, args.name)
    except npc_compose.ComposeRefusal as e:
        return _err(str(e))
    for r in results:
        if r.hand_edited:
            print(npc_compose.hand_edit_warning(r, root), file=sys.stderr)
        print(f"{r.subject}: composed {schema.display_path(r.out_path, root)}")
    return 0


def _players_path(config_path: Path) -> Path:
    return config_path.expanduser().resolve().parent / PLAYERS_CONFIG_FILENAME


def _extract(args, root: Path, config_path: Path, cfg: dict, report, range_dir: Path, summaries_dir: Path,
             registry_path) -> int:
    """extract: the map step. flag > grounding.yaml summary_native.extract > schema (contracts/cli.md)."""
    try:
        settings = resolve.resolve_extract(cfg, backend=args.backend, model=args.model, chunk_chars=args.chunk_chars)
        args.backend, args.model = settings.backend, settings.model
        args.model = resolve_cli_model(args, legacy_default=DEFAULT_MODEL).effective_model
    except ValueError as e:  # ConfigRefusal is a ValueError
        return _err(str(e))
    return extract.run_extract(
        args,
        root=root,
        range_dir=range_dir,
        report=report,
        summaries_dir=summaries_dir,
        registry_path=registry_path,
        players_path=_players_path(config_path),
        settings=settings,
    )


def _audit(args, root: Path, config_path: Path, cfg: dict, report, range_dir: Path, summaries_dir: Path,
           registry_path) -> int:
    """audit: judge each tracking item. Backend family and defaults are extract's (contracts/cli.md);
    track files: --track-file (repeatable) > grounding.yaml campaign_state.track_files."""
    try:
        settings = resolve.resolve_extract(cfg, backend=args.backend, model=args.model)
        args.backend, args.model = settings.backend, settings.model
        args.model = resolve_cli_model(args, legacy_default=DEFAULT_MODEL).effective_model
    except ValueError as e:
        return _err(str(e))
    given = args.track_file or _grounding_group(config_path.expanduser().resolve(), "campaign_state").get("track_files") or []
    track_files = [_under(root, t) for t in given]
    return audit.run_audit(
        args,
        root=root,
        range_dir=range_dir,
        report=report,
        summaries_dir=summaries_dir,
        registry_path=registry_path,
        players_path=_players_path(config_path),
        settings=settings,
        track_files=track_files,
        candidates_n=args.candidates,
    )


def _synth(args, root: Path, config_path: Path, cfg: dict, report, range_dir: Path, registry_path,
           summaries_dir: Path) -> int:
    budgets = None
    try:
        if args.doc in schema.STATE_DOCS:
            # every document: flag > grounding.yaml summary_native.prose > schema.
            prose = resolve.resolve_prose(
                cfg, backend=args.backend, model=args.model, effort=getattr(args, "claude_code_effort", None))
            args.backend, args.model, args.claude_code_effort = prose.backend, prose.model, prose.effort
            budgets = {"party": prose.party_budgets, "planning": prose.planning_budgets}.get(args.doc, prose.budgets)
        args.model = resolve_cli_model(args, legacy_default=DEFAULT_MODEL).effective_model
    except ValueError as e:
        return _err(str(e))
    track = _grounding_group(config_path.expanduser().resolve(), "campaign_state").get("track_files") or []
    npc_root = None
    if args.doc == "world_state":
        try:
            npc_root = _npc_root(args, root, config_path)
        except ValueError as e:  # a malformed npc_dossiers.yaml
            return _err(str(e))
    return synth.run_synth(
        args,
        root=root,
        registry_path=registry_path,
        range_dir=range_dir,
        report=report,
        audit_default=[str(t) for t in track],
        config_dir=config_path.expanduser().resolve().parent,
        recent_chapters=_pick(args.recent_chapters, cfg, "recent_chapters", schema.DEFAULT_RECENT_CHAPTERS),
        recurring_min=_pick(args.recurring_min, cfg, "recurring_min", schema.DEFAULT_RECURRING_MIN),
        parts=_pick(args.parts, cfg, "parts", schema.DEFAULT_PARTS),
        summaries_dir=summaries_dir,
        players_path=_players_path(config_path),
        budgets=budgets,
        npc_root=npc_root,
    )


def _pick(flag, cfg: dict, key: str, default: int) -> int:
    return int(flag if flag is not None else cfg.get(key, default))


def _compare(args, root: Path, range_dir: Path) -> int:
    draft = schema.draft_dir(range_dir, args.doc) / f"{args.doc}.draft.md"
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
    out = schema.draft_dir(range_dir, args.doc) / f"{args.doc}.vs-live.diff"
    atomic_write_text(out, rep.diff)
    print(rep.to_text(), end="")
    print(f"diff: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
