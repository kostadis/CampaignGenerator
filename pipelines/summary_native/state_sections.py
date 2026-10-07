"""The code-owned sections of world_state and campaign_state (spec 033 T018, FR-007..FR-010). No model call.

The event timeline, the completed-encounters list and the NPC current-status table are built here,
by code, from the checked notes, the entity registry and ``players.yaml``. A model never decides
who an NPC is, which row is the latest, or whether a player character belongs in the table; those
are identity and ordering decisions (Principle II).

Every function is a pure function of its inputs and emits no timestamp and no absolute path, so
the output is byte-identical across rebuilds from the same notes, registry and roster (FR-010).
Guarded by ``tests/test_summary_native_no_llm.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from campaignlib.players_config import load_players_config
from campaignlib.registry import load_registry
from pipelines.summary_native import freshness, notes, schema

# ── Timeline and completed encounters ───────────────────────────────────────


def _bullets(items: list[str]) -> str:
    return "\n".join(items) if items else schema.NONE_VERIFIED


def timeline_md(results: Sequence[notes.CheckedChunk]) -> str:
    """Every kept event note, one bullet each, in chapter order with exact duplicates removed."""
    return _bullets(notes.stitched(results, "event"))


def completed_md(results: Sequence[notes.CheckedChunk]) -> str:
    """Every kept concluded note, in chapter order with exact duplicates removed."""
    return _bullets(notes.stitched(results, "concluded"))


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
#: ``party``, ``threads`` or a World tag. Code routes the notes; the model never chooses its inputs.
PROSE_SECTIONS: dict[str, tuple[tuple[str, str, bool], ...]] = {
    "world_state": (
        ("## Party", "party", True),
        ("## Factions and Powers", "FACTION", False),
        # TODO(T031/T032): Key NPCs is rendered from the published dossiers (key_npcs.py), not from
        # these [NPC] notes. Until then it is a prose section like the others; replace, don't extend.
        ("## Key NPCs", "NPC", False),
        ("## Locations", "LOCATION", False),
        ("## Items and Artifacts", "ITEM", False),
        ("## Active Threats and Open Pressures", "THREAT", False),
    ),
    "campaign_state": (
        ("## Resolved Plot Threads", "threads", False),
        ("## Active Quests & Open Threads", "threads", True),
        ("## Party Current Situation", "party", True),
    ),
}

BRIEFS: dict[str, str] = {
    "## Party": "Who the party is NOW: name, level, rank, each PC's current capabilities, gear and standing, and where they are. Latest note wins where notes conflict.",
    "## Factions and Powers": "Each faction or power as it stands NOW: goals, leaders, relationship to the party, last known move.",
    "## Key NPCs": "The NPCs who matter NOW: who they are, where they stand with the party, what they want. One sub-entry per NPC; skip walk-ons.",
    "## Locations": "Places as they stand NOW: what each is, who controls it, what the party did there and left unresolved.",
    "## Items and Artifacts": "Significant items NOW: what each does, who holds it, open questions about it.",
    "## Active Threats and Open Pressures": "What is pressing on the party NOW and from whom. Only things the notes do not show resolved.",
    "## Resolved Plot Threads": "Every thread the notes show RESOLVED or ABANDONED: one bullet each, saying how it ended, citing the resolution.",
    "## Active Quests & Open Threads": "Every thread OPENED or ADVANCED whose resolution the notes do not show. One bullet each with its latest state. If it is listed, it is unfinished.",
    "## Party Current Situation": "Where the party is, what they just did, and what they are about to face, at the very end of the range.",
}


def route_notes(route: str, results: Sequence[notes.CheckedChunk]) -> list[str]:
    """The checked notes one prose section may see."""
    if route == "party":
        return notes.stitched(results, "party")
    if route == "threads":
        return notes.thread_ledger(results)
    return notes.stitched(results, "world", route)


# ── The audit section ───────────────────────────────────────────────────────


def audit_md(range_dir: Path) -> str:
    """campaign_state's ``## Audit: Tracking Claims`` body: ``state/audit/audit.md`` when the audit
    has run, else the single line "Audit not run for this range." (the audit is ``summary_native audit``)."""
    if freshness.audit_exists(range_dir):
        p = freshness.audit_dir(range_dir) / "audit.md"
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    return schema.AUDIT_NOT_RUN
