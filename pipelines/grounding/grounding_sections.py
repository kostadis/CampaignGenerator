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
import glob
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from campaignlib.constants import config_path
from campaignlib.projection_config import (
    PROJECTION_CONFIG_FILENAME,
    load_projection_config,
)

STAMP_RE = re.compile(r"<!-- section: (?P<name>[\w-]+) \| inputs-sha: (?P<sha>[0-9a-f]{16}) -->")


@dataclass
class Section:
    name: str
    mode: str                      # "synthesis" | "spine" | "threads" | "copy"
    dossier_prefixes: list[str] = field(default_factory=list)
    # A key into _SOURCE_FIELD (below), NOT a path. SPECS is a module-level
    # dict evaluated at import time, before any campaign's projections.yaml
    # is loaded — so a "copy"/"emerging" section's source cannot be an
    # already-resolved literal without reintroducing the exact defect this
    # feature closes (contracts/cli.md "SPECS `source=` paths"). The section
    # LIST staying in code is FR-014; only the concrete path each key names
    # comes from config — main() resolves every key in _SOURCE_FIELD into
    # args.source_paths once per run, and section_inputs/render_copy/
    # render_emerging look themselves up in it by this key.
    source: str | None = None
    optional: bool = False
    window: int | None = None


# Where each SPECS `source` key resolves in the loaded config — the group and
# field name on ProjectionConfig. `thread_proposals` lives under `stores`
# (it is a store this service's own `thread_registry propose` writes); the
# other three are `inputs` (produced elsewhere, declared here per FR-003).
_SOURCE_FIELD: dict[str, tuple[str, str]] = {
    "party": ("inputs", "party"),
    "planning_notes": ("inputs", "planning_notes"),
    "speculations": ("inputs", "speculations"),
    "thread_proposals": ("stores", "thread_proposals"),
}


def _source_path(sec: Section, cfg) -> Path:
    group, attr = _SOURCE_FIELD[sec.source]
    return Path(getattr(getattr(cfg, group), attr))


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
        # Module-progress audit: every tracking-list item judged against the
        # event spine (DONE/PARTIAL/NOT SEEN with chapter citations). LLM
        # proposes, the GM verifies line by line at the draft gate — the
        # lists carry no completion markers of their own (GM, 2026-07-31:
        # "campaign_state is supposed to tell me how many events from the
        # tracking lists are completed").
        Section("tracking", "tracking", optional=True),
        Section("party", "copy", source="party"),
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
                source="thread_proposals", optional=True),
        Section("npc_outlook", "npc_outlook", optional=True),
        Section("speculations", "copy",
                source="speculations", optional=True),
        Section("factions", "synthesis", dossier_prefixes=["faction_"],
                optional=True),
        Section("notes", "copy", source="planning_notes", optional=True),
    ],
}


# ── inputs + freshness ───────────────────────────────────────────────────

def section_inputs(sec: Section, args) -> list[Path]:
    if sec.mode == "synthesis":
        d = Path(args.dossiers_dir)
        return sorted(p for pref in sec.dossier_prefixes for p in d.glob(f"{pref}*.md"))
    if sec.mode == "spine":
        return [args.events_store]
    if sec.mode == "threads":
        return [args.thread_registry_path]
    if sec.mode in ("copy", "emerging"):
        return [args.source_paths[sec.source]]
    if sec.mode == "npc_outlook":
        return []          # per-NPC freshness handled in build_outlook_section
    if sec.mode == "tracking":
        lists = sorted(Path(p) for p in glob.glob(args.tracking_glob))
        # Same `args.events_store` main() resolved for the "spine" branch
        # above — the three-site split research D1 flags (this freshness
        # hash, render_spine's read, render_tracking's read) closes here:
        # all three now point at one resolved Path, never three literals
        # that could silently diverge (US3, FR-009).
        return lists + [args.events_store] if lists else []
    raise ValueError(sec.mode)


