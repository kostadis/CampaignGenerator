"""The code-owned sections of world_state and campaign_state (spec 033 T018, FR-007..FR-010). No model call.

The event timeline, the completed-encounters list and the NPC current-status table are built here,
by code, from the checked notes, the entity registry and ``players.yaml``. A model never decides
who an NPC is, which row is the latest, or whether a player character belongs in the table; those
are identity and ordering decisions (Principle II).

Every function is a pure function of its inputs and emits no timestamp, so
the output is byte-identical across rebuilds from the same notes, registry and roster (FR-010).
Guarded by ``tests/test_summary_native_no_llm.py``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from campaignlib.players_config import load_players_config
from campaignlib.registry import load_registry
from pipelines.summary_native import audit_select, freshness, notes, schema, thread_attach

# ── Timeline and completed encounters ───────────────────────────────────────


def _bullets(items: list[str]) -> str:
    return "\n".join(items) if items else schema.NONE_VERIFIED


def timeline_md(results: Sequence[notes.CheckedChunk]) -> str:
    """Every kept event note, one bullet each, in chapter order with exact duplicates removed."""
    return _bullets(notes.stitched(results, "event"))


def completed_md(results: Sequence[notes.CheckedChunk]) -> str:
    """Every kept concluded note, in chapter order with exact duplicates removed."""
    return _bullets(notes.stitched(results, "concluded"))


def timeline_file_md(results: Sequence[notes.CheckedChunk]) -> str:
    """``canon_events_timeline.md``: the whole timeline, a file of its own (FR-013)."""
    return "# Canon Events Timeline\n\n" + timeline_md(results) + "\n"


def timeline_pointer(results: Sequence[notes.CheckedChunk], since: int, until: int) -> str:
    """world_state's ``## Canon Events Timeline`` body: the count and where the events are."""
    n = len(notes.stitched(results, "event"))
    return (
        f"The full timeline ({n} events, ch {since:03d}-{until:03d}, every one cited) is a separate file: "
        f"`{schema.TIMELINE_FILE}`. It is built by code from the checked notes, in chapter order, "
        "and is not loaded with this document."
    )


# ── Reference files (FR-013) ────────────────────────────────────────────────

#: ``kind -> the World tag it holds`` (``None``: the thread ledger). The file is
#: ``reference/<kind>.md``; the reading contract lists all six.
REFERENCE_KINDS: dict[str, str | None] = {
    "factions": "FACTION", "npcs": "NPC", "locations": "LOCATION",
    "items": "ITEM", "threats": "THREAT", "threads": None,
}
_NO_SUBJECT = "(no subject)"
_COUNTS_RE = re.compile(r"^(\d+) checked notes, (\d+) subjects", re.M)


def _reference_md(kind: str, results: Sequence[notes.CheckedChunk], forms: dict[str, str]) -> str:
    tag = REFERENCE_KINDS[kind]
    seen: set[str] = set()
    found: list[notes.Note] = []
    for r in results:
        for n in r.notes:
            if n.text in seen or (n.kind != "thread" if tag is None else (n.kind != "world" or n.tag != tag)):
                continue
            seen.add(n.text)
            found.append(n)
    groups: dict[str, list[notes.Note]] = {}
    for n in sorted(found, key=lambda n: n.first_chapter):  # stable: extraction order within a chapter
        subject = n.subject or _NO_SUBJECT
        groups.setdefault(forms.get(subject.strip().casefold(), subject), []).append(n)
    lines = [
        f"# Reference: {kind.title()}", "",
        f"{len(found)} checked notes, {len(groups)} subjects, chapter order within each. "
        "Built by code from the checked notes; nothing is reworded.", "",
    ]
    if not found:
        lines += [schema.NONE_VERIFIED, ""]
    for subject in sorted(groups, key=lambda s: (s.casefold(), s)):
        lines += [f"## {subject}", *(n.text for n in groups[subject]), ""]
    return "\n".join(lines)


def reference_files(results: Sequence[notes.CheckedChunk], forms: dict[str, str] | None = None) -> dict[str, str]:
    """``{kind: markdown}`` for the six reference files: every kept note of the kind, verbatim,
    under canonical registry headings when known, otherwise the original subject. Exact matches only;
    note text stays verbatim and notes stay in chapter order within each heading."""
    return {kind: _reference_md(kind, results, forms or {}) for kind in REFERENCE_KINDS}


