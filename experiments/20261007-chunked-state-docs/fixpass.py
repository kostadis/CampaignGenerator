"""PROTOTYPE: check-then-fix pass over a drafted world_state.

    detect (code) + review (model, flags only) -> fix (model, one flagged entry at a time)
        -> verify (code) -> apply + log

The model never edits the document directly. A reviewer may only RAISE flags, each tied to a line; a fixer
sees one flagged entry plus that subject's checked notes and answers KEEP / DELETE / REPLACE; code accepts a
REPLACE only if every citation is real, every quotation verbatim, it names no entity absent from the entry and
the notes it was given, and it is not much longer than the original. Anything that fails keeps the original.

Usage:
    python fixpass.py --campaign DIR --run RUN_DIR [--doc world_state.budgeted.md] [--dry-run] [--no-review]
                      [--model ID --endpoint URL ...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from campaignlib import client_from_args  # noqa: E402
from pipelines.summary_native import npc_check  # noqa: E402
import chunked_state as cs  # noqa: E402

HERE = Path(__file__).resolve().parent
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
SKIP_SECTIONS = {"## Canon Events Timeline"}
EXTRA_SKIP: set[str] = set()  # --skip-section: sections sourced from a reviewed authority (e.g. dossiers)
MAX_GROWTH = 1.6  # a fix may not be more than this many times the original's length
MAX_REVIEW_FLAGS = 25


# ── Evidence ────────────────────────────────────────────────────────────────


@dataclass
class Evidence:
    chapters: list[cs.Chapter]
    allowed: dict[int, set[str]]
    hay: str
    forms: dict[str, str]  # casefolded name/alias -> canonical
    pcs: set[str]
    by_subject: dict[str, list[tuple[int, str]]] = field(default_factory=dict)  # canonical.casefold -> (chapter, note)
    timeline: list[str] = field(default_factory=list)
    entity_forms: list[tuple[str, list[str]]] = field(default_factory=list)

    def canon(self, name: str) -> str:
        name = name.strip().strip("*").strip()
        return self.forms.get(name.casefold(), name)

    def forms_of(self, canon: str) -> list[str]:
        out = [canon]
        out += [f for f, c in self.forms.items() if c == canon]
        return sorted({f for f in out if len(f) > 2}, key=len, reverse=True)


def load_evidence(campaign: Path, run: Path, chunk_chars: int) -> Evidence:
    """Subject-anchored notes come from the CACHED, code-checked map outputs (World notes by bold subject,
    NPC Status rows by name); the timeline file gives later mentions. Nothing here calls a model."""
    import yaml

    chapters = cs.load_chapters(campaign / "docs" / "summaries", 2, 70)
    chunks = cs.make_chunks(chapters, chunk_chars)
    audit = cs.load_audit(sorted((campaign / "docs" / "tracking").glob("tracking*.txt")))
    ids = {i for i, _, _ in audit}
    forms, pcs = cs.load_identity(campaign)
    ev = Evidence(chapters, {c.number: c.targets for c in chapters}, "\n".join(c.text for c in chapters), forms, pcs)
    for k, chunk in enumerate(chunks, 1):
        raw = (run / "map" / f"chunk{k:02d}.{cs.rng(chunk)}.out.md").read_text(encoding="utf-8")
        res = cs.check_map(raw, chunk, ids)
        for note in res.kept["## World"]:
            m = cs.SUBJECT_RE.match(note)
            if m:
                ev.by_subject.setdefault(ev.canon(m.group(1)).casefold(), []).append((cs.first_chapter(note), note))
        for row in res.npc_rows:
            note = f"- [STATUS] {row['name']} | {row['status']} | {row['location']} | {row['disposition']} {row['cite']}"
            ev.by_subject.setdefault(ev.canon(row["name"]).casefold(), []).append((cs.first_chapter(row["cite"]), note))
    for v in ev.by_subject.values():
        v.sort(key=lambda x: x[0])
    tl = run / cs.TIMELINE_FILE
    if tl.is_file():
        ev.timeline = [ln for ln in tl.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]
    reg = yaml.safe_load((campaign / "docs" / "entity_registry.yaml").read_text(encoding="utf-8"))
    ev.entity_forms = [(e["name"], [f for f in [e["name"], *(e.get("aliases") or [])] if len(str(f)) > 3])
                       for e in reg["entities"]]
    return ev


def entities_in(text: str, ev: Evidence) -> set[str]:
    return {name for name, fs in ev.entity_forms
            if any(re.search(rf"(?<!\w){re.escape(str(f))}(?!\w)", text) for f in fs)}


# ── The document ────────────────────────────────────────────────────────────


@dataclass
class Entry:
    line: int  # 0-based index into the document's lines
    section: str
    group: str  # the ### heading or standalone bold label above it, if any
    text: str
    subject: str  # canonical

    def cited_chapters(self) -> list[int]:
        return [c for _, c, _ in cs.cites(self.text) if c >= 0]


def parse_entries(lines: list[str], ev: Evidence) -> list[Entry]:
    out, section, group = [], "", ""
    for n, ln in enumerate(lines):
        if ln.startswith("## "):
            section, group = ln.rstrip(), ""
        elif ln.startswith("### "):
            group = ln[4:].strip()
        elif re.fullmatch(r"\*\*[^*]+\*\*\s*", ln.strip()):
            group = ln.strip().strip("*").strip()
        elif ln.startswith("- ") and section not in SKIP_SECTIONS and section not in EXTRA_SKIP:
            m = BOLD_RE.search(ln)
            subject = m.group(1) if m else group
            out.append(Entry(n, section, group, ln, ev.canon(subject)))
    return out


# ── Detection (code) ────────────────────────────────────────────────────────


@dataclass
class Flag:
    entry: Entry
    kind: str  # pc-in-npc-section | stale | cross-section | invalid-citation | quote-not-verbatim | reviewer
    detail: str
    context: list[str] = field(default_factory=list)


def detect(entries: list[Entry], ev: Evidence) -> list[Flag]:
    flags: list[Flag] = []
    for e in entries:
        if e.subject in ev.pcs and (e.section == "## Key NPCs" or e.group.casefold() == "companions"):
            flags.append(Flag(e, "pc-in-npc-section", f"{e.subject} is a player character (players.yaml)"))
        for b, c, t in cs.cites(e.text):
            if c < 0 or c not in ev.allowed or t not in ev.allowed[c]:
                flags.append(Flag(e, "invalid-citation", f"{b} is not a real target"))
        for span in npc_check.SPAN_RE.findall(e.text):
            inner = npc_check.strip_quote_marks(span)
            if len(inner) >= 4 and npc_check._contains(ev.hay, inner) is None:
                flags.append(Flag(e, "quote-not-verbatim", f"{span} is not in the summaries"))
        cited = e.cited_chapters()
        notes = ev.by_subject.get(e.subject.casefold(), [])
        if cited and notes and notes[-1][0] > max(cited):
            later = [nt for ch, nt in notes if ch > max(cited)]
            flags.append(Flag(e, "stale", f"cites up to ch {max(cited):03d}; notes about {e.subject} run to "
                                         f"ch {notes[-1][0]:03d} ({len(later)} later notes)"))
    by_subj: dict[str, list[Entry]] = {}
    for e in entries:
        if e.cited_chapters():
            by_subj.setdefault(e.subject.casefold(), []).append(e)
    for group in by_subj.values():
        for e in group:
            others = [o for o in group if o.section != e.section]
            if not others:
                continue
            newest = max(others, key=lambda o: max(o.cited_chapters()))
            if max(e.cited_chapters()) < max(newest.cited_chapters()):
                flags.append(Flag(e, "cross-section", f"{newest.section} says more recently: {newest.text}"))
    # An NPC MENTIONED in an entry (not its subject) whose status rows run past the entry's citations:
    # "Kalan fled [ch 065]" inside the Avowed's entry, with Kalan reinstated at ch 067.
    # Judged PER CLAIM: a claim is the text up to and including its own citation bracket, so a bullet whose
    # other claim cites a later chapter cannot hide a stale one.
    status = lambda nt: nt.split("|")[1].strip()  # noqa: E731
    for e in entries:
        seen: set[str] = set()
        for claim in claims_of(e.text):
            cited = [c for _, c, _ in cs.cites(claim) if c >= 0]
            if not cited:
                continue
            for name in sorted(entities_in(claim, ev) - {e.subject} - ev.pcs - seen):
                rows = [(ch, nt) for ch, nt in ev.by_subject.get(name.casefold(), []) if nt.startswith("- [STATUS]")]
                before = [nt for ch, nt in rows if ch <= max(cited)]
                later = [nt for ch, nt in rows if ch > max(cited)]
                # Only a CHANGE of status matters; "still alive later" tells the fixer nothing.
                # A change needs a status on both sides: "Alaundo — Dead" with no earlier row is not news.
                if later and before and status(later[-1]) != status(before[-1]):
                    seen.add(name)
                    flags.append(Flag(e, "mentioned-stale", f"mentions {name} in a claim citing ch {max(cited):03d}; "
                                                            f"{name}'s status changed later: {later[-1]}"))
    return flags


def claims_of(text: str) -> list[str]:
    """The text split after every citation bracket: each piece ends with the citation that backs it."""
    out, last = [], 0
    for m in cs.CITE_BRACKET_RE.finditer(text):
        out.append(text[last:m.end()])
        last = m.end()
    return out


# ── Review (model raises flags only) ────────────────────────────────────────


def review(client, lines: list[str], entries: list[Entry], npc_table: str, args, ev_allowed: dict) -> tuple[list[Flag], str]:
    by_line = {e.line: e for e in entries}
    numbered = "\n".join(f"L{n + 1}: {ln}" for n, ln in enumerate(lines))
    system = (HERE / "prompts" / "fix_review.system.md").read_text(encoding="utf-8")
    user = (f"DOCUMENT (numbered lines):\n\n{numbered}\n\nCODE-BUILT NPC STATUS TABLE (latest cited status per NPC):\n\n"
            f"{npc_table}\n\nList at most {MAX_REVIEW_FLAGS} suspected errors.\n")
    raw, _ = cs.call(client, system, user, args.max_tokens)
    flags, dropped = [], []
    for m in re.finditer(r"^L(\d+)\s*\|\s*(.+)$", raw, re.M):
        e = by_line.get(int(m.group(1)) - 1)
        text = m.group(2).strip()
        # A flag must point at an entry AND carry a real citation for its evidence; a self-retracting one
        # ("no error here") is not a flag.
        if e is None:
            dropped.append(f"not an entry line: {m.group(0)}")
        elif re.search(r"\bno (error|issue)\b|\bconsistent\b|\bskip\b", text, re.I):
            dropped.append(f"self-retracting: {m.group(0)}")
        elif not any(c >= 0 and t in ev_allowed.get(c, ()) for _, c, t in cs.cites(text)):
            dropped.append(f"no valid citation: {m.group(0)}")
        else:
            flags.append(Flag(e, "reviewer", text))
    return flags[:MAX_REVIEW_FLAGS], raw + "\n\n<!-- dropped by code -->\n" + "\n".join(dropped)


# ── Fix (model, one entry) + verify (code) ──────────────────────────────────


def fix_context(e: Entry, ev: Evidence, reasons: list["Flag"] | None = None) -> list[str]:
    notes = [nt for _, nt in ev.by_subject.get(e.subject.casefold(), [])][-15:]
    for f in reasons or []:  # a mentioned NPC's later status rows, for a mentioned-stale flag
        m = re.match(r"mentions (.+?);", f.detail) if f.kind == "mentioned-stale" else None
        if m:
            notes += [nt for _, nt in ev.by_subject.get(m.group(1).casefold(), [])][-5:]
    fs = ev.forms_of(e.subject)
    mentions = [t for t in ev.timeline if any(re.search(rf"(?<!\w){re.escape(f)}(?!\w)", t) for f in fs)][-10:]
    return notes + mentions


def fix_prompt(e: Entry, reasons: list[Flag], ctx: list[str], ev: Evidence) -> tuple[str, str]:
    system = (HERE / "prompts" / "fix.system.md").read_text(encoding="utf-8")
    user = (
        f"SECTION: {e.section}{(' / ' + e.group) if e.group else ''}\n"
        f"PLAYER CHARACTERS (never NPCs): {', '.join(sorted(ev.pcs))}\n\n"
        f"ENTRY:\n{e.text}\n\n"
        "WHY IT WAS FLAGGED:\n" + "\n".join(f"- {f.kind}: {f.detail}" for f in reasons) + "\n\n"
        f"CHECKED NOTES ABOUT {e.subject} (chapter order, latest last):\n" + ("\n".join(ctx) or "(none)") + "\n"
    )
    return system, user


def verify_fix(new: str, e: Entry, ctx: list[str], ev: Evidence) -> str | None:
    """A reason to reject the replacement, or None."""
    if "\n" in new.strip() or not new.startswith("- "):
        return "not a single bullet line"
    if len(new) > MAX_GROWTH * max(len(e.text), 200):
        return f"too long ({len(new)} chars vs {len(e.text)})"
    parts = cs.cites(new)
    if not parts:
        return "uncited"
    for b, c, t in parts:
        if c < 0 or c not in ev.allowed or t not in ev.allowed[c]:
            return f"invalid citation {b}"
    for span in npc_check.SPAN_RE.findall(new):
        inner = npc_check.strip_quote_marks(span)
        if len(inner) >= 4 and npc_check._contains(ev.hay, inner) is None:
            return f"quotation not verbatim {span}"
    new_names = entities_in(new, ev) - entities_in(e.text + "\n" + "\n".join(ctx), ev)
    if new_names:
        return f"names entities not in the entry or its notes: {sorted(new_names)}"
    return None


def parse_decision(raw: str) -> tuple[str, str]:
    s = raw.strip()
    first = s.splitlines()[0].strip() if s else ""
    if first.upper().startswith("KEEP"):
        return "KEEP", ""
    if first.upper().startswith("DELETE"):
        return "DELETE", ""
    if first.upper().startswith("REPLACE"):
        rest = s.split("\n", 1)[1].strip() if "\n" in s else first.split(":", 1)[-1].strip()
        line = next((ln for ln in rest.splitlines() if ln.startswith("- ")), rest.splitlines()[0] if rest else "")
        return "REPLACE", line.rstrip()
    if first.upper().startswith("MOVE"):
        return "MOVE", first.split(":", 1)[-1].strip().strip("*").strip() if ":" in first else ""
    return "UNPARSEABLE", s[:200]


def delete_allowed(e: Entry, fs: list[Flag]) -> str | None:
    """The code reason that licenses a DELETE, or None. A model's suspicion alone never deletes a line:
    it takes a code rule (player character, the subject covered more recently in another section) or a
    reviewer flag citing a chapter LATER than anything the entry cites."""
    kinds = {f.kind for f in fs}
    if "pc-in-npc-section" in kinds:
        return "player character in an NPC section"
    if "cross-section" in kinds:
        return "subject covered more recently in another section"
    # A reviewer flag never licenses a delete, even citing later evidence: in round 1 that removed a correct
    # line (Gyrgum's key) on a false "contradiction". Reviewer flags can lead only to a verified REPLACE/MOVE.
    return None


def apply_move(lines: list[str | None], e: Entry, label: str) -> str | None:
    """Move the entry under ``label`` within its own section: an existing ``### label`` / ``**label**`` group,
    else a new bold label appended to the section. Returns an error, or None."""
    if not label or len(label) > 60:
        return "no usable label"
    plain = label.strip("#").strip().casefold()
    # A section name or the entry's own group is "move it where it is": the fixer's way of saying KEEP.
    if (re.search(r"[#/<>]", label) or not re.search(r"[A-Za-z]{3}", label)
            or plain in {e.section[3:].casefold(), e.group.casefold()}):
        return f"not a different label within the section: {label!r}"
    start = next(i for i, ln in enumerate(lines) if ln is not None and ln.rstrip() == e.section)
    end = next((i for i in range(start + 1, len(lines)) if lines[i] is not None and lines[i].startswith("## ")), len(lines))
    is_label = lambda ln, lab: ln is not None and ln.strip().strip("#").strip().strip("*").strip().casefold() == lab.casefold()  # noqa: E731
    text = lines[e.line]
    lines[e.line] = None
    tgt = next((i for i in range(start + 1, end) if is_label(lines[i], label)), None)
    if tgt is not None:
        ins = tgt + 1
        while ins < end and lines[ins] is not None and (lines[ins].startswith("- ") or not lines[ins].strip()):
            if not lines[ins].strip() and ins + 1 < end and lines[ins + 1] is not None and not lines[ins + 1].startswith("- "):
                break
            ins += 1
        lines.insert(ins, text)
    else:
        foot = next((i for i in range(start + 1, end) if lines[i] is not None and lines[i].startswith("_Full notes")), end)
        lines[foot:foot] = [f"**{label}**", "", text, ""]
    return None


# ── Driver ──────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", type=Path, required=True)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--doc", default="world_state.budgeted.md")
    ap.add_argument("--chunk-chars", type=int, default=60000)
    ap.add_argument("--model", default="deepseek-ai/DeepSeek-V4-Flash-0731")
    ap.add_argument("--endpoint", action="append", default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-tokens", type=int, default=4000)
    ap.add_argument("--no-review", action="store_true", help="code detectors only; no model reviewer")
    ap.add_argument("--dry-run", action="store_true", help="detect (code only) and print flags; no model calls")
    ap.add_argument("--skip-section", action="append", default=[], metavar="HEADING",
                    help="a section sourced from a reviewed authority; fix it there, not here (e.g. 'Key NPCs')")
    args = ap.parse_args()
    EXTRA_SKIP.update(h if h.startswith("## ") else f"## {h}" for h in args.skip_section)
    cs.MODEL = args.model

    ev = load_evidence(args.campaign, args.run, args.chunk_chars)
    doc_path = args.run / args.doc
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    entries = parse_entries(lines, ev)
    flags = detect(entries, ev)
    print(f"{len(entries)} entries; code flags: " + json.dumps(_count(flags)))

    review_raw = ""
    if not args.dry_run:
        endpoints = list(dict.fromkeys(args.endpoint or [cs.ENDPOINT]))
        problem = cs.preflight(endpoints)
        if problem:
            print(f"Error: {problem}", file=sys.stderr)
            return 2
        clients = {ep: client_from_args(argparse.Namespace(backend="dgx", endpoint=ep, model=args.model)) for ep in endpoints}
        if not args.no_review:
            camp = (args.run / "campaign_state.chunked.md").read_text(encoding="utf-8")
            table = camp.split("## NPC Current States", 1)[1].split("\n## ", 1)[0].strip()
            rflags, review_raw = review(next(iter(clients.values())), lines, entries, table, args, ev.allowed)
            flags += rflags
            print(f"reviewer flags: {len(rflags)}")

    flagged: dict[int, list[Flag]] = {}
    for f in flags:
        flagged.setdefault(f.entry.line, []).append(f)
    if args.dry_run:
        for ln, fs in sorted(flagged.items()):
            print(f"\nL{ln + 1} {fs[0].entry.section} :: {fs[0].entry.text[:140]}")
            for f in fs:
                print(f"   - {f.kind}: {f.detail[:200]}")
        return 0

    by_line = {e.line: e for e in entries}
    jobs = []
    for ln, fs in sorted(flagged.items()):
        e = by_line[ln]
        if all(f.kind == "pc-in-npc-section" for f in fs):
            jobs.append((e, fs, None, None))  # code removes it; no model call
            continue
        ctx = fix_context(e, ev, fs)
        jobs.append((e, fs, ctx, fix_prompt(e, fs, ctx, ev)))

    def one(client, job):
        e, fs, ctx, prompt = job
        if prompt is None:
            return e, fs, ctx, "DELETE", "", "code: player character in an NPC section"
        raw, _ = cs.call(client, prompt[0], prompt[1], args.max_tokens)
        decision, new = parse_decision(raw)
        return e, fs, ctx, decision, new, raw

    new_lines = list(lines)
    log = ["# Corrections log", "", f"Document: `{args.doc}`. {len(entries)} entries, {len(flagged)} flagged.", ""]
    stats = {"KEEP": 0, "DELETE": 0, "REPLACE": 0, "MOVE": 0, "rejected": 0, "UNPARSEABLE": 0}
    moves: list = []
    results = sorted(cs.run_pool(jobs, one, clients, args.workers), key=lambda r: r[1][0].line)
    for _, _, (e, fs, ctx, decision, new, raw) in results:
        log += [f"## L{e.line + 1} — {e.section[3:]}{(' / ' + e.group) if e.group else ''}", "",
                *[f"- **{f.kind}**: {f.detail}" for f in fs], "", f"Before: {e.text}", ""]
        if decision == "REPLACE":
            why = verify_fix(new, e, ctx or [], ev)
            if why:
                stats["rejected"] += 1
                log += [f"Proposed: {new}", "", f"**Rejected by code** ({why}); original kept.", ""]
                continue
            new_lines[e.line] = new
            stats["REPLACE"] += 1
            log += [f"After: {new}", ""]
        elif decision == "DELETE":
            why = delete_allowed(e, fs)
            if why is None:
                stats["rejected"] += 1
                log += ["Proposed: DELETE", "", "**Rejected by code** (no code reason licenses a delete); original kept.", ""]
                continue
            new_lines[e.line] = None
            stats["DELETE"] += 1
            log += [f"**Deleted** ({why}).", ""]
        elif decision == "MOVE":
            moves.append((e, new))
            log += [f"**Move** under `{new}` (applied after all line edits).", ""]
        else:
            stats[decision if decision in stats else "UNPARSEABLE"] += 1
            log += [f"{decision}: original kept.", ""]
    # Moves last, bottom-up, so earlier line numbers stay valid while lines are inserted below them.
    for e, label in sorted(moves, key=lambda m: -m[0].line):
        err = apply_move(new_lines, e, label)
        stats["MOVE" if err is None else "rejected"] += 1
        if err:
            log += [f"L{e.line + 1}: move under `{label}` **rejected** ({err}); original kept in place.", ""]
    out = [ln for ln in new_lines if ln is not None]
    stem = args.doc.removesuffix(".md")
    cs.dump(args.run / f"{stem}.checked.md", "\n".join(out) + "\n")
    cs.dump(args.run / f"{stem}.corrections.md", "\n".join(log) + "\n")
    if review_raw:
        cs.dump(args.run / f"{stem}.review.raw.md", review_raw)
    print("decisions:", json.dumps(stats))
    print(f"wrote {stem}.checked.md and {stem}.corrections.md")
    return 0


def _count(flags: list[Flag]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in flags:
        out[f.kind] = out.get(f.kind, 0) + 1
    return out


if __name__ == "__main__":
    raise SystemExit(main())
