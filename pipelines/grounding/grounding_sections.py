#!/usr/bin/env python3
"""Grounding docs as per-section projections of the state stores (#213 Phase 4).

Until now every grounding doc was one monolithic synthesis: a new chapter
meant regenerating the whole document (~full token cost), and review meant
diffing a 30-40KB file. This tool renders each doc as INDEPENDENT SECTIONS
over the state layer, assembles them into the usual ``*_draft.md``, and
skips any section whose inputs are byte-identical to what it was last
rendered from.

Section map (per the GM granularity ruling on the #213 anchor):

  world_state     npcs / factions / locations / world   (LLM synthesis over
                  type-scoped dossier subsets — the narrowness is the depth)
  campaign_state  recent_events (event spine window — deterministic)
                  party (copy of docs/party.md)
  planning        threads (thread registry render — deterministic)
                  notes (copy of docs/planning_notes.md, optional)

Incremental principle: updates flow THROUGH THE STATE LAYER (dossiers, the
event spine, the thread registry), never by patching prose. A section is
re-rendered when — and only when — its input store changed; the assembled
draft then reflects it. This answers the deferred ``--since`` question
without incremental-synthesis drift, and respects the
ChapterExtractConsolidation lesson: sections stay narrow.

Freshness is CONTENT-DERIVED, not mtime (#137): every section file carries
an ``inputs-sha`` stamp — the hash of the exact bytes it was rendered from —
and staleness is stamp-vs-recomputed-hash, so a no-op touch changes nothing
and a real edit is never missed.

The ``*_draft.md`` -> diff -> promote gate is unchanged and remains the
human checkpoint. Deterministic sections cost zero tokens; synthesis
sections only spend tokens when their dossier subset actually changed.

Usage (from inside a campaign dir):

  grounding_sections.py list  --doc world_state
  grounding_sections.py build --doc campaign_state             # deterministic, free
  grounding_sections.py build --doc world_state \\
      --backend dgx --endpoint http://... --model ...          # LLM sections
  grounding_sections.py build --doc world_state --force        # ignore stamps
"""
import argparse
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

SECTIONS_DIR = Path("docs/grounding_sections")
STAMP_RE = re.compile(r"<!-- section: (?P<name>[\w-]+) \| inputs-sha: (?P<sha>[0-9a-f]{16}) -->")


@dataclass
class Section:
    name: str
    mode: str                      # "synthesis" | "spine" | "threads" | "copy"
    dossier_prefixes: list[str] = field(default_factory=list)
    source: str | None = None
    optional: bool = False
    window: int | None = None


SPECS: dict[str, list[Section]] = {
    "world_state": [
        Section("npcs", "synthesis", dossier_prefixes=["npc_"]),
        Section("factions", "synthesis", dossier_prefixes=["faction_"]),
        Section("locations", "synthesis", dossier_prefixes=["location_"]),
        Section("world", "synthesis",
                dossier_prefixes=["object_", "monster_", "event_", "date_"]),
    ],
    "campaign_state": [
        Section("recent_events", "spine", window=4),
        Section("party", "copy", source="docs/party.md"),
    ],
    "planning": [
        Section("threads", "threads"),
        Section("notes", "copy", source="docs/planning_notes.md", optional=True),
    ],
}


# ── inputs + freshness ───────────────────────────────────────────────────

def section_inputs(sec: Section, args) -> list[Path]:
    if sec.mode == "synthesis":
        d = Path(args.dossiers_dir)
        return sorted(p for pref in sec.dossier_prefixes for p in d.glob(f"{pref}*.md"))
    if sec.mode == "spine":
        return [Path("docs/ensemble/events.jsonl")]
    if sec.mode == "threads":
        return [Path("docs/thread_registry.yaml")]
    if sec.mode == "copy":
        return [Path(sec.source)]
    raise ValueError(sec.mode)


