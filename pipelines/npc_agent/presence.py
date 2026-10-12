"""Presence candidates: every item that names an NPC, and the evidence it carries.

A candidate is an item (see :mod:`pipelines.npc_agent.corpus`) in which one of
the NPC's exact name forms appears. Matching is ``npc-link``'s rule — exact,
case-sensitive, word-bounded — through its own compiled pattern, so the two can
never drift apart.

**A candidate is a mention, never presence** (spec 032 FR-005, and the
narrator-eligibility lesson in ``CLAUDE.md``: the GM narrates *about* absent
characters). The signals below are evidence laid out for the GM's ruling; none of
them marks anything present:

``quoted``     a quote in the item is attributed to the NPC (``> — Sylvira``)
``headline``   the NPC is named in a scene's ``####`` headline (the GM's recap)
``own_entry``  the item is the NPC's own ``## NPCs`` observation
``named``      the NPC is named on any other line

The summaries give little to go on structurally: across Out of the Abyss there
are 909 attributed quotes, and Ilvara — who speaks in chapters 2 and 51 — has
none. That is why presence is ruled, not computed.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pipelines.npc_agent.corpus import ENTRY, MOMENT, PROSE, SCENE, Corpus, Item
from pipelines.npc_agent.dossier import Dossier

# npc-link's matcher and generic-word test, reused rather than restated so the scope cannot drift.
from pipelines.summary_native.npc_forms import _compile as compile_forms
from pipelines.summary_native.npc_forms import is_generic_token

QUOTED = "quoted"
HEADLINE = "headline"
OWN_ENTRY = "own_entry"
NAMED = "named"
SIGNALS = (QUOTED, HEADLINE, OWN_ENTRY, NAMED)

#: An attribution line under a quote: ``> — Sylvira``, ``— Sylvira``.
_ATTRIBUTION_RE = re.compile(r"^\s*(?:>\s*)?[—–]\s*(.+?)\s*$")


@dataclass(frozen=True)
class Candidate:
    item: Item
    signals: tuple[str, ...]  # in SIGNALS order
    forms_matched: tuple[str, ...]
    match_lines: tuple[int, ...]  # file lines on which a form matched


# ── Forms: npc-link's statuses, over the published dossiers ─────────────────

LINKABLE = "linkable"
AMBIGUOUS = "ambiguous"
GENERIC = "generic"
GENERIC_SAFE = "generic-safe"
GENERIC_NEVER = "generic-never"


@dataclass(frozen=True)
class FormTable:
    """Every published NPC's forms, their status, and one combined matcher.

    The statuses are ``npc-link``'s (spec 032 R4, R5): a form owned by two NPCs is
    *ambiguous*; a single word in its packaged word list is *generic* and withheld
    unless ``canon.yaml link_rulings`` says ``safe``. The matcher covers every form
    of every NPC, longest first, so ``Manshoon`` inside ``Manshoon (Simulacrum)``
    belongs to the longer name, as it does in ``npc-link``.

    ``npc-link`` also sees registry aliases and every corpus heading; the published
    layout carries neither, so this table knows only the dossiers' own forms. The
    check against each dossier's counts is what shows where that difference bites.
    """

    owners: dict[str, tuple[str, ...]]  # form -> subjects
    status: dict[str, str]  # form -> one of the statuses above
    pattern: re.Pattern[str] | None

    def linkable(self, form: str) -> bool:
        return self.status.get(form) in (LINKABLE, GENERIC_SAFE)

    def withheld_for(self, d: Dossier) -> tuple[tuple[str, str], ...]:
        return tuple((f, self.status[f]) for f in d.forms if not self.linkable(f))


def build_form_table(dossiers: list[Dossier], wordlist, link_rulings: dict[str, str]) -> FormTable:
    owners: dict[str, list[str]] = {}
    for d in dossiers:
        for f in d.forms:
            owners.setdefault(f, [])
            if d.subject not in owners[f]:
                owners[f].append(d.subject)
    status = {}
    for f, subs in owners.items():
        if len(subs) > 1:
            status[f] = AMBIGUOUS
        elif is_generic_token(f, wordlist):
            ruling = link_rulings.get(f)
            status[f] = GENERIC_SAFE if ruling == "safe" else GENERIC_NEVER if ruling == "never" else GENERIC
        else:
            status[f] = LINKABLE
    return FormTable(
        owners={f: tuple(s) for f, s in owners.items()},
        status=status,
        pattern=compile_forms(owners),
    )


def _signals(item: Item, d: Dossier, table: FormTable) -> Candidate | None:
    found: set[str] = set()
    matched: set[str] = set()
    lines: list[int] = []
    headlines = set(item.headline_lines)
    for n, text in item.lines:
        if table.pattern is None:
            break
        hits = [
            m.group(0)
            for m in table.pattern.finditer(text)
            if table.owners[m.group(0)] == (d.subject,) and table.linkable(m.group(0))
        ]
        if not hits:
            continue
        matched.update(hits)
        lines.append(n)
        att = _ATTRIBUTION_RE.match(text)
        if att and att.group(1) in d.forms:
            found.add(QUOTED)
        elif n in headlines:
            found.add(HEADLINE)
        elif not (item.kind == ENTRY and n == item.line):
            found.add(NAMED)
    # An NPC's own ``## NPCs`` observation is theirs by its heading, whatever the
    # form's link status: ``npc-link`` takes entries from the corpus heading too.
    if item.kind == ENTRY and item.title in d.forms:
        found.add(OWN_ENTRY)
        matched.add(item.title)
        if item.line not in lines:
            lines.insert(0, item.line)
    if not found:
        return None
    return Candidate(
        item=item,
        signals=tuple(s for s in SIGNALS if s in found),
        forms_matched=tuple(sorted(matched)),
        match_lines=tuple(sorted(lines)),
    )


def candidates(corpus: Corpus, dossier: Dossier, table: FormTable) -> list[Candidate]:
    """Every item naming the NPC, in corpus order (chapter, then scene/prose/moment/entry)."""
    out = []
    for item in corpus.items():
        c = _signals(item, dossier, table)
        if c is not None:
            out.append(c)
    return out


# ── Check against the published dossier ─────────────────────────────────────


@dataclass(frozen=True)
class Check:
    subject: str
    ok: bool
    lines: tuple[str, ...]  # human-readable, one fact or problem per line


def check_against_dossier(
    corpus: Corpus, dossier: Dossier, cands: list[Candidate], table: FormTable
) -> Check:
    """Compare the candidate list with the counts ``npc-link`` wrote into the dossier.

    ``npc-link`` ran on the refactored private copy, where prose sits inside scenes.
    So moments, own entries and chapters must match exactly; scenes may differ only
    by scenes whose chapter has a prose candidate (the refactor placed that prose
    under them). A mismatch is reported, never repaired.
    """
    out: list[str] = []
    ok = True
    for form, status in table.withheld_for(dossier):
        why = {
            AMBIGUOUS: f"ambiguous (also {', '.join(s for s in table.owners[form] if s != dossier.subject)})",
            GENERIC: "generic word, no link ruling (pass --canon with a `safe` ruling to link it)",
            GENERIC_NEVER: "generic word, ruled never",
        }[status]
        out.append(f"withheld form {form!r}: {why}")
    by_kind = {k: [c for c in cands if c.item.kind == k] for k in (SCENE, PROSE, MOMENT, ENTRY)}
    own_entries = [c for c in by_kind[ENTRY] if OWN_ENTRY in c.signals]
    chapters = sorted({c.item.chapter for c in by_kind[SCENE] + by_kind[MOMENT] + own_entries
                       + by_kind[PROSE]})

    def exact(label: str, here, there) -> None:
        nonlocal ok
        if here == there:
            out.append(f"{label}: {here} (matches the dossier)")
        else:
            ok = False
            out.append(f"MISMATCH {label}: {here} here, {there} in the dossier")

    exact("chapters", chapters, sorted(dossier.chapters))
    exact("moments", len(by_kind[MOMENT]), dossier.n_moments)
    exact("own entries", len(own_entries), dossier.n_entries)

    scene_ids = {c.item.item_id for c in by_kind[SCENE]}
    prose_chapters = {c.item.chapter for c in by_kind[PROSE]}
    placeable = {
        it.item_id
        for ch in corpus.chapters
        if ch.chapter in prose_chapters
        for it in ch.items
        if it.kind == SCENE and it.item_id not in scene_ids
    }
    gap = dossier.n_scenes - len(scene_ids)
    if 0 <= gap <= len(placeable):
        out.append(
            f"scenes: {len(scene_ids)} name the NPC in their own text; the dossier counts "
            f"{dossier.n_scenes}. The {gap} more are within the {len(placeable)} scenes of "
            f"chapters whose prose names the NPC (the refactor placed that prose under a scene)"
        )
    else:
        ok = False
        out.append(
            f"MISMATCH scenes: {len(scene_ids)} here, {dossier.n_scenes} in the dossier, "
            f"and only {len(placeable)} scenes could hold refactor-placed prose"
        )
    unexplained = [s for s in dossier.cited_scenes if s not in scene_ids and s not in placeable]
    if unexplained:
        ok = False
        out.append(f"MISMATCH cited scenes not found here: {', '.join(unexplained)}")
    else:
        out.append(f"cited scenes: all {len(dossier.cited_scenes)} resolve")
    return Check(subject=dossier.subject, ok=ok, lines=tuple(out))


# ── Ruling template ─────────────────────────────────────────────────────────


def _yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def ruling_template(dossiers_and_cands: list[tuple[Dossier, list[Candidate]]]) -> str:
    """A ruling file with every candidate listed and unruled, for the GM to fill in.

    An empty value is *unruled*. The tool never writes the real ruling file; this
    template is written beside the report for the GM to copy from.
    """
    out = [
        "# NPC presence rulings — GM-authored. npc_agent reads this file and never writes it.",
        "# items: one value per item; leave a value empty to keep it unruled.",
        "#   present    the NPC was there (for a chapter-level item: in the event it describes)",
        "#   mentioned  the item is about the NPC, who was not there (items that name the NPC only)",
        "#   unsure     you looked and cannot tell; kept apart from unruled",
        "#   absent     an exception inside a span, for a scene that does not name the NPC",
        "# default: mentioned (or unsure) rules every listed item you leave empty, e.g. for an NPC",
        "#   who is present in a few passages and talked about in the rest.",
        "# A scene not listed (it never names the NPC) may still be added as present, unsure or absent.",
        "# spans: rule a run of scenes at once, e.g. for a companion:",
        "#   spans:",
        "#     - {from: \"034.03\", to: \"071.10\", value: present, follows: Zalthir}",
        "version: 2",
        "npcs:",
    ]
    for d, cands in dossiers_and_cands:
        out.append(f"  {_yaml_str(d.subject)}:")
        out.append("    spans: []")
        if not cands:
            out.append("    items: {}")
            continue
        out.append("    items:")
        for c in cands:
            it = c.item
            label = it.title or it.text.splitlines()[0][:70]
            note = f"{it.kind} · {','.join(c.signals)} · {label}".replace("\n", " ")
            out.append(f"      {_yaml_str(it.item_id)}:   # {note}")
    return "\n".join(out) + "\n"
