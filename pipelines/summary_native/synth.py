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
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from campaignlib import client_from_args, stream_api
from campaignlib.api.client import resolve_cli_model
from campaignlib.util import atomic_write_text
from pipelines.summary_native import annotate, context, corpus, freshness, key_npcs, notes, npc_check, party_notes, schema, select, state_sections, validate
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
    pre = re.sub(r"\A(?:<!--.*?-->\s*)+", "", pre, flags=re.S).strip()
    if pre and not re.fullmatch(r"(?:>[^\n]*(?:\n|$))+", pre):
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
    summaries_dir: Path | None = None,
    players_path: Path | None = None,
    budgets: dict[str, int] | None = None,
    npc_root: Path | None = None,
    now=None,
) -> int:
    now = now or _utcnow
    doc = args.doc
    if doc not in schema.SYNTH_DOCS:
        return _refuse(f"synth {doc}: not implemented yet (available: {', '.join(schema.SYNTH_DOCS)})")
    if args.audit and doc != "campaign_state":
        return _refuse(f"--audit applies to campaign_state only, not {doc}")
    if doc in schema.STATE_DOCS:
        # Every document builds from the checked notes, one call per section (spec 034 retired the
        # one-shot path). The retired flags are refused, never silently ignored.
        if args.parts:
            return _refuse(schema.STATE_PARTS_REFUSAL.format(doc=doc))
        if args.audit:
            return _refuse(schema.STATE_AUDIT_REFUSAL)
    if getattr(args, "npc_root", None) and doc != "world_state":
        return _refuse(f"--npc-root applies to world_state only, not {doc}")
    if getattr(args, "fallback_npc_lines", None) and doc not in ("world_state", "planning"):
        return _refuse(f"--fallback-npc-lines {schema.FALLBACK_NPC_LINES_REFUSAL}, not {doc}")
    if doc == "party":
        # party selects no NPCs: the flags that choose them belong to planning and world_state
        for flag in ("name", "recent_chapters", "recurring_min"):
            if getattr(args, flag, None) is not None:
                return _refuse(f"--{flag.replace('_', '-')} does not apply to party: {schema.PARTY_SELECTION_REFUSAL}")
    if doc == "campaign_state":
        # the Key NPCs selection flags choose world_state's Key NPCs; this document has no such section
        for flag in ("name", "recent_chapters", "recurring_min"):
            if getattr(args, flag, None) is not None:
                return _refuse(f"--{flag.replace('_', '-')} does not apply to {doc}: it has no Key NPCs section")
    for flag in ("world_state", "campaign_state"):
        if getattr(args, flag, None):
            if doc in ("party", "planning"):
                return _refuse(schema.UPSTREAM_REFUSAL)
            return _refuse(f"--{flag.replace('_', '-')} does not apply to {doc}")
    for flag, owner in (("party_config", "party"), ("planning_config", "planning")):
        if getattr(args, flag, None) and doc != owner:
            return _refuse(f"--{flag.replace('_', '-')} applies to {owner} only, not {doc}")
    if doc in schema.STATE_DOCS:
        return run_state_synth(
            args, root=root, range_dir=range_dir, report=report, summaries_dir=summaries_dir,
            registry_path=registry_path, players_path=players_path, track_files=audit_default,
            budgets=budgets, recent_chapters=recent_chapters, recurring_min=recurring_min,
            npc_root=npc_root, now=now, config_dir=config_dir,
        )

    # ── The one-shot path (retired). Unreachable since spec 034 T012: ``schema.STATE_DOCS`` is every
    # document, so the branch above always returns. Spec 034 T048 deletes the rest of this function.
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


# ── world_state and campaign_state from checked notes (spec 033 T019) ───────

#: world_state's sections are written within word budgets; campaign_state's are not.
STATE_SYSTEM = {
    "world_state": "state.prose_world.system.md",
    "campaign_state": "state.prose.system.md",
    "party": "state.party.system.md",
    "planning": "state.planning.system.md",
}
#: The documents that open with a reading contract (campaign_state, as before, does not).
CONTRACT_DOCS = ("world_state", "party", "planning")