def reference_pointer(kind: str, md: str) -> str:
    """The line a section ends with, pointing to its reference file."""
    m = _COUNTS_RE.search(md)
    notes_n, subjects_n = (m.group(1), m.group(2)) if m else ("0", "0")
    return f"_Full notes: reference/{kind}.md ({subjects_n} subjects, {notes_n} checked notes)._"


# ── The reading contract (FR-015, research R10) ─────────────────────────────

_HEAD = """\
> **How to read this document.** It is the long-range memory of the campaign (ch {since:03d}-{until:03d}), generated
> from the session summaries and checked by code. The last two session summaries outrank it for recent events.
> - `{later}` under a line is newer information about the **same subject**: where the two conflict, the
>   later one wins; where they don't, both hold.
> - `{since_}` under a line is the later status of someone the line **mentions**: context, not a correction
>   of the line.
> - `{unverified}` marks a quotation that is not verbatim in the chapter it cites, or a citation that does
>   not resolve: read it as a paraphrase, not as words anyone said.
> - `[ch NNN / target]` cites `{summaries}/NNN-*.md`. The target is a scene id (`NNN.SS`), or that chapter's
>   `npcs`, `locations`, `items`, `spells`, `moment` (Memorable Moments) or `end` (Session-End State) section.
"""

#: The published-dossier paragraph: world_state's ``## Key NPCs`` and planning's ``## NPC Dossiers``.
_DOSSIERS = """\
> - Each line under `{section}` ends with `→ docs/npcs/<slug>.md`, the NPC's published dossier (open it for
>   the full account), or with `{fallback}`: that NPC has no published dossier, and the line is its latest
>   status and checked notes, verbatim.
"""

#: planning only: the two layers of ``## Active Plots`` and where the proposals queue is.
_THREADS = """\
> - `## Active Plots` lists the threads the GM has ratified in `docs/thread_registry.yaml`, newest activity first,
>   each written from its checked notes. `{dormant}` lists the ones the GM marked dormant, as their latest note,
>   verbatim. `{unratified}` counts the checked thread notes that no ratified thread owns; the notes themselves,
>   verbatim and in chapter order, are in `{unratified_file}`: evidence, not plots. Rule on them at
>   `/grounding/threads` (the proposals queue is `docs/ensemble/thread_proposals.yaml`).
"""

_FILES = "> - Every checked note, by subject: {files}.\n"
_TIMELINE = ">   Every event, in order: `{timeline}`.\n"

_TAIL = """\
> - {paths_are} relative to this document. Summary and dossier paths are
>   relative to the campaign root unless absolute. After copying, run `summary_native check-pointers FILE`.
> - Anything this document does not settle is a decision for the GM, not something to fill in.
"""

#: ``reference/threads_unratified.md``: planning's unattached thread notes (FR-009b), not a World-tag kind.
UNRATIFIED_KIND = "threads_unratified"

#: The reference files each document's contract lists, in order (research R13). world_state lists
#: all six kinds; the other documents name only the files they point to.
CONTRACT_REFERENCES: dict[str, tuple[str, ...]] = {
    "world_state": tuple(REFERENCE_KINDS),
    "campaign_state": ("threads",),
    "party": ("party",),
    "planning": ("factions", "npcs", "threads", UNRATIFIED_KIND),
}
#: The section whose lines point to a published dossier, for the documents that have one.
_DOSSIER_SECTION = {"world_state": "## Key NPCs", "planning": "## NPC Dossiers"}