def resolve_dossiers_dir(cfg, explicit: str | None) -> tuple[str, str]:
    """Which dossier directory feeds the synthesis sections of this build
    (research D4, FR-024a).

    ``cfg.inputs.dossiers`` — the type-merge-curated set — is preferred;
    ``cfg.inputs.dossiers_fallback`` is used only when the curated
    directory has no dossier files at all. Today that fallback happens
    silently: one live campaign (Phandalin) has no ``merged_dossiers/``
    and runs entirely on the fallback with nothing on disk saying so. The
    caller reports the returned label (never absorbs it), which is the
    fix. An explicit ``--dossiers-dir`` always wins outright — the caller
    named the directory, so no fallback logic applies to it.
    """
    if explicit is not None:
        return explicit, "explicit"
    curated = cfg.inputs.dossiers
    if any(Path(curated).glob("*.md")):
        return curated, "curated"
    return cfg.inputs.dossiers_fallback, "fallback"


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
    rows = load_store(args.events_store)
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
    from pipelines.grounding.thread_registry import STATUSES, load_registry
    data = load_registry(args.thread_registry_path)
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
    src = args.source_paths[sec.source]
    return src.read_text(encoding="utf-8").strip()


def render_emerging(sec: Section, args) -> str:
    """Digest of un-ruled thread proposals — the maybe-at-play layer.

    Recency-sorted (latest evidence chapter first). Matched-to-canon
    proposals lead, since they are ratifications waiting to happen. One
    evidence line each keeps 100+ proposals scannable.
    """
    import yaml
    data = yaml.safe_load(args.source_paths[sec.source].read_text(encoding="utf-8")) or {}
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
    imp = args.narrative_importance_path
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


def outlook_inputs(slug: str, cfg) -> tuple[list[Path], str]:
    """The per-NPC freshness basis: this NPC's ensemble dossier + registry.

    ENSEMBLE-PATH ONLY (GM, 2026-07-31: docs/npcs/ build-dossiers is the
    old path). The dossier is ``inputs.dossiers``/npc_<slug>.md — the
    type-merge-curated layer the ensemble planning synthesis itself
    consumes — falling back to ``inputs.dossiers_fallback``/npc_<slug>.md
    where the type-merge has not run yet. Which one fed this NPC is
    returned alongside the paths rather than absorbed silently (research
    D4, FR-024a): this is a per-NPC choice, finer-grained than — and
    independent of — the whole-directory choice ``resolve_dossiers_dir``
    makes for the synthesis sections.

    The spine window is provided as prompt context but deliberately NOT
    hashed — a chapter in which the NPC did nothing must not re-render
    their block; anything they did do lands in their state dossier.
    """
    curated = Path(cfg.inputs.dossiers) / f"npc_{slug}.md"
    fallback = Path(cfg.inputs.dossiers_fallback) / f"npc_{slug}.md"
    if curated.exists():
        dossier, source = curated, "curated"
    elif fallback.exists():
        dossier, source = fallback, "fallback"
    else:
        dossier, source = None, "missing"
    candidates = [dossier, Path(cfg.stores.thread_registry)]
    return [p for p in candidates if p and p.exists()], source


def render_outlook_block(slug: str, inputs: list[Path], args, sections_dir: Path) -> str:
    from campaignlib import client_from_args, load_agent_prompt, stream_api
    system = load_agent_prompt("planning_npc_outlook")
    parts = []
    for p in inputs:
        parts.append(f"=== {p} ===\n{p.read_text(encoding='utf-8')}")
    spine = sections_dir / "campaign_state" / "recent_events.md"
    if spine.exists():
        parts.append(f"=== recent events window ===\n"
                     f"{spine.read_text(encoding='utf-8')}")
    user = "\n\n".join(parts) + f"\n\nWrite the outlook block for: {slug}"
    client = client_from_args(args)
    return stream_api(client, system, user, args.model,
                      max_tokens=args.max_tokens or 2048).strip()


