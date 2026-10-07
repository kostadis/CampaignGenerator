"""PROTOTYPE: annotate, don't rewrite. No model call.

The reader of world_state is Claude doing session prep (gm-assistant/skills/gm-session-prep), which treats the
docs as canon and is told not to invent any. A model rewrite can put an invented detail into canon; an
annotation cannot. So the fix-pass detectors run, and instead of a model rewriting a flagged line, code
appends the LATER EVIDENCE beneath it, verbatim from the checked notes, and the document's reading contract
tells the reader that the annotation supersedes the line.

    stale / cross-section / mentioned-stale -> "  - ⚠ later: <the later checked note, with its citation>"
    quote-not-verbatim / invalid-citation   -> "  - ⚠ unverified: <what failed>"
    player character in an NPC section      -> line removed (a rule, not a judgment)

Key NPCs (rendered from the published dossiers) gets each NPC's dossier path, and is never annotated: an NPC
is fixed in its dossier.

    python annotate.py --campaign DIR --run RUN_DIR [--doc world_state.dossiers.md] [--install]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chunked_state as cs  # noqa: E402
import fixpass as fp  # noqa: E402

HERE = Path(__file__).resolve().parent
LATER = "⚠ later:"
SINCE = "ℹ since:"
UNVERIFIED = "⚠ unverified:"

CONTRACT = """\
> **How to read this document.** It is the long-range memory of the campaign (ch {since}–{until}), generated
> from the session summaries and checked by code; the last two session summaries outrank it for recent events.
> - `{later}` under a line is newer information about the **same subject**: where the two conflict, the
>   later one wins; where they don't, both hold.
> - `{since_}` under a line is the later status of someone the line **mentions** (context, not a correction
>   of the line).
> - `{unverified}` marks a quotation or citation code could not confirm: treat it as a paraphrase.
> - `[ch NNN / target]` cites `{summaries}/NNN-*.md` — target is a scene id (`NNN.SS`), or that chapter's
>   `npcs`, `locations`, `items`, `spells`, `moment` (Memorable Moments) or `end` (Session-End State) section.
> - Key NPCs is rendered from the published dossiers: open `docs/npcs/<slug>.md` for the full dossier.
> - Every checked note, by subject: `docs/reference/` (factions, npcs, locations, items, threats).
>   Every event in order: `docs/{timeline}`.
> - Anything this document does not settle is a decision for the GM, not something to fill in.
"""


def note_text(note: str) -> str:
    """A checked note without its tag: '- [LOCATION] **X** — fact [cite]' -> '**X** — fact [cite]'."""
    if note.startswith("- [STATUS]"):
        parts = [p.strip() for p in note[len("- [STATUS]"):].split("|")]
        if len(parts) == 4:
            name, status, loc, rest = parts
            m = re.search(r"(\[ch .*\])\s*$", rest)
            disp = rest[: m.start()].strip() if m else rest
            cite = m.group(1) if m else ""
            bits = [f"**{name}** — {status}", loc if loc not in ("—", "") else None, disp if disp not in ("—", "") else None]
            return "; ".join(b for b in bits if b) + f" {cite}"
    return re.sub(r"^-\s*\[[A-Z]+\]\s*", "", note).strip()


def annotations_for(e: fp.Entry, fs: list[fp.Flag], ev: fp.Evidence) -> list[str]:
    out: list[str] = []
    cited = max(e.cited_chapters(), default=-1)
    for f in fs:
        if f.kind == "stale":
            later = [nt for ch, nt in ev.by_subject.get(e.subject.casefold(), []) if ch > cited]
            if later:
                out.append(f"{LATER} {note_text(later[-1])}")
        elif f.kind == "mentioned-stale":
            m = re.match(r"mentions (.+?) in a claim", f.detail)
            rows = [nt for _, nt in ev.by_subject.get(m.group(1).casefold(), []) if nt.startswith("- [STATUS]")] if m else []
            if rows:
                out.append(f"{SINCE} {note_text(rows[-1])}")
        elif f.kind == "cross-section":
            sec, _, line = f.detail.partition(" says more recently: ")
            out.append(f"{LATER} see {sec[3:]}: {line.lstrip('- ').strip()}")
        elif f.kind in ("quote-not-verbatim", "invalid-citation"):
            out.append(f"{UNVERIFIED} {f.detail}")
    return list(dict.fromkeys(out))  # one copy of each, first-seen order


def add_dossier_paths(lines: list[str], campaign: Path) -> int:
    """Append `docs/npcs/<file>` to each Key NPCs line whose name a published dossier carries."""
    pub = {}
    for p in (campaign / "docs" / "npcs").glob("*.md"):
        m = re.search(r"\| npc: (.+?) \|", p.read_text(encoding="utf-8").split("\n", 1)[0])
        if m:
            pub[m.group(1)] = f"docs/npcs/{p.name}"
    n, in_sec = 0, False
    for i, ln in enumerate(lines):
        if ln.startswith("## "):
            in_sec = ln.rstrip() == "## Key NPCs"
        elif in_sec and ln.startswith("- **"):
            name = ln[4:].split("**", 1)[0]
            if name in pub and pub[name] not in ln:
                lines[i] = f"{ln.rstrip()} → `{pub[name]}`"
                n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", type=Path, required=True)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--doc", default="world_state.dossiers.md")
    ap.add_argument("--since", type=int, default=2)
    ap.add_argument("--until", type=int, default=70)
    ap.add_argument("--chunk-chars", type=int, default=60000)
    ap.add_argument("--install", action="store_true",
                    help="copy world_state, reference/ and the timeline into the campaign's docs/ (backs up what it replaces)")
    args = ap.parse_args()

    fp.EXTRA_SKIP.add("## Key NPCs")  # sourced from dossiers: fixed there, never annotated here
    ev = fp.load_evidence(args.campaign, args.run, args.chunk_chars)
    lines = (args.run / args.doc).read_text(encoding="utf-8").splitlines()
    entries = fp.parse_entries(lines, ev)
    flags = fp.detect(entries, ev)
    flagged: dict[int, list[fp.Flag]] = {}
    for f in flags:
        flagged.setdefault(f.entry.line, []).append(f)

    out: list[str | None] = list(lines)
    log, n_ann, n_removed = [], 0, 0
    for ln_no, fs in sorted(flagged.items()):
        e = fs[0].entry
        if any(f.kind == "pc-in-npc-section" for f in fs):
            out[ln_no] = None
            n_removed += 1
            log.append(f"- L{ln_no + 1} removed (player character in an NPC section): {e.text[:120]}")
            continue
        ann = annotations_for(e, fs, ev)
        if ann:
            out[ln_no] = e.text + "".join(f"\n  - {a}" for a in ann)
            n_ann += len(ann)
            log.append(f"- L{ln_no + 1} {e.section[3:]}: {e.text[:100]}" + "".join(f"\n  - {a}" for a in ann))
    final = [ln for ln in out if ln is not None]
    final_lines = "\n".join(final).splitlines()
    n_paths = add_dossier_paths(final_lines, args.campaign)

    # Reading contract right after the provenance comment, before the first section.
    first = next(i for i, ln in enumerate(final_lines) if ln.startswith("## "))
    summaries = "docs/summaries"
    contract = CONTRACT.format(since=args.since, until=args.until, later=LATER, since_=SINCE, unverified=UNVERIFIED,
                               summaries=summaries, timeline=cs.TIMELINE_FILE.replace(".chunked", ""))
    final_lines[first:first] = contract.rstrip("\n").splitlines() + [""]
    stem = args.doc.removesuffix(".md")
    target = args.run / f"{stem}.annotated.md"
    cs.dump(target, "\n".join(final_lines) + "\n")
    cs.dump(args.run / f"{stem}.annotations.md",
            f"# Annotations\n\n{n_ann} annotations on {len(log) - n_removed} lines, {n_removed} lines removed, "
            f"{n_paths} dossier paths added.\n\n" + "\n".join(log) + "\n")
    print(f"wrote {target.name}: {n_ann} annotations, {n_removed} removed, {n_paths} dossier paths")

    if args.install:
        docs = args.campaign / "docs"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = HERE / "install_backup" / stamp
        backup.mkdir(parents=True)
        moved = []
        for rel in ("world_state.md", "reference", "canon_events_timeline.md"):
            if (docs / rel).exists():
                (shutil.copytree if (docs / rel).is_dir() else shutil.copy2)(docs / rel, backup / rel)
                moved.append(rel)
        shutil.copy2(target, docs / "world_state.md")
        if (docs / "reference").exists():
            shutil.rmtree(docs / "reference")
        shutil.copytree(args.run / "reference", docs / "reference")
        shutil.copy2(args.run / cs.TIMELINE_FILE, docs / "canon_events_timeline.md")
        (backup / "INSTALL.json").write_text(json.dumps({"campaign": str(args.campaign), "backed_up": moved,
                                                         "installed": ["world_state.md", "reference/", "canon_events_timeline.md"]},
                                                        indent=2))
        print(f"installed into {docs}; backed up {moved or 'nothing'} to {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