def reading_contract(rng: tuple[int, int], paths: dict[str, str], doc: str = "world_state") -> str:
    """The blockquote a document opens with: the markers, what a citation points to, where the
    reference files are. ``rng`` is ``(since, until)``; ``paths`` holds the ``summaries`` and
    ``reference`` directories and the ``timeline`` file as the reader will find them once promoted.
    References and timeline are document-relative; summaries are campaign-relative or absolute when
    outside the campaign.

    ``doc`` selects the paragraphs (research R13): the dossier paragraph names ``## Key NPCs``
    (world_state) or ``## NPC Dossiers`` (planning) and is omitted for party and campaign_state; the
    thread paragraph is planning's; the reference list names only that document's files, and only
    world_state names the timeline.
    """
    if doc not in CONTRACT_REFERENCES:
        raise ValueError(f"no reading contract for {doc!r}")
    ref = str(paths["reference"]).rstrip("/")
    text = _HEAD.format(
        since=rng[0], until=rng[1], later=schema.LATER, since_=schema.SINCE, unverified=schema.UNVERIFIED,
        summaries=str(paths["summaries"]).rstrip("/"),
    )
    if doc in _DOSSIER_SECTION:
        text += _DOSSIERS.format(section=_DOSSIER_SECTION[doc], fallback=schema.KEY_NPC_FALLBACK_MARK)
    if doc == "planning":
        text += _THREADS.format(dormant=schema.DORMANT_HEADING, unratified=schema.UNRATIFIED_HEADING,
                                unratified_file=f"{ref}/{UNRATIFIED_KIND}.md")
    text += _FILES.format(files=", ".join(f"`{ref}/{kind}.md`" for kind in CONTRACT_REFERENCES[doc]))
    if doc == "world_state":
        text += _TIMELINE.format(timeline=paths["timeline"])
    text += _TAIL.format(paths_are="Reference and timeline paths are" if doc == "world_state" else "Reference paths are")
    return text + "> <!-- summary_native pointers: " + json.dumps(paths, sort_keys=True) + " -->\n"


# ── Identity ────────────────────────────────────────────────────────────────

Identity = tuple[dict[str, str], set[str], dict[str, list[str]]]


def build_identity(entities, plays) -> Identity:
    """``(forms, player characters, ambiguous forms)`` from ``entities`` (``(name, aliases)`` pairs)
    and ``plays`` (the character names ``players.yaml`` lists).

    ``forms`` maps a casefolded name or alias to its entity's canonical name, by exact equality only;
    nothing is matched by similarity. A form that two entities claim is left out of ``forms`` and
    reported in ``ambiguous`` (``{form: [canonical names]}``), so it stays unresolved rather than
    being given to either. A player character is mapped to its canonical name when the registry
    knows it.
    """
    claims: dict[str, set[str]] = {}
    for name, aliases in entities:
        for form in [name, *aliases]:
            claims.setdefault(str(form).strip().casefold(), set()).add(name)
    forms = {f: next(iter(c)) for f, c in claims.items() if len(c) == 1}
    ambiguous = {f: sorted(c) for f, c in sorted(claims.items()) if len(c) > 1}
    pcs = {forms.get(str(n).strip().casefold(), str(n).strip()) for n in plays}
    return forms, pcs, ambiguous


def load_identity(registry_path: Path | None, players_path: Path | None) -> Identity:
    """:func:`build_identity` from the entity registry and ``players.yaml`` files.

    Raises ``ValueError`` for a registry or roster that does not load (``load_registry`` itself
    refuses a name or alias claimed by two entities). A missing file is an empty one.
    """
    entities = []
    if registry_path is not None and Path(registry_path).is_file():
        entities = [(e.name, list(e.aliases)) for e in load_registry(registry_path).entities]
    plays: list[str] = []
    if players_path is not None and Path(players_path).is_file():
        plays = [n for p in load_players_config(Path(players_path)).players for n in p.plays]
    return build_identity(entities, plays)


# ── The NPC current-status table ────────────────────────────────────────────

_HEADER = ["| NPC | Status | Last Known Location | Disposition toward Party | Established |", "|---|---|---|---|---|"]


def _cell(s: str | None) -> str:
    return (s or "").replace("|", "/").strip() or "—"