def build_outlook_section(sec: Section, args, section_file: Path,
                          sections_dir: Path, cfg) -> tuple[list[str], list[str]]:
    """Per-NPC block files, each with its own inputs-sha; combined section."""
    slugs = outlook_selection(args)
    block_dir = section_file.parent / "npc_outlook"
    rebuilt, skipped = [], []
    for slug in slugs:
        inputs, dossier_source = outlook_inputs(slug, cfg)
        if dossier_source == "missing":
            skipped.append(f"npc_outlook/{slug} (no ensemble dossier found)")
            continue
        block_file = block_dir / f"{slug}.md"
        sha = inputs_sha(inputs)
        if not args.force and current_stamp(block_file) == sha:
            skipped.append(f"npc_outlook/{slug} (fresh, {dossier_source} dossier)")
            continue
        body = render_outlook_block(slug, inputs, args, sections_dir)
        block_file.parent.mkdir(parents=True, exist_ok=True)
        # The per-NPC provenance line (research D4, FR-024a): a curated vs
        # fallback dossier choice is now stated on disk, in the block that
        # was actually rendered from it — not only in stdout, which nobody
        # rereads after the run.
        block_file.write_text(
            f"<!-- section: {slug} | inputs-sha: {sha} -->\n"
            f"_Dossier: {dossier_source}._\n\n{body}\n",
            encoding="utf-8")
        rebuilt.append(f"npc_outlook/{slug} ({dossier_source})")
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


def render_tracking(sec: Section, args, inputs: list[Path]) -> str:
    """Module-progress audit: tracking lists judged against the event spine.

    LLM call — the completion judgment ("did 'Wyvern attack' happen?") is
    semantic matching the spine's phrasing will never satisfy verbatim. The
    GM verifies line by line at the draft gate; nothing downstream consumes
    the verdicts.
    """
    from campaignlib import client_from_args, load_agent_prompt, stream_api
    from pipelines.grounding.event_spine import load_store, _row_order

    lists = [p for p in inputs if p.suffix == ".txt"]
    parts = []
    for p in lists:
        parts.append(f"=== TRACKING LIST: {p.stem} ===\n"
                     f"{p.read_text(encoding='utf-8')}")
    rows = sorted(load_store(args.events_store), key=_row_order)
    spine = "\n".join(f"ch{r.get('chapter', '?')}: {r['event']}" for r in rows)
    parts.append(f"=== EVENT SPINE (what actually happened) ===\n{spine}")
    user = "\n\n".join(parts) + "\n\nAudit every list now."
    client = client_from_args(args)
    body = stream_api(client, load_agent_prompt("tracking_completion"), user,
                      args.model, max_tokens=args.max_tokens or 8000)
    return ("## Module Tracking (completion audit — LLM-proposed, verify "
            "line by line)\n\n" + body.strip())


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
        # Which dossier set fed this synthesis, stated in the rendered body
        # itself — not only in stdout — so the fallback is visible in the
        # draft the GM actually reviews (research D4, FR-024a).
        body = f"_Dossiers: {args.dossiers_source} ({args.dossiers_dir})._\n\n{body}"
    elif sec.mode == "spine":
        body = render_spine(sec, args)
    elif sec.mode == "threads":
        body = render_threads(sec, args)
    elif sec.mode == "emerging":
        body = render_emerging(sec, args)
    elif sec.mode == "tracking":
        body = render_tracking(sec, args, inputs)
    else:
        body = render_copy(sec, args)
    section_file.parent.mkdir(parents=True, exist_ok=True)
    section_file.write_text(stamp + body.strip() + "\n", encoding="utf-8")


# ── listing (`list` and `list --json` share this) ──────────────────────────

def section_row(sec: Section, args, cfg, sections_dir: Path, doc: str) -> dict:
    """One row of ``list``'s output — the single computation both the human
    table and ``--json`` (contracts/cli.md, T037) render from, so the two
    presentations cannot silently disagree about a section's state.

    ``state`` follows the enum ``{fresh, stale, unbuilt, no-input, optional,
    per-npc}``. ``per-npc`` is the outlook section: the human table prints
    ``-`` for it because freshness is tracked per NPC block, not per
    section (``build_outlook_section`` stamps each block file separately).

    ``provenance`` carries FR-024a's read-only attribution — which dossier
    set fed the section and which importance list applied — and is ``None``
    for a section that consumes neither (the deterministic spine/threads/
    copy/emerging/tracking modes).
    """
    f = sections_dir / doc / f"{sec.name}.md"
    if sec.mode == "npc_outlook":
        slugs = outlook_selection(args)
        inputs: list[Path] = []
        sources: list[str] = []
        for slug in slugs:
            paths, source = outlook_inputs(slug, cfg)
            inputs += paths
            if source in ("curated", "fallback"):
                sources.append(source)
        # Per-NPC dossier source can differ NPC to NPC; a mix is reported as
        # "fallback" (the more conservative of the two — at least one block
        # is running off the un-curated set) rather than inventing a third
        # provenance value the schema doesn't declare.
        dossier_set = ("fallback" if "fallback" in sources
                       else "curated" if sources else None)
        provenance = {
            "dossier_set": dossier_set,
            "importance_list": str(cfg.inputs.narrative_importance),
        }
        return {
            "name": sec.name, "mode": sec.mode, "state": "per-npc",
            "inputs": [str(p) for p in inputs], "provenance": provenance,
            "npc_count": len(slugs),
        }

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
    provenance = ({"dossier_set": args.dossiers_source, "importance_list": None}
                 if sec.mode == "synthesis" else None)
    return {
        "name": sec.name, "mode": sec.mode, "state": state,
        "inputs": [str(p) for p in inputs], "provenance": provenance,
    }


