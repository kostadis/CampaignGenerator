"""Annotate, never rewrite (spec 033 US4, FR-019..FR-021). No model call.

The reader of ``world_state`` and ``campaign_state`` is a model doing session prep that treats them as
canon. A model that rewrites a flagged line can put an invented detail into canon; an annotation cannot.
So the detectors run, and code appends the LATER EVIDENCE beneath the line, verbatim from the checked notes:

    stale / cross-section        -> ``  - ⚠ later: <the later checked note, with its citation>``
    a mentioned NPC's status     -> ``  - ℹ since: <that NPC's later status row>``
    quote not verbatim / a bad
    citation                     -> ``  - ⚠ unverified: <what failed>``
    a player character listed as
    a companion (an NPC group)   -> the line is removed (a rule, not a judgment)

The annotated line's text is never changed, and re-annotating replaces the old annotation sub-bullets
instead of stacking new ones. Not scanned (FR-019): world_state's Key NPCs, which is fixed in the NPC
dossiers, and the sections code builds from the checked notes, which carry their own handling of later
evidence. Guarded by ``tests/test_summary_native_no_llm.py`` and ``tests/test_annotate_never_rewrites.py``.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from campaignlib.registry import load_registry
from campaignlib.util import atomic_write_text
from pipelines.summary_native import corpus, freshness, notes, npc_check, schema, state_sections

LATER, SINCE, UNVERIFIED = schema.LATER, schema.SINCE, schema.UNVERIFIED
MARKERS = (LATER, SINCE, UNVERIFIED)
#: An annotation sub-bullet, as this module writes it. Only these are ever replaced.
ANNOTATION_RE = re.compile(r"^\s+- (?:" + "|".join(re.escape(m) for m in MARKERS) + ")")

#: Sections whose lines are never scanned (FR-019): Key NPCs is fixed in the dossiers; the others are
#: built by code from the checked notes.
SKIP_SECTIONS = frozenset({
    "## Key NPCs",
    "## Threat Tracker",
    "## NPC Dossiers",
    "## Canon Events Timeline",
    "## Completed Encounters & Quests",
    "## NPC Current States",
    "## Audit: Tracking Claims",
})

#: ``###`` blocks of planning's Active Plots that code builds from the notes verbatim (the dormant threads
#: and the unratified thread notes): evidence, not claims, so never annotated (spec 034 FR-019).
SKIP_GROUPS = frozenset({schema.DORMANT_HEADING[4:], schema.UNRATIFIED_HEADING[4:]})

REPORT_FILE = "annotations.md"
COUNTS_FILE = "annotations.json"

PC_IN_NPC = "pc-in-npc-section"
STALE = "stale"
CROSS_SECTION = "cross-section"
MENTIONED = "mentioned-stale"
INVALID_CITATION = "invalid-citation"
NOT_VERBATIM = "quote-not-verbatim"
_MARKER_OF = {STALE: LATER, CROSS_SECTION: LATER, MENTIONED: SINCE, INVALID_CITATION: UNVERIFIED, NOT_VERBATIM: UNVERIFIED}
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_TAG_RE = re.compile(r"^-\s*\[[A-Z]+\]\s*")


# ── Evidence ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Fact:
    """One checked note about a subject, as it is shown under a line."""

    chapter: int
    kind: str  # "world" | "status_row"
    text: str
    status: str | None = None


@dataclass
class Evidence:
    chapters: dict[int, notes.Chapter]
    forms: dict[str, str]  # casefolded name/alias -> canonical
    pcs: set[str]
    by_subject: dict[str, list[Fact]] = field(default_factory=dict)  # canonical.casefold -> chapter order
    mention_re: re.Pattern | None = None
    mention_name: dict[str, str] = field(default_factory=dict)  # a name/alias as written -> canonical

    @cached_property
    def allowed(self) -> dict[int, set[str]]:
        return {n: c.targets for n, c in self.chapters.items()}

    @cached_property
    def hay(self) -> str:
        return "\n".join(c.text for c in self.chapters.values())

    def canon(self, name: str) -> str:
        name = name.strip().strip("*").strip()
        return self.forms.get(name.casefold(), name)

    def facts(self, subject: str) -> list[Fact]:
        return self.by_subject.get(subject.casefold(), [])

    def mentioned_in(self, text: str) -> set[str]:
        """Canonical names of the entities ``text`` names, by exact (case-sensitive, whole-word) form."""
        if self.mention_re is None:
            return set()
        return {self.mention_name[m.group(0)] for m in self.mention_re.finditer(text)}


def _status_text(row: notes.Note) -> str:
    """A status row as it reads under a line: ``**Name** — Status; location; disposition [cite]``."""
    bits = [f"**{row.subject}** — {row.status}"]
    bits += [b for b in (row.location, row.disposition) if b not in (None, "", "—")]
    return "; ".join(bits) + f" {row.cite}"


def _world_text(note: notes.Note) -> str:
    return _TAG_RE.sub("", note.text).strip()


def load_evidence(
    results: Sequence[notes.CheckedChunk],
    chapters: Sequence[notes.Chapter],
    registry_path: Path | None,
    players_path: Path | None,
) -> Evidence:
    """The checked notes, the summaries and the identity files, as the detectors read them.

    Raises ``ValueError`` for a registry or roster that does not load (as ``state_sections.load_identity`` does).
    """
    forms, pcs, ambiguous = state_sections.load_identity(registry_path, players_path)
    ev = Evidence({c.number: c for c in chapters}, forms, pcs)
    seen: set[tuple[str, str]] = set()
    for r in results:
        for n in r.notes:
            if n.kind == "world" and n.subject:
                fact = Fact(n.first_chapter, "world", _world_text(n))
            elif n.kind == "status_row" and n.subject:
                fact = Fact(n.first_chapter, "status_row", _status_text(n), n.status)
            else:
                continue
            if (n.kind, n.text) in seen:
                continue
            seen.add((n.kind, n.text))
            ev.by_subject.setdefault(ev.canon(n.subject).casefold(), []).append(fact)
    for facts in ev.by_subject.values():
        facts.sort(key=lambda f: f.chapter)  # stable: extraction order within a chapter
    # Names a line may mention: the registry's names and aliases, never one two entities claim.
    if registry_path is not None and Path(registry_path).is_file():
        claims: dict[str, set[str]] = {}
        for e in load_registry(registry_path).entities:
            for f in [e.name, *e.aliases]:
                if len(str(f)) > 3:
                    claims.setdefault(str(f), set()).add(e.name)
        ev.mention_name = {f: next(iter(c)) for f, c in claims.items() if len(c) == 1}
        ev.mention_name = {f: n for f, n in ev.mention_name.items() if f.casefold() not in ambiguous}
        if ev.mention_name:
            alt = "|".join(re.escape(f) for f in sorted(ev.mention_name, key=len, reverse=True))
            ev.mention_re = re.compile(rf"(?<!\w)(?:{alt})(?!\w)")
    return ev


# ── The document ────────────────────────────────────────────────────────────


@dataclass
class Entry:
    line: int  # 0-based index into the document's lines
    section: str
    group: str  # the ### heading or standalone bold label above it, if any
    text: str
    subject: str  # canonical

    def cited_chapters(self) -> list[int]:
        return [c for _, c, _ in notes.cites(self.text) if c >= 0]


def strip_annotations(lines: Sequence[str]) -> list[str]:
    """``lines`` without the annotation sub-bullets a previous run wrote."""
    return [ln for ln in lines if not ANNOTATION_RE.match(ln)]


def parse_entries(lines: Sequence[str], ev: Evidence) -> list[Entry]:
    """The bullet lines the detectors scan: column-0 ``- `` lines outside the skipped sections.

    An entry's subject is its first bold name, else the group (``### `` heading or standalone bold
    label) it sits under, resolved to the registry's canonical name.
    """
    out: list[Entry] = []
    section = group = ""
    for n, ln in enumerate(lines):
        if ln.startswith("## "):
            section, group = ln.rstrip(), ""
        elif ln.startswith("### "):
            group = ln[4:].strip()
        elif re.fullmatch(r"\*\*[^*]+\*\*\s*", ln.strip()):
            group = ln.strip().strip("*").strip()
        elif ln.startswith("- ") and section not in SKIP_SECTIONS and group not in SKIP_GROUPS:
            m = _BOLD_RE.search(ln)
            out.append(Entry(n, section, group, ln, ev.canon(m.group(1) if m else group)))
    return out


# ── Detection ───────────────────────────────────────────────────────────────


@dataclass
class Flag:
    entry: Entry
    kind: str
    detail: str  # why it was flagged
    evidence: str = ""  # the text written under the line (without its marker); empty for a removal

    @property
    def annotation(self) -> str | None:
        return f"{_MARKER_OF[self.kind]} {self.evidence}" if self.kind in _MARKER_OF and self.evidence else None


def _pieces(text: str) -> list[str]:
    """``text`` split after every citation bracket, plus whatever follows the last one."""
    out = notes.claims_of(text)
    tail = text[sum(len(p) for p in out):]
    return out + ([tail] if tail.strip() else [])


def _bad_spans(e: Entry, ev: Evidence) -> list[str]:
    """Quoted spans not verbatim in the chapter their own claim cites (the whole range when it cites none)."""
    bad: list[str] = []
    for piece in _pieces(e.text):
        cited = sorted({c for _, c, _ in notes.cites(piece) if c in ev.chapters})
        hay = "\n".join(ev.chapters[c].text for c in cited) if cited else ev.hay
        for span in npc_check.SPAN_RE.findall(piece):
            inner = npc_check.strip_quote_marks(span)
            if len(inner) >= 4 and npc_check._contains(hay, inner) is None and span not in bad:
                bad.append(span)
    return bad


def detect(entries: Sequence[Entry], ev: Evidence) -> list[Flag]:
    flags: list[Flag] = []
    allowed = ev.allowed
    for e in entries:
        if e.subject in ev.pcs and e.group.casefold() == "companions":
            flags.append(Flag(e, PC_IN_NPC, f"{e.subject} is a player character (players.yaml)"))
        for bracket, c, t in notes.cites(e.text):
            if c < 0 or c not in allowed or t not in allowed[c] or ("." in t and int(t[:3]) != c):
                flags.append(Flag(e, INVALID_CITATION, f"{bracket} is not a real target", f"citation {bracket} does not resolve"))
        for span in _bad_spans(e, ev):
            flags.append(Flag(e, NOT_VERBATIM, f"{span} is not in the chapter it cites", f"quotation {span} is not verbatim in the chapter it cites"))
        cited = e.cited_chapters()
        facts = ev.facts(e.subject)
        if cited and facts and facts[-1].chapter > max(cited):
            later = [f for f in facts if f.chapter > max(cited)]
            flags.append(Flag(e, STALE, f"cites up to ch {max(cited):03d}; notes about {e.subject} run to ch {facts[-1].chapter:03d}",
                              later[-1].text))
    by_subject: dict[str, list[Entry]] = {}
    for e in entries:
        if e.cited_chapters():
            by_subject.setdefault(e.subject.casefold(), []).append(e)
    for group in by_subject.values():
        for e in group:
            others = [o for o in group if o.section != e.section]
            if not others:
                continue
            newest = max(others, key=lambda o: max(o.cited_chapters()))
            if max(e.cited_chapters()) < max(newest.cited_chapters()):
                flags.append(Flag(e, CROSS_SECTION, f"{newest.section} says more recently: {newest.text}",
                                  f"see {newest.section[3:]}: {newest.text[2:].strip()}"))
    # An NPC MENTIONED in a claim (not the entry's subject) whose status changed after the claim's citation:
    # "Kalan fled [ch 065]" inside the Avowed's line, with Kalan reinstated at ch 067. Judged PER CLAIM, so a
    # line whose other claim cites a later chapter cannot hide a stale one. A change needs a status on both
    # sides: "Alaundo — Dead" with no earlier row is not news.
    for e in entries:
        seen: set[str] = set()
        for claim in notes.claims_of(e.text):
            cited = [c for _, c, _ in notes.cites(claim) if c >= 0]
            if not cited:
                continue
            for name in sorted(ev.mentioned_in(claim) - {e.subject} - ev.pcs - seen):
                # "Unknown" means the chapter did not say, not that the status changed (state_sections)
                rows = [f for f in ev.facts(name) if f.kind == "status_row" and f.status != "Unknown"]
                before = [f for f in rows if f.chapter <= max(cited)]
                later = [f for f in rows if f.chapter > max(cited)]
                if later and before and later[-1].status != before[-1].status:
                    seen.add(name)
                    flags.append(Flag(e, MENTIONED, f"mentions {name} in a claim citing ch {max(cited):03d}; "
                                                    f"{name}'s status changed later", later[-1].text))
    return flags


# ── Applying ────────────────────────────────────────────────────────────────


@dataclass
class Hit:
    line: int  # 1-based, in the annotated document
    section: str
    text: str
    annotations: list[str]


@dataclass
class Removal:
    section: str
    text: str
    reason: str


@dataclass
class Result:
    text: str  # the annotated document
    hits: list[Hit] = field(default_factory=list)
    removed: list[Removal] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        notes_ = [a for h in self.hits for a in h.annotations]
        return {
            "later": sum(a.startswith(LATER) for a in notes_),
            "since": sum(a.startswith(SINCE) for a in notes_),
            "unverified": sum(a.startswith(UNVERIFIED) for a in notes_),
            "removed": len(self.removed),
            "lines": len(self.hits),
        }

    def summary(self) -> str:
        c = self.counts()
        return f"annotations: {c['later']} later, {c['since']} since, {c['unverified']} unverified; {c['removed']} removed"


def apply_annotations(lines: Sequence[str], flags: Sequence[Flag]) -> tuple[list[str], list[Hit], list[Removal]]:
    """``lines`` with an annotation sub-bullet under each flagged line and each removal dropped.

    ``lines`` must carry no old annotations (``strip_annotations``). A line's own text is passed through
    unchanged; the only line that leaves is a player character in an NPC group. One copy of each
    annotation, in first-seen order.
    """
    by_line: dict[int, list[Flag]] = {}
    for f in flags:
        by_line.setdefault(f.entry.line, []).append(f)
    out: list[str] = []
    hits: list[Hit] = []
    removed: list[Removal] = []
    for n, ln in enumerate(lines):
        fs = by_line.get(n, [])
        if any(f.kind == PC_IN_NPC for f in fs):
            e = fs[0].entry
            removed.append(Removal(e.section[3:], e.text, next(f.detail for f in fs if f.kind == PC_IN_NPC)))
            continue
        out.append(ln)
        ann = list(dict.fromkeys(a for f in fs if (a := f.annotation)))
        if ann:
            out.extend(f"  - {a}" for a in ann)
            hits.append(Hit(len(out) - len(ann), fs[0].entry.section[3:], ln, ann))
    return out, hits, removed


def annotate_text(text: str, ev: Evidence) -> Result:
    """``text`` with its annotations replaced by this run's. Everything else in it is byte-for-byte unchanged."""
    lines = strip_annotations(text.split("\n"))
    flags = detect(parse_entries(lines, ev), ev)
    out, hits, removed = apply_annotations(lines, flags)
    return Result("\n".join(out), hits, removed)