def _default_budgets(doc: str) -> dict[str, int]:
    """The schema's word budgets for ``doc``'s sections (campaign_state has none)."""
    return {
        "world_state": schema.DEFAULT_WORLD_BUDGETS,
        "party": schema.DEFAULT_PARTY_BUDGETS,
        "planning": schema.DEFAULT_PLANNING_BUDGETS,
    }.get(doc, schema.DEFAULT_WORLD_BUDGETS)


@dataclass
class StateCtx:
    """What a per-document job builder may read (spec 034). Nothing here is mutable state of the run."""

    doc: str
    args: object
    root: Path
    range_dir: Path
    config_dir: Path
    since: int
    until: int
    results: list
    forms: dict
    pcs: set
    ambiguous: dict
    last_chunk: list
    budgets: dict
    system: str
    registry_path: Path | None = None
    players_path: Path | None = None
    #: party only: the configured characters (``party.yaml`` order), every distinct party note's
    #: attribution, and each character's code-built level (spec 034 US1).
    party: list = field(default_factory=list)
    attributions: list = field(default_factory=list)
    levels: dict = field(default_factory=dict)


_FENCE = "`````"
_HEADING_LINE_RE = re.compile(r"^#{1,3}\s")  # h4 and below stay the model's (arc-score candidates, US4)
_LEVEL_LINE_RE = re.compile(r"^\s*[*_]*level[*_]*\s*[:|]", re.I)


def _party_prompt(heading: str, brief: str, budget: int, blocks: list[tuple[str, str]], character: str | None = None) -> str:
    """One party call's user prompt: its identifying lines, then labelled blocks of evidence.

    ``blocks`` is ``[(label, text)]`` in the order shown. ``CHARACTER:`` appears only for a character
    call, so a reader of the run directory can tell the calls apart.
    """
    # PART names which of the system prompt's three parts this call is (a CHARACTER, the PARTY OVERVIEW or the PARTY DYNAMICS)
    head = (f"DOCUMENT: party\nPART: {'CHARACTER' if character else heading[3:].upper()}\nSECTION: {heading}\n"
            + (f"CHARACTER: {character}\n" if character else ""))
    out = head + f"BRIEF: {brief}\nWORD BUDGET: {budget} words, hard limit.\n"
    for label, text in blocks:
        out += f"\n{label}\n\n{text}\n"
    return out + "\nOUTPUT: write the body only. No heading of any level, and no level line: code writes both.\n"


def _note_block(label: str, ns: list) -> tuple[str, str]:
    return (f"{label} ({len(ns)} bullets, chapter order, every one already checked by code):",
            "\n".join(n.text for n in ns) or "(none)")


def _name_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "x"


