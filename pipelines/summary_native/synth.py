"""Render grounding-doc drafts from a built corpus (FR-018..FR-027).

Context assembly lives in ``context``; this module orchestrates and owns the only
model call, ``render_part``. The model is a renderer inside a structure the GM
already reviewed: the corpus, the selection, and the outline. Its output is
checked deterministically against the outline and is never written as a draft
unless complete. Live ``docs/*.md`` files are never touched.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from campaignlib import client_from_args, stream_api
from campaignlib.api.client import resolve_cli_model
from campaignlib.util import atomic_write_text
from pipelines.summary_native import context, corpus, schema, select, validate
from pipelines.summary_native.freshness import check_fresh

EXIT_REFUSED = 2
EXIT_INCOMPLETE = 3
EXIT_MODEL_FAILED = 4
EXIT_BLOCKING = 1


def load_outline(doc: str) -> list[str]:
    path = context.PROMPT_DIR / f"{doc}.outline.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [str(h) for h in data["headings"]]


def split_parts(headings: list[str], n: int) -> list[list[str]]:
    """``n`` contiguous groups, as even as possible, earlier groups larger."""
    n = max(1, min(n, len(headings)))
    size, extra = divmod(len(headings), n)
    out, i = [], 0
    for k in range(n):
        j = i + size + (1 if k < extra else 0)
        out.append(headings[i:j])
        i = j
    return out


def check_outline(text: str, headings: list[str]) -> list[str]:
    """Problems with ``text`` against the ordered H2 ``headings`` (empty list = complete)."""
    lines = text.splitlines()
    wanted = {h.strip(): k for k, h in enumerate(headings)}
    at: dict[str, int] = {}
    problems: list[str] = []
    for n, line in enumerate(lines):
        if line.startswith("## ") and line.rstrip() in wanted and line.rstrip() not in at:
            at[line.rstrip()] = n
    first = min(at.values()) if at else len(lines)
    pre = "\n".join(lines[:first]).strip()
    if pre and not re.fullmatch(r"(<!--.*?-->\s*)+", pre, re.S):
        problems.append("text before the first heading (no preamble allowed)")
    for h in headings:
        if h not in at:
            problems.append(f"missing heading: {h}")
    present = [h for h in headings if h in at]
    positions = [at[h] for h in present]
    if positions != sorted(positions):
        problems.append("headings out of order (expected: " + " | ".join(present) + ")")
    h2_lines = sorted(n for n, line in enumerate(lines) if line.startswith("## "))
    for n in h2_lines:
        if lines[n].rstrip() not in wanted:
            problems.append(f"unexpected heading: {lines[n].rstrip()}")
    for h in present:
        start = at[h]
        end = next((n for n in h2_lines if n > start), len(lines))
        if not "\n".join(lines[start + 1 : end]).strip():
            problems.append(f"empty body: {h}")
    return problems


def check_threat_tracker(text: str) -> list[str]:
    """With no arc score configured, ``## Threat Tracker`` is exactly the sentinel line."""
    lines = text.splitlines()
    try:
        start = next(n for n, line in enumerate(lines) if line.rstrip() == "## Threat Tracker")
    except StopIteration:
        return []  # a missing heading is check_outline's report
    end = next((n for n in range(start + 1, len(lines)) if lines[n].startswith("## ")), len(lines))
    body = " ".join("\n".join(lines[start + 1 : end]).split())
    # The sentinel is required, not merely allowed: an empty section cannot be
    # told apart from a dropped or truncated one.
    if body == context.NO_ARC_SENTINEL:
        return []
    return ["threat tracker must be empty: no arc scores configured"]


def render_part(client, system: str, user: str, model: str, max_tokens: int) -> str:
    """The one model call in this package."""
    return stream_api(client, system, user, model, max_tokens=max_tokens)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_run_dir(runs_root: Path, stamp: str) -> Path:
    """Create ``runs_root/<stamp>[-k]`` — a directory no earlier run owns."""
    runs_root.mkdir(parents=True, exist_ok=True)
    k = 0
    while True:
        d = runs_root / (stamp if k == 0 else f"{stamp}-{k}")
        try:
            d.mkdir()
            return d
        except FileExistsError:
            k += 1


def _previous_draft_run(draft: Path, doc: str) -> str:
    m = re.search(rf"runs/{re.escape(doc)}/([^/\s]+)/record\.json", draft.read_text(encoding="utf-8").split("\n", 1)[0])
    return m.group(1) if m else "unknown"