# ── assembly ─────────────────────────────────────────────────────────────

def _omission_reason(sec: Section, args) -> str:
    """Why ``sec``'s file doesn't exist yet, in the SAME vocabulary the
    build loop's own skip messages use (`"no GM salience list"`,
    `"no tracking lists"`, `"no dossiers matched"` — see main()'s per-
    section loop) — a single run must never explain the same fact two
    different ways, once in stdout and once in the draft. Distinguishes
    "genuinely no input" from "input exists, just not rendered this run"
    (e.g. an optional synthesis/tracking/npc_outlook section skipped only
    for want of --backend) — "optional, no input" would be flatly wrong for
    the latter.
    """
    if sec.mode == "npc_outlook":
        return "no GM salience list" if not outlook_selection(args) else "not yet built"
    if sec.mode == "tracking":
        return "no tracking lists" if not section_inputs(sec, args) else "not yet built"
    if sec.mode == "synthesis":
        if not section_inputs(sec, args):
            return (f"no dossiers matched under "
                    f"{args.dossiers_dir} ({args.dossiers_source})")
        return "not yet built"
    return "optional, no input"


def assemble(doc: str, sections: list[Section], out: Path, sections_dir: Path,
            args) -> tuple[bool, list[tuple[str, str]]]:
    """Assemble the doc's section files into its draft.

    Returns ``(wrote, omitted)``. ``omitted`` names every section left out of
    the assembled body, with its reason — an optional section with no input,
    or a synthesis section whose dossier set (curated or fallback) matched
    nothing (research D4). SC-007: a document must never read as silently
    empty or partial, and the artifact is what a GM diffs — possibly days
    later, without this run's stdout. So when ``omitted`` is non-empty the
    draft carries an explicit block naming it, near the top, before any
    rendered content (not just reported here for the caller to print).

    ``wrote`` is False when NOTHING rendered — every section in ``sections``
    was omitted. A zero-section document's only diff against a populated
    live doc reads as "delete everything", which is worse than no file at
    all (nothing to review vs. a false deletion), so in that case no draft
    is written; the caller reports why instead.
    """
    rendered: list[str] = []
    omitted: list[tuple[str, str]] = []
    for sec in sections:
        f = sections_dir / doc / f"{sec.name}.md"
        if f.exists():
            rendered.append(f.read_text(encoding="utf-8").strip())
            continue
        # Safe to degrade only for a truly optional section, or a
        # (possibly non-optional) synthesis section whose dossier set —
        # curated or fallback — matched nothing (research D4): there is
        # nothing to build FROM, as opposed to "forgot to build it", which
        # stays a hard failure for every other required section.
        safe_to_omit = sec.optional or (
            sec.mode == "synthesis" and not section_inputs(sec, args))
        if not safe_to_omit:
            raise SystemExit(f"error: missing section file {f} — build it first")
        omitted.append((sec.name, _omission_reason(sec, args)))

    if not rendered:
        return False, omitted

    parts = [f"# {doc.replace('_', ' ').title()} (draft)", ""]
    if omitted:
        # The visually-obvious incomplete-draft notice (SC-007): before any
        # rendered content, so a GM skimming a diff sees immediately that
        # the document is incomplete and why — not buried after prose a
        # skim would stop reading at.
        parts += [
            f"## INCOMPLETE DRAFT — {len(omitted)} of {len(sections)} section(s) omitted",
            "",
            "**This draft does not reflect the full document.** Diffing it "
            "against a populated live doc will make every omitted section "
            "below look deleted — it was never rendered here, not deleted. "
            "Do not promote without addressing:",
            "",
        ]
        parts += [f"- **{name}** — {reason}" for name, reason in omitted]
        parts.append("")
    parts += [
        "_Assembled per-section from the state stores by `grounding_sections.py` "
        "(#213 Phase 4). Each section carries an `inputs-sha` stamp of the exact "
        "bytes it was rendered from; unchanged inputs mean the section was not "
        "re-rendered. Review per section, then promote via the usual "
        "draft -> diff -> copy gate._",
        "",
    ]
    for body in rendered:
        parts.append(body)
        parts.append("")
    # own-subdirectory output (research D13) may not exist yet on a fresh
    # campaign — unlike the pre-move shared `docs/` path, nothing else is
    # guaranteed to have created it first.
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return True, omitted


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
        p.add_argument("--dossiers-dir", default=None,
                       help="Dossier store for synthesis sections (default: "
                            "config inputs.dossiers, falling back to "
                            "inputs.dossiers_fallback when the curated set "
                            "has no dossier files — reported as such)")
        p.add_argument("--registry", default=None,
                       help="Entity registry path forwarded to synthesis")
        p.add_argument("--window", type=int, default=None,
                       help="Override the spine section's chapter window")
        p.add_argument("--npcs", default=None,
                       help="Comma-separated NPC slugs for the outlook section "
                            "(default: npc_* entries in narrative_importance "
                            "force_include)")
        if name == "list":
            p.add_argument("--json", action="store_true",
                           help="Emit {doc, sections:[{name,mode,state,inputs,"
                                "provenance}]} JSON instead of the human table "
                                "(contracts/cli.md) — the shape the UI's "
                                "GET /api/projections/sections route consumes, "
                                "so no parsing of the human table happens "
                                "server-side (Constitution VI, FR-023)")
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
    # Loaded once — every path this run resolves comes from here, so the
    # sections directory, the draft path and the legacy-draft gate can never
    # disagree about what "output" means (contracts/cli.md's resolution
    # rule). Threaded through explicitly rather than rebound onto a global —
    # a hidden global reassignment is exactly the coupling this feature
    # exists to remove (#213 Phase 6 / 006-state-projection-service).
    cfg = load_projection_config(config_path(Path.cwd(), PROJECTION_CONFIG_FILENAME))
    sections_dir = Path(cfg.output.sections_dir)
    # Every store/input path a section may read is resolved from `cfg`
    # exactly once here and stashed on `args` — the same single-resolution
    # shape as dossiers_dir/dossiers_source below. `events_store` in
    # particular closes the three-site split research D1 flags:
    # section_inputs' freshness hash, render_spine's read and
    # render_tracking's read all resolve THIS Path, so they cannot disagree
    # about which file "the event spine" means (US3, FR-009). `source_paths`
    # resolves SPECS' symbolic `source` keys (see _SOURCE_FIELD above),
    # which is why SPECS itself can stay declarative Python (FR-014) while
    # the paths it names still come from config.
    args.events_store = Path(cfg.stores.events)
    args.thread_registry_path = Path(cfg.stores.thread_registry)
    args.tracking_glob = cfg.stores.tracking
    args.narrative_importance_path = Path(cfg.inputs.narrative_importance)
    args.source_paths = {
        key: Path(getattr(getattr(cfg, group), attr))
        for key, (group, attr) in _SOURCE_FIELD.items()
    }
    # Resolved once, same as sections_dir above — the curated-vs-fallback
    # choice must not diverge between what freshness is computed from and
    # what gets reported (US2's counterpart to US1's single output
    # resolution). Stashed on args because section_inputs/render_synthesis
    # already take args, not cfg, as their input-resolution seam.
    dossiers_dir, dossiers_source = resolve_dossiers_dir(cfg, args.dossiers_dir)
    args.dossiers_dir = dossiers_dir
    args.dossiers_source = dossiers_source
    uses_dossiers = any(s.mode == "synthesis" for s in SPECS[args.doc])
    sections = SPECS[args.doc]
    if args.sections:
        wanted = set(args.sections.split(","))
        unknown = wanted - {s.name for s in sections}
        if unknown:
            ap.error(f"unknown section(s) for {args.doc}: {', '.join(sorted(unknown))}")
        sections = [s for s in sections if s.name in wanted]

    if args.cmd == "list":
        # Unfiltered by --sections deliberately (unchanged from before this
        # refactor) — a staleness overview is for the whole document; the
        # --sections narrowing only ever applied to `build`.
        rows = [section_row(sec, args, cfg, sections_dir, args.doc)
                for sec in SPECS[args.doc]]

        if args.json:
            payload = {
                "doc": args.doc,
                "sections": [{k: v for k, v in row.items() if k != "npc_count"}
                            for row in rows],
            }
            print(json.dumps(payload))
            return

        # Silent fallback is the bug FR-024a fixes — say which dossier set
        # this run would use before showing per-section state, so a
        # campaign with no merged_dossiers/ (Phandalin, research D4) does
        # not look identical to one with a curated set.
        if uses_dossiers:
            print(f"dossiers: {dossiers_dir} ({dossiers_source})")
        print(f"{'section':<16} {'mode':<10} {'state':<9} inputs")
        for row in rows:
            if row["mode"] == "npc_outlook":
                print(f"{row['name']:<16} {row['mode']:<10} "
                      f"{'-':<9} {row['npc_count']} npc(s) on the salience list")
                continue
            print(f"{row['name']:<16} {row['mode']:<10} {row['state']:<9} "
                  f"{len(row['inputs'])} file(s)")
        return

    # Legacy-draft gate (FR-007b): the pre-move shared path is never moved or
    # deleted by this tool — a rendering service asked to produce a draft that
    # would collide with an un-attributed old one refuses instead of guessing
    # or clobbering. Checked before any section is (re)rendered, so a gated
    # run never spends tokens it then throws away, and unconditionally rather
    # than only when something changed — main() assembles on every build
    # unless --no-assemble, so a no-op build still writes the draft this
    # gates.
    if not args.no_assemble:
        legacy_path = Path(cfg.output.legacy_draft.format(doc=args.doc))
        if legacy_path.exists():
            draft_path = cfg.output.draft.format(doc=args.doc)
            raise SystemExit(
                f"error: a pre-move draft still exists at {legacy_path}\n"
                f"       This service now writes {draft_path}.\n"
                f"       Move or delete the old file to continue; nothing will be moved for you."
            )

    if uses_dossiers:
        print(f"dossiers: {dossiers_dir} ({dossiers_source})")

    rebuilt, skipped = [], []
    for sec in sections:
        f = sections_dir / args.doc / f"{sec.name}.md"
        if sec.mode == "npc_outlook":
            slugs = outlook_selection(args)
            if not slugs:
                skipped.append(f"{sec.name} (no GM salience list)")
                continue
            if not args.backend:
                skipped.append(f"{sec.name} (synthesis — pass --backend to render)")
                continue
            rb, sk = build_outlook_section(sec, args, f, sections_dir, cfg)
            rebuilt += rb
            skipped += sk
            continue
        inputs = section_inputs(sec, args)
        if sec.mode == "tracking" and not inputs:
            skipped.append(f"{sec.name} (no tracking lists)")
            continue
        if sec.mode == "tracking" and not args.backend:
            skipped.append(f"{sec.name} (synthesis — pass --backend to render)")
            continue
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
        draft = Path(cfg.output.draft.format(doc=args.doc))
        wrote, omitted = assemble(args.doc, SPECS[args.doc], draft, sections_dir, args)
        if wrote:
            print(f"assembled {draft}")
            if omitted:
                # The full reasons live IN the draft (SC-007) — this line is
                # a pointer to them, not a substitute; stdout scrollback is
                # exactly what a GM reviewing the draft days later won't have.
                print(f"  incomplete: {len(omitted)} section(s) omitted — "
                      f"see the draft's INCOMPLETE DRAFT block")
        else:
            # Every section omitted: writing an empty-but-titled draft would
            # diff as "delete everything" against a populated live doc, so
            # nothing is written at all — say so plainly, here, since
            # there's no draft to say it in.
            print(f"no draft written for {args.doc}: nothing to assemble "
                  f"— every section was omitted")
            for name, reason in omitted:
                print(f"  {name}: {reason}")
    print(f"rebuilt: {', '.join(rebuilt) or 'nothing'}")
    print(f"skipped: {', '.join(skipped) or 'nothing'}")


if __name__ == "__main__":
    main()
