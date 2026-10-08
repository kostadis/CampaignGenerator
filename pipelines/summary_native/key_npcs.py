"""world_state's Key NPCs, rendered from the published NPC dossiers (spec 033 US3, FR-016..FR-018b). No model call.

The published dossier (``docs/npcs/<slug>.md``, spec 032) is the one authority for an NPC: it was
verified by ``npc-verify`` and published by the GM. world_state renders from it instead of
re-deriving it, so an NPC is fixed once, in its dossier.

    code selects   the NPCs (031's recent/recurring rules over the global NPCs, never a model)
    code reads     ONLY ``## Identity`` and ``## Last Observed State`` of each (``published_view``)
    model writes   one line per published NPC (the one call lives in ``synth``)
    code checks    exactly one line per NPC, citations from that NPC's dossier, quotations verbatim,
                   and substitutes the dossier's own first sentence for a line that fails

An NPC with no published, verification-passing dossier refuses the build by default, naming each NPC
and why. ``--fallback-npc-lines`` (per run, never config) writes a line built by code alone instead.

The reader below keeps the two named sections and discards every other line as it scans, so nothing
else the file holds can reach a prompt or an output. Guarded by ``tests/test_summary_native_no_llm.py``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from campaignlib.registry import load_registry
from pipelines.summary_native import notes, npc_check, npc_compose, npc_publish, npc_slug, schema, select

#: The only two sections ever read. Anything else in a dossier is discarded unread.
TAKE: tuple[str, str] = ("## Identity", "## Last Observed State")
#: Ends a code-built line, and tells the reader the NPC has no dossier behind it.
FALLBACK_MARK = schema.KEY_NPC_FALLBACK_MARK
POINTER = "→ docs/npcs/{slug}.md"
#: Fewest words a line may be given, however many NPCs share the section budget.
MIN_LINE_WORDS = 15
#: Key NPCs body when the selection rules pick nobody.
NO_NPCS_SELECTED = "_(no global NPC met the selection rules)_"

_PUBLISHED_RE = re.compile(
    r"\A<!-- published by summary_native npc-publish \| source: summary_native \| npc: (?P<npc>.+?) "
    r"\| range: (?P<range>ch\d{3}-\d{3}) .*?\| verify: (?P<verify>[a-z()]+)"
)
_ENTRY_CITE_RE = re.compile(r"(ch \d{3} / )entry\b")
_FAILURE_RE = re.compile(r"^- ([a-z][a-z-]*) \(", re.M)
_NPC_NOTE_RE = re.compile(r"^- \[NPC\] \*\*.+?\*\* — (.*)$", re.S)
_BLANK = {"", "—", "-"}


class NotPublished(Exception):
    """A file in ``docs/npcs/`` that is not a usable summary_native publication; the message says why."""


@dataclass(frozen=True)
class PublishedView:
    """What world_state may know of a published dossier: its name, header facts and two sections."""

    name: str
    slug: str
    range: str
    verify: str
    identity: str
    state: str

    @property
    def source(self) -> str:
        return f"{self.identity}\n{self.state}"


@dataclass(frozen=True)
class KeyNpc:
    """One selected NPC. ``view`` is its usable published dossier, or ``None`` when it has none."""

    name: str
    stem: str
    slug: str
    reason: str
    last_seen: int = 0
    view: PublishedView | None = None
    missing: str | None = None  # why there is no usable dossier
    carried_from: str | None = None


# ── Reading a published dossier ─────────────────────────────────────────────


def _norm(text: str) -> str:
    """A dossier cites an NPC's own entry as ``entry``; world_state calls that section ``npcs``."""
    return _ENTRY_CITE_RE.sub(r"\1npcs", text)


def _read_sections(path: Path, take: Sequence[str]) -> tuple["re.Match[str]", dict[str, str]]:
    """``(header match, {heading: normalised body})`` for the ``take`` sections of one published dossier.

    One pass over the lines: a line is kept only while a ``take`` heading is current, so no other
    section is ever held, parsed or returned. Raises ``NotPublished`` for any other file.
    """
    text = Path(path).read_text(encoding="utf-8")
    m = _PUBLISHED_RE.match(text.split("\n", 1)[0])
    if m is None:
        raise NotPublished("not a summary_native publication")
    kept: dict[str, list[str]] = {h: [] for h in take}
    current = None
    for line in text.splitlines()[1:]:
        if line.startswith("## "):
            current = line.rstrip() if line.rstrip() in kept else None
        elif current is not None:
            kept[current].append(line)
    return m, {h: _norm("\n".join(kept[h]).strip("\n")) for h in take}