def _party_jobs(ctx: StateCtx) -> list[dict]:
    """party's prose jobs: one per character, plus Party Overview and Party Dynamics (spec 034 US1, research R9).

    Each job is ``{"heading", "route", "notes", "user", "budget", "system"}`` like world_state's, plus
    ``part`` (``character`` / ``overview`` / ``dynamics``), ``label``, ``file`` (its prompt's stem) and,
    for a character, ``name`` and the code-built ``level_line``. A job with nothing to write from has an
    empty ``user`` and a ``code_body``: no call is made and code says so.

    A character's prompt holds that character's attributed notes (level rows left out: code writes the
    level), the party-wide notes of the last chunk, and that character's sheet and backstory. It holds no
    other character's notes. The overview and the dynamics get every party-wide note plus the latest two
    notes of each character; the dynamics also get the latest two notes of each companion (GM ruling 2026-10-08).
    """
    attrs, names = ctx.attributions, [c.name for c in ctx.party]
    last = ctx.results[-1].chunk if ctx.results else None
    wide = party_notes.party_wide_notes(attrs)
    wide_last = [n for n in wide if n.chunk == last]
    jobs: list[dict] = []
    for c in ctx.party:
        own = party_notes.character_notes(attrs, c.name)
        job = {
            "heading": "## Characters", "route": "character", "part": "character", "name": c.name,
            "label": f"Characters: {c.name}", "file": f"characters_{_name_slug(c.name)}",
            "notes": len(own), "level_line": ctx.levels[c.name].line, "budget": None, "system": ctx.system,
            "user": "", "code_body": party_notes.NOTHING_RECORDED.format(name=c.name),
        }
        if own:
            blocks = [
                _note_block(f"VERIFIED NOTES ABOUT {c.name}", own),
                _note_block(f"PARTY-WIDE NOTES OF THE LAST CHUNK ({last})", wide_last),
                (f"SHEET ({_rel(c.sheet, ctx.root)}), exactly as the GM authored it:", f"{_FENCE}text\n{c.sheet_text}\n{_FENCE}"),
            ]
            if c.backstory_text is not None:
                blocks.append((f"BACKSTORY ({_rel(c.backstory, ctx.root)}), exactly as the GM authored it:",
                               f"{_FENCE}text\n{c.backstory_text}\n{_FENCE}"))
            budget = ctx.budgets["Characters"]
            job.update(user=_party_prompt("## Characters", state_sections.BRIEFS["## Characters"], budget, blocks, c.name),
                       budget=budget, code_body=None)
        jobs.append(job)
    latest = party_notes.latest_per_character(attrs, names)
    # Party Dynamics also sees the companions travelling with the party (GM ruling 2026-10-08).
    companions = party_notes.latest_per_companion(attrs)
    for heading, part, file in (("## Party Overview", "overview", "party_overview"),
                                ("## Party Dynamics", "dynamics", "party_dynamics")):
        extra = companions if part == "dynamics" else []
        job = {
            "heading": heading, "route": part, "part": part, "label": heading[3:], "file": file,
            "notes": len(wide) + len(latest) + len(extra), "budget": None, "system": ctx.system,
            "user": "", "code_body": party_notes.NOTHING_ABOUT_PARTY,
        }
        if wide or latest or extra:
            budget = ctx.budgets[heading[3:]]
            blocks = [_note_block("PARTY-WIDE NOTES", wide), _note_block("THE LATEST TWO NOTES OF EACH CHARACTER", latest)]
            if part == "dynamics":
                blocks.append(_note_block("THE LATEST TWO NOTES OF EACH COMPANION", extra))
            job.update(user=_party_prompt(heading, state_sections.BRIEFS[heading], budget, blocks),
                       budget=budget, code_body=None)
        jobs.append(job)
    return jobs


def _job_key(j: dict) -> str:
    """Where a job's body is kept: its heading, or (party characters, who share one) heading and name."""
    return f"{j['heading']}|{j['name']}" if j.get("part") == "character" else j["heading"]


def _party_body(out: str) -> str | None:
    """The body a party call wrote: its text with any heading the model repeated at the top dropped."""
    lines = out.strip().splitlines()
    while lines and (not lines[0].strip() or _HEADING_LINE_RE.match(lines[0])):
        lines.pop(0)
    return "\n".join(lines).strip() or None


def _party_body_problems(label: str, body: str) -> list[str]:
    """What the model may not write in a party body: a heading or a level line (code writes both)."""
    out = []
    for ln in body.splitlines():
        if _HEADING_LINE_RE.match(ln):
            out.append(f"{label}: the model wrote a heading ({ln.strip()!r}); code writes the headings")
        elif _LEVEL_LINE_RE.match(ln):
            out.append(f"{label}: the model wrote a level line ({ln.strip()!r}); code writes the level")
    return out


def _party_sections(jobs: list[dict], bodies: dict) -> tuple[dict[str, str], list[str]]:
    """``({heading: body}, problems)`` for party. ``## Characters`` is built by code: for each configured
    character, ``### name``, the level line, the model's body (or the code line when there was nothing to
    write from) and the pointer. A missing or malformed model body is a problem, so the draft is incomplete."""
    sections: dict[str, str] = {}
    problems: list[str] = []
    blocks: list[str] = []
    for j in jobs:
        body = j["code_body"] if j["code_body"] is not None else bodies.get(_job_key(j))
        if body is None:
            problems.append(f"{j['label']}: the model wrote no body")
        elif j["code_body"] is None:
            problems += _party_body_problems(j["label"], body)
        if j["part"] != "character":
            if body is not None:
                sections[j["heading"]] = body
            continue
        block = f"### {j['name']}\n\n{j['level_line']}\n"
        if body is not None:
            block += f"\n{body}\n"
        blocks.append(block + f"\n{party_notes.FULL_NOTES_POINTER}\n")
    sections["## Characters"] = "\n".join(blocks).rstrip("\n")
    return sections, problems


def _planning_jobs(ctx: StateCtx) -> list[dict]:
    """planning's prose jobs: NPC Dossiers, Faction States, Active Plots, DM Notes (spec 034 US2/US3).

    Not built yet: until US2 fills this in, planning has no model-written sections and its draft is incomplete.
    """
    return []
