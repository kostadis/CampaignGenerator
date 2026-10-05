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
from campaignlib.util import atomic_write_text
from pipelines.summary_native import context, corpus, schema, select, validate

EXIT_REFUSED = 2
EXIT_INCOMPLETE = 3


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
    for h in present:
        start = at[h]
        end = next((n for n in h2_lines if n > start), len(lines))
        if not "\n".join(lines[start + 1 : end]).strip():
            problems.append(f"empty body: {h}")
    return problems


def render_part(client, system: str, user: str, model: str, max_tokens: int) -> str:
    """The one model call in this package."""
    return stream_api(client, system, user, model, max_tokens=max_tokens)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _refuse(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return EXIT_REFUSED


def _rel(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _check_fresh(report, range_dir: Path, root: Path) -> str | None:
    """FR-005b: refuse on blocking findings or any in-range file differing from the manifest."""
    if report.blocking_count:
        return report.to_markdown() + "\nvalidation has blocking problems; fix the summaries, then build --force"
    state = corpus.describe_existing(range_dir, report, root)
    if state is None or state.get("state") != "matches":
        return "summaries changed since build — run `summary_native build --force`"
    return None


def run_synth(
    args,
    *,
    root: Path,
    range_dir: Path,
    report: validate.ValidationReport,
    audit_default: list[str],
    recent_chapters: int,
    recurring_min: int,
    parts: int,
) -> int:
    doc = args.doc
    if doc not in schema.SYNTH_DOCS:
        return _refuse(f"synth {doc}: not implemented yet (available: {', '.join(schema.SYNTH_DOCS)})")
    if args.audit and doc != "campaign_state":
        return _refuse(f"--audit applies to campaign_state only, not {doc}")

    try:
        manifest = corpus.load_manifest(range_dir, require_complete=True)
    except corpus.CorpusError as e:
        return _refuse(str(e))
    stale = _check_fresh(report, range_dir, root)
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
    existing = [p for p in (drafts / f"{doc}.draft.md", drafts / f"{doc}.incomplete.md") if p.exists()]
    if existing and not args.force and not args.dump_only:
        return _refuse(f"{existing[0]} exists; pass --force to overwrite it")

    range_end = int(manifest["range"]["until"])
    range_since = int(manifest["range"]["since"])
    try:
        selection = select.select_dossiers(
            select.read_corpus_dossiers(range_dir),
            range_end,
            recent_chapters,
            recurring_min,
            tuple(args.name or ()),
        )
    except select.SelectionError as e:
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
            )
        )

    runs = range_dir / "runs" / doc
    runs.mkdir(parents=True, exist_ok=True)
    atomic_write_text(runs / "selection.json", selection.to_json())
    for k, (system, user) in enumerate(prompts, 1):
        atomic_write_text(runs / f"part-{k}.system.md", system)
        atomic_write_text(runs / f"part-{k}.user.md", user)

    manifest_sha = corpus.sha256_file(range_dir / "manifest.json")
    record = {
        "doc": doc,
        "backend": getattr(args, "backend", None),
        "model": args.model,
        "max_tokens": args.max_tokens,
        "parts": len(groups),
        "range": {"since": range_since, "until": range_end},
        "corpus_manifest_sha256": manifest_sha,
        "upstream": {n: {"path": _rel(p, root), "sha256": corpus.sha256_file(p)} for n, p in upstream.items()},
        "audit": [{"path": _rel(p, root), "sha256": corpus.sha256_file(p)} for p in audit_paths],
        "outline": headings,
        "check": "not run",
        "started": _now(),
        "finished": None,
    }

    def save_record() -> None:
        atomic_write_text(runs / "record.json", json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    if args.dump_only:
        record["finished"] = _now()
        save_record()
        print(f"[--dump-only: prompts written to {runs}; no model call]")
        return 0

    client = client_from_args(args)
    outputs: list[str] = []
    for k, (system, user) in enumerate(prompts, 1):
        out = render_part(client, system, user, args.model, args.max_tokens)
        atomic_write_text(runs / f"part-{k}.out.md", out)
        outputs.append(out.strip())
    joined = "\n\n".join(outputs) + "\n"
    problems = check_outline(joined, headings)
    record["check"] = {"complete": not problems, "problems": problems}
    record["finished"] = _now()
    save_record()

    drafts.mkdir(parents=True, exist_ok=True)
    if problems:
        target = drafts / f"{doc}.incomplete.md"
        atomic_write_text(target, joined)
        print(f"Incomplete: {target}", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("Retry with --parts N to write the outline in separate calls, or raise --max-tokens.", file=sys.stderr)
        return EXIT_INCOMPLETE
    header = (
        f"<!-- summary_native draft | doc: {doc} | range: ch{range_since:03d}-{range_end:03d} "
        f"| record: runs/{doc}/record.json | corpus manifest sha256: {manifest_sha} -->\n"
    )
    target = drafts / f"{doc}.draft.md"
    atomic_write_text(target, header + joined)
    (drafts / f"{doc}.incomplete.md").unlink(missing_ok=True)
    print(f"Wrote draft: {target}")
    return 0