def published_view(path: Path) -> PublishedView:
    """The view of one published dossier. Raises ``NotPublished`` for any other file.

    Reads only the ``TAKE`` sections (see :func:`_read_sections`).
    """
    m, got = _read_sections(path, TAKE)
    ident, state = (got[h] for h in TAKE)
    if not state:
        raise NotPublished("no Last Observed State")
    return PublishedView(m.group("npc"), Path(path).stem, m.group("range"), m.group("verify"), ident, state)


#: planning's NPC Dossiers read four sections: the two above plus the NPC's motives and relationships.
PLANNING_TAKE: tuple[str, str, str, str] = (
    "## Identity", "## Personality and Motivations", "## Last Observed State", "## Relationships")


@dataclass(frozen=True)
class PlanningView:
    """What planning may know of a published dossier: its name, header facts and four sections."""

    name: str
    slug: str
    range: str
    verify: str
    identity: str
    personality: str
    state: str
    relationships: str

    @property
    def source(self) -> str:
        """Everything the NPC's block may be written from, and every quotation checked against."""
        return "\n".join(s for s in (self.identity, self.personality, self.state, self.relationships) if s)


def planning_view(path: Path) -> PlanningView:
    """The planning view of one published dossier. Raises ``NotPublished`` like :func:`published_view`.

    The same one-pass, held-heading-only reader, with ``PLANNING_TAKE`` as its take-set.
    """
    m, got = _read_sections(path, PLANNING_TAKE)
    ident, pers, state, rels = (got[h] for h in PLANNING_TAKE)
    if not state:
        raise NotPublished("no Last Observed State")
    return PlanningView(m.group("npc"), Path(path).stem, m.group("range"), m.group("verify"), ident, pers, state, rels)


def _range_numbers(rng: str) -> tuple[int, int]:
    match = re.fullmatch(r"ch(\d{3})-(\d{3})", rng)
    if match is None:
        raise ValueError(f"invalid chapter range: {rng}")
    return int(match[1]), int(match[2])


def _touched(name: str, after: int, until: int, results: Sequence[notes.CheckedChunk], forms: dict[str, str]) -> bool:
    """Any checked note citing new chapters that names this NPC, including prose mentions.

    Match whole registry names/aliases only, casefolded as in the status table. Similar spellings
    and ambiguous registry forms are never inferred. Inspect every citation, not just the first.
    """
    canon = forms.get(name.casefold(), name).casefold()
    aliases = {f for f, n in forms.items() if n.casefold() == canon} | {canon}
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(f) for f in sorted(aliases, key=len, reverse=True)) + r")(?!\w)")
    for chunk in results:
        for note in chunk.notes:
            if not any(after < chapter <= until for _, chapter, _ in notes.cites(note.text)):
                continue
            subject = note.subject or ""
            if forms.get(subject.casefold(), subject).casefold() == canon or pattern.search(note.text.casefold()):
                return True
    return False


def published_dossiers(
    campaign: Path, rng: str, *, results: Sequence[notes.CheckedChunk] | None = None,
    forms: dict[str, str] | None = None,
) -> tuple[dict[str, PublishedView], dict[str, str]]:
    """Usable/unusable publications keyed by canonical casefolded name.

    Same-range publications pass as before. An earlier end with the same start is safe only
    when checked notes were supplied and none in the added chapters names this NPC. Different
    starts stay refused: their evidence coverage differs. Future end chapters always refuse.
    """
    forms = forms or {}
    since, until = _range_numbers(rng)
    usable: dict[str, PublishedView] = {}
    unusable: dict[str, str] = {}
    for p in sorted((Path(campaign) / schema.NPCS_DIR).glob("*.md")):
        try:
            v = published_view(p)
        except (NotPublished, OSError, UnicodeDecodeError):
            continue
        key = forms.get(v.name.casefold(), v.name).casefold()
        previous_since, previous_until = _range_numbers(v.range)
        why = None
        if v.range != rng:
            why = f"published for {v.range}, not {rng}"
            if previous_since == since and previous_until < until and results is not None:
                if _touched(v.name, previous_until, until, results, forms):
                    why += "; checked notes name this NPC in the added chapters"
                else:
                    why = None
        if v.verify != "pass":
            why = f"failed verification (published with verify: {v.verify}; published for {v.range}, build {rng})"
        if why:
            unusable[key] = why
        else:
            usable[key] = v
    return usable, unusable


# ── Selection ───────────────────────────────────────────────────────────────


