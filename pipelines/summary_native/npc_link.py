"""Deterministic NPC linking: every scene and moment that names an NPC (spec 032 T014-T016).

``iter_items`` cuts a parsed summary into the two kinds of linkable item (a whole scene,
a memorable-moment block). ``link`` matches the run's name forms against each item and
builds one evidence dossier per NPC corpus dossier. The writers render the evidence
dossiers, the link report and the link manifest.

A linked item is labelled *mentioned*, never *present* (FR-005). Text is copied verbatim
(FR-004, FR-007); mention lines are reported beside it as file line numbers, never by
altering the text. Output is byte-deterministic (FR-009): sorted keys, sorted files, no
timestamps, no absolute paths.

No model call (guarded by ``tests/test_summary_native_no_llm.py``).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from campaignlib.util import atomic_write_text
from pipelines.summary_native import corpus, npc_forms, parse, schema

EVIDENCE_DIR = "evidence"
LINK_MANIFEST = "link_manifest.json"
LINK_REPORT_MD = "link_report.md"
LINK_REPORT_JSON = "link_report.json"
EVIDENCE_SOURCE_KIND = "summary_native_npc_link"

_ENTRY_RE = re.compile(
    r"^## Chapter (\d+) — (.+?)\n\n- Source: (.+?) \(line (\d+)\)\n", re.MULTILINE
)


# ── Items ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LinkedItemCandidate:
    """A scene or moment cut out of a summary, before any form is matched."""

    kind: str  # "scene" | "moment"
    chapter: int
    scene_id: str | None
    title: str | None
    source_file: str
    line: int  # first line of the item (a scene's heading line; a moment's first ``>`` line)
    text: str  # verbatim, leading/trailing blank lines trimmed
    #: ``(file line, text)`` for every line a form is matched against. A scene includes
    #: its heading line, so a title that names the NPC counts as a mention.
    lines: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class LinkedItem:
    kind: str
    chapter: int
    scene_id: str | None
    title: str | None
    source_file: str
    line: int
    text: str
    mention_lines: tuple[int, ...]
    forms_matched: tuple[str, ...]


@dataclass(frozen=True)
class ComputedHeader:
    canonical: str
    aliases_used: tuple[str, ...]
    type: str
    first_seen: int
    last_seen: int
    chapters: tuple[int, ...]
    n_entries: int
    n_scenes: int
    n_moments: int
    range: str


@dataclass(frozen=True)
class EvidenceDossier:
    stem: str
    subject: str
    global_: bool
    exclusion: str | None
    entries: tuple[corpus.Observation, ...]
    items: tuple[LinkedItem, ...]
    header: ComputedHeader


@dataclass
class LinkResult:
    dossiers: list[EvidenceDossier]
    findings: list[dict]
    counts: dict = field(default_factory=dict)


def _trim_blank(lines: list[str]) -> list[str]:
    a, b = 0, len(lines)
    while a < b and not lines[a].strip():
        a += 1
    while b > a and not lines[b - 1].strip():
        b -= 1
    return lines[a:b]


def _text_of(lines: list[str]) -> str:
    return "".join(_trim_blank(lines)).rstrip("\n")


def _strip_nl(line: str) -> str:
    return line.rstrip("\n").rstrip("\r")


_MOMENT_OPENERS = (">", "**", "- ")


def _moment_spans(mlines: list[str]) -> list[tuple[int, int]]:
    """``(start, end)`` line indexes of each moment in a ``## Memorable Moments`` body.

    A moment starts at a paragraph (a non-blank line after a blank line, or the first
    line) that opens with ``>``, ``**`` or ``- ``; each ``- `` line starts its own moment.
    Any other paragraph (italic context, attribution, loose prose) attaches to the moment
    before it. Such a paragraph before the first start is an item of its own
    (research R3, GM ruling 2026-10-06). ``end`` may include trailing blank lines.
    """
    starts: list[int] = []
    orphans: set[int] = set()
    prev_blank = True
    opener = ""
    for i, ln in enumerate(mlines):
        if not ln.strip():
            prev_blank = True
            continue
        if prev_blank:
            opener = next((o for o in _MOMENT_OPENERS if ln.startswith(o)), "")
            if opener:
                starts.append(i)
            elif not starts or starts[-1] in orphans:
                starts.append(i)  # before the first real start: its own item
                orphans.add(i)
        elif opener == "- " and ln.startswith("- "):
            starts.append(i)
        prev_blank = False
    spans = []
    for k, s in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(mlines)
        spans.append((s, end))
    return spans


def iter_items(pf: parse.ParsedFile) -> list[LinkedItemCandidate]:
    """Every scene under ``## Scenes``, then every moment under ``## Memorable Moments``.

    A moment is a run that starts at a ``>`` line and runs until the next blank line that
    is followed by a new ``>`` line (or the section ends), so the quote, its attribution
    and its context paragraph stay together (research R3). Moments are chapter-level:
    they carry no scene id. Lines before the first ``>`` are not part of any moment.
    """
    out: list[LinkedItemCandidate] = []
    for sc in pf.scenes:
        body_lines = parse.split_lines(sc.body)
        numbered = [(sc.line, sc.heading)] + [
            (sc.line + 1 + i, _strip_nl(ln)) for i, ln in enumerate(body_lines)
        ]
        out.append(
            LinkedItemCandidate(
                kind="scene",
                chapter=pf.prefix_chapter,
                scene_id=sc.source_scene_id,
                title=sc.title,
                source_file=pf.path,
                line=sc.line,
                text=_text_of(body_lines),
                lines=tuple(numbered),
            )
        )
    sec = pf.section(schema.MEMORABLE_MOMENTS)
    if sec is not None:
        mlines = parse.split_lines(sec.body)
        for s, e in _moment_spans(mlines):
            block = mlines[s:e]
            while block and not block[-1].strip():
                block.pop()
            out.append(
                LinkedItemCandidate(
                    kind="moment",
                    chapter=pf.prefix_chapter,
                    scene_id=None,
                    title=None,
                    source_file=pf.path,
                    line=sec.line + 1 + s,
                    text="".join(block).rstrip("\n"),
                    lines=tuple((sec.line + 1 + s + j, _strip_nl(ln)) for j, ln in enumerate(block)),
                )
            )
    return out


# ── Linking ─────────────────────────────────────────────────────────────────


def _read_entries(
    range_dir: Path, stem: str, subject: str, by_loc: dict[tuple[str, int], parse.EntityEntry]
) -> tuple[corpus.Observation, ...]:
    """A dossier's observations. The body is read from the summary itself (exact), the
    heading and place from the built dossier."""
    text = (Path(range_dir) / "dossiers" / f"{stem}.md").read_text(encoding="utf-8")
    out = []
    for m in _ENTRY_RE.finditer(text):
        chapter, heading, path, line = int(m.group(1)), m.group(2), m.group(3), int(m.group(4))
        ent = by_loc.get((path, line))
        if ent is None:
            raise npc_forms.LinkRefusal(
                f"{range_dir}/dossiers/{stem}.md cites {path} line {line}, which holds no entry; "
                "run `summary_native build --force`"
            )
        out.append(
            corpus.Observation(
                category="npc",
                heading=heading,
                canonical=subject,
                grouped_by=(),
                chapter=chapter,
                source_file=path,
                source_scene_id=None,
                line=line,
                body=ent.body,
            )
        )
    return tuple(sorted(out, key=lambda o: (o.chapter, o.line, o.source_file)))


def _loc(path: str, line: int) -> str:
    return f"{path}:{line}"


def _item_sort_key(i: LinkedItem) -> tuple:
    return (i.chapter, 0 if i.kind == "scene" else 1, i.scene_id or "", i.line)


def _range_of(range_dir: Path) -> tuple[int, int]:
    manifest = corpus.load_manifest(range_dir)
    return int(manifest["range"]["since"]), int(manifest["range"]["until"])


def link_with_findings(
    files: list[parse.ParsedFile], corpus_range_dir: Path, form_index: npc_forms.FormIndex
) -> LinkResult:
    """Link every NPC corpus dossier. Also returns the report findings (withheld forms,
    ruling findings, mentions of registry NPCs that have no heading)."""
    range_dir = Path(corpus_range_dir)
    since, until = _range_of(range_dir)
    rng = f"{since}-{until}"
    files = sorted(files, key=lambda f: (f.prefix_chapter, f.path))
    npc_dossiers = [d for d in npc_forms.read_corpus_dossiers(range_dir) if d.type == "npc"]

    by_loc: dict[tuple[str, int], parse.EntityEntry] = {}
    for pf in files:
        for e in pf.entities:
            by_loc[(pf.path, e.line)] = e

    hits: dict[str, list[LinkedItem]] = {d.stem: [] for d in npc_dossiers}
    occurrences: dict[str, set[tuple[int, str, int]]] = {}  # withheld form -> (chapter, path, line)
    registry_only_hits: dict[str, dict] = {}
    ruled = sorted(form_index.rulings)
    ruled_res = {f: re.compile(rf"(?<!\w){re.escape(f)}(?!\w)") for f in ruled}
    occurring: set[str] = set()

    def note_ruled(text: str) -> None:
        for f, rx in ruled_res.items():
            if f not in occurring and rx.search(text):
                occurring.add(f)

    for pf in files:
        for item in iter_items(pf):
            per_stem: dict[str, dict] = {}
            for lineno, text in item.lines:
                note_ruled(text)
                for _, _, nf in form_index.match_line(text):
                    if nf.status in npc_forms.LINKABLE_STATUSES:
                        if nf.stems:
                            slot = per_stem.setdefault(nf.stems[0], {"lines": set(), "forms": set()})
                            slot["lines"].add(lineno)
                            slot["forms"].add(nf.text)
                        elif nf.owner is not None:
                            r = registry_only_hits.setdefault(nf.owner[1], {"forms": set(), "locs": set()})
                            r["forms"].add(nf.text)
                            r["locs"].add((item.chapter, item.source_file, lineno))
                    else:
                        occurrences.setdefault(nf.text, set()).add((item.chapter, item.source_file, lineno))
            for stem, slot in per_stem.items():
                hits[stem].append(
                    LinkedItem(
                        kind=item.kind,
                        chapter=item.chapter,
                        scene_id=item.scene_id,
                        title=item.title,
                        source_file=item.source_file,
                        line=item.line,
                        text=item.text,
                        mention_lines=tuple(sorted(slot["lines"])),
                        forms_matched=tuple(sorted(slot["forms"])),
                    )
                )
        for ent in pf.entities:  # a withheld form used as a heading is also somewhere to fix
            note_ruled(ent.heading)
            nf = form_index.forms.get(ent.heading)
            if nf is not None and nf.status not in npc_forms.LINKABLE_STATUSES:
                occurrences.setdefault(nf.text, set()).add((pf.prefix_chapter, pf.path, ent.line))

    dossiers: list[EvidenceDossier] = []
    for d in npc_dossiers:
        entries = _read_entries(range_dir, d.stem, d.subject, by_loc)
        items = tuple(sorted(hits[d.stem], key=_item_sort_key))
        chapters = sorted({o.chapter for o in entries} | {i.chapter for i in items})
        used = {o.heading for o in entries} | {f for i in items for f in i.forms_matched}
        header = ComputedHeader(
            canonical=d.subject,
            aliases_used=tuple(sorted(used)),
            type="npc",
            first_seen=chapters[0],
            last_seen=chapters[-1],
            chapters=tuple(chapters),
            n_entries=len(entries),
            n_scenes=sum(1 for i in items if i.kind == "scene"),
            n_moments=sum(1 for i in items if i.kind == "moment"),
            range=rng,
        )
        is_global, exclusion = form_index.global_status(d.subject)
        dossiers.append(EvidenceDossier(d.stem, d.subject, is_global, exclusion, entries, items, header))
    dossiers.sort(key=lambda e: e.stem)

    findings = _withheld_findings(form_index, occurrences)
    findings += [
        {
            "code": schema.MENTION_WITHOUT_HEADING,
            "subject": canonical,
            "forms": sorted(r["forms"]),
            "locations": _locs(r["locs"]),
            "message": (
                f"registry NPC {canonical!r} is named in scenes or moments but has no heading "
                "in any summary, so no dossier exists for it"
            ),
        }
        for canonical, r in sorted(registry_only_hits.items())
    ]
    findings += form_index.ruling_findings(occurring)
    findings += [
        {
            "code": schema.PLAYER_CHARACTER_UNRESOLVED,
            "subject": character,
            "player": player,
            "message": (
                f"players.yaml: {player} plays {character!r}, which is neither the name nor an "
                "alias of any registry entity; it cannot be excluded as a player character"
            ),
        }
        for player, character in form_index.unresolved_players
    ]
    findings.sort(key=_finding_key)
    counts = {
        "npcs": len(dossiers),
        "scenes": sum(e.header.n_scenes for e in dossiers),
        "moments": sum(e.header.n_moments for e in dossiers),
        "ambiguous": sum(1 for f in findings if f["code"] == schema.AMBIGUOUS_FORM),
        "generic_unruled": sum(
            1 for f in findings if f["code"] == schema.GENERIC_FORM and f["ruling"] is None
        ),
        "generic_never": sum(
            1 for f in findings if f["code"] == schema.GENERIC_FORM and f["ruling"] == "never"
        ),
    }
    return LinkResult(dossiers, findings, counts)


def link(
    files: list[parse.ParsedFile], corpus_range_dir: Path, form_index: npc_forms.FormIndex
) -> list[EvidenceDossier]:
    return link_with_findings(files, corpus_range_dir, form_index).dossiers


def _locs(triples) -> list[str]:
    return [_loc(p, n) for _, p, n in sorted(triples)]


def _withheld_findings(form_index: npc_forms.FormIndex, occurrences) -> list[dict]:
    out = []
    for nf in form_index.withheld():
        occ = occurrences.get(nf.text)
        if not occ:  # a form that occurs nowhere in range is withholding nothing
            continue
        if nf.status == npc_forms.AMBIGUOUS:
            out.append(
                {
                    "code": schema.AMBIGUOUS_FORM,
                    "form": nf.text,
                    "collides_with": [{"type": t, "canonical": c} for t, c in nf.collides_with],
                    "ruling": None,
                    "locations": _locs(occ),
                    "message": (
                        f"{nf.text!r} names more than one entity "
                        + " and ".join(f"{t} {c!r}" for t, c in nf.collides_with)
                        + "; withheld, and it cannot be ruled - fix the summaries"
                    ),
                }
            )
        else:
            ruling = "never" if nf.status == npc_forms.GENERIC_NEVER else None
            out.append(
                {
                    "code": schema.GENERIC_FORM,
                    "form": nf.text,
                    "collides_with": [],
                    "ruling": ruling,
                    "locations": _locs(occ),
                    "message": (
                        f"{nf.text!r} is an ordinary English word; "
                        + ("ruled never to link" if ruling else "withheld until canon.yaml link_rulings says safe or never")
                    ),
                }
            )
    return out


_CODE_ORDER = {
    c: i
    for i, c in enumerate(
        (
            schema.AMBIGUOUS_FORM,
            schema.GENERIC_FORM,
            schema.STALE_LINK_RULING,
            schema.LINK_RULING_UNNEEDED,
            schema.MENTION_WITHOUT_HEADING,
            schema.PLAYER_CHARACTER_UNRESOLVED,
        )
    )
}


def _finding_key(f: dict) -> tuple:
    return (_CODE_ORDER[f["code"]], f.get("form") or f.get("subject") or "")


# ── Rendering and writing ───────────────────────────────────────────────────


def _body(text: str) -> str:
    return "\n".join(_trim_blank(text.split("\n"))) if text else ""


def render_evidence(d: EvidenceDossier) -> str:
    h = d.header
    fm = {
        "subject": d.subject,
        "type": h.type,
        "global": d.global_,
        "exclusion": d.exclusion,
        "aliases_used": list(h.aliases_used),
        "first_seen": h.first_seen,
        "last_seen": h.last_seen,
        "chapters": list(h.chapters),
        "n_entries": h.n_entries,
        "n_scenes": h.n_scenes,
        "n_moments": h.n_moments,
        "range": h.range,
        "source_kind": EVIDENCE_SOURCE_KIND,
    }
    head = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, default_flow_style=None, width=10**6)
    parts = [f"---\n{head}---\n\n# NPC — {d.subject}\n"]
    for ch in h.chapters:
        parts.append(f"\n## Chapter {ch:03d}\n")
        for o in d.entries:
            if o.chapter == ch:
                parts.append(
                    f"\n### Entry — {o.heading}\n- Source: {o.source_file} (line {o.line})\n\n{_body(o.body)}\n"
                )
        for i in d.items:
            if i.chapter != ch:
                continue
            mention = ", ".join(str(n) for n in i.mention_lines)
            if i.kind == "scene":
                parts.append(
                    f"\n### Scene {i.scene_id} — {i.title} (mentioned)\n"
                    f"- Source: {i.source_file} (line {i.line})\n"
                    f"- Mention lines: {mention}\n\n{i.text}\n"
                )
            else:
                parts.append(
                    f"\n### Moment (mentioned)\n"
                    f"- Source: {i.source_file} (line {i.line})\n"
                    f"- Scene: none\n"
                    f"- Mention lines: {mention}\n\n{i.text}\n"
                )
    return "".join(parts)


def _dumps(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_report_md(rng: str, result_counts: dict, findings: list[dict]) -> str:
    c = result_counts
    out = [
        f"# NPC link report — chapters {rng}\n",
        "\n"
        f"- NPCs linked: {c['npcs']}\n"
        f"- Scenes linked: {c['scenes']}\n"
        f"- Moments linked: {c['moments']}\n"
        f"- Ambiguous forms withheld: {c['ambiguous']}\n"
        f"- Generic forms withheld (unruled): {c['generic_unruled']}\n"
        f"- Generic forms ruled never: {c['generic_never']}\n",
    ]
    sections = (
        (schema.AMBIGUOUS_FORM, "Ambiguous forms (withheld; fix the summaries, no ruling can resolve them)"),
        (schema.GENERIC_FORM, "Generic forms (withheld unless ruled `safe` in canon.yaml link_rulings)"),
        (schema.STALE_LINK_RULING, "Stale link rulings (form occurs nowhere in the range)"),
        (schema.LINK_RULING_UNNEEDED, "Unneeded link rulings (form is neither generic nor ambiguous)"),
        (schema.MENTION_WITHOUT_HEADING, "Registry NPCs named without a heading (no dossier)"),
        (schema.PLAYER_CHARACTER_UNRESOLVED, "players.yaml `plays` names that match no registry entity"),
    )
    for code, title in sections:
        rows = [f for f in findings if f["code"] == code]
        if not rows:
            continue
        out.append(f"\n## {title}\n")
        for f in rows:
            label = f.get("form") or f.get("subject")
            line = f"\n### {label}\n\n- {f['message']}\n"
            if f.get("collides_with"):
                line += "- Collides with: " + ", ".join(
                    f"{x['type']} {x['canonical']}" for x in f["collides_with"]
                ) + "\n"
            if f.get("ruling"):
                line += f"- Ruling: {f['ruling']}\n"
            if f.get("forms"):
                line += "- Forms: " + ", ".join(f["forms"]) + "\n"
            if f.get("locations"):
                line += "- Occurs at:\n" + "".join(f"  - {x}\n" for x in f["locations"])
            out.append(line)
    if len(out) == 2:
        out.append("\nNothing withheld and nothing to report.\n")
    return "".join(out)


def write_link_outputs(npc_range_dir: Path, dossiers, findings, digests: dict, counts: dict | None = None) -> dict:
    """Write ``evidence/<stem>.md``, ``link_report.{md,json}`` and ``link_manifest.json``.

    ``digests`` carries ``range`` (``{since, until}``), ``corpus_manifest_sha256``,
    ``registry_sha256``, ``canon_sha256`` and ``wordlist_sha256``. The manifest is
    written last, so its presence means the run finished. Returns the manifest.
    """
    d = Path(npc_range_dir)
    edir = d / EVIDENCE_DIR
    edir.mkdir(parents=True, exist_ok=True)
    keep = {f"{e.stem}.md" for e in dossiers}
    for old in edir.glob("*.md"):  # evidence is generated; a vanished NPC must not linger
        if old.name not in keep:
            old.unlink()
    shas: dict[str, str] = {}
    for e in dossiers:
        text = render_evidence(e)
        atomic_write_text(edir / f"{e.stem}.md", text)
        shas[e.stem] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if counts is None:
        counts = {
            "npcs": len(dossiers),
            "scenes": sum(e.header.n_scenes for e in dossiers),
            "moments": sum(e.header.n_moments for e in dossiers),
            "ambiguous": sum(1 for f in findings if f["code"] == schema.AMBIGUOUS_FORM),
            "generic_unruled": sum(1 for f in findings if f["code"] == schema.GENERIC_FORM and f["ruling"] is None),
            "generic_never": sum(1 for f in findings if f["code"] == schema.GENERIC_FORM and f["ruling"] == "never"),
        }
    rng = f"{digests['range']['since']}-{digests['range']['until']}"
    atomic_write_text(d / LINK_REPORT_MD, render_report_md(rng, counts, findings))
    atomic_write_text(
        d / LINK_REPORT_JSON,
        _dumps({"kind": "npc_link_report", "range": digests["range"], "counts": counts, "findings": findings}),
    )
    manifest = {
        "kind": "npc_link",
        "schema": 1,
        "range": digests["range"],
        "corpus_manifest_sha256": digests["corpus_manifest_sha256"],
        "registry_sha256": digests["registry_sha256"],
        "canon_sha256": digests["canon_sha256"],
        "wordlist_sha256": digests["wordlist_sha256"],
        # players.yaml decides each evidence file's `global`/`exclusion`, so later stages must see a change.
        "players_sha256": digests.get("players_sha256"),
        "evidence": shas,
    }
    atomic_write_text(d / LINK_MANIFEST, _dumps(manifest))
    return manifest


# ── Reading evidence back (shared by npc-draft and npc-compose) ─────────────


@dataclass(frozen=True)
class EvidenceFile:
    """One written evidence dossier, as later stages read it (frontmatter facts, not recomputed)."""

    stem: str
    subject: str
    global_: bool
    exclusion: str | None
    n_entries: int
    n_scenes: int
    n_moments: int
    first_seen: int
    last_seen: int
    chapters: tuple[int, ...]
    path: Path
    sha256: str
    header: str  # the frontmatter block, ``---`` fences included, exactly as written
    body: str  # everything after it, exactly as written


def split_frontmatter(text: str) -> tuple[str, str]:
    """``(header block, rest)``. The block keeps its fences and its final newline."""
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end < 0:
        return "", text
    cut = end + len("\n---\n")
    return text[:cut], text[cut:]


def read_evidence_files(npc_range_dir: Path) -> list[EvidenceFile]:
    out = []
    for p in sorted((Path(npc_range_dir) / EVIDENCE_DIR).glob("*.md")):
        raw = p.read_bytes()
        text = raw.decode("utf-8")
        header, body = split_frontmatter(text)
        fm = yaml.safe_load(header.split("---\n")[1]) if header else {}
        fm = fm if isinstance(fm, dict) else {}
        out.append(
            EvidenceFile(
                stem=p.stem,
                subject=str(fm.get("subject", "")),
                global_=bool(fm.get("global")),
                exclusion=fm.get("exclusion"),
                n_entries=int(fm.get("n_entries", 0)),
                n_scenes=int(fm.get("n_scenes", 0)),
                n_moments=int(fm.get("n_moments", 0)),
                first_seen=int(fm.get("first_seen", 0)),
                last_seen=int(fm.get("last_seen", 0)),
                chapters=tuple(int(c) for c in fm.get("chapters") or ()),
                path=p,
                sha256=hashlib.sha256(raw).hexdigest(),
                header=header,
                body=body,
            )
        )
    return out