def npc_status_table(
    results: Sequence[notes.CheckedChunk],
    forms: dict[str, str],
    pcs: set[str],
    ambiguous: dict[str, list[str]] | None = None,
) -> tuple[str, str]:
    """``(table markdown, identity report markdown)``.

    One row per entity. A row's name resolves to its registry canonical name by exact casefolded
    name or alias; a name that does not resolve keys on itself, is marked ``⚠`` and is listed in the
    report. Rows for player characters are dropped. Of an entity's rows the latest one with a known
    status is kept: an ``Unknown`` row means the chapter did not say, not that the status changed,
    so it never replaces a known status. A *later* ``Unknown`` row is shown beside the known one,
    with its citation, for the GM to read.
    """
    ambiguous = ambiguous or {}
    pc_keys = {p.casefold() for p in pcs}
    groups: dict[str, dict] = {}
    unresolved: set[str] = set()
    dropped_pc: set[str] = set()
    for r in results:
        for row in r.kept("status_row"):
            name = row.subject or ""
            canon = forms.get(name.casefold())
            key = canon or name
            if key.casefold() in pc_keys or name.casefold() in pc_keys:
                dropped_pc.add(name)
                continue
            if canon is None:
                unresolved.add(name)
            g = groups.setdefault(key.casefold(), {"key": key, "rows": [], "forms": set(), "resolved": canon is not None})
            g["rows"].append(row)
            g["forms"].add(name)

    lines = list(_HEADER)
    for k in sorted(groups, key=lambda k: (groups[k]["key"].casefold(), groups[k]["key"])):
        g = groups[k]
        ordered = sorted(g["rows"], key=lambda n: n.first_chapter)  # stable: extraction order within a chapter
        known = [n for n in ordered if n.status != "Unknown"]
        kept = known[-1] if known else ordered[-1]
        later = [n for n in ordered if n.status == "Unknown" and n.first_chapter > kept.first_chapter]
        loc = _cell(kept.location)
        if later:
            lt = later[-1]
            loc += f"; later, status not stated: {_cell(lt.location)} ({_cell(lt.disposition)}) {lt.cite}"
        mark = "" if g["resolved"] else " ⚠"
        lines.append(f"| {_cell(g['key'])}{mark} | {kept.status} | {loc} | {_cell(kept.disposition)} | {kept.cite} |")

    merged = {k: g for k, g in groups.items() if len(g["forms"]) > 1}
    rep = [
        "# NPC table identity report", "",
        f"{len(groups)} rows. ⚠ marks a name the registry does not know (kept as written, never guessed).", "",
        f"## Forms merged by registry name/alias ({len(merged)})", "",
    ]
    rep += [f"- {merged[k]['key']}: {', '.join(sorted(merged[k]['forms']))}"
            for k in sorted(merged, key=lambda k: merged[k]["key"].casefold())]
    rep += ["", f"## Unresolved names ({len(unresolved)}) — add to the registry or fix at source", ""]
    for n in sorted(unresolved, key=lambda s: (s.casefold(), s)):
        claimed = ambiguous.get(n.casefold())
        rep.append(f"- {n}" + (f" (claimed by more than one entity: {', '.join(claimed)})" if claimed else ""))
    rep += ["", f"## Player-character rows dropped ({len(dropped_pc)})", ""]
    rep += [f"- {n}" for n in sorted(dropped_pc, key=lambda s: (s.casefold(), s))]
    return "\n".join(lines), "\n".join(rep) + "\n"


# ── Which notes go to which prose section (research R8) ─────────────────────

#: ``doc -> ((heading, route, attach the last chunk's summaries), ...)`` in outline order. A route is
#: ``party`` or a World tag. Code routes the notes; the model never chooses its inputs.
#: world_state's ``## Key NPCs`` is not here: it is rendered from the published dossiers (``key_npcs``).
#: Neither are campaign_state's two thread sections: they are built from the GM's thread registry
#: (``thread_attach``, ``resolved_threads_md`` / ``active_plots_md``), like planning's Active Plots.
PROSE_SECTIONS: dict[str, tuple[tuple[str, str, bool], ...]] = {
    "world_state": (
        ("## Party", "party", True),
        ("## Factions and Powers", "FACTION", False),
        ("## Locations", "LOCATION", False),
        ("## Items and Artifacts", "ITEM", False),
        ("## Active Threats and Open Pressures", "THREAT", False),
    ),
    "campaign_state": (
        ("## Party Current Situation", "party", True),
    ),
}

#: ``heading -> the reference file it points to`` (Party and the code-owned sections have none).
REFERENCE_FOR: dict[str, str] = {
    "## Factions and Powers": "factions",
    "## Key NPCs": "npcs",
    "## NPC Dossiers": "npcs",
    "## Faction States": "factions",
    "## Active Plots": "threads",
    "## Locations": "locations",
    "## Items and Artifacts": "items",
    "## Active Threats and Open Pressures": "threats",
    "## Resolved Plot Threads": "threads",
    "## Active Quests & Open Threads": "threads",
}