_TIMELINE_HEADING = "## Canon Events Timeline"
_PROMOTED_SUMMARIES = "docs/summaries"  # the reading contract's fallback when the summaries sit outside the campaign


def _slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", heading[3:].lower()).strip("_")


def _budget_words(body: str) -> int:
    """Words in a section body, citations excluded (they are evidence, not prose)."""
    return len(schema.STATE_CITE_RE.sub("", body).split())


def _prose_prompt(doc: str, heading: str, brief: str, routed: list[str], extra: str, last_chunk,
                  budget: int | None = None) -> str:
    """The user prompt of one prose call: its routed notes, any code-built context, and (for the
    current state) the last chunk's summaries. ``budget`` is the section's word limit, if it has one."""
    limit = f"WORD BUDGET: {budget} words, hard limit.\n" if budget else ""
    return (
        f"DOCUMENT: {doc}\nSECTION: {heading}\nBRIEF: {brief}\n{limit}\n"
        f"VERIFIED NOTES ({len(routed)} bullets, chapter order, every one already checked by code):\n\n"
        + ("\n".join(routed) if routed else "(none)")
        + ("\n\n" + extra if extra else "")
        + (
            f"\n\nEVIDENCE OF THE LAST CHUNK ONLY (chapters {last_chunk[0].number:03d}-{last_chunk[-1].number:03d}), "
            "for the current state:\n" + "".join(notes.chapter_block(c) for c in last_chunk)
            if last_chunk else ""
        )
        + f"\n\nOUTLINE: write exactly this one `##` heading and its body, nothing else at that level:\n\n{heading}\n"
    )


def _body_of(out: str, heading: str) -> str | None:
    """The body the model wrote under ``heading``, or ``None`` when it wrote no such heading."""
    secs = npc_check.parse_sections(out)
    if heading not in secs:
        return None
    return npc_check.section_text(secs, heading)


