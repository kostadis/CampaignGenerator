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
from campaignlib.thread_registry import check_registry, load_registry
from campaignlib.util import atomic_write_text
from pipelines.summary_native import annotate, arc_check, context, corpus, freshness, key_npcs, notes, npc_check, party_notes, schema, select, state_sections, thread_attach, thread_check, validate
from pipelines.summary_native.freshness import check_fresh

EXIT_REFUSED = 2
EXIT_INCOMPLETE = 3
EXIT_MODEL_FAILED = 4
EXIT_BLOCKING = 1


def load_outline(doc: str) -> list[str]:
    path = context.PROMPT_DIR / f"{doc}.outline.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [str(h) for h in data["headings"]]


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


def _refuse(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return EXIT_REFUSED


def _rel(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def retired_flag_refusal(args) -> str | None:
    """The refusal for the first retired ``synth`` option ``args`` carries (any value, even ``0``), or ``None``."""
    for flag, refusal in schema.RETIRED_SYNTH_FLAGS.items():
        if getattr(args, flag, None) is not None:
            return refusal
    return None


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
    registry_path: Path | None = None,
    summaries_dir: Path | None = None,
    players_path: Path | None = None,
    budgets: dict[str, int] | None = None,
    npc_root: Path | None = None,
    thread_registry_path: Path | None = None,
    thread_proposals_path: Path | None = None,
    now=None,
) -> int:
    """Refuse what does not apply to ``args.doc`` (exit 2, before any read of the corpus), then build it.

    Every document builds from the checked notes, one call per section (spec 034 retired the one-shot
    path). The retired flags are refused, never silently ignored.
    """
    now = now or _utcnow
    doc = args.doc
    if doc not in schema.SYNTH_DOCS:
        return _refuse(f"synth {doc}: not implemented yet (available: {', '.join(schema.SYNTH_DOCS)})")
    retired = retired_flag_refusal(args)
    if retired:
        return _refuse(retired)
    if args.audit and doc != "campaign_state":
        return _refuse(f"--audit applies to campaign_state only, not {doc}")
    if args.audit:
        return _refuse(schema.STATE_AUDIT_REFUSAL)
    if getattr(args, "npc_root", None) and doc not in ("world_state", "planning"):
        return _refuse(f"--npc-root applies to world_state and planning only, not {doc}")
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
    for flag, owner in (("party_config", "party"), ("planning_config", "planning")):
        if getattr(args, flag, None) and doc != owner:
            return _refuse(f"--{flag.replace('_', '-')} applies to {owner} only, not {doc}")
    return run_state_synth(
        args, root=root, range_dir=range_dir, report=report, summaries_dir=summaries_dir,
        registry_path=registry_path, players_path=players_path, track_files=audit_default,
        budgets=budgets, recent_chapters=recent_chapters, recurring_min=recurring_min,
        npc_root=npc_root, now=now, config_dir=config_dir, thread_registry_path=thread_registry_path,
        thread_proposals_path=thread_proposals_path,
    )


def _detached_lines(proposals_path: Path | None, att: thread_attach.Attachment) -> list[str]:
    """Ratified proposal members that no longer attach, for ``threads_report.md`` (read-only; a build never
    refuses over the proposals file)."""
    if proposals_path is None:
        return []
    try:
        entries = thread_check.load_proposals(proposals_path)
    except (OSError, ValueError) as e:  # a directory, permissions, or YAML: a warning, never a failed build
        return [f"warning: cannot read the proposals file, so no ratified member was checked: {e}"]
    return thread_check.detached_lines(entries, thread_check.detached(entries, att.unattached))


def _excluded_lines(proposals_path: Path | None, registry: dict, range_dir: Path, root: Path) -> list[str]:
    """Excluded or pinned notes (a split's rulings, #529) found in no range's notes, for the thread reports.
    Read-only; an unreadable notes file means nothing is judged, and the line says so. An unreadable proposals
    file only costs the note names in the lines."""
    entries: list = []
    if proposals_path is not None:
        try:
            entries = thread_check.load_proposals(proposals_path)
        except (OSError, ValueError):
            entries = []
    known, unreadable = thread_check.scan_note_ids(range_dir)
    return thread_check.ruling_stale_lines(registry, known, entries, [schema.display_path(f, root) for f in unreadable])


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
#: The documents whose thread sections are built from the GM's thread registry (spec 034 for planning, #530 for campaign_state).
THREAD_DOCS = ("planning", "campaign_state")


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
    #: planning only: the tracked NPCs and factions, the selected NPCs with their dossier views, the ratified
    #: threads attached to the range's thread notes, and the code-built NPC status table (spec 034 US2).
    planning: object = None
    npc_plan: object = None
    attachment: object = None
    #: planning and campaign_state: the GM's thread registry as loaded (the chapter a thread was resolved at is read from it).
    thread_registry: object = None
    status_table: str = ""


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
    notes of each character and of each companion (GM rulings 2026-10-08).
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
    # The overview and the dynamics also see the companions travelling with the party (GM rulings 2026-10-08).
    companions = party_notes.latest_per_companion(attrs)
    for heading, part, file in (("## Party Overview", "overview", "party_overview"),
                                ("## Party Dynamics", "dynamics", "party_dynamics")):
        job = {
            "heading": heading, "route": part, "part": part, "label": heading[3:], "file": file,
            "notes": len(wide) + len(latest) + len(companions), "budget": None, "system": ctx.system,
            "user": "", "code_body": party_notes.NOTHING_ABOUT_PARTY,
        }
        if wide or latest or companions:
            budget = ctx.budgets[heading[3:]]
            blocks = [_note_block("PARTY-WIDE NOTES", wide), _note_block("THE LATEST TWO NOTES OF EACH CHARACTER", latest),
                      _note_block("THE LATEST TWO NOTES OF EACH COMPANION", companions)]
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
        elif ln.strip() == schema.ARC_HEADING:
            out.append(f"{label}: the model wrote {schema.ARC_HEADING!r}; code places the checked candidates there")
        elif _LEVEL_LINE_RE.match(ln):
            out.append(f"{label}: the model wrote a level line ({ln.strip()!r}); code writes the level")
    return out


def _party_sections(jobs: list[dict], bodies: dict, arc: dict | None = None) -> tuple[dict[str, str], list[str]]:
    """``({heading: body}, problems)`` for party. ``## Characters`` is built by code: for each configured
    character, ``### name``, the level line, the model's body (or the code line when there was nothing to
    write from), the character's checked arc-score candidates (``arc``: name -> kept lines; the subsection
    is omitted when none survived) and the pointer. A missing or malformed model body is a problem, so the
    draft is incomplete."""
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
        if (arc or {}).get(j["name"]):
            block += f"\n{schema.ARC_HEADING}\n\n" + "\n".join(arc[j["name"]]) + "\n"
        blocks.append(block + f"\n{party_notes.FULL_NOTES_POINTER}\n")
    sections["## Characters"] = "\n".join(blocks).rstrip("\n")
    return sections, problems


@dataclass
class PlanningPart:
    """What one planning job's ``finish`` hands back: the section body (``None``: the model wrote none), the
    model-written words the budget counts, one line per entry code replaced, and any extras to record."""

    body: str | None
    model_text: str = ""
    report: list = field(default_factory=list)
    record: dict = field(default_factory=dict)
    payload: object = None


def _entries_prompt(doc: str, heading: str, brief: str, budget: int | None, names_label: str, names: list[str], blocks: str) -> str:
    """One per-entry call's user prompt (planning's factions and plots, campaign_state's threads): its
    identifying lines, the names to write about in the order to write them, then each name's notes.
    ``SECTION:`` is the heading the call writes for, so a reader of the run directory can tell the calls
    apart. ``budget`` is ``None`` for a document with no word budgets (campaign_state)."""
    listing = "\n".join(f"{i}. {n}" for i, n in enumerate(names, 1))
    limit = f"WORD BUDGET: {budget} words, hard limit, for the whole section.\n" if budget else ""
    return (
        f"DOCUMENT: {doc}\nSECTION: {heading}\nBRIEF: {brief}\n{limit}\n"
        f"{names_label}, in this order (write exactly one `### <name exactly as given>` block for each, in this order, and no other block):\n"
        f"{listing}\n\n{blocks}\n\n"
        "OUTPUT: the `###` blocks only. No `##` heading, no preamble, no closing remarks.\n"
    )


def _note_lines(ns: list) -> str:
    return "\n".join(n.text for n in ns)


def _npc_dossiers_job(ctx: StateCtx) -> dict:
    """NPC Dossiers: one call for the NPCs that have a published dossier; code checks every block and builds the rest."""
    plan = ctx.npc_plan
    published = [k for k in plan.npcs if plan.view_of(k) is not None]
    per = key_npcs.planning_words_per_block(ctx.budgets["NPC Dossiers"], len(published))

    def finish(out: str | None) -> PlanningPart:
        a = key_npcs.assemble_planning(plan, out, per, ctx.results, ctx.forms)
        body = key_npcs.planning_section_body(a, len(published), len(plan.npcs)) if plan.npcs else key_npcs.NO_NPCS_SELECTED
        return PlanningPart(body, a.model_text, a.report, {
            "from_model": a.from_model, "substituted": a.substituted, "fallbacks": a.fallbacks}, payload=(a, per))

    return {
        "heading": "## NPC Dossiers", "route": "planning_npcs", "file": "npc_dossiers", "notes": len(published),
        "user": key_npcs.planning_prompt(plan, per) if published else "", "budget": ctx.budgets["NPC Dossiers"],
        "system": (context.PROMPT_DIR / "state.planning_npcs.system.md").read_text(encoding="utf-8"), "finish": finish,
    }


def _faction_states_job(ctx: StateCtx) -> dict:
    """Faction States: the factions are chosen by code; one call writes a block per faction that has notes."""
    sel = state_sections.select_factions(
        ctx.results, ctx.forms, [e.name for e in ctx.planning.factions], schema.DEFAULT_MAX_FACTIONS)
    writing = [f for f in sel.selected if f.notes]
    budget = ctx.budgets["Faction States"]
    blocks = "\n\n".join(
        f"=== FACTION: {f.name} ({len(f.notes)} notes, chapter order, every one already checked by code) ===\n{_note_lines(f.notes)}"
        for f in writing)

    def finish(out: str | None) -> PlanningPart:
        check = state_sections.check_entries(out, [f.name for f in writing])
        body, report = state_sections.faction_states_md(sel, check.bodies, check.bad)
        report += [f"- discarded (not a selected faction, or repeated): ### {x}" for x in check.extras]
        return PlanningPart(body, "\n".join(check.bodies.values()), report, {
            "selected": [f.name for f in sel.selected], "overflow": sel.overflow,
            "replaced": sum(1 for f in writing if f.name not in check.bodies)})

    return {
        "heading": "## Faction States", "route": "FACTION", "file": "faction_states", "notes": sum(len(f.notes) for f in writing),
        "user": _entries_prompt("planning", "## Faction States", state_sections.BRIEFS["## Faction States"], budget,
                                "FACTIONS", [f.name for f in writing], blocks) if writing else "",
        "budget": budget, "system": ctx.system, "finish": finish,
    }


def _thread_blocks(threads: list, *, why=None) -> str:
    """Each thread's attached notes, in chapter order, under a ``=== THREAD: title (...) ===`` line. ``why`` is a
    function from a thread to the reason code closed it, for the call that writes how threads ended."""
    return "\n\n".join(
        f"=== THREAD: {s.title} ({len(s.notes)} notes, chapter order, every one already checked by code"
        + (f"; closed because {why(s)}" if why else "") + f") ===\n{_note_lines(s.notes)}"
        for s in threads)


def _thread_job(ctx: StateCtx, *, heading: str, file: str, threads: list, build, record, system: str | None = None,
                why=None, discarded: str = "not an open ratified thread, or repeated") -> dict:
    """One thread section: the threads code chose, in code's order, are written by one call; code checks the entries
    and builds the section around them (``build`` is ``state_sections.active_plots_md`` or ``resolved_threads_md``).

    ``record(section)`` is what the run record keeps about the section. The budget is the document's, if it has
    one (planning's Active Plots; campaign_state has none). ``why``, ``system`` and
    ``discarded`` (the wording of the report line for a heading the model added) are per document: campaign_state's
    calls say nothing about a word budget or a planning document, and planning's output must stay as it was.
    """
    att = ctx.attachment
    budget = ctx.budgets["Active Plots"] if ctx.doc == "planning" else None

    def finish(out: str | None) -> PlanningPart:
        check = state_sections.check_entries(out, [s.title for s in threads])
        sec = build(att, {s.id: check.bodies.get(s.title) for s in threads}, {s.id: check.bad.get(s.title, "") for s in threads})
        report = sec.report + [f"- discarded ({discarded}): ### {x}" for x in check.extras]
        return PlanningPart(sec.text, sec.model_text, report, record(sec))

    return {
        "heading": heading, "route": "threads", "file": file, "notes": sum(len(s.notes) for s in threads),
        "user": _entries_prompt(ctx.doc, heading, state_sections.BRIEFS[heading], budget, "THREADS",
                                [s.title for s in threads], _thread_blocks(threads, why=why)) if threads else "",
        "budget": budget, "system": system or ctx.system, "finish": finish,
    }


def _open_record(att):
    """What the run record keeps about a section of open threads (Active Plots, Active Quests & Open Threads)."""
    return lambda sec: {
        "open": [s.title for s in att.open_threads], "dormant": [s.title for s in att.dormant_threads],
        "unratified": len(att.unattached), "replaced": sec.replaced}


def _active_plots_job(ctx: StateCtx) -> dict:
    """Active Plots: the open ratified threads, newest activity first, are written by one call; code checks the
    entries and builds the dormant and unratified blocks."""
    att = ctx.attachment
    return _thread_job(
        ctx, heading="## Active Plots", file="active_plots", threads=att.open_threads,
        build=state_sections.active_plots_md, record=_open_record(att))


def _dm_notes_job(ctx: StateCtx) -> dict:
    """DM Notes: one call, from the open threads' latest notes, the NPC status table and the last chunk."""
    budget = ctx.budgets["DM Notes"]
    latest = [s.latest.text for s in ctx.attachment.open_threads]
    has_input = bool(latest or ctx.status_table.count("\n") > 1 or ctx.last_chunk)
    user = ""
    if has_input:
        user = (
            f"DOCUMENT: planning\nSECTION: ## DM Notes\nBRIEF: {state_sections.BRIEFS['## DM Notes']}\n"
            f"WORD BUDGET: {budget} words, hard limit.\n\n"
            f"THE LATEST NOTE OF EACH OPEN THREAD ({len(latest)} bullets, every one already checked by code):\n\n"
            + ("\n".join(latest) if latest else "(none)")
            + "\n\nNPC CURRENT STATES (built by code from the checked notes):\n\n" + ctx.status_table
            + (
                f"\n\nEVIDENCE OF THE LAST CHUNK ONLY (chapters {ctx.last_chunk[0].number:03d}-{ctx.last_chunk[-1].number:03d}), "
                "for the current state:\n" + "".join(notes.chapter_block(c) for c in ctx.last_chunk)
                if ctx.last_chunk else "")
            + "\n\nOUTPUT: bullets only, each cited. No heading, no preamble, and not the label that opens the section: code writes it.\n"
        )

    def finish(out: str | None) -> PlanningPart:
        if not user:
            return PlanningPart(f"{schema.DM_NOTES_LABEL}\n\n_No open thread, NPC status or recent evidence in this range to suggest from._")
        body = _party_body(out) if out else None
        if body is None:
            return PlanningPart(None, report=["- DM Notes: the model wrote no body"])
        return PlanningPart(f"{schema.DM_NOTES_LABEL}\n\n{body}", body)

    return {
        "heading": "## DM Notes", "route": "dm_notes", "file": "dm_notes", "notes": len(latest),
        "user": user, "budget": budget, "system": ctx.system, "finish": finish,
    }


def _planning_jobs(ctx: StateCtx) -> list[dict]:
    """planning's prose jobs: NPC Dossiers, Faction States, Active Plots, DM Notes (spec 034 US2, research R8/R9).

    The Threat Tracker is code only. Each job is ``{"heading", "route", "file", "notes", "user", "budget",
    "system", "finish"}``; ``finish(out)`` is the code that checks the call's output (``None`` when no call
    was made) and builds the section. A job with nothing to write from has an empty ``user``: no call is
    made and ``finish`` builds the section from what code knows.
    """
    return [_npc_dossiers_job(ctx), _faction_states_job(ctx), _active_plots_job(ctx), _dm_notes_job(ctx)]


def _campaign_jobs(ctx: StateCtx) -> list[dict]:
    """campaign_state's thread jobs: Resolved Plot Threads and Active Quests & Open Threads (#530).

    Thread identity, openness and order are planning's (``thread_attach``): the GM's registry decides which
    notes are one thread and a registry status or the latest note's tag decides whether it is open. The
    closed threads go to Resolved, the open ones to Active Quests (with the dormant and unratified blocks,
    which code builds). campaign_state's other prose section, Party Current Situation, is a plain routed call.
    """
    att = ctx.attachment
    system = (context.PROMPT_DIR / "state.campaign_threads.system.md").read_text(encoding="utf-8")
    heading = "## Resolved Plot Threads"
    resolved = _thread_job(
        ctx, heading=heading, file=_slug(heading), threads=att.closed_threads, build=state_sections.resolved_threads_md,
        record=lambda sec: {"resolved": [s.title for s in att.closed_threads], "replaced": sec.replaced},
        system=system, why=lambda s: s.why, discarded="not a thread given to the model, or repeated")
    heading = "## Active Quests & Open Threads"
    active = _thread_job(
        ctx, heading=heading, file=_slug(heading), threads=att.open_threads, build=state_sections.active_plots_md,
        record=_open_record(att), system=system, discarded="not a thread given to the model, or repeated")
    return [resolved, active]


# ── arc-score candidates (spec 034 US4, research R10) ───────────────────────

_ARC_BRIEF = ("List the events in these notes that a rule in the MECHANIC FILE might count toward the arc score. "
              "You are not tracking the score: never state a value, a total or a threshold.")


def _arc_prompt(doc: str, subject: str, kind: str, ns: list, mechanic: str, mechanic_text: str) -> str:
    """One arc call's user prompt: the subject's checked notes and the mechanic file's text, nothing else.

    ``SECTION:`` is the call's own marker (never a real heading), so a reader of a run directory can tell it
    from the prose calls. Notes are the subject's alone: a PC's attributed party notes, or an NPC or faction's
    notes by canonical subject.
    """
    return (
        f"DOCUMENT: {doc}\nSECTION: {schema.ARC_CALL_SECTION}\nSUBJECT: {subject}\nKIND: {kind}\nBRIEF: {_ARC_BRIEF}\n\n"
        f"VERIFIED NOTES ABOUT {subject} ({len(ns)} bullets, chapter order, every one already checked by code):\n\n"
        + "\n".join(n.text for n in ns)
        + f"\n\nMECHANIC FILE ({mechanic}), exactly as the GM authored it:\n\n{_FENCE}text\n{mechanic_text}\n{_FENCE}\n\n"
        "OUTPUT: candidate lines only, in the form `- <event> [citation] — trigger: \"<trigger text>\"`; "
        "or `- (none)`. No heading, no preamble, no closing remarks.\n"
    )


def _arc_jobs(ctx: StateCtx) -> tuple[list[dict], list[arc_check.ArcSubject]]:
    """``(jobs, subjects)`` for the arc step: one job per configured, non-trackless score with notes behind it.

    ``subjects`` lists every tracked subject in config order (party: the characters; planning: the NPCs then
    the factions) for ``arc_report.md``. A trackless subject, or one with no checked notes, has no job: no
    call is made and no candidate can appear. A job is ``{"subject", "kind", "file", "user", "system",
    "notes", "cites", "mechanic", "mechanic_text"}``.
    """
    if ctx.doc == "party":
        subjects = [(c.name, "character", c.arc_score, party_notes.character_notes(ctx.attributions, c.name)) for c in ctx.party]
    else:
        kinds = [(e, "npc") for e in ctx.planning.npcs] + [(e, "faction") for e in ctx.planning.factions]
        subjects = [(e.name, k, e.arc_score, arc_check.entity_notes(ctx.results, ctx.forms, e.name)) for e, k in kinds]
    system = (context.PROMPT_DIR / "state.arc.system.md").read_text(encoding="utf-8")
    jobs: list[dict] = []
    report: list[arc_check.ArcSubject] = []
    for name, kind, path, ns in subjects:
        if path is None:  # trackless (or none declared): no call, no candidate, no suggestion (FR-015)
            report.append(arc_check.ArcSubject(name, kind, None, trackless=True))
            continue
        shown = _rel(path, ctx.root)
        report.append(arc_check.ArcSubject(name, kind, shown, len(ns)))
        if not ns:
            continue
        text = Path(path).read_text(encoding="utf-8")
        stem = f"arc_{_name_slug(name)}"
        while any(j["file"] == stem for j in jobs):  # two subjects can slug alike (an NPC and a faction)
            stem += "_"
        jobs.append({
            "subject": name, "kind": kind, "file": stem, "system": system, "notes": len(ns),
            "user": _arc_prompt(ctx.doc, name, kind, ns, shown, text), "cites": arc_check.cites_of(ns),
            "mechanic": shown, "mechanic_text": text,
        })
    return jobs, report


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
    thread_registry_path: Path | None = None,
    thread_proposals_path: Path | None = None,
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

    planning: context.ResolvedPlanning | None = None
    planning_path: Path | None = None
    attachment: thread_attach.Attachment | None = None
    if doc == "planning":
        given = getattr(args, "planning_config", None)
        planning_path = schema.resolve_under(root, given) if given else (
            Path(config_dir) if config_dir is not None else Path(root) / "config") / "planning.yaml"
        try:
            planning = context.load_planning(planning_path, root, explicit=bool(given))
        except context.DocConfigError as e:
            return _refuse(str(e))
    if doc in THREAD_DOCS:
        # Thread identity is the GM's registry; a registry that fails its own check is not read (spec 034 R4).
        # campaign_state reads it the same way (#530): no registry file is an empty one, so no ratified thread.
        try:
            thread_registry = load_registry(thread_registry_path) if thread_registry_path is not None else {"version": 1, "threads": []}
            thread_registry["threads"] = list(thread_registry.get("threads") or [])
            findings = check_registry(thread_registry)
        except (OSError, ValueError, AttributeError, TypeError) as e:  # YAML errors are ValueErrors
            return _refuse(f"cannot read the thread registry: {e}")
        if findings:
            return _refuse(
                f"the thread registry {schema.display_path(thread_registry_path, root)} fails `thread_registry check`; "
                "fix it first:\n  " + "\n  ".join(findings))
        attachment = thread_attach.attach(results, thread_registry, until)

    rng_name = f"ch{since:03d}-{until:03d}"
    key_plan: list[key_npcs.KeyNpc] = []
    npc_plan: key_npcs.PlanningPlan | None = None
    if doc in ("world_state", "planning"):
        named = [forms.get(n.strip().casefold(), n.strip()) for n in args.name or ()]
        npc_dir = npc_root or Path(root) / schema.DEFAULT_NPC_ROOT
        scopes = key_npcs.registry_npc_scopes(registry_path)
        try:
            if doc == "world_state":
                chosen = key_npcs.select_key_npcs(
                    select.read_corpus_dossiers(range_dir), scopes, pcs,
                    range_until=until, recent_chapters=recent_chapters, recurring_min=recurring_min, named=named,
                )
                key_plan = key_npcs.plan_key_npcs(
                    chosen, root, npc_root=npc_dir, rng=rng_name, results=results, forms=forms)
            else:
                npc_plan = key_npcs.plan_planning_npcs(
                    select.read_corpus_dossiers(range_dir), scopes, pcs, forms, [e.name for e in planning.npcs],
                    range_until=until, recent_chapters=recent_chapters, recurring_min=recurring_min, named=named,
                    campaign=Path(root), npc_root=npc_dir, rng=rng_name, results=results,
                )
                key_plan = npc_plan.npcs
        except select.SelectionError as e:
            return _refuse(f"{e} ({'Key NPCs' if doc == 'world_state' else 'NPC Dossiers'} select the global NPCs only)")
        refusal = key_npcs.refusal_message(key_plan, since, until, getattr(args, "npc_root", None), doc=doc)
        refused = bool(refusal) and not getattr(args, "fallback_npc_lines", False)
        # What `GET /state` reports as missing_dossiers: the NPCs the latest attempt of this document found
        # without a usable dossier, whether it then refused or went on with fallback lines.
        atomic_write_text(Path(range_dir) / schema.STATE_DIR / schema.missing_dossiers_file(doc), json.dumps({
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
    if doc == "planning":
        # planning points at four reference files only (its reading contract lists them), and builds its
        # Threat Tracker, the pointers and the thread layers by code; thread identity is the GM's registry.
        reference = {k: v for k, v in reference.items() if k in state_sections.CONTRACT_REFERENCES["planning"]}
        code_body["## Threat Tracker"] = state_sections.threat_tracker_md(planning.entries, None, root=root)
        reference[state_sections.UNRATIFIED_KIND] = state_sections.unratified_reference_md(attachment)
        thread_attach.write_attach(range_dir, attachment, (since, until))
    elif doc == "world_state":
        code_body[_TIMELINE_HEADING] = state_sections.timeline_pointer(results, since, until)
    elif doc != "party":
        code_body["## Completed Encounters & Quests"] = state_sections.completed_md(results)
        code_body["## NPC Current States"] = table
        code_body["## Audit: Tracking Claims"] = state_sections.audit_md(range_dir)
        # the Active Quests section points at the unratified notes (#530), as planning's Active Plots does
        reference[state_sections.UNRATIFIED_KIND] = state_sections.unratified_reference_md(attachment)
        thread_attach.write_attach(range_dir, attachment, (since, until))

    # ── prose prompts ──
    system = (context.PROMPT_DIR / STATE_SYSTEM[doc]).read_text(encoding="utf-8")
    last_numbers = set(notes_manifest["chunks"][-1]["numbers"]) if notes_manifest.get("chunks") else set()
    last_chunk = []
    if last_numbers and summaries_dir is not None:
        last_chunk = [c for c in notes.load_chapters(Path(summaries_dir), min(last_numbers), max(last_numbers))
                      if c.number in last_numbers]
    jobs = []
    arc_jobs: list[dict] = []
    arc_subjects: list[arc_check.ArcSubject] = []
    if doc in ("party", "planning", "campaign_state"):
        ctx = StateCtx(
            doc=doc, args=args, root=Path(root), range_dir=Path(range_dir),
            config_dir=Path(config_dir) if config_dir is not None else Path(root) / "config",
            since=since, until=until, results=results, forms=forms, pcs=pcs, ambiguous=ambiguous,
            last_chunk=last_chunk, budgets=budgets, system=system,
            registry_path=registry_path, players_path=players_path,
            party=party_chars, attributions=attributions, levels=levels,
            planning=planning, npc_plan=npc_plan, attachment=attachment, status_table=table if doc == "planning" else "",
            thread_registry=thread_registry if doc in THREAD_DOCS else None,
        )
        jobs.extend({"party": _party_jobs, "planning": _planning_jobs, "campaign_state": _campaign_jobs}[doc](ctx))
        if doc != "campaign_state":
            arc_jobs, arc_subjects = _arc_jobs(ctx)
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
            if j["system"] != system:  # planning's NPC Dossiers call has a prompt of its own
                atomic_write_text(run_dir / f"{doc}.{j.get('file') or _slug(j['heading'])}.system.md", j["system"])
    for aj in arc_jobs:
        atomic_write_text(run_dir / f"{doc}.{aj['file']}.user.md", aj["user"])
    if arc_jobs:
        atomic_write_text(run_dir / f"{doc}.arc.system.md", arc_jobs[0]["system"])
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
            # planning: the config and every mechanic file it names, the GM's thread registry, and the budgets
            **({"planning_config": {
                "path": _rel(planning_path, root) if planning.path is not None else None,
                "sha256": corpus.sha256_file(planning.path) if planning.path is not None else None,
                "files": [{"role": f"arc_score:{e.name}", "path": _rel(e.arc_score, root), "sha256": corpus.sha256_file(e.arc_score)}
                          for e in planning.scored],
            }, "thread_registry_sha256": freshness.sha_file(thread_registry_path),
                "budgets": dict(sorted(budgets.items()))} if doc == "planning" else {}),
            # campaign_state: the GM's thread registry decides its two thread sections, so it is an input (#530)
            **({"thread_registry_sha256": freshness.sha_file(thread_registry_path)} if doc == "campaign_state" else {}),
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
        } if doc in ("world_state", "planning") else None,
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
    planning_parts: dict[str, PlanningPart] = {}
    hay = ""
    if doc == "world_state" and summaries_dir is not None:
        hay = "\n".join(c.text for c in notes.load_chapters(Path(summaries_dir), since, until))
    for j in jobs:
        t0 = time.monotonic()
        if j.get("finish"):
            # planning's sections: a call when there is something to write from, then code checks the output
            # and builds the section (a block that fails its check is replaced by the source text).
            out = None
            label = j["heading"][3:]
            if j["user"]:
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
                atomic_write_text(run_dir / f"{doc}.{j['file']}.out.md", out)
                record["calls"].append({
                    "heading": j["heading"], "route": j["route"], "notes": j["notes"],
                    "secs": round(secs, 1), "prompt_chars": len(j["user"]), "out_chars": len(out),
                })
                print(f"{label}: {j['notes']} notes, {secs:.0f}s", flush=True)
            else:
                print(f"{label}: nothing to write from, no call", flush=True)
            part = j["finish"](out)
            planning_parts[j["heading"]] = part
            bodies[j["heading"]] = part.body
            budget_text[j["heading"]] = part.model_text
            for line in part.report:
                print(f"  {line}", flush=True)
            continue
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

    # ── arc-score candidates: one call per configured, non-trackless score, each checked by code before
    # it is placed (party: under the character's section; planning: in the Threat Tracker's cell).
    arc_by_name = {s.name: s for s in arc_subjects}
    for aj in arc_jobs:
        t0 = time.monotonic()
        label = f"Arc score: {aj['subject']}"
        try:
            out = render_part(client, aj["system"], aj["user"], args.model, args.max_tokens)
        except Exception as e:
            fail(f"{label}: {type(e).__name__}: {e}")
            print(
                f"Error: model call failed in {label}: {type(e).__name__}: {e} "
                f"(see {schema.display_path(run_dir / 'record.json', root)})",
                file=sys.stderr,
            )
            return EXIT_MODEL_FAILED
        secs = time.monotonic() - t0
        atomic_write_text(run_dir / f"{doc}.{aj['file']}.out.md", out)
        kept, drops = arc_check.check_candidates(out, aj["cites"], aj["mechanic_text"])
        arc_by_name[aj["subject"]].kept, arc_by_name[aj["subject"]].drops = kept, drops
        record["calls"].append({
            "heading": schema.ARC_HEADING, "route": "arc", "subject": aj["subject"], "notes": aj["notes"],
            "secs": round(secs, 1), "prompt_chars": len(aj["user"]), "out_chars": len(out),
        })
        print(f"{label}: {aj['notes']} notes, {len(kept)} kept, {len(drops)} dropped, {secs:.0f}s", flush=True)
    if any(not s.trackless for s in arc_subjects):
        record["arc"] = {s.name: {"kind": s.kind, "mechanic": s.mechanic, "trackless": s.trackless, "notes": s.notes,
                                  "kept": len(s.kept), "dropped": len(s.drops)} for s in arc_subjects}
    arc_kept = {s.name: s.kept for s in arc_subjects if s.kept}
    if doc == "planning":
        code_body["## Threat Tracker"] = state_sections.threat_tracker_md(
            planning.entries, {n: arc_check.candidate_cell(k) for n, k in arc_kept.items()}, root=root)

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

    if doc == "planning":
        record["planning"] = {h[3:]: p.record for h, p in sorted(planning_parts.items()) if p.record}
        if "## NPC Dossiers" in planning_parts:
            record["key_npcs"].update(planning_parts["## NPC Dossiers"].record)
            record["key_npcs"]["report"] = planning_parts["## NPC Dossiers"].report
        record["planning"]["Active Plots"] = {
            **record["planning"].get("Active Plots", {}),
            "report": planning_parts["## Active Plots"].report if "## Active Plots" in planning_parts else []}
        record["planning"]["Faction States"] = {
            **record["planning"].get("Faction States", {}),
            "report": planning_parts["## Faction States"].report if "## Faction States" in planning_parts else []}
    if doc == "campaign_state":
        # what code decided about each thread section, and every entry it replaced (#530)
        record["threads"] = {h[3:]: {**p.record, "report": p.report} for h, p in sorted(planning_parts.items())}
    headings = load_outline(doc)
    parts: list[str] = []
    party_problems: list[str] = []
    party_sections: dict[str, str] = {}
    if doc == "party":
        party_sections, party_problems = _party_sections(jobs, bodies, arc_kept)
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

    planning_problems = [f"{h[3:]}: the model wrote no body" for h, part in planning_parts.items() if part.body is None]
    problems = check_outline(joined, headings) + party_problems + planning_problems
    record["check"] = {"complete": not problems, "problems": problems}
    record["finished"] = now().isoformat(timespec="seconds")
    save_record()

    drafts.mkdir(parents=True, exist_ok=True)
    if status_report is not None:
        atomic_write_text(drafts / "npc_status_report.md", status_report)
    if doc == "party":
        atomic_write_text(drafts / "party_report.md", party_notes.report_md(
            results, attributions, [c.name for c in party_chars], levels, since=since, until=until, budgets=budget_report))
    if any(not s.trackless for s in arc_subjects):
        atomic_write_text(drafts / "arc_report.md", arc_check.arc_report_md(arc_subjects))
    else:  # no score configured: no report, and none left over from a run that had one
        (drafts / "arc_report.md").unlink(missing_ok=True)
    if key_assembled is not None:
        kb = budget_report.get("Key NPCs", {})
        atomic_write_text(drafts / "key_npcs_report.md", key_npcs.report_md(
            key_plan, key_assembled, key_per, kb.get("words", 0), kb.get("budget", 0)))
    # ratified proposal members that no longer attach (#525), for the thread report of either document that reads the registry
    detached_lines = _detached_lines(thread_proposals_path, attachment) if doc in THREAD_DOCS else []
    # split-off notes whose exclusion id is on no disk (#529), likewise computed once for both reports
    excluded_lines = _excluded_lines(thread_proposals_path, thread_registry, range_dir, root) if doc in THREAD_DOCS else []
    if doc == "planning":
        # What code replaced in planning, and the thread layers it built (the attach map itself is state/threads/attach.json).
        nb = budget_report.get("NPC Dossiers", {})
        npc_part = planning_parts.get("## NPC Dossiers")
        faction_part = planning_parts.get("## Faction States")
        faction_lines = None
        if faction_part is not None:
            # Faction States' side of the same file: which factions were written, which the cap left out, and
            # every entry code replaced or discarded (also in the run record, but a report is what a GM opens).
            sel_rec = faction_part.record
            faction_lines = [
                f"- {len(sel_rec.get('selected', []))} written: {', '.join(sel_rec.get('selected', [])) or '(none)'}",
                *([f"- {len(sel_rec['overflow'])} not written (the cap): {', '.join(sel_rec['overflow'])}"]
                  if sel_rec.get("overflow") else []),
                *faction_part.report,
            ]
        if npc_part is not None and npc_part.payload is not None:
            a, per = npc_part.payload
            atomic_write_text(drafts / "planning_npcs_report.md", key_npcs.planning_report_md(
                npc_plan, a, per, nb.get("words", 0), nb.get("budget", 0), faction_lines))
        plots_part = planning_parts.get("## Active Plots")
        atomic_write_text(drafts / "threads_report.md", thread_attach.threads_report_md(
            attachment, (since, until), detached_lines, excluded_lines) + "\n".join([
            "", "## Active Plots entries replaced by code", "", *((plots_part.report if plots_part else []) or ["- (none)"]), ""]))
    if doc == "campaign_state":
        # campaign_state's side of threads_report.md, in a file of its own so one document's report never replaces the other's
        lines = [f"## {h[3:]} entries replaced by code\n\n" + "\n".join(planning_parts[h].report or ["- (none)"]) + "\n"
                 for h in ("## Resolved Plot Threads", "## Active Quests & Open Threads") if h in planning_parts]
        atomic_write_text(drafts / schema.CAMPAIGN_THREADS_REPORT_FILE,
                          thread_attach.threads_report_md(attachment, (since, until), detached_lines, excluded_lines)
                          + "\n".join(["", *lines]))
    # The files the sections point to. Written whether or not the draft is complete: they are
    # built by code from the checked notes and do not depend on the model.
    for kind, md in reference.items():
        atomic_write_text(drafts / "reference" / f"{kind}.md", md)
    if doc not in ("party", "planning"):
        atomic_write_text(drafts / schema.TIMELINE_FILE, state_sections.timeline_file_md(results))
    # one file per document: planning's and party's budgets must not replace world_state's, and a document
    # with no budgets (campaign_state) neither writes nor deletes one
    if doc in schema.BUDGET_DOCS:
        budget_file = drafts / schema.budget_report_file(doc)
        if budget_report:
            atomic_write_text(budget_file, json.dumps(budget_report, indent=2, ensure_ascii=False) + "\n")
        else:
            # a run with nothing to report must not leave the previous build's numbers standing as "the last build"
            budget_file.unlink(missing_ok=True)
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