def registry_npc_scopes(registry_path: Path | None) -> dict[str, str]:
    """``{canonical name: scope}`` for the registry's NPCs; empty when there is no registry."""
    if registry_path is None or not Path(registry_path).is_file():
        return {}
    return {e.name: e.scope for e in load_registry(registry_path).entities if e.type == "npc"}


def select_key_npcs(
    dossiers: Sequence[select.Dossier],
    scopes: dict[str, str],
    pcs: set[str],
    *,
    range_until: int,
    recent_chapters: int,
    recurring_min: int,
    named: Sequence[str] = (),
) -> list[tuple[select.Dossier, str]]:
    """``[(corpus dossier, reason)]`` in 031's order: named, then recent, then recurring.

    The pool is the global NPCs: a corpus ``npc`` dossier whose subject is a persistent registry NPC
    and not a player character. Raises ``select.SelectionError`` for a ``named`` subject outside it.
    """
    pc_keys = {p.casefold() for p in pcs}
    pool = [
        d for d in dossiers
        if d.category == "npc" and scopes.get(d.subject) == "persistent" and d.subject.casefold() not in pc_keys
    ]
    sel = select.select_dossiers(pool, range_until, recent_chapters, recurring_min, tuple(named))
    return [(i.dossier, i.reason) for i in sel.items]


# ── Why a dossier is missing ────────────────────────────────────────────────


def _failure_checks(verify_md: Path) -> str:
    """``"not-found 2, citation-mismatch 1"`` from a ``*.verify.md``'s Failures section."""
    try:
        text = verify_md.read_text(encoding="utf-8")
    except OSError:
        return ""
    body = text.split("## Failures", 1)[-1].split("\n## ", 1)[0]
    counts: dict[str, int] = {}
    for code in _FAILURE_RE.findall(body):
        counts[code] = counts.get(code, 0) + 1
    return ", ".join(f"{c} {n}" for c, n in counts.items())


def missing_dossier_state(
    name: str, stem: str, slug: str, *, npc_root: Path, rng: str, unusable: dict[str, str], log: dict[str, dict],
) -> str:
    """Why ``name`` has no usable published dossier, from its publication, its draft's
    verification and the publish log (``npc_root`` is where the ``npc-*`` commands wrote them).

    ``not drafted`` | ``drafted, not verified`` | ``failed verification (<checks>)`` |
    ``drafted, not published`` | ``published for <range>, not <range>``.
    """
    if name.casefold() in unusable:
        return unusable[name.casefold()]
    npc_range_dir = Path(npc_root) / rng
    verdict = npc_publish.read_verdict(npc_range_dir, stem)
    if verdict == "fail":
        checks = _failure_checks(npc_range_dir / npc_compose.DRAFT_DIR / f"{stem}.verify.md")
        return f"failed verification ({checks})" if checks else "failed verification"
    if verdict == "pass":
        logged = (log.get(slug) or {}).get("range")
        if logged and logged != rng:
            return f"published for {logged}, not {rng}"
        return "drafted, not published"
    if (npc_range_dir / npc_compose.DRAFT_DIR / f"{stem}.md").is_file():
        return "drafted, not verified"
    return "not drafted"


def plan_key_npcs(
    chosen: Sequence[tuple[select.Dossier, str]], campaign: Path, *, npc_root: Path, rng: str,
    results: Sequence[notes.CheckedChunk] | None = None, forms: dict[str, str] | None = None,
) -> list[KeyNpc]:
    """Attach to each selected NPC its usable dossier, or the reason it has none."""
    usable, unusable = published_dossiers(campaign, rng, results=results, forms=forms)
    try:
        log = npc_publish.read_publish_log(Path(campaign), Path(npc_root))
    except npc_publish.PublishRefusal:
        log = {}  # an unreadable log only loses a hint; the headers above are the authority
    out = []
    for d, reason in chosen:
        slug = npc_slug.slug_for(d.subject)
        view = usable.get(d.subject.casefold())
        missing = None if view else missing_dossier_state(
            d.subject, d.stem, slug, npc_root=npc_root, rng=rng, unusable=unusable, log=log)
        out.append(KeyNpc(d.subject, d.stem, view.slug if view else slug, reason, d.last_chapter, view, missing,
                          view.range if view is not None and view.range != rng else None))
    return out