def run_state_synth(
    args,
    *,
    root: Path,
    range_dir: Path,
    report: validate.ValidationReport,
    summaries_dir: Path | None,
    registry_path: Path | None,
    players_path: Path | None,
    track_files: list[str],
    budgets: dict[str, int] | None = None,
    recent_chapters: int = schema.DEFAULT_RECENT_CHAPTERS,
    recurring_min: int = schema.DEFAULT_RECURRING_MIN,
    npc_root: Path | None = None,
    now=None,
    config_dir: Path | None = None,
) -> int:
    """Build a document from the checked notes ``extract`` wrote (party and planning: spec 034).

    ``party`` and ``planning`` are dispatched to ``_party_jobs`` / ``_planning_jobs`` and refuse notes
    extracted before the party subject grammar; the description below is world_state's and campaign_state's.


    Code builds the timeline (its own file), the reference files, the completed list, the NPC
    status table, the audit section and world_state's reading contract; a model writes each
    remaining section from only the notes code routed to it, world_state's within word budgets
    (``budgets``: section name -> words, default ``schema.DEFAULT_WORLD_BUDGETS``). An overrun is
    reported and the text is kept whole. world_state's Key NPCs are rendered from the published NPC
    dossiers (``key_npcs``): the build refuses when a selected NPC has none, unless ``--fallback-npc-lines``.
    Output goes to ``state/drafts/``; no live document is touched.
    """
    now = now or _utcnow
    doc = args.doc
    budgets = {**_default_budgets(doc), **(budgets or {})}
    if report.blocking_count:
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
    since, until = int(manifest["range"]["since"]), int(manifest["range"]["until"])
    extract_cmd = f"summary_native extract --since {since} --until {until}"
    problem = freshness.check_notes_fresh(range_dir, registry_path, players_path, extract_cmd=extract_cmd)
    if problem:
        return _refuse(problem)
    if doc in ("party", "planning"):
        problem = freshness.check_party_grammar(range_dir)
        if problem:
            return _refuse(problem)
    try:
        notes_manifest, results = notes.load_checked(range_dir)
    except notes.NotesIncomplete as e:
        return _refuse(f"{e}; run `{extract_cmd}`")

    track_paths: list[Path] = []
    if doc == "campaign_state":
        for value in track_files:
            p = Path(value).expanduser()
            track_paths.append(p if p.is_absolute() else root / p)
        problem = freshness.check_audit_fresh(range_dir, track_paths)
        if problem:
            return _refuse(problem)
    try:
        forms, pcs, ambiguous = state_sections.load_identity(registry_path, players_path)
    except (ValueError, OSError) as e:
        return _refuse(f"cannot read the entity registry or players.yaml: {e}")
    party_chars: list[context.ResolvedCharacter] = []
    party_path: Path | None = None
    if doc == "party":
        given = getattr(args, "party_config", None)
        party_path = schema.resolve_under(root, given) if given else (
            Path(config_dir) if config_dir is not None else Path(root) / "config") / "party.yaml"
        try:
            party_chars = context.load_party(party_path, root)
        except context.DocConfigError as e:
            return _refuse(str(e))

    rng_name = f"ch{since:03d}-{until:03d}"
    key_plan: list[key_npcs.KeyNpc] = []
    if doc == "world_state":
        try:
            chosen = key_npcs.select_key_npcs(
                select.read_corpus_dossiers(range_dir), key_npcs.registry_npc_scopes(registry_path), pcs,
                range_until=until, recent_chapters=recent_chapters, recurring_min=recurring_min,
                named=[forms.get(n.strip().casefold(), n.strip()) for n in args.name or ()],
            )
        except select.SelectionError as e:
            return _refuse(f"{e} (Key NPCs select the global NPCs only)")
        key_plan = key_npcs.plan_key_npcs(
            chosen, root, npc_root=npc_root or Path(root) / schema.DEFAULT_NPC_ROOT, rng=rng_name, results=results, forms=forms)
        refusal = key_npcs.refusal_message(key_plan, since, until, getattr(args, "npc_root", None))
        refused = bool(refusal) and not getattr(args, "fallback_npc_lines", False)
        # What `GET /state` reports as missing_dossiers: the NPCs the latest world_state attempt found
        # without a usable dossier, whether it then refused or went on with fallback lines.
        atomic_write_text(Path(range_dir) / schema.STATE_DIR / schema.MISSING_DOSSIERS_FILE, json.dumps({
            "range": {"since": since, "until": until},
            "refused": refused,
            "npcs": [{"name": k.name, "state": k.missing} for k in key_plan if k.view is None],
        }, indent=2, ensure_ascii=False) + "\n")
        if refused:
            return _refuse(refusal)

    state_dir = Path(range_dir) / schema.STATE_DIR
    drafts = schema.draft_dir(range_dir, doc)
    draft_path = drafts / f"{doc}.draft.md"
    if draft_path.exists() and not args.force and not args.dump_only:
        return _refuse(f"{draft_path} exists; pass --force to overwrite it")

    # ── code-owned sections ──
    threads = notes.thread_ledger(results)
    code_body: dict[str, str] = {}
    attributions: list[party_notes.Attribution] = []
    levels: dict[str, party_notes.Level] = {}
    status_report = None
    if doc == "party":
        # party's code-built half: who each note is about, each character's level line, and the one
        # reference file its sections point to. It owns no NPC table, timeline or other reference file.
        names = [c.name for c in party_chars]
        attributions = party_notes.attribute(results, (forms, pcs, ambiguous), names)
        levels = {c.name: party_notes.level_for(c.name, results, attributions, c.sheet_text) for c in party_chars}
        reference = {"party": party_notes.reference_md(results, attributions, names)}
    else:
        table, status_report = state_sections.npc_status_table(results, forms, pcs, ambiguous)
        reference = state_sections.reference_files(results, forms)
    if doc == "world_state":
        code_body[_TIMELINE_HEADING] = state_sections.timeline_pointer(results, since, until)
    elif doc != "party":
        code_body["## Completed Encounters & Quests"] = state_sections.completed_md(results)
        code_body["## NPC Current States"] = table
        code_body["## Audit: Tracking Claims"] = state_sections.audit_md(range_dir)

    # ── prose prompts ──
    system = (context.PROMPT_DIR / STATE_SYSTEM[doc]).read_text(encoding="utf-8")
    last_numbers = set(notes_manifest["chunks"][-1]["numbers"]) if notes_manifest.get("chunks") else set()
    last_chunk = []
    if last_numbers and summaries_dir is not None:
        last_chunk = [c for c in notes.load_chapters(Path(summaries_dir), min(last_numbers), max(last_numbers))
                      if c.number in last_numbers]
    jobs = []
    if doc in ("party", "planning"):
        ctx = StateCtx(
            doc=doc, args=args, root=Path(root), range_dir=Path(range_dir),
            config_dir=Path(config_dir) if config_dir is not None else Path(root) / "config",
            since=since, until=until, results=results, forms=forms, pcs=pcs, ambiguous=ambiguous,
            last_chunk=last_chunk, budgets=budgets, system=system,
            registry_path=registry_path, players_path=players_path,
            party=party_chars, attributions=attributions, levels=levels,
        )
        jobs.extend((_party_jobs if doc == "party" else _planning_jobs)(ctx))
    for heading, route, attach in state_sections.PROSE_SECTIONS.get(doc, ()):
        routed = state_sections.route_notes(route, results)
        extra = ""
        if heading == "## Active Threats and Open Pressures":
            extra = "THREAD LEDGER (OPENED / ADVANCED / RESOLVED / ABANDONED):\n\n" + "\n".join(threads)
        budget = budgets[heading[3:]] if doc == "world_state" else None
        user = _prose_prompt(doc, heading, state_sections.BRIEFS[heading], routed, extra,
                             last_chunk if attach else None, budget)
        jobs.append({"heading": heading, "route": route, "notes": len(routed), "user": user, "budget": budget,
                     "system": system})
    key_per = key_published = 0
    if doc == "world_state":
        key_published = sum(1 for k in key_plan if k.view is not None)
        key_per = key_npcs.words_per_line(budgets["Key NPCs"], key_published)
        jobs.append({
            "heading": "## Key NPCs", "route": "dossiers", "notes": key_published,
            "user": key_npcs.lines_prompt(key_plan, key_per) if key_published else "", "budget": budgets["Key NPCs"],
            "system": (context.PROMPT_DIR / "state.npc_lines.system.md").read_text(encoding="utf-8"),
        })
    outline_at = {h: n for n, h in enumerate(load_outline(doc))}
    jobs.sort(key=lambda j: outline_at.get(j["heading"], len(outline_at)))

    started = now()
    run_dir = _new_run_dir(state_dir / "runs", started.strftime("%Y%m%dT%H%M%SZ"))
    run_id = run_dir.name
    atomic_write_text(run_dir / f"{doc}.system.md", system)
    for j in jobs:
        if j["user"]:  # a Key NPCs call with no published dossier behind it is never made
            atomic_write_text(run_dir / f"{doc}.{j.get('file') or _slug(j['heading'])}.user.md", j["user"])
    backend = resolve_cli_model(args, legacy_default=None).backend
    record = {
        "step": "synth",
        "doc": doc,
        "run_id": run_id,
        "range": {"since": since, "until": until},
        "backend": backend,
        "model": args.model,
        "effort": getattr(args, "claude_code_effort", None),
        "max_tokens": args.max_tokens,
        "inputs": {
            "corpus_manifest_sha256": corpus.sha256_file(range_dir / "manifest.json"),
            "notes_manifest_sha256": freshness.sha_file(freshness.notes_dir(range_dir) / freshness.NOTES_MANIFEST),
            "registry_sha256": freshness.sha_file(registry_path),
            "players_sha256": freshness.sha_file(players_path),
            "track_files": [{"path": _rel(p, root), "sha256": corpus.sha256_file(p)} for p in track_paths if p.is_file()],
            # party: the roster file and every sheet, backstory and mechanic file it names, by content
            **({"party_config": {
                "path": _rel(party_path, root), "sha256": corpus.sha256_file(party_path),
                "files": [{"role": role, "path": _rel(p, root), "sha256": corpus.sha256_file(p)}
                          for c in party_chars for role, p in c.files],
            }, "budgets": dict(sorted(budgets.items()))} if doc == "party" else {}),
        },
        "calls": [],
        "key_npcs": {
            "fallback_requested": bool(getattr(args, "fallback_npc_lines", False)),
            "selected": [
                {"name": k.name, "reason": k.reason, "dossier": f"{schema.NPCS_DIR}/{k.slug}.md" if k.view else None,
                 "sha256": freshness.sha_file(Path(root) / schema.NPCS_DIR / f"{k.slug}.md") if k.view else None,
                 "missing": k.missing}
                for k in key_plan
            ],
        } if doc == "world_state" else None,
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
    bodies: dict[str, str | None] = {}
    budget_text: dict[str, str] = {}  # what a section's word budget counts, where that is not the whole body
    key_assembled: key_npcs.Assembled | None = None
    hay = ""
    if doc == "world_state" and summaries_dir is not None:
        hay = "\n".join(c.text for c in notes.load_chapters(Path(summaries_dir), since, until))
    for j in jobs:
        t0 = time.monotonic()
        if j["route"] == "dossiers":
            # world_state's Key NPCs: one call for the NPCs that have a published dossier (none if none do),
            # then code checks every line and builds the rest.
            out = None
            if j["user"]:
                try:
                    out = render_part(client, j["system"], j["user"], args.model, args.max_tokens)
                except Exception as e:
                    fail(f"{j['heading']}: {type(e).__name__}: {e}")
                    print(
                        f"Error: model call failed in section {j['heading']}: {type(e).__name__}: {e} "
                        f"(see {schema.display_path(run_dir / 'record.json', root)})",
                        file=sys.stderr,
                    )
                    return EXIT_MODEL_FAILED
                atomic_write_text(run_dir / f"{doc}.{_slug(j['heading'])}.out.md", out)
            key_assembled = key_npcs.assemble(key_plan, out, hay, key_per, results, forms)
            bodies[j["heading"]] = (
                key_npcs.section_body(key_assembled, key_published, len(key_plan)) if key_plan else key_npcs.NO_NPCS_SELECTED
            )
            budget_text[j["heading"]] = "\n".join(key_assembled.lines)
            record["calls"].append({
                "heading": j["heading"], "route": j["route"], "notes": j["notes"],
                "secs": round(time.monotonic() - t0, 1), "prompt_chars": len(j["user"]), "out_chars": len(out or ""),
            })
            a = key_assembled
            print(f"Key NPCs: {len(key_plan)} NPCs ({a.from_model} from the model, {a.substituted} replaced by the "
                  f"dossier's own sentence, {a.fallbacks} from checked notes)", flush=True)
            for line in a.report:
                print(f"  {line}", flush=True)
            record["key_npcs"].update(from_model=a.from_model, substituted=a.substituted, fallbacks=a.fallbacks,
                                      report=a.report)
            continue
        if j.get("code_body") is not None and not j["user"]:
            # nothing to write from: code says so and no call is made (a party character with no notes)
            print(f"{j['label']}: no notes, no call", flush=True)
            continue
        label = j.get("label") or j["heading"][3:]
        try:
            out = render_part(client, j["system"], j["user"], args.model, args.max_tokens)
        except Exception as e:
            fail(f"{label}: {type(e).__name__}: {e}")
            print(
                f"Error: model call failed in section {label}: {type(e).__name__}: {e} "
                f"(see {schema.display_path(run_dir / 'record.json', root)})",
                file=sys.stderr,
            )
            return EXIT_MODEL_FAILED
        secs = time.monotonic() - t0
        atomic_write_text(run_dir / f"{doc}.{j.get('file') or _slug(j['heading'])}.out.md", out)
        bodies[_job_key(j)] = _party_body(out) if doc == "party" else _body_of(out, j["heading"])
        record["calls"].append({
            "heading": j["heading"], "route": j["route"], "notes": j["notes"],
            "secs": round(secs, 1), "prompt_chars": len(j["user"]), "out_chars": len(out),
            **({"character": j["name"]} if j.get("part") == "character" else {}),
        })
        print(f"{label}: {j['notes']} notes, {secs:.0f}s", flush=True)

    # Budgets count the model's words only, before the pointer is appended. An overrun is reported,
    # never trimmed: cutting prose mid-sentence would be a worse defect than a long section (FR-012).
    budget_report: dict[str, dict] = {}
    for j in jobs:
        body = bodies.get(_job_key(j))
        if j["budget"] and body is not None:
            words = _budget_words(budget_text.get(j["heading"], body))
            budget_report[j.get("label") or j["heading"][3:]] = {"budget": j["budget"], "words": words, "over": words > j["budget"]}
    for name, r in budget_report.items():
        print(f"{name}: {r['words']}/{r['budget']} words" + ("  OVER" if r["over"] else ""), flush=True)
    if budget_report:
        record["budgets"] = budget_report

    headings = load_outline(doc)
    parts: list[str] = []
    party_problems: list[str] = []
    party_sections: dict[str, str] = {}
    if doc == "party":
        party_sections, party_problems = _party_sections(jobs, bodies)
    for h in headings:
        body = code_body[h] if h in code_body else party_sections.get(h) if doc == "party" else bodies.get(h)
        if body is not None and h in state_sections.REFERENCE_FOR and h not in code_body:
            kind = state_sections.REFERENCE_FOR[h]
            body = body.rstrip() + "\n\n" + state_sections.reference_pointer(kind, reference[kind])
        if body is not None:
            parts.append(f"{h}\n{body}\n")
    joined = "\n".join(parts)
    if doc in CONTRACT_DOCS:
        # The reading contract travels with its reference bundle; external summaries keep their path.
        shown = _rel(Path(summaries_dir), root) if summaries_dir is not None else _PROMOTED_SUMMARIES
        contract = state_sections.reading_contract((since, until), {
            "summaries": shown,
            "reference": "reference", "timeline": schema.TIMELINE_FILE,
        }, doc)
        joined = contract + "\n" + joined

    problems = check_outline(joined, headings) + party_problems
    record["check"] = {"complete": not problems, "problems": problems}
    record["finished"] = now().isoformat(timespec="seconds")
    save_record()

    drafts.mkdir(parents=True, exist_ok=True)
    if status_report is not None:
        atomic_write_text(drafts / "npc_status_report.md", status_report)
    if doc == "party":
        atomic_write_text(drafts / "party_report.md", party_notes.report_md(
            results, attributions, [c.name for c in party_chars], levels, since=since, until=until, budgets=budget_report))
    if key_assembled is not None:
        kb = budget_report.get("Key NPCs", {})
        atomic_write_text(drafts / "key_npcs_report.md", key_npcs.report_md(
            key_plan, key_assembled, key_per, kb.get("words", 0), kb.get("budget", 0)))
    # The files the sections point to. Written whether or not the draft is complete: they are
    # built by code from the checked notes and do not depend on the model.
    for kind, md in reference.items():
        atomic_write_text(drafts / "reference" / f"{kind}.md", md)
    if doc != "party":
        atomic_write_text(drafts / schema.TIMELINE_FILE, state_sections.timeline_file_md(results))
    if budget_report:
        atomic_write_text(drafts / "budget_report.json", json.dumps(budget_report, indent=2, ensure_ascii=False) + "\n")
    record_ref = f"runs/{run_id}/record.json"
    if problems:
        target = drafts / f"{doc}.incomplete.md"
        atomic_write_text(
            target,
            f"<!-- summary_native INCOMPLETE | doc: {doc} | range: ch{since:03d}-{until:03d} "
            f"| record: {record_ref} | run: {run_id} -->\n" + joined,
        )
        print(f"Incomplete: {target}", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        if draft_path.exists():
            m = re.search(r"record: runs/([^/\s]+)/record\.json", draft_path.read_text(encoding="utf-8").split("\n", 1)[0])
            print(f"previous draft kept: {_rel(draft_path, range_dir)} (from run {m.group(1) if m else 'unknown'})", file=sys.stderr)
        return EXIT_INCOMPLETE
    text = (
        f"<!-- summary_native draft | doc: {doc} | range: ch{since:03d}-{until:03d} "
        f"| record: {record_ref} | notes manifest sha256: {record['inputs']['notes_manifest_sha256']} -->\n" + joined
    )
    if summaries_dir is not None:
        # Later evidence goes under the line it bears on, verbatim; no line's text changes (FR-020).
        # Code only: a model never rewrites a line after the sections are built.
        ev = annotate.load_evidence(results, notes.load_chapters(Path(summaries_dir), since, until), registry_path, players_path)
        annotated = annotate.annotate_text(text, ev)
        text = annotated.text
        annotate.write_report(drafts, doc, annotated)
        record["annotations"] = annotated.counts()
        save_record()
        print(annotated.summary(), flush=True)
    atomic_write_text(draft_path, text)
    (drafts / f"{doc}.incomplete.md").unlink(missing_ok=True)
    print(f"Wrote draft: {draft_path}")
    return 0