def inputs_sha(paths: list[Path], extra: str = "") -> str:
    h = hashlib.sha256()
    h.update(extra.encode())
    for p in paths:
        h.update(str(p).encode())
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def current_stamp(section_file: Path) -> str | None:
    if not section_file.exists():
        return None
    m = STAMP_RE.search(section_file.read_text(encoding="utf-8"))
    return m.group("sha") if m else None


# ── renderers ────────────────────────────────────────────────────────────

def render_spine(sec: Section, args) -> str:
    from pipelines.grounding.event_spine import load_store, _row_order
    rows = load_store(Path("docs/ensemble/events.jsonl"))
    by_chap: dict[int, list[dict]] = {}
    for r in rows:
        by_chap.setdefault(r.get("chapter", 99), []).append(r)
    chapters = sorted(by_chap)
    window = args.window if args.window is not None else (sec.window or 0)
    if window and len(chapters) > window:
        chapters = chapters[-window:]
    lines = [f"## Recent Events (last {len(chapters)} chapters — event spine window)", ""]
    for c in chapters:
        lines.append(f"### Chapter {c}")
        lines.extend(f"- {r['event']}" for r in sorted(by_chap[c], key=_row_order))
        lines.append("")
    return "\n".join(lines)


def render_threads(sec: Section, args) -> str:
    from pipelines.grounding.thread_registry import (
        STATUSES, load_registry, DEFAULT_REGISTRY)
    data = load_registry(DEFAULT_REGISTRY)
    lines = ["## Threads (GM-ratified registry)", ""]
    for status in STATUSES:
        threads = [t for t in data["threads"] if t.get("status") == status]
        if not threads:
            continue
        lines.append(f"### {status.capitalize()}")
        for t in sorted(threads, key=lambda t: t.get("id", "")):
            span = f"opened ch{t.get('opened')}"
            if t.get("resolved"):
                span += f", closed ch{t['resolved']}"
            head = f"- **{t.get('title')}** ({span}"
            if t.get("tracker"):
                head += f"; tracker: {t['tracker']}"
            head += ")"
            lines.append(head)
            for row in t.get("log") or []:
                lines.append(f"  - [ch{row['chapter']:02d}] ({row['change']}) {row['summary']}")
        lines.append("")
    return "\n".join(lines)


def render_copy(sec: Section, args) -> str:
    src = Path(sec.source)
    return src.read_text(encoding="utf-8").strip()


def render_synthesis(sec: Section, args, inputs: list[Path], out_file: Path) -> None:
    """Type-scoped synthesise_world_state run — one narrow section per call."""
    cmd = [sys.executable,
           str(_REPO_ROOT / "pipelines/ensemble/synthesise_world_state.py"),
           "--dossiers", *(str(p) for p in inputs),
           "--output", str(out_file)]
    if args.registry:
        cmd += ["--registry", args.registry]
    if args.backend:
        cmd += ["--backend", args.backend]
    if args.endpoint:
        cmd += ["--endpoint", args.endpoint]
    if args.model:
        cmd += ["--model", args.model]
    if args.max_tokens:
        cmd += ["--max-tokens", str(args.max_tokens)]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(f"synthesis failed for section {sec.name!r} (exit {result.returncode})")


def build_section(sec: Section, args, section_file: Path, sha: str,
                  inputs: list[Path]) -> None:
    stamp = f"<!-- section: {sec.name} | inputs-sha: {sha} -->\n"
    if sec.mode == "synthesis":
        tmp = section_file.with_suffix(".synth.md")
        render_synthesis(sec, args, inputs, tmp)
        body = tmp.read_text(encoding="utf-8").strip()
        tmp.unlink(missing_ok=True)
    elif sec.mode == "spine":
        body = render_spine(sec, args)
    elif sec.mode == "threads":
        body = render_threads(sec, args)
    else:
        body = render_copy(sec, args)
    section_file.parent.mkdir(parents=True, exist_ok=True)
    section_file.write_text(stamp + body.strip() + "\n", encoding="utf-8")


# ── assembly ─────────────────────────────────────────────────────────────