BRIEFS: dict[str, str] = {
    "## Party": "Who the party is NOW: name, level, rank, each PC's current capabilities, gear and standing, and where they are. Latest note wins where notes conflict.",
    "## Factions and Powers": "Each faction or power as it stands NOW: goals, leaders, relationship to the party, last known move.",
    "## Locations": "Places as they stand NOW: what each is, who controls it, what the party did there and left unresolved.",
    "## Items and Artifacts": "Significant items NOW: what each does, who holds it, open questions about it.",
    "## Active Threats and Open Pressures": "What is pressing on the party NOW and from whom. Only things the notes do not show resolved.",
    # campaign_state's thread sections (#530): one call each, one entry per thread code gives it
    "## Resolved Plot Threads": "Each thread's entry: how it ended, citing the resolution. Every thread you are given has ended (the GM marked it resolved or abandoned, or its latest note says so), but if no note in its block shows the ending, say the notes in this range do not show how it ended: never infer one. Use only that thread's own notes.",
    "## Active Quests & Open Threads": "Each thread's entry as it stands NOW: its latest state, what the party did, what is unresolved. Every thread you are given is unfinished. Use only that thread's own notes.",
    "## Party Current Situation": "Where the party is, what they just did, and what they are about to face, at the very end of the range.",
    # planning (spec 034): one call each; NPC Dossiers has its own system prompt and prompt builder (key_npcs)
    "## Faction States": "Each faction's entry as it stands NOW: goals, leaders, relationship to the party, last known move. Use only that faction's own notes.",
    "## Active Plots": "Each thread's entry as it stands NOW: where it stands, what the party did, what is unresolved. Use only that thread's own notes.",
    "## DM Notes": "Suggestions for the GM: what to prepare or consider next, each line cited to the notes that prompted it. A suggestion is not an event.",
    # party (spec 034): one call per character, one for the overview, one for the dynamics
    "## Party Overview": "Where the party stands as a group at the END of the range, including the companions travelling with them: where they are, what they are doing, what presses on them, what they intend. Latest note wins where notes conflict. Do not state a level.",
    "## Characters": "This one player character NOW: current situation, recent decisions, injuries, losses, acquisitions and relationships that changed. Use only this character's notes, sheet and backstory. Do not state a level.",
    "## Party Dynamics": "How the player characters relate to one another and to the companions travelling with them NOW: alliances, tensions, bonds, who defers to whom, and what changed between them. Only what the notes show. Do not state a level.",
}


def route_notes(route: str, results: Sequence[notes.CheckedChunk]) -> list[str]:
    """The checked notes one prose section may see."""
    if route == "party":
        return notes.stitched(results, "party")
    return notes.stitched(results, "world", route)


# ── The audit section ───────────────────────────────────────────────────────


