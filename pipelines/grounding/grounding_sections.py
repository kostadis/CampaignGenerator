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
    # planning.md is the GM's threads-at-play cockpit — a creative input, not
    # a state dump (GM, 2026-07-31: campaign_state/world_state are "what's
    # going on", party.md is "what the party is up to", planning.md "is
    # supposed to help me see the threads that are at play"). It layers by
    # certainty: ratified canon, then the un-ruled harvest, then the
    # explicitly-non-canon idea surface, then faction outlook and GM notes.
    "planning": [
        Section("threads", "threads"),
        Section("emerging", "emerging",
                source="docs/ensemble/thread_proposals.yaml", optional=True),
        Section("npc_outlook", "npc_outlook", optional=True),
        Section("speculations", "copy",
                source="notes/thread_speculations.md", optional=True),
        Section("factions", "synthesis", dossier_prefixes=["faction_"],
                optional=True),
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
    if sec.mode in ("copy", "emerging"):
        return [Path(sec.source)]
    if sec.mode == "npc_outlook":
        return []          # per-NPC freshness handled in build_outlook_section
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


def render_emerging(sec: Section, args) -> str:
    """Digest of un-ruled thread proposals — the maybe-at-play layer.

    Recency-sorted (latest evidence chapter first). Matched-to-canon
    proposals lead, since they are ratifications waiting to happen. One
    evidence line each keeps 100+ proposals scannable.
    """
    import yaml
    data = yaml.safe_load(Path(sec.source).read_text(encoding="utf-8")) or {}
    pending = [p for p in data.get("proposals") or []
               if isinstance(p, dict) and p.get("status") == "pending"]
    ruled = len([p for p in data.get("proposals") or []
                 if isinstance(p, dict) and p.get("status") != "pending"])

    def latest(p):
        return max(p.get("chapters") or [0])

    matched = sorted((p for p in pending if p.get("matches")),
                     key=latest, reverse=True)
    fresh = sorted((p for p in pending if not p.get("matches")),
                   key=latest, reverse=True)
    lines = [
        "## Emerging Threads (harvested, not yet ruled on)",
        "",
        f"_{len(pending)} pending proposal(s) from the extraction corpus "
        f"({ruled} already ruled). These are threads the record *suggests* are "
        "at play — ratify, alias, or reject via thread-triage; nothing here is "
        "canon._",
        "",
    ]
    if matched:
        lines.append("### Continuations of ratified threads")
        for p in matched:
            lines.append(f"- **{p.get('title')}** -> `{p['matches']}` "
                         f"(ch {p.get('chapters')})")
            ev = (p.get("evidence") or [{}])[0]
            if ev.get("fact"):
                lines.append(f"  - ch{ev.get('chapter')}: {ev['fact']}")
        lines.append("")
    if fresh:
        lines.append("### New thread candidates (latest first)")
        for p in fresh:
            lines.append(f"- **{p.get('title')}** (ch {p.get('chapters')})")
            ev = (p.get("evidence") or [{}])[0]
            if ev.get("fact"):
                lines.append(f"  - ch{ev.get('chapter')}: {ev['fact']}")
    return "\n".join(lines)


def outlook_selection(args) -> list[str]:
    """Which NPCs rate an outlook block — the GM's salience decision.

    ``--npcs a,b`` wins; otherwise `npc_*` entries in
    narrative_importance.yaml's force_include (the existing GM curation
    knob). Never inferred from fact counts — salience stays with the GM.
    """
    if getattr(args, "npcs", None):
        return [s.strip() for s in args.npcs.split(",") if s.strip()]
    imp = Path("docs/ensemble/narrative_importance.yaml")
    if not imp.exists():
        return []
    import yaml
    data = yaml.safe_load(imp.read_text(encoding="utf-8")) or {}
    slugs = []
    for entry in data.get("force_include") or []:
        stem = Path(str(entry)).stem
        if stem.startswith("npc_"):
            slugs.append(stem[len("npc_"):])
    return slugs


def outlook_inputs(slug: str) -> list[Path]:
    """The per-NPC freshness basis: this NPC's ensemble dossier + registry.

    ENSEMBLE-PATH ONLY (GM, 2026-07-31: docs/npcs/ build-dossiers is the
    old path). The dossier is merged_dossiers/npc_<slug>.md — the
    type-merge-curated layer the ensemble planning synthesis itself
    consumes — falling back to state_dossiers/ where the type-merge has
    not run yet.

    The spine window is provided as prompt context but deliberately NOT
    hashed — a chapter in which the NPC did nothing must not re-render
    their block; anything they did do lands in their state dossier.
    """
    dossier = Path(f"docs/ensemble/merged_dossiers/npc_{slug}.md")
    if not dossier.exists():
        dossier = Path(f"docs/ensemble/state_dossiers/npc_{slug}.md")
    candidates = [dossier, Path("docs/thread_registry.yaml")]
    return [p for p in candidates if p.exists()]


def render_outlook_block(slug: str, inputs: list[Path], args) -> str:
    from campaignlib import client_from_args, load_agent_prompt, stream_api
    system = load_agent_prompt("planning_npc_outlook")
    parts = []
    for p in inputs:
        parts.append(f"=== {p} ===\n{p.read_text(encoding='utf-8')}")
    spine = Path(SECTIONS_DIR / "campaign_state" / "recent_events.md")
    if spine.exists():
        parts.append(f"=== recent events window ===\n"
                     f"{spine.read_text(encoding='utf-8')}")
    user = "\n\n".join(parts) + f"\n\nWrite the outlook block for: {slug}"
    client = client_from_args(args)
    return stream_api(client, system, user, args.model,
                      max_tokens=args.max_tokens or 2048).strip()


def build_outlook_section(sec: Section, args, section_file: Path) -> tuple[list[str], list[str]]:
    """Per-NPC block files, each with its own inputs-sha; combined section."""
    slugs = outlook_selection(args)
    block_dir = section_file.parent / "npc_outlook"
    rebuilt, skipped = [], []
    for slug in slugs:
        inputs = outlook_inputs(slug)
        if not any("dossiers" in str(p) for p in inputs):
            skipped.append(f"npc_outlook/{slug} (no ensemble dossier found)")
            continue
        block_file = block_dir / f"{slug}.md"
        sha = inputs_sha(inputs)
        if not args.force and current_stamp(block_file) == sha:
            skipped.append(f"npc_outlook/{slug} (fresh)")
            continue
        body = render_outlook_block(slug, inputs, args)
        block_file.parent.mkdir(parents=True, exist_ok=True)
        block_file.write_text(
            f"<!-- section: {slug} | inputs-sha: {sha} -->\n{body}\n",
            encoding="utf-8")
        rebuilt.append(f"npc_outlook/{slug}")
    # Combined section = concatenation of the per-NPC blocks (stamp = their shas)
    blocks = sorted(block_dir.glob("*.md")) if block_dir.exists() else []
    combined_sha = inputs_sha(blocks)
    parts = ["## NPC Outlook (antagonist play, per GM salience list)", ""]
    for b in blocks:
        text = STAMP_RE.sub("", b.read_text(encoding="utf-8")).strip()
        parts.append(text)
        parts.append("")
    section_file.parent.mkdir(parents=True, exist_ok=True)
    section_file.write_text(
        f"<!-- section: {sec.name} | inputs-sha: {combined_sha} -->\n"
        + "\n".join(parts).strip() + "\n", encoding="utf-8")
    return rebuilt, skipped


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
    elif sec.mode == "emerging":
        body = render_emerging(sec, args)
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
        p.add_argument("--npcs", default=None,
                       help="Comma-separated NPC slugs for the outlook section "
                            "(default: npc_* entries in narrative_importance "
                            "force_include)")
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
            if sec.mode == "npc_outlook":
                slugs = outlook_selection(args)
                print(f"{sec.name:<16} {sec.mode:<10} "
                      f"{'-':<9} {len(slugs)} npc(s) on the salience list")
                continue
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
        if sec.mode == "npc_outlook":
            slugs = outlook_selection(args)
            if not slugs:
                skipped.append(f"{sec.name} (no GM salience list)")
                continue
            if not args.backend:
                skipped.append(f"{sec.name} (synthesis — pass --backend to render)")
                continue
            rb, sk = build_outlook_section(sec, args, f)
            rebuilt += rb
            skipped += sk
            continue
        inputs = section_inputs(sec, args)
        if sec.mode == "synthesis" and not inputs:
            skipped.append(f"{sec.name} (no dossiers matched)")
            continue
        if sec.mode == "synthesis" and not args.backend:
            # An LLM section never spends tokens implicitly — a build without
            # --backend is a deterministic-only build by definition.
            skipped.append(f"{sec.name} (synthesis — pass --backend to render)")
            continue
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