# ── The report ──────────────────────────────────────────────────────────────


def _record(result: Result) -> dict:
    return {
        "counts": result.counts(),
        "annotated": [{"line": h.line, "section": h.section, "text": h.text, "annotations": h.annotations} for h in result.hits],
        "removed": [{"section": r.section, "text": r.text, "reason": r.reason} for r in result.removed],
    }


def render_report(by_doc: dict[str, dict]) -> str:
    """``annotations.md``: every annotation and every removal, per document, under the line it belongs to."""
    out = ["# Annotations", "",
           "Every annotation and removal the last annotate step made. A line's own text is never changed.", ""]
    if not by_doc:
        out.append("(none)")
    for doc in sorted(by_doc):
        rec = by_doc[doc]
        c = rec["counts"]
        out += [f"## {doc}", "",
                f"{c['later']} later, {c['since']} since, {c['unverified']} unverified on {c['lines']} lines; "
                f"{c['removed']} lines removed.", ""]
        for h in rec["annotated"]:
            out += [f"### L{h['line']} — {h['section']}", "", h["text"], *(f"  - {a}" for a in h["annotations"]), ""]
        if rec["removed"]:
            out += ["### Removed", ""]
            out += [f"- {r['section']}: {r['text']} ({r['reason']})" for r in rec["removed"]]
            out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def read_counts(drafts_dir: Path) -> dict[str, dict]:
    """``{doc: counts}`` from the last annotate step of each document (``{}`` when none ran)."""
    try:
        data = json.loads((Path(drafts_dir) / COUNTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {d: r["counts"] for d, r in data.items() if isinstance(r, dict) and "counts" in r} if isinstance(data, dict) else {}


def write_report(drafts_dir: Path, doc: str, result: Result) -> Path:
    """Record ``doc``'s annotations in ``annotations.json`` and re-render ``annotations.md`` from every document's."""
    drafts_dir = Path(drafts_dir)
    try:
        data = json.loads((drafts_dir / COUNTS_FILE).read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data[doc] = _record(result)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(drafts_dir / COUNTS_FILE, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    atomic_write_text(drafts_dir / REPORT_FILE, render_report(data))
    return drafts_dir / REPORT_FILE


def dry_run_text(doc: str, result: Result) -> str:
    """What ``--dry-run`` prints: the same report for this one document, written nowhere."""
    return render_report({doc: _record(result)})


# ── The standalone step ─────────────────────────────────────────────────────

EXIT_REFUSED = 2


def run_annotate(
    args,
    *,
    range_dir: Path,
    summaries_dir: Path,
    registry_path: Path | None,
    players_path: Path | None,
) -> int:
    """``summary_native annotate <doc> [--dry-run]``: re-run the detectors over an existing draft.

    Rewrites only the draft's annotations (and removes a player character listed as a companion);
    no line's text changes and no model is called. Refuses when there is no draft or the notes are stale.
    """
    doc = args.doc
    draft = schema.draft_dir(range_dir, doc) / f"{doc}.draft.md"
    if not draft.is_file():
        hint = f" (only {doc}.incomplete.md exists: a draft is annotated only once it is complete)" \
            if (draft.parent / f"{doc}.incomplete.md").is_file() else ""
        return _refuse(f"no draft for {doc} at {draft}{hint}; run `summary_native synth {doc}`")
    try:
        manifest = corpus.load_manifest(range_dir, require_complete=True)
    except corpus.CorpusError as e:
        return _refuse(str(e))
    since, until = int(manifest["range"]["since"]), int(manifest["range"]["until"])
    extract_cmd = f"summary_native extract --since {since} --until {until}"
    problem = freshness.check_notes_fresh(range_dir, registry_path, players_path, extract_cmd=extract_cmd)
    if problem:
        return _refuse(problem)
    try:
        _, results = notes.load_checked(range_dir)
        ev = load_evidence(results, notes.load_chapters(Path(summaries_dir), since, until), registry_path, players_path)
    except notes.NotesIncomplete as e:
        return _refuse(f"{e}; run `{extract_cmd}`")
    except (ValueError, OSError) as e:
        return _refuse(f"cannot read the entity registry or players.yaml: {e}")
    result = annotate_text(draft.read_text(encoding="utf-8"), ev)
    if args.dry_run:
        print(dry_run_text(doc, result), end="")
        print(f"{result.summary()} [--dry-run: nothing written]")
        return 0
    atomic_write_text(draft, result.text)
    write_report(draft.parent, doc, result)
    print(result.summary())
    return 0


def _refuse(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return EXIT_REFUSED