def refusal_message(plan: Sequence[KeyNpc], since: int, until: int, npc_root_flag: str | None = None) -> str | None:
    """The refusal text for the NPCs in ``plan`` with no usable dossier, or ``None`` when there are none."""
    missing = [k for k in plan if k.view is None]
    if not missing:
        return None
    rng = f"--since {since} --until {until}" + (f" --npc-root {npc_root_flag}" if npc_root_flag else "")
    names = " ".join(f'"{k.name}"' for k in missing)
    lines = [
        f"world_state's Key NPCs need a published, verified dossier for each selected NPC; "
        f"{len(missing)} of {len(plan)} have none:",
        *(f"  {k.name}: {k.missing}" for k in missing),
        "Draft, verify and publish them, then build again:",
        f"  summary_native npc-draft {rng} --name {names}",
        f"  summary_native npc-verify {rng} --name {names}",
        f"  summary_native npc-compose {rng} --name {names}",
        f"  summary_native npc-publish {rng} --name {names}",
        f"or pass --fallback-npc-lines to write a code-built line {FALLBACK_MARK} for each of them.",
    ]
    return "\n".join(lines)


# ── The model's lines, and the checks on them ───────────────────────────────


def _words(line: str) -> int:
    return len(schema.STATE_CITE_RE.sub("", line).split())