def assemble(doc: str, sections: list[Section], out: Path) -> None:
    parts = [
        f"# {doc.replace('_', ' ').title()} (draft)",
        "",
        "_Assembled per-section from the state stores by `grounding_sections.py` "
        "(#213 Phase 4). Each section carries an `inputs-sha` stamp of the exact "
        "bytes it was rendered from; unchanged inputs mean the section was not "
        "re-rendered. Review per section, then promote via the usual "
        "draft -> diff -> copy gate._",
        "",
    ]
    for sec in sections:
        f = SECTIONS_DIR / doc / f"{sec.name}.md"
        if not f.exists():
            if sec.optional:
                continue
            raise SystemExit(f"error: missing section file {f} — build it first")
        parts.append(f.read_text(encoding="utf-8").strip())
        parts.append("")
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")


# ── cli ──────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "build"):
        p = sub.add_parser(name)
        p.add_argument("--doc", required=True, choices=sorted(SPECS))
        p.add_argument("--sections", default=None,
                       help="Comma-separated subset (default: all in the doc)")
        p.add_argument("--dossiers-dir", default="docs/ensemble/merged_dossiers",
                       help="Dossier store for synthesis sections")
        p.add_argument("--registry", default=None,
                       help="Entity registry path forwarded to synthesis")
        p.add_argument("--window", type=int, default=None,
                       help="Override the spine section's chapter window")
        if name == "build":
            p.add_argument("--force", action="store_true",
                           help="Re-render even when inputs-sha is unchanged")
            p.add_argument("--no-assemble", action="store_true")
            p.add_argument("--backend", default=None,
                           choices=["anthropic", "dgx", "openrouter", "claude-code"])
            p.add_argument("--endpoint", default=None)
            p.add_argument("--model", default=None)
            p.add_argument("--max-tokens", type=int, default=None)

    args = ap.parse_args()
    sections = SPECS[args.doc]
    if args.sections:
        wanted = set(args.sections.split(","))
        unknown = wanted - {s.name for s in sections}
        if unknown:
            ap.error(f"unknown section(s) for {args.doc}: {', '.join(sorted(unknown))}")
        sections = [s for s in sections if s.name in wanted]

    if args.cmd == "list":
        print(f"{'section':<16} {'mode':<10} {'state':<9} inputs")
        for sec in SPECS[args.doc]:
            f = SECTIONS_DIR / args.doc / f"{sec.name}.md"
            inputs = section_inputs(sec, args)
            missing = [p for p in inputs if not p.exists()]
            if missing and sec.optional:
                state = "optional"
            elif missing:
                state = "no-input"
            else:
                sha = inputs_sha(inputs)
                state = ("fresh" if current_stamp(f) == sha
                         else "stale" if f.exists() else "unbuilt")
            print(f"{sec.name:<16} {sec.mode:<10} {state:<9} "
                  f"{len(inputs)} file(s)")
        return

    rebuilt, skipped = [], []
    for sec in sections:
        f = SECTIONS_DIR / args.doc / f"{sec.name}.md"
        inputs = section_inputs(sec, args)
        if any(not p.exists() for p in inputs):
            if sec.optional:
                skipped.append(f"{sec.name} (optional, no input)")
                continue
            raise SystemExit(f"error: section {sec.name!r} input missing: "
                             f"{[str(p) for p in inputs if not p.exists()]}")
        sha = inputs_sha(inputs, extra=str(args.window or ""))
        if not args.force and current_stamp(f) == sha:
            skipped.append(f"{sec.name} (fresh)")
            continue
        build_section(sec, args, f, sha, inputs)
        rebuilt.append(sec.name)

    if not args.no_assemble:
        draft = Path(f"docs/{args.doc}_draft.md")
        assemble(args.doc, SPECS[args.doc], draft)
        print(f"assembled {draft}")
    print(f"rebuilt: {', '.join(rebuilt) or 'nothing'}")
    print(f"skipped: {', '.join(skipped) or 'nothing'}")


if __name__ == "__main__":
    main()