def audit_md(range_dir: Path) -> str:
    """campaign_state's ``## Audit: Tracking Claims`` body, rendered from ``state/audit/audit.json``
    when the audit has run, else the single line "Audit not run for this range." (the audit is
    ``summary_native audit``). Whether the audit is stale is ``freshness.check_audit_fresh``'s call,
    made by ``synth`` before this is read; an unreadable ``audit.json`` reads as not run."""
    if freshness.audit_exists(range_dir):
        try:
            data = json.loads((freshness.audit_dir(range_dir) / "audit.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return schema.AUDIT_NOT_RUN
        if isinstance(data, dict) and data.get("kind") == "audit" and data.get("verdicts"):
            return audit_select.render_audit_md(data).strip()
    return schema.AUDIT_NOT_RUN


# ── planning: the Threat Tracker, factions and Active Plots (spec 034 US2) ──────

_THREAT_HEADER = ["| Score | Subject | Candidate events | Trigger text |", "|---|---|---|---|"]


def _shown(path, root) -> str:
    p = Path(path)
    if root is not None and p.is_absolute():
        try:
            return p.resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            pass
    return p.as_posix()


def threat_tracker_md(entries, candidates_by_subject: Mapping[str, Sequence[str]] | None = None, *, root=None) -> str:
    """planning's ``## Threat Tracker`` body: one row per configured, non-trackless arc score (FR-008).

    ``entries`` are the config's NPCs then factions (``.name``, ``.arc_score``); an entry with no
    ``arc_score`` (trackless, or none declared) has no row. With no row at all the body is exactly the
    sentinel line. The score is the mechanic file's name and the trigger cell is its path: the file is
    the GM's, and nothing here quotes or paraphrases it. ``candidates_by_subject`` is where the arc-score
    candidate events go (spec 034 US4); a subject with none shows ``—``.
    """
    rows = []
    for e in entries:
        if e.arc_score is None:
            continue
        shown = _shown(e.arc_score, root)
        cands = list((candidates_by_subject or {}).get(e.name) or [])
        rows.append(
            f"| {_cell(Path(shown).stem)} | {_cell(e.name)} | {_cell('<br>'.join(cands)) if cands else '—'} | {_cell(shown)} |")
    if not rows:
        from pipelines.summary_native import context  # declared once in context, where the prompt and the check read it

        return context.NO_ARC_SENTINEL
    return "\n".join([*_THREAT_HEADER, *rows])


@dataclass
class FactionEntry:
    name: str
    notes: list = field(default_factory=list)
    configured: bool = False

    @property
    def latest_chapter(self) -> int:
        return max((n.first_chapter for n in self.notes), default=-1)

    @property
    def latest(self):
        """The note with the highest ``first_chapter``, the last extracted among equals."""
        out = None
        for n in self.notes:
            if out is None or n.first_chapter >= out.first_chapter:
                out = n
        return out


@dataclass
class FactionSelection:
    #: The factions to write, newest latest-note first (those with no note last, in config order).
    selected: list
    #: The names left out by the cap, in the same order.
    overflow: list


def select_factions(
    results: Sequence[notes.CheckedChunk], forms: dict[str, str], configured: Sequence[str], cap: int,
) -> FactionSelection:
    """The factions Faction States covers, chosen by code (FR-012, research R9).

    The config's factions plus every ``[FACTION]`` subject in the checked notes, each canonicalised by
    ``forms`` (exact casefolded name or alias); a subject the registry does not know keys on itself.
    Ordered by the chapter of the latest note, newest first; ties go to the config's order, then the
    name. At most ``cap`` are written: the rest are named in ``overflow``.
    """

    def canon(name: str) -> str:
        return forms.get(name.strip().casefold(), name.strip())

    groups: dict[str, FactionEntry] = {}
    rank: dict[str, int] = {}
    for i, name in enumerate(configured):
        key = canon(name).casefold()
        if key not in groups:
            groups[key] = FactionEntry(canon(name), [], True)
            rank[key] = i
    seen: set[str] = set()
    found = []
    for r in results:
        for n in r.notes:
            if n.kind == "world" and n.tag == "FACTION" and n.subject and n.note_id not in seen:
                seen.add(n.note_id)
                found.append(n)
    for n in sorted(found, key=lambda n: n.first_chapter):  # stable: extraction order within a chapter
        key = canon(n.subject).casefold()
        groups.setdefault(key, FactionEntry(canon(n.subject))).notes.append(n)
    ordered = sorted(
        groups, key=lambda k: (-groups[k].latest_chapter, rank.get(k, len(rank)), groups[k].name.casefold(), groups[k].name))
    cap = max(cap, 1)
    return FactionSelection([groups[k] for k in ordered[:cap]], [groups[k].name for k in ordered[cap:]])


@dataclass
class EntryCheck:
    #: ``{expected name: body}`` for each entry the model wrote cleanly.
    bodies: dict
    #: ``{expected name: why}`` for each one it dropped, misplaced or left empty.
    bad: dict
    #: Headings the model added or repeated; their text is ignored.
    extras: list


_ENTRY_HEAD_RE = re.compile(r"^###(?!#)\s+(.+?)\s*$")


def check_entries(out: str | None, expected: Sequence[str]) -> EntryCheck:
    """Check a model's ``### Name`` blocks against the names code gave it, in the order code gave them.

    A block belongs to an expected name only by exact heading text. A block that is missing, empty or out
    of place (not where the expected order puts it among the blocks that were written) is ``bad``; a
    heading that was not asked for, or that repeats, is an ``extra`` and its text goes nowhere. Code
    decides what replaces a bad block; this decides nothing about it.
    """
    blocks: list[tuple[str, list[str]]] = []
    cur = None
    for ln in (out or "").splitlines():
        m = _ENTRY_HEAD_RE.match(ln)
        if m:
            cur = (m.group(1), [])
            blocks.append(cur)
        elif ln.startswith("# ") or ln.startswith("## "):
            cur = None  # a higher heading ends the block; its own text belongs to nobody
        elif cur is not None:
            cur[1].append(ln)
    wanted = set(expected)
    first: dict[str, str] = {}
    extras: list[str] = []
    seq: list[str] = []
    for name, body in blocks:
        if name not in wanted or name in first:
            extras.append(name)
            continue
        first[name] = "\n".join(body).strip()
        seq.append(name)
    present = [n for n in expected if n in first]
    bodies: dict[str, str] = {}
    bad: dict[str, str] = {}
    for n in expected:
        if n not in first:
            bad[n] = "missing from the model's output"
        elif seq.index(n) != present.index(n):
            bad[n] = "out of order"
        elif not first[n]:
            bad[n] = "empty body"
        else:
            bodies[n] = first[n]
    return EntryCheck(bodies, bad, extras)


def faction_states_md(
    sel: FactionSelection, bodies: Mapping[str, str | None], reasons: Mapping[str, str] | None = None,
) -> tuple[str, list[str]]:
    """``(Faction States body, report lines)``.

    One ``### name`` block per selected faction, in the selection's order. A faction with no note gets the
    code line and never reaches the model; one whose model block is missing or bad gets its latest note,
    verbatim, and a report line. The cap's overflow is named in one closing line with a pointer.
    """
    reasons = reasons or {}
    blocks: list[str] = []
    report: list[str] = []
    for f in sel.selected:
        if not f.notes:
            body = f"The summaries in this range record nothing for {f.name}."
        elif bodies.get(f.name) and bodies[f.name].strip():
            body = bodies[f.name].strip()
        else:
            body = f.latest.text
            report.append(f"- {f.name}: the latest note replaces the model's block ({reasons.get(f.name, 'no usable block')})")
        blocks.append(f"### {f.name}\n{body}\n")
    if sel.overflow:
        n = len(sel.overflow)
        blocks.append(
            f"_{n} more faction{'s' if n != 1 else ''} not written here (the least recently active): "
            f"{', '.join(sel.overflow)}. Their notes are in reference/factions.md._\n")
    if not blocks:
        return schema.NO_FACTIONS, report
    return "\n".join(blocks).rstrip("\n"), report


# ── Active Plots ────────────────────────────────────────────────────────────

_TAIL_RE = re.compile(r"^- (?:\[[A-Z]+\]\s+)?\*\*.+?\*\*\s+—\s+(.*)$", re.S)


def note_tail(note) -> str:
    """A thread note's own sentence and citation, verbatim: its text without the bullet, the tag and the bold name."""
    m = _TAIL_RE.match(note.text)
    return (m.group(1) if m else note.text.removeprefix("- ")).strip()


@dataclass
class ActivePlots:
    """A thread section as code assembled it: planning's Active Plots, or one of campaign_state's two (#530)."""

    text: str
    #: One line per entry replaced by code.
    report: list
    replaced: int
    from_model: int
    #: The model-written bodies that were kept, for the word budget.
    model_text: str


def unratified_reference_md(att: "thread_attach.Attachment") -> str:
    """``reference/threads_unratified.md``: every unattached thread note, verbatim, in chapter order (FR-009b)."""
    ns = sorted(att.unattached, key=lambda n: n.first_chapter)  # stable: extraction order within a chapter
    lines = ["# Reference: Threads, unratified", "",
             f"{len(ns)} checked thread notes, no ratified thread owns them, chapter order. "
             "Built by code from the checked notes; nothing is reworded.", ""]
    lines += [x.text for x in ns] if ns else [schema.NONE_VERIFIED]
    return "\n".join(lines) + "\n"


def _thread_entries(
    threads: Sequence["thread_attach.ThreadState"], bodies: Mapping[str, str | None], reasons: Mapping[str, str],
    report: list[str], kept: list[str],
) -> str:
    """One ``### title`` entry per thread, in the order given. A thread whose body is missing is its latest
    attached note, verbatim, and is reported; a body the model wrote is kept and counted."""
    entries = []
    for s in threads:
        body = bodies.get(s.id)
        if body is None or not body.strip():
            body = s.latest.text
            report.append(
                f"- {s.title}: the latest attached note replaces the model's entry ({reasons.get(s.id, 'no usable entry')})")
        else:
            body = body.strip()
            kept.append(body)
        entries.append(f"### {s.title}\n{body}\n")
    return "\n".join(entries).rstrip("\n")


def _dormant_block(att: "thread_attach.Attachment") -> str | None:
    """``### Dormant threads``: each dormant thread as its title and latest note, verbatim, built without a model."""
    dormant = att.dormant_threads
    if not dormant:
        return None
    return "\n".join([schema.DORMANT_HEADING, *(f"- **{s.title}** — {note_tail(s.latest)}" for s in dormant)])


def _unratified_block(att: "thread_attach.Attachment") -> str:
    """The count of unattached thread notes and two pointers; the notes are in ``reference/threads_unratified.md``."""
    n = len(att.unattached)
    head = [
        schema.UNRATIFIED_HEADING,
        f"_{n} checked thread note{'s' if n != 1 else ''} {'are' if n != 1 else 'is'} not in the thread registry. "
        f"Verbatim, in chapter order, in reference/{UNRATIFIED_KIND}.md. "
        "They are evidence, not plots: rule on them at /grounding/threads "
        "(or `summary_native thread-propose`, then `thread_registry ratify`)._",
    ]
    if att.ambiguous:
        k = len(att.ambiguous)
        head.append(
            f"_{k} thread name{'s' if k != 1 else ''} below {'are' if k != 1 else 'is'} claimed by more than one "
            f"ratified thread and stay unattached: {', '.join(sorted(att.ambiguous))}._")
    return "\n".join(head)


def active_plots_md(
    att: "thread_attach.Attachment", bodies: Mapping[str, str | None], reasons: Mapping[str, str] | None = None,
) -> ActivePlots:
    """``## Active Plots`` as its three layers (data-model "Active Plots section"), assembled by code.

    ``bodies`` maps a thread id to the body the model wrote for it (``None`` or empty: it wrote none).
    Entries are the *open* ratified threads, newest activity first, as ``att`` orders them; an entry whose
    body is missing is the thread's latest attached note, verbatim. Then ``### Dormant threads`` (only if
    a thread is dormant), each as its title and latest note, verbatim, built without a model; then the
    unratified block (the count and two pointers; the notes are in ``reference/threads_unratified.md``,
    see ``unratified_reference_md``). With no open thread the ratified part is
    one code line: ``NO_RATIFIED_THREADS`` when no ratified thread has notes at all, ``NO_OPEN_THREADS``
    when some have but none is open.

    campaign_state's ``## Active Quests & Open Threads`` is this same body (#530): the open ratified threads,
    the dormant block and the unratified pointer.
    """
    reasons = reasons or {}
    report: list[str] = []
    kept: list[str] = []
    open_threads = att.open_threads
    parts = [_thread_entries(open_threads, bodies, reasons, report, kept) if open_threads else
             (schema.NO_RATIFIED_THREADS if not att.threads else schema.NO_OPEN_THREADS)]
    if (dormant := _dormant_block(att)) is not None:
        parts.append(dormant)
    parts.append(_unratified_block(att))
    return ActivePlots("\n\n".join(parts), report, len(report), len(kept), "\n".join(kept))


def resolved_threads_md(
    att: "thread_attach.Attachment", bodies: Mapping[str, str | None], reasons: Mapping[str, str] | None = None,
) -> ActivePlots:
    """campaign_state's ``## Resolved Plot Threads``: the ratified threads that are closed (#530).

    A thread is closed when the GM set it ``resolved`` or ``abandoned`` in the registry at or before the range's
    last chapter (after it, the thread is decided as ``open``), or when its status is ``open`` and its latest
    attached note is tagged ``RESOLVED`` or ``ABANDONED`` (``Attachment.closed_threads``).
    Entries are written like Active Plots': one per thread, newest activity first, the model's body or, when it
    is missing, the thread's latest attached note verbatim. A dormant thread is neither open nor closed and is
    listed only in Active Quests' dormant block. With no closed thread the body is one code line:
    ``NO_RATIFIED_THREADS`` when no ratified thread has notes at all, ``NO_RESOLVED_THREADS`` when some have.
    """
    reasons = reasons or {}
    report: list[str] = []
    kept: list[str] = []
    closed = att.closed_threads
    if not closed:
        text = schema.NO_RATIFIED_THREADS if not att.threads else schema.NO_RESOLVED_THREADS
        return ActivePlots(text, report, 0, 0, "")
    text = _thread_entries(closed, bodies, reasons, report, kept)
    return ActivePlots(text, report, len(report), len(kept), "\n".join(kept))