def words_per_line(budget: int, n: int) -> int:
    """Each published NPC's share of the section's word budget."""
    return max(MIN_LINE_WORDS, budget // max(n, 1))


def lines_prompt(plan: Sequence[KeyNpc], per: int) -> str:
    """The user prompt of the one Key NPCs call: each published NPC's two passages, in selection order."""
    views = [(k, k.view) for k in plan if k.view is not None]
    blocks = "\n\n".join(
        f"### {v.name} (last seen ch {k.last_seen:03d})\nIDENTITY: {v.identity}\nLAST OBSERVED STATE: {v.state}"
        for k, v in views
    )
    return (
        "DOCUMENT: world_state\nSECTION: ## Key NPCs\n\n"
        f"{len(views)} NPCs, in this order. At most {per} words per line (citations not counted).\n\n{blocks}\n\n"
        "Write exactly one line per NPC, in the same order, each starting `- **<name exactly as given>** — `.\n"
    )


def verify_line(line: str, view: PublishedView, hay: str, max_words: int) -> str | None:
    """Why ``line`` is not an acceptable line for ``view``, or ``None``.

    It must start with the NPC's exact name, cite, cite only what that NPC's dossier cites, quote
    only words found in the dossier or the summaries, and stay within twice the word limit.
    """
    if not line.startswith(f"- **{view.name}**"):
        return "does not start with the NPC's exact name"
    allowed = {(c, t) for _, c, t in notes.cites(view.source)}
    found = notes.cites(line)
    if not found:
        return "uncited"
    for bracket, c, t in found:
        if c < 0 or (c, t) not in allowed:
            return f"citation not in this NPC's dossier: {bracket}"
    for span in npc_check.SPAN_RE.findall(line):
        inner = npc_check.strip_quote_marks(span)
        if len(inner) >= 4 and npc_check._contains(view.source, inner) is None and npc_check._contains(hay, inner) is None:
            return f"quotation not verbatim: {span}"
    if _words(line) > 2 * max_words:
        return f"too long ({_words(line)} words)"
    return None


def first_sentence(text: str) -> str:
    """The first sentence of ``text`` with the citation(s) that close it; the first citation found
    in ``text`` is appended when the sentence carries none."""
    m = re.match(r"(.+?[.!?](?:\s*\[ch [^\]]+\])*)(?:\s|$)", text.strip(), re.S)
    s = (m.group(1) if m else text.strip()).replace("\n", " ")
    if not notes.cites(s):
        c = schema.STATE_CITE_RE.search(text)
        s = s.rstrip(".") + (f" {c.group(0)}." if c else ".")
    return s


def fallback_from_dossier(view: PublishedView) -> str:
    """The dossier's own first Last Observed State sentence, led by its Identity sentence when the
    state sentence carries no citation (``Status not established in the summaries.``)."""
    fb = first_sentence(view.state)
    if not notes.cites(fb):
        fb = f"{first_sentence(view.identity)} {fb}"
    return f"- **{view.name}** — {fb}"


def with_pointer(line: str, slug: str) -> str:
    return f"{line.rstrip()} {POINTER.format(slug=slug)}"


def _clean(s: str | None) -> str:
    return "" if (s or "").strip() in _BLANK else s.strip()


def fallback_from_notes(
    name: str, results: Sequence[notes.CheckedChunk], forms: dict[str, str],
) -> str:
    """A line for an NPC with no published dossier, built from checked notes alone (FR-018b).

    The NPC's latest status row with a known status (else its latest row), then its latest ``[NPC]``
    world note, each verbatim with its own citation. Nothing is reworded or invented, and the line
    ends with ``FALLBACK_MARK``.
    """
    key = name.casefold()

    def is_it(subject: str | None) -> bool:
        s = subject or ""
        return forms.get(s.casefold(), s).casefold() == key

    rows = sorted((r for c in results for r in c.kept("status_row") if is_it(r.subject)), key=lambda n: n.first_chapter)
    known = [r for r in rows if r.status != "Unknown"]
    row = known[-1] if known else (rows[-1] if rows else None)
    world = sorted((n for c in results for n in c.kept("world") if n.tag == "NPC" and is_it(n.subject)),
                   key=lambda n: n.first_chapter)
    parts = []
    if row is not None:
        facts = [row.status, _clean(row.location), _clean(row.disposition)]
        parts.append("; ".join(f for f in facts if f) + f" {row.cite}")
    if world:
        m = _NPC_NOTE_RE.match(world[-1].text)
        parts.append(m.group(1).strip() if m else world[-1].text.lstrip("- ").strip())
    body = " ".join(parts) if parts else "no checked note names this NPC."
    return f"- **{name}** — {body} {FALLBACK_MARK}"


# ── Assembling the section ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Assembled:
    lines: list[str]
    report: list[str]  # one line per substitution, fallback and discard, for the build report
    from_model: int
    substituted: int  # a failing or missing model line replaced by the dossier's own sentence
    fallbacks: int  # an NPC with no dossier, line built from checked notes


def assemble(
    plan: Sequence[KeyNpc], model_out: str | None, hay: str, per: int,
    results: Sequence[notes.CheckedChunk], forms: dict[str, str],
) -> Assembled:
    """One line per selected NPC, in selection order. ``model_out`` is the call's raw output, or
    ``None`` when no call was made. Extra, duplicated or reordered lines from the model are discarded."""
    got = [ln.strip() for ln in (model_out or "").splitlines() if ln.strip().startswith("- **")]
    lines: list[str] = []
    report: list[str] = []
    from_model = substituted = fallbacks = 0
    for k in plan:
        if k.view is None:
            lines.append(fallback_from_notes(k.name, results, forms))
            report.append(f"- {k.name}: fallback line from checked notes ({k.missing})")
            fallbacks += 1
            continue
        cand = next((ln for ln in got if ln.startswith(f"- **{k.view.name}**")), None)
        why = "missing from the model's output" if cand is None else verify_line(cand, k.view, hay, per)
        if why:
            lines.append(with_pointer(fallback_from_dossier(k.view), k.slug))
            report.append(f"- {k.name}: the dossier's own sentence replaces the model's line ({why})")
            substituted += 1
        else:
            lines.append(with_pointer(cand, k.slug))
            from_model += 1
    names = [k.view.name for k in plan if k.view is not None]
    report += [
        f"- discarded (not a selected NPC, repeated, or out of place): {ln[:100]}"
        for ln in got if sum(ln.startswith(f"- **{n}**") for n in names) == 0
    ]
    return Assembled(lines, report, from_model, substituted, fallbacks)


def section_body(a: Assembled, n_published: int, n_total: int) -> str:
    """Key NPCs' body: the lines, then a note saying where they come from."""
    note = (
        f"_Source: the published NPC dossiers in `docs/npcs/` ({n_published} of {n_total} NPCs; verified). "
        "Fix an NPC in its dossier, not here."
        + (f" {a.fallbacks} NPC(s) have no published dossier and are marked." if a.fallbacks else "")
        + "_"
    )
    return "\n".join(a.lines) + "\n\n" + note


def report_md(plan: Sequence[KeyNpc], a: Assembled, per: int, words: int, budget: int) -> str:
    """``key_npcs_report.md``: who was selected and why, what the model wrote, what code replaced."""
    out = [
        "# Key NPCs", "",
        f"{len(plan)} selected; {a.from_model} lines from the model, {a.substituted} replaced by the "
        f"dossier's own sentence, {a.fallbacks} built from checked notes. {words}/{budget} words, "
        f"{per} words per model line.", "", "## Selected (order)", "",
    ]
    out += [f"- {k.name} ({k.reason}) — " + (f"docs/npcs/{k.slug}.md" if k.view else f"no dossier: {k.missing}") for k in plan]
    out += [f"- {k.name}: carried over from {k.carried_from}" for k in plan if k.carried_from]
    out += ["", "## Substitutions, fallbacks and discards", ""] + (a.report or ["(none)"])
    return "\n".join(out) + "\n"