def _refuse(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return EXIT_REFUSED


def _rel(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def run_synth(
    args,
    *,
    root: Path,
    range_dir: Path,
    report: validate.ValidationReport,
    audit_default: list[str],
    config_dir: Path | None = None,
    recent_chapters: int,
    recurring_min: int,
    parts: int,
    registry_path: Path | None = None,
    now=None,
) -> int:
    now = now or _utcnow
    doc = args.doc
    if doc not in schema.SYNTH_DOCS:
        return _refuse(f"synth {doc}: not implemented yet (available: {', '.join(schema.SYNTH_DOCS)})")
    if args.audit and doc != "campaign_state":
        return _refuse(f"--audit applies to campaign_state only, not {doc}")
    for flag, owners in (("world_state", ("campaign_state", "party", "planning")),
                         ("campaign_state", ("party", "planning"))):
        if getattr(args, flag, None) and doc not in owners:
            return _refuse(f"--{flag.replace('_', '-')} does not apply to {doc}")
    for flag, owner in (("party_config", "party"), ("planning_config", "planning")):
        if getattr(args, flag, None) and doc != owner:
            return _refuse(f"--{flag.replace('_', '-')} applies to {owner} only, not {doc}")

    if report.blocking_count:
        # Same outcome as validate/build: the summaries need fixing, not the flags.
        print(report.to_markdown(), end="")
        print("validation has blocking problems; fix the summaries, then build --force", file=sys.stderr)
        return EXIT_BLOCKING
    try:
        manifest = corpus.load_manifest(range_dir, require_complete=True)
    except corpus.CorpusError as e:
        return _refuse(str(e))
    stale = check_fresh(report, range_dir, root, manifest, registry_path)
    if stale:
        return _refuse(stale)

    upstream: dict[str, Path] = {}
    for name, value in (("world_state", args.world_state), ("campaign_state", args.campaign_state)):
        if value:
            p = Path(value).expanduser()
            p = p if p.is_absolute() else root / p
            if not p.is_file():
                return _refuse(f"--{name.replace('_', '-')} {value}: no such file")
            upstream[name] = p
    audit_paths: list[Path] = []
    if doc == "campaign_state":
        for value in args.audit if args.audit else audit_default:
            p = Path(value).expanduser()
            p = p if p.is_absolute() else root / p
            if not p.is_file():
                return _refuse(f"audit file {value}: no such file")
            audit_paths.append(p)

    drafts = range_dir / "drafts"
    # An existing .incomplete.md never blocks a run (it is replaced); an existing
    # .draft.md is GM-reviewed material and needs --force to be replaced.
    draft_path = drafts / f"{doc}.draft.md"
    if draft_path.exists() and not args.force and not args.dump_only:
        return _refuse(f"{draft_path} exists; pass --force to overwrite it")

    doc_config = None
    cfg_dir = Path(config_dir) if config_dir is not None else root / "config"
    try:
        if doc == "party":
            given = getattr(args, "party_config", None)
            doc_config = context.party_config_block(
                schema.resolve_under(root, given) if given else cfg_dir / "party.yaml", root
            )
        elif doc == "planning":
            given = getattr(args, "planning_config", None)
            doc_config = context.planning_config_block(
                schema.resolve_under(root, given) if given else cfg_dir / "planning.yaml",
                root,
                explicit=bool(given),
            )
    except context.DocConfigError as e:
        return _refuse(str(e))

    range_end = int(manifest["range"]["until"])
    range_since = int(manifest["range"]["since"])
    candidates = select.read_corpus_dossiers(range_dir)
    if doc == "planning":
        candidates = [d for d in candidates if d.category == "npc"]
    try:
        selection = select.select_dossiers(
            candidates,
            range_end,
            recent_chapters,
            recurring_min,
            tuple(args.name or ()),
        )
    except select.SelectionError as e:
        if doc == "planning":
            return _refuse(f"{e} (planning selects NPC dossiers only)")
        return _refuse(str(e))

    headings = load_outline(doc)
    groups = split_parts(headings, parts) if parts and parts > 1 else [headings]
    prompts = []
    for group in groups:
        prompts.append(
            context.build_context(
                doc, range_dir, selection, upstream, audit_paths,
                group if len(groups) > 1 else None,
                headings=headings, range_since=range_since, root=root,
                config_block=doc_config.block if doc_config else None,
            )
        )

    started = now()
    run_dir = _new_run_dir(range_dir / "runs" / doc, started.strftime("%Y%m%dT%H%M%SZ"))
    run_id = run_dir.name
    atomic_write_text(run_dir / "selection.json", selection.to_json())
    for k, (system, user) in enumerate(prompts, 1):
        atomic_write_text(run_dir / f"part-{k}.system.md", system)
        atomic_write_text(run_dir / f"part-{k}.user.md", user)

    manifest_sha = corpus.sha256_file(range_dir / "manifest.json")
    record = {
        "doc": doc,
        "backend": resolve_cli_model(args, legacy_default=None).backend,
        "model": args.model,
        "max_tokens": args.max_tokens,
        "parts": len(groups),
        "range": {"since": range_since, "until": range_end},
        "corpus_manifest_sha256": manifest_sha,
        "upstream": {n: {"path": _rel(p, root), "sha256": corpus.sha256_file(p)} for n, p in upstream.items()},
        "audit": [{"path": _rel(p, root), "sha256": corpus.sha256_file(p)} for p in audit_paths],
        "config": (
            [{"path": _rel(p, root), "sha256": corpus.sha256_file(p)} for p in doc_config.files]
            if doc_config else []
        ),
        "outline": headings,
        "check": "not run",
        "started": started.isoformat(timespec="seconds"),
        "finished": None,
    }

    def save_record() -> None:
        atomic_write_text(run_dir / "record.json", json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    if args.dump_only:
        record["finished"] = now().isoformat(timespec="seconds")
        save_record()
        print(f"[--dump-only: prompts written to {run_dir}; no model call]")
        return 0

    def fail(message: str) -> None:
        # Every run directory keeps a record, including one that never reached
        # the model, so a directory of prompts is never left unexplained.
        record["check"] = {"complete": False, "error": message}
        record["finished"] = now().isoformat(timespec="seconds")
        save_record()

    try:
        client = client_from_args(args)
    except SystemExit as e:  # client_from_args fails fast with SystemExit(message)
        msg = str(e.code) if isinstance(e.code, str) else f"backend setup failed (exit {e.code})"
        fail(msg)
        return _refuse(msg)
    except (ValueError, RuntimeError, ImportError) as e:
        fail(str(e))
        return _refuse(str(e))
    outputs: list[str] = []
    for k, (system, user) in enumerate(prompts, 1):
        try:
            out = render_part(client, system, user, args.model, args.max_tokens)
        except Exception as e:
            fail(f"part {k}: {type(e).__name__}: {e}")
            print(
                f"Error: model call failed in part {k}: {type(e).__name__}: {e} "
                f"(see {schema.display_path(run_dir / 'record.json', root)})",
                file=sys.stderr,
            )
            return EXIT_MODEL_FAILED
        atomic_write_text(run_dir / f"part-{k}.out.md", out)
        outputs.append(out.strip())
    joined = "\n\n".join(outputs) + "\n"
    if len(groups) > 1:
        problems = [
            f"part {k}: {p}"
            for k, (group, out) in enumerate(zip(groups, outputs), 1)
            for p in check_outline(out + "\n", group)
        ]
    else:
        problems = check_outline(joined, headings)
    if doc == "planning" and doc_config is not None and doc_config.arc_scores == 0:
        problems += check_threat_tracker(joined)
    record["check"] = {"complete": not problems, "problems": problems}
    record["finished"] = now().isoformat(timespec="seconds")
    save_record()

    drafts.mkdir(parents=True, exist_ok=True)
    record_ref = f"runs/{doc}/{run_id}/record.json"
    if problems:
        target = drafts / f"{doc}.incomplete.md"
        header = (
            f"<!-- summary_native INCOMPLETE | doc: {doc} | range: ch{range_since:03d}-{range_end:03d} "
            f"| record: {record_ref} | run: {run_id} -->\n"
        )
        atomic_write_text(target, header + joined)
        print(f"Incomplete: {target}", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        if draft_path.exists():
            print(
                f"previous draft kept: drafts/{doc}.draft.md (from run {_previous_draft_run(draft_path, doc)})",
                file=sys.stderr,
            )
        print("Retry with --parts N to write the outline in separate calls, or raise --max-tokens.", file=sys.stderr)
        return EXIT_INCOMPLETE
    header = (
        f"<!-- summary_native draft | doc: {doc} | range: ch{range_since:03d}-{range_end:03d} "
        f"| record: {record_ref} | corpus manifest sha256: {manifest_sha} -->\n"
    )
    atomic_write_text(draft_path, header + joined)
    (drafts / f"{doc}.incomplete.md").unlink(missing_ok=True)
    print(f"Wrote draft: {draft_path}")
    return 0
