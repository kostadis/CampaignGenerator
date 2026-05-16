#!/usr/bin/env python3
"""Generate a planning.md document from NPC dossiers, threat arc scores, and session summaries.

Combines:
  - NPC dossier files — definitive source for each NPC's identity, motivation, and abilities
  - Threat arc score documents — mechanics tracking NPC/faction progress through the campaign
  - Session summaries (large file) — what has actually happened with each NPC/faction at the table
  - World context files (optional) — faction documents, location notes, etc.

Runs in two passes for the session summaries:
  1. Extract — chunks the summaries, pulls NPC/faction-relevant info from each chunk
  2. Synthesize — combines dossiers + arc scores + extractions into planning.md

Usage:
  python planning.py \\
      --npc grundar.md xalvosh.md jena_roscoe.md \\
      --arc-scores brundar_echo.md kraken_echoes.md kp_planar_distortion.md \\
      --summaries "Neverwinter Expansionism and the North.md" \\
      --output docs/planning.md

  # With optional world context
  python planning.py \\
      --npc grundar.md \\
      --arc-scores brundar_echo.md \\
      --summaries summaries.md \\
      --context factions.md locations.md \\
      --output docs/planning.md

  # Re-synthesize without re-extracting
  python planning.py \\
      --npc grundar.md xalvosh.md \\
      --arc-scores brundar_echo.md \\
      --synthesize-only \\
      --extract-dir docs/planning_extractions \\
      --output docs/planning.md

  # Build per-NPC dossier files from session summaries (run once, then edit)
  python planning.py \\
      --summaries "Neverwinter Expansionism and the North.md" \\
      --build-dossiers \\
      --dossier-dir docs/npcs/

  # Preferred: per-entity config so the synthesizer can't confuse which
  # arc score belongs to which NPC/faction (mirrors party.py --party-config).
  python planning.py \\
      --planning-config config/planning.yaml \\
      --summaries summaries.md \\
      --output docs/planning.md
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from campaignlib import (
    build_alias_normalizer,
    format_npc_roster,
    load_alias_map,
    make_client,
    normalize_npc_key as _normalize_npc_key,
    parse_dossier,
    run_extract_pipeline,
    stream_api,
)


# ── Planning config (per-NPC / per-faction arc-score binding) ────────────────
# Mirrors party.py's --party-config mechanism: lets the GM explicitly attach an
# arc-score file to a specific NPC or faction. The synthesizer renders each
# entry as a `## {name}` block nesting dossier (NPCs only) + arc-score together,
# so the LLM can't lose the dossier-↔-score binding the way it can with the
# legacy flat-group rendering.

@dataclass
class PlanningEntry:
    name: str
    dossier: Path | None = None       # NPC entries only; None for factions
    arc_score: Path | None = None
    trackless: bool = False           # True when arc_score is explicitly null


@dataclass
class PlanningConfig:
    npcs: list[PlanningEntry] = field(default_factory=list)
    factions: list[PlanningEntry] = field(default_factory=list)


def load_planning_config(path: Path) -> PlanningConfig:
    """Read a planning config YAML, validate referenced files, return PlanningConfig.

    YAML shape (mirrors party.py):

        npcs:
          - name: Adabra
            dossier: docs/npcs/adabra.md
            arc_score: docs/tracking/Adabra quest line.md
          - name: Lyra
            dossier: docs/npcs/lyra.md
            arc_score: null            # explicitly trackless

        factions:
          - name: Kraken Society
            arc_score: docs/tracking/echoes-score.md

    Distinctions for arc_score:
        key absent      → arc_score=None, trackless=False
        key present, null → arc_score=None, trackless=True
        key present, path → arc_score=Path, trackless=False

    NPC entries require `dossier`. Faction entries do not. All paths resolve
    against the config file's parent directory; missing files are a hard error.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        print(f"Error: invalid YAML in {path}: {e}", file=sys.stderr)
        sys.exit(1)

    base = path.parent

    def _resolve(rel: str, field_name: str, entry_name: str) -> Path:
        p = (base / rel).expanduser().resolve()
        if not p.exists():
            print(f"Error: planning config references missing file for "
                  f"{entry_name}.{field_name}: {p}", file=sys.stderr)
            sys.exit(1)
        return p

    def _parse_entry(entry: dict, kind: str) -> PlanningEntry:
        if not isinstance(entry, dict):
            print(f"Error: each {kind} entry in {path} must be a mapping",
                  file=sys.stderr)
            sys.exit(1)
        name = entry.get("name")
        if not name:
            print(f"Error: {kind} entry in {path} missing 'name': {entry}",
                  file=sys.stderr)
            sys.exit(1)

        dossier = None
        if kind == "npc":
            dossier_rel = entry.get("dossier")
            if not dossier_rel:
                print(f"Error: npc entry {name!r} in {path} missing 'dossier'",
                      file=sys.stderr)
                sys.exit(1)
            dossier = _resolve(dossier_rel, "dossier", name)
        elif "dossier" in entry and entry["dossier"]:
            # Allow faction entries to carry an optional faction-overview file
            # under the same key — keep it simple by resolving identically.
            dossier = _resolve(entry["dossier"], "dossier", name)

        if "arc_score" in entry:
            if entry["arc_score"] is None:
                arc_score = None
                trackless = True
            else:
                arc_score = _resolve(entry["arc_score"], "arc_score", name)
                trackless = False
        else:
            arc_score = None
            trackless = False

        return PlanningEntry(name=str(name), dossier=dossier,
                             arc_score=arc_score, trackless=trackless)

    npcs_raw = raw.get("npcs") or []
    factions_raw = raw.get("factions") or []
    if not isinstance(npcs_raw, list) or not isinstance(factions_raw, list):
        print(f"Error: {path} must define 'npcs' and/or 'factions' as lists",
              file=sys.stderr)
        sys.exit(1)
    if not npcs_raw and not factions_raw:
        print(f"Error: {path} must define a non-empty 'npcs' or 'factions' list",
              file=sys.stderr)
        sys.exit(1)

    return PlanningConfig(
        npcs=[_parse_entry(e, "npc") for e in npcs_raw],
        factions=[_parse_entry(e, "faction") for e in factions_raw],
    )


def _read_normalized(p: Path, normalize) -> str:
    body = p.read_text(encoding="utf-8").strip()
    return normalize(body) if normalize else body


def _render_planning_blocks(
    config: PlanningConfig,
    extra_npc_files: list[Path] | None = None,
    normalize=None,
) -> tuple[str, dict[str, list[str]]]:
    """Render a PlanningConfig as # NPC DOSSIERS + # FACTIONS sections, each
    with one `## {name}` subsection that nests the dossier (NPCs only) and
    the arc-score file together. Returns (rendered_text, canonical_to_aliases)
    so the caller can build the alias normalizer the same way `run_synthesize`
    does for the legacy path.

    `extra_npc_files` are additional dossier files (from --npc) that don't
    appear in the config — typically the majority of NPCs, who have no arc
    score and are pass-through. They render as `## {name}` blocks at the end
    of the # NPC DOSSIERS section with no arc-score nested. The script-level
    caller is responsible for rejecting overlap with config entries.

    A config entry with `arc_score: null` carries an INTENTIONALLY TRACKLESS
    marker so the LLM can't invent a score for it. An entry (or extra dossier)
    with no arc-score block at all is just a dossier — also no score, but the
    distinction is "not tracked at all" vs "deliberately untracked".
    """
    canonical_to_aliases: dict[str, list[str]] = {}

    def _entry_block(entry: PlanningEntry, dossier_label: str) -> str:
        parts = [f"## {entry.name}"]
        if entry.dossier is not None:
            name, aliases, _, body = parse_dossier(entry.dossier)
            canonical_to_aliases[name] = aliases
            parts.append(f"<!-- {dossier_label}: {entry.dossier.name} -->\n\n"
                         f"{body.strip()}")
        if entry.arc_score is not None:
            parts.append(f"<!-- Threat arc score: {entry.arc_score.name} -->\n\n"
                         f"{_read_normalized(entry.arc_score, normalize)}")
        elif entry.trackless:
            parts.append(
                "<!-- Arc score: INTENTIONALLY TRACKLESS -->\n\n"
                f"{entry.name} has no formal arc score mechanic. This is a "
                "deliberate design choice — do not invent an arc score for "
                "this entity and do not suggest creating one."
            )
        return "\n\n".join(parts)

    def _flat_dossier_block(f: Path) -> str:
        name, aliases, _, body = parse_dossier(f)
        canonical_to_aliases[name] = aliases
        return (f"## {name}\n\n"
                f"<!-- NPC dossier: {f.name} -->\n\n"
                f"{body.strip()}")

    npc_blocks: list[str] = [_entry_block(e, "NPC dossier") for e in config.npcs]
    if extra_npc_files:
        npc_blocks.extend(_flat_dossier_block(f) for f in extra_npc_files)

    sections: list[str] = []
    if npc_blocks:
        sections.append("# NPC DOSSIERS\n\n" + "\n\n---\n\n".join(npc_blocks))
    if config.factions:
        fac_blocks = [_entry_block(e, "Faction overview") for e in config.factions]
        sections.append("# FACTIONS\n\n" + "\n\n---\n\n".join(fac_blocks))

    return "\n\n===\n\n".join(sections), canonical_to_aliases


def _render_flat_section(heading: str, files: list[Path], label: str,
                         normalize=None) -> str:
    """Render extracts/context the same way run_synthesize does (flat group
    with per-file source comments) so the planning-config path produces an
    equivalent prompt structure for non-bound source material."""
    if not files:
        return ""
    blocks = [
        f"<!-- {label}: {f.name} -->\n\n{_read_normalized(f, normalize)}"
        for f in sorted(files)
    ]
    return f"# {heading}\n\n" + "\n\n---\n\n".join(blocks)


def write_dossier(
    path: Path,
    name: str,
    aliases: list[str],
    source_extracts: list[int],
    body: str,
) -> None:
    """Write dossier with frontmatter: name, aliases, source_extracts."""
    if aliases:
        alias_yaml = "aliases:\n" + "\n".join(f"  - {a}" for a in aliases) + "\n"
    else:
        alias_yaml = "aliases: []\n"
    nums = sorted(set(int(n) for n in source_extracts))
    extracts_yaml = "source_extracts: [" + ", ".join(str(n) for n in nums) + "]\n"
    fm = f"---\nname: {name}\n{alias_yaml}{extracts_yaml}---\n\n"
    path.write_text(fm + body.lstrip(), encoding="utf-8")

EXTRACT_SYSTEM = """\
You are extracting NPC and faction-relevant information from D&D session summary notes.

Focus ONLY on named NPCs, factions, and threat actors (not player characters). Extract:

## NPC Activity
For each named NPC: what they did, where they appeared, what they revealed, \
how they interacted with the party or other NPCs.

## Faction Movements
For each faction: actions taken, resources gained or lost, alliances shifted, \
plans advanced or disrupted.

## Threat Arc Events
Specific moments that would trigger arc score increases for any tracked threat \
(e.g. Brundar's Echo, Kraken Society Echoes, Planar Distortion). \
Name the score and describe the triggering event.

## Revealed Information
Secrets, plans, or intel about NPCs/factions that the party has uncovered.

## Current Whereabouts
Last known location or status of any named NPC or faction operative.

Rules:
- Only include information about NPCs and factions, not player characters.
- Be specific: name the NPC/faction and the session event.
- Preserve information about every named NPC and faction mentioned in this chunk. Do not make scope decisions about which NPCs are "important enough" — scope and consolidation happen in the next phase; your job here is to capture everything.
- Include deceased NPCs whose corpses or remains are in play, being examined, harvested, or discussed (e.g. "the party harvested the dragon's breath pouch"). Death does not disqualify an NPC from the notes.
- Include referenced-but-absent NPCs when they are meaningfully discussed — a mentor named in dialogue, a faction leader whose plans are debated, an NPC whose belongings are in play. Physical presence is not required; being talked about counts.
- If a section has nothing relevant, omit it entirely.
- Output only the structured notes under the headings above.
"""

SYNTHESIZE_SYSTEM = """\
You are creating a GM planning reference document for a D&D campaign.

You may receive two input shapes:

**A. Per-entity blocks** (preferred, when a planning config is supplied):
A `# NPC DOSSIERS` section with one `## {Name}` subsection per NPC, each
nesting that NPC's dossier and (optionally) their arc-score mechanic; and a
`# FACTIONS` section with one `## {Name}` subsection per tracked faction,
each nesting the faction's arc-score mechanic.

Most NPCs do NOT have a score. The three states for any `## {Name}` block are:
1. **Score bound** — block contains a `<!-- Threat arc score: ... -->` comment
   followed by mechanic text. This entity MUST appear as a row in the Threat
   Tracker. Use the file's track name as the score name.
2. **Intentionally trackless** — block contains the marker
   `<!-- Arc score: INTENTIONALLY TRACKLESS -->`. Never put this entity on the
   Threat Tracker. Do not invent a score. Do not suggest creating one.
3. **No score block at all** — just a dossier (this is the common case for
   most NPCs). Treat as ordinary; omit from the Threat Tracker. Do not invent
   a score. Do not flag the absence as a problem to solve.

**B. Flat groups** (legacy CLI flags):
Separate `# NPC DOSSIERS` and `# THREAT ARC SCORE MECHANICS` groups with no
explicit binding. Infer which arc score belongs to which NPC/faction by
name match.

In both shapes you will also receive:
- `# SESSION EXTRACTIONS` — what has actually happened at the table with each NPC/faction
- `# WORLD CONTEXT` (optional) — faction overviews, location notes

Produce a single authoritative planning.md with these sections:

## Threat Tracker
A compact table of all active threat arc scores:
| Score Name | NPC/Faction | Current Value | Next Threshold | What Triggers Next |

## NPC Dossiers
One subsection per NPC with:
- Current location and status
- Active plans and immediate goals
- What the party knows vs. what is hidden
- Key relationships and leverage points
- Current arc score value (if applicable) and what unlocks next

## Faction States
One subsection per faction with:
- Current goals and active operations
- Key members and their roles
- Relationship to the party and other factions
- Resources and vulnerabilities

## Active Plots
Threads currently in motion, ordered by urgency. For each:
- What is happening
- Timeline or trigger conditions
- How it intersects with the party

## DM Notes
Foreshadowing opportunities, convergence points between plot threads, \
and NPCs whose paths are about to cross.

Rules:
- NPC dossiers take precedence over session notes for definitive facts.
- Session notes take precedence for current emotional state and recent actions.
- Arc score documents define the mechanics; session notes track the current value.
- Be concise. This is a quick-reference document used during live play.
- Do not invent anything not present in the source material.
- Output only the planning document. No preamble or commentary.
"""


BUILD_EXTRACT_SYSTEM = """\
You are extracting information about named NPCs from D&D session summary notes.

For each named NPC that appears in this text, create a section using their full name as the heading. Include everything relevant:
- What they did, said, or ordered
- Where they appeared and under what circumstances
- Motivations, plans, or secrets revealed
- Their relationships with the party and other characters
- Any arc score events (e.g. Brundar's Echo increasing, Kraken Society Echoes)
- Current status or last known whereabouts

Rules:
- Use ## Full NPC Name as the heading for each NPC (one ## per NPC, no sub-headings)
- Every named NPC that appears gets their own section. Do NOT fold one NPC's activity into another NPC's section — even if they interact, even if one is dead, even if one is minor. Scope/consolidation decisions happen in the next phase; your job is to preserve information per-NPC.
- Include deceased NPCs if they are present in the events (e.g. a corpse being examined, a body being harvested, a named casualty). Death does not disqualify an NPC from having their own section.
- Include referenced-but-absent NPCs if they are meaningfully discussed — e.g. a PC's mentor mentioned in dialogue, a faction leader whose plans are being debated, an NPC whose belongings are in play. Physical presence is not required; being talked about counts. If you include such an NPC, open their section by noting they do not appear in this chunk, then record what was said about them.
- Only include named NPCs — not player characters, not generic "bandits" or "guards"
- Be specific: name the session event, not a generic description
- If an NPC is not mentioned, referenced, or discussed anywhere in this chunk, omit them entirely
- Output only the NPC sections. No preamble, no summary.
"""

BUILD_SYNTHESIZE_SYSTEM = """\
You are writing an NPC dossier for a D&D campaign GM.

You will receive raw session notes about a single NPC, extracted from multiple sessions. \
Synthesize these into a clean, organized dossier for use during session prep.

Structure:

# [NPC Full Name]

## Identity
- Role / title / faction affiliation
- First appearance and how the party met them

## Personality & Motivations
- Core goals and drives
- Personality traits demonstrated through play (2–4 sentences)

## History with the Party
Chronological summary of significant interactions and events at the table.

## Current Status
- Last known location and what they were doing
- Active plans or operations in progress
- What the party knows vs. what remains hidden

## Relationships
Key relationships with other NPCs, factions, and the party members individually.

## Arc Score Events
If applicable: events that triggered arc score changes, and the direction (increase/decrease).

Rules:
- Only include information present in the source notes — do not invent anything.
- Be concise. This document is read quickly during live play.
- Output only the dossier. No preamble or commentary.
"""




def run_build_dossiers(
    client, summaries_text: str, chunk_size: int, model: str, extract_dir: Path, dossier_dir: Path,
    split_chapters: str | None = None,
    since: int | None = None,
    extract_only: bool = False,
) -> list[Path]:
    """Two-phase dossier builder: extract per-chunk → aggregate by NPC → synthesize each dossier.

    since — if set, Phase 2 aggregation and Phase 3 synthesis only consider extracts with
            number >= since. Phase 1 extraction is unaffected (cache already handles it).
            Use this after a new session: --since <new_extract_num> skips re-processing
            historical chunks that have already been rolled into dossiers.

    extract_only — if True, stop after Phase 1 so the user can review per-chunk
                   NPC extractions before Phase 2 aggregation and Phase 3
                   per-NPC LLM synthesis proceed.
    """

    # ── Phase 1: extract NPC mentions from each chunk ─────────────────────────
    # Seed the extract prompt with the existing canonical roster so re-builds
    # don't fragment NPCs the human has already merged (e.g. Tolubb vs
    # "Captain Tolubb"). No-op for a fresh campaign with an empty dossier dir.
    existing_roster = format_npc_roster(load_alias_map(dossier_dir))
    if existing_roster:
        print(f"  Seeding extract prompt with {existing_roster.count(chr(10))} known NPC(s).")
    run_extract_pipeline(
        client, summaries_text,
        extract_system=BUILD_EXTRACT_SYSTEM,
        model=model,
        extract_dir=extract_dir,
        chunk_size=chunk_size,
        split_chapters=split_chapters,
        split_label="session",
        filename_template="dossier_extract_{i:03d}.md",
        system_suffix=existing_roster,
    )

    if extract_only:
        print(f"\n[Extract-only mode — stopping before Phase 2 aggregation and Phase 3 synthesis]")
        print(f"Review per-chunk NPC extractions in: {extract_dir}")
        print(f"When ready, re-run the same command without --extract-only to continue.")
        return []

    # ── Load existing dossiers to resolve merged aliases ─────────────────────
    # After /dossier-merge, name variants live in the canonical file's `aliases:`
    # frontmatter. Without this, a rerun would re-create the merged-away duplicates.
    # Keys are normalized (punctuation stripped, whitespace collapsed) so that
    # LLM-emitted variants like "Harbin (Townmaster)" still match an alias
    # recorded as "Harbin Townmaster".
    dossier_dir.mkdir(parents=True, exist_ok=True)
    existing_dossiers: dict[str, Path] = {}
    alias_to_canonical: dict[str, str] = {}
    # Canonical-name → set of extract_nums already absorbed (per `source_extracts:`
    # frontmatter). Used to skip writing *.new_notes.NNN.md sidecars for extracts
    # that are already in the canonical dossier — prevents sidecar accumulation on
    # deterministic re-runs and after sidecar merges.
    canonical_source_extracts: dict[str, set[int]] = {}
    for dossier_file in dossier_dir.glob("*.md"):
        name, aliases, source_extracts, _ = parse_dossier(dossier_file)
        existing_dossiers[_normalize_npc_key(name)] = dossier_file
        alias_to_canonical[_normalize_npc_key(name)] = name
        for alias in aliases:
            alias_to_canonical[_normalize_npc_key(alias)] = name
        canonical_source_extracts[name] = set(source_extracts)

    # ── Phase 2: aggregate sections by NPC name (folding aliases) ────────────
    # Track source extract per body so we can write per-extract new_notes
    # files for NPCs whose canonical dossier already exists.
    npc_by_extract: dict[str, dict[int, list[str]]] = {}
    alias_resolutions: dict[str, str] = {}
    if since is not None:
        print(f"\n  [--since {since}] aggregating only extracts with number >= {since}")
    for extract_file in sorted(extract_dir.glob("dossier_extract_*.md")):
        m = re.search(r"dossier_extract_(\d+)\.md", extract_file.name)
        extract_num = int(m.group(1)) if m else 0
        if since is not None and extract_num < since:
            continue
        content = extract_file.read_text(encoding="utf-8")
        # split on lines that start with "## "
        sections = re.split(r"(?m)^## ", content)
        for section in sections:
            section = section.strip()
            if not section:
                continue
            lines = section.splitlines()
            npc_name = lines[0].strip()
            body = "\n".join(lines[1:]).strip()
            if not (npc_name and body):
                continue
            canonical = alias_to_canonical.get(_normalize_npc_key(npc_name), npc_name)
            if canonical != npc_name:
                alias_resolutions[npc_name] = canonical
            npc_by_extract.setdefault(canonical, {}).setdefault(extract_num, []).append(body)

    npc_excerpts: dict[str, list[str]] = {
        canonical: [body for bodies in by_extract.values() for body in bodies]
        for canonical, by_extract in npc_by_extract.items()
    }

    if not npc_excerpts:
        print("  No NPC sections found in extractions.", file=sys.stderr)
        return []

    if alias_resolutions:
        print(f"\n  Resolved {len(alias_resolutions)} variant(s) to existing dossiers:")
        for variant, canonical in sorted(alias_resolutions.items()):
            print(f"    {variant!r} → {canonical!r}")

    print(f"\n  Found {len(npc_excerpts)} NPC(s): {', '.join(sorted(npc_excerpts))}\n")

    # ── Phase 3: synthesize each NPC into a dossier file ─────────────────────
    saved = []

    for npc_name in sorted(npc_excerpts):
        # If the canonical dossier already exists, don't rewrite it — instead
        # drop per-extract new_notes files beside it for the user to manually
        # merge. Named after the existing dossier's stem so aliased files land
        # next to their canonical owner.
        if _normalize_npc_key(npc_name) in existing_dossiers:
            existing_file = existing_dossiers[_normalize_npc_key(npc_name)]
            existing_canonical = alias_to_canonical[_normalize_npc_key(npc_name)]
            absorbed = canonical_source_extracts.get(existing_canonical, set())
            stem = existing_file.stem
            written = []
            skipped_absorbed = 0
            for extract_num, bodies in sorted(npc_by_extract[npc_name].items()):
                if extract_num in absorbed:
                    skipped_absorbed += 1
                    continue
                new_note_file = dossier_dir / f"{stem}.new_notes.{extract_num:03d}.md"
                if new_note_file.exists():
                    continue
                header = f"# New notes for {npc_name} (from dossier_extract_{extract_num:03d}.md)\n\n"
                new_note_file.write_text(header + "\n\n---\n\n".join(bodies) + "\n", encoding="utf-8")
                written.append(new_note_file.name)
            if written:
                print(f"  Dossier exists ({existing_file.name}): wrote {len(written)} new_notes file(s) for {npc_name}")
                for name in written:
                    print(f"    → {name}")
            elif skipped_absorbed:
                print(f"  Skipping (dossier exists: {existing_file.name}): {npc_name} — {skipped_absorbed} extract(s) already absorbed")
            else:
                print(f"  Skipping (dossier exists: {existing_file.name}): {npc_name}")
            saved.append(existing_file)
            continue

        slug = re.sub(r"[^a-z0-9]+", "_", npc_name.lower()).strip("_")
        out_file = dossier_dir / f"{slug}.md"
        if out_file.exists():
            # Slug collides with an existing dossier whose canonical name didn't
            # match this extraction's heading (punctuation drift, etc). Don't
            # overwrite — drop new_notes sidecars so content isn't lost.
            _, _, collided_source_extracts, _ = parse_dossier(out_file)
            absorbed = set(collided_source_extracts)
            written = []
            skipped_absorbed = 0
            for extract_num, bodies in sorted(npc_by_extract[npc_name].items()):
                if extract_num in absorbed:
                    skipped_absorbed += 1
                    continue
                new_note_file = dossier_dir / f"{slug}.new_notes.{extract_num:03d}.md"
                if new_note_file.exists():
                    continue
                header = f"# New notes for {npc_name} (from dossier_extract_{extract_num:03d}.md)\n\n"
                new_note_file.write_text(header + "\n\n---\n\n".join(bodies) + "\n", encoding="utf-8")
                written.append(new_note_file.name)
            if written:
                print(f"  Slug collision ({out_file.name}): wrote {len(written)} new_notes file(s) for {npc_name}")
                for name in written:
                    print(f"    → {name}")
            elif skipped_absorbed:
                print(f"  Skipping (slug collision: {out_file.name}): {npc_name} — {skipped_absorbed} extract(s) already absorbed")
            else:
                print(f"  Skipping (slug collision, sidecars exist: {out_file.name}): {npc_name}")
            saved.append(out_file)
            continue

        excerpts = npc_excerpts[npc_name]
        raw_notes = (
            f"# Raw session notes: {npc_name}\n\n"
            + "\n\n---\n\n".join(excerpts)
        )
        print(f"  Synthesizing: {npc_name} ({len(excerpts)} excerpt(s), {len(raw_notes):,} chars)...")
        print("  " + "─" * 56)
        dossier = stream_api(client, BUILD_SYNTHESIZE_SYSTEM, raw_notes, model)
        print("  " + "─" * 56)
        contributing_extracts = sorted(npc_by_extract[npc_name].keys())
        write_dossier(out_file, npc_name, [], contributing_extracts, dossier.strip() + "\n")
        saved.append(out_file)
        print(f"  Saved: {out_file.name}\n")

    return saved


def run_synthesize(
    client,
    npc_files: list[Path],
    arc_score_files: list[Path],
    extract_files: list[Path],
    context_files: list[Path],
    model: str,
) -> str:
    parts = []

    canonical_to_aliases: dict[str, list[str]] = {}
    dossier_blocks: list[str] = []
    for f in npc_files:
        name, aliases, _, body = parse_dossier(f)
        canonical_to_aliases[name] = aliases
        dossier_blocks.append(f"<!-- NPC dossier: {f.name} -->\n\n{body.strip()}")

    normalize, resolution_entries = build_alias_normalizer(canonical_to_aliases)

    if dossier_blocks:
        parts.append("# NPC DOSSIERS\n\n" + "\n\n---\n\n".join(dossier_blocks))

    if arc_score_files:
        arc_scores = "\n\n---\n\n".join(
            f"<!-- Threat arc score: {f.name} -->\n\n{normalize(f.read_text(encoding='utf-8').strip())}"
            for f in arc_score_files
        )
        parts.append(f"# THREAT ARC SCORE MECHANICS\n\n{arc_scores}")

    if extract_files:
        extractions = "\n\n---\n\n".join(
            f"<!-- Session extract: {f.name} -->\n\n{normalize(f.read_text(encoding='utf-8').strip())}"
            for f in sorted(extract_files)
        )
        parts.append(f"# SESSION EXTRACTIONS\n\n{extractions}")

    if context_files:
        context = "\n\n---\n\n".join(
            f"<!-- World context: {f.name} -->\n\n{normalize(f.read_text(encoding='utf-8').strip())}"
            for f in context_files
        )
        parts.append(f"# WORLD CONTEXT\n\n{context}")

    user_prompt = "\n\n===\n\n".join(parts)
    if not user_prompt.strip():
        print("Error: no source material to synthesize — provide --npc, --arc-scores, or --summaries.",
              file=sys.stderr)
        raise SystemExit(1)

    system_prompt = SYNTHESIZE_SYSTEM
    if resolution_entries:
        lines = [f"- **{name}** (also: {', '.join(aliases)})"
                 for name, aliases in resolution_entries]
        resolution_block = (
            "# ENTITY RESOLUTION\n\n"
            "The source text below has been pre-normalized: variant names have been "
            "replaced with the canonical NPC name. If any variant still appears, treat "
            "it as referring to the canonical NPC listed here.\n\n"
            + "\n".join(lines) + "\n\n"
        )
        system_prompt = resolution_block + SYNTHESIZE_SYSTEM
        print(f"  Alias map: {len(resolution_entries)} NPC(s) with variants.")

    print(f"  Synthesizing ({len(user_prompt):,} chars total)...")
    print("  " + "─" * 56)
    result = stream_api(client, system_prompt, user_prompt, model)
    print("  " + "─" * 56)
    return result


def _check_npc_overlap(config: PlanningConfig, extra_npc_files: list[Path]) -> None:
    """Reject if any --npc dossier's canonical name matches a config NPC entry.
    Otherwise the same NPC would render twice (once with arc-score nested,
    once without)."""
    if not extra_npc_files:
        return
    config_names = {_normalize_npc_key(e.name) for e in config.npcs}
    # Also include each config dossier's frontmatter name, since the YAML
    # `name:` may differ from the dossier's own canonical name.
    for e in config.npcs:
        if e.dossier is not None:
            cname, aliases, _, _ = parse_dossier(e.dossier)
            config_names.add(_normalize_npc_key(cname))
            for a in aliases:
                config_names.add(_normalize_npc_key(a))
    overlaps = []
    for f in extra_npc_files:
        cname, _aliases, _, _ = parse_dossier(f)
        if _normalize_npc_key(cname) in config_names:
            overlaps.append((f.name, cname))
    if overlaps:
        lines = "\n".join(f"  - {fname} (canonical: {cname})" for fname, cname in overlaps)
        print(f"Error: --npc dossier(s) overlap with --planning-config entries; "
              f"each NPC must appear in exactly one place:\n{lines}",
              file=sys.stderr)
        sys.exit(1)


def run_synthesize_with_config(
    client,
    config: PlanningConfig,
    extra_npc_files: list[Path],
    extract_files: list[Path],
    context_files: list[Path],
    model: str,
) -> str:
    """Synthesize using the per-entity planning-config rendering. Mirrors
    party.py's --party-config path: each NPC/faction in the config is a
    `## {name}` block with the dossier and arc-score nested inside, so the
    LLM can't mismatch a score to the wrong entity.

    `extra_npc_files` are pass-through NPC dossiers (from --npc) for NPCs
    with no arc score — typically the majority. They render as plain
    `## {name}` blocks alongside the config entries.
    """
    _check_npc_overlap(config, extra_npc_files)

    blocks_text, canonical_to_aliases = _render_planning_blocks(
        config, extra_npc_files=extra_npc_files, normalize=None
    )
    normalize, resolution_entries = build_alias_normalizer(canonical_to_aliases)

    # Re-render so dossier-internal alias normalization is applied. Cheap;
    # parse_dossier is just a regex + YAML parse per file.
    blocks_text, _ = _render_planning_blocks(
        config, extra_npc_files=extra_npc_files, normalize=normalize
    )

    parts = [blocks_text] if blocks_text else []
    extracts_block = _render_flat_section(
        "SESSION EXTRACTIONS", extract_files, "Session extract", normalize=normalize
    )
    if extracts_block:
        parts.append(extracts_block)
    context_block = _render_flat_section(
        "WORLD CONTEXT", context_files, "World context", normalize=normalize
    )
    if context_block:
        parts.append(context_block)

    user_prompt = "\n\n===\n\n".join(parts)
    if not user_prompt.strip():
        print("Error: planning config produced no source material to synthesize.",
              file=sys.stderr)
        raise SystemExit(1)

    system_prompt = SYNTHESIZE_SYSTEM
    if resolution_entries:
        lines = [f"- **{name}** (also: {', '.join(aliases)})"
                 for name, aliases in resolution_entries]
        resolution_block = (
            "# ENTITY RESOLUTION\n\n"
            "The source text below has been pre-normalized: variant names have been "
            "replaced with the canonical NPC name. If any variant still appears, treat "
            "it as referring to the canonical NPC listed here.\n\n"
            + "\n".join(lines) + "\n\n"
        )
        system_prompt = resolution_block + SYNTHESIZE_SYSTEM
        print(f"  Alias map: {len(resolution_entries)} NPC(s) with variants.")

    print(f"  Synthesizing ({len(user_prompt):,} chars total)...")
    print("  " + "─" * 56)
    result = stream_api(client, system_prompt, user_prompt, model)
    print("  " + "─" * 56)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a planning.md from NPC dossiers, threat arc scores, and the canonical timeline."
    )
    parser.add_argument("--planning-config", metavar="FILE", default=None,
                        help="Planning config YAML mapping each NPC/faction to its dossier "
                             "and arc-score file. When set, --npc and --arc-scores are rejected. "
                             "Tighter coupling than the flat flags — prevents the synthesizer "
                             "from mismatching a score to the wrong entity.")
    parser.add_argument("--npc", "-n", nargs="+", metavar="FILE", default=[],
                        help="NPC dossier file(s)")
    parser.add_argument("--arc-scores", "-a", nargs="+", metavar="FILE", default=[],
                        help="Threat arc score document(s) (e.g. brundar_echo.md, kraken_echoes.md)")
    parser.add_argument("--summaries", "-s", metavar="FILE",
                        help="Canonical timeline — the master narrative bible (large, will be chunked)")
    parser.add_argument("--context", "-c", nargs="+", metavar="FILE", default=[],
                        help="Optional world context files (factions, locations, etc.)")
    parser.add_argument("--output", "-o", metavar="FILE",
                        help="Where to save the planning document (required unless --build-dossiers)")
    parser.add_argument("--chunk-size", type=int, default=60000, metavar="CHARS",
                        help="Max characters per extract chunk (default: 60000)")
    parser.add_argument("--split-chapters", metavar="PREFIX", default=None,
                        help="Split summaries at lines beginning with PREFIX instead of by character "
                             "count (e.g. '# Session'). Each session becomes one extract chunk.")
    parser.add_argument("--extract-dir", metavar="DIR", default=None,
                        help="Where to save/load session extractions "
                             "(default: <output_dir>/planning_extractions/ or ./planning_extractions/)")
    parser.add_argument("--synthesize-only", action="store_true",
                        help="Skip extraction, synthesize from existing files in --extract-dir")
    parser.add_argument("--extract-only", action="store_true",
                        help="Run the extract pass only, then stop so you can review "
                             "extractions before synthesis. In --build-dossiers mode, stops "
                             "after Phase 1 (per-chunk NPC extraction) before Phase 2 "
                             "aggregation and Phase 3 per-NPC LLM synthesis. In the normal "
                             "mode, stops before the planning.md synthesis call.")
    parser.add_argument("--build-dossiers", action="store_true",
                        help="Build individual per-NPC dossier files from --summaries instead of "
                             "producing planning.md (save to --dossier-dir, review/edit, then run "
                             "the normal synthesize pass with --npc)")
    parser.add_argument("--dossier-dir", metavar="DIR", default=None,
                        help="Where to save per-NPC dossier files when using --build-dossiers "
                             "(default: ./npcs/ relative to CWD)")
    parser.add_argument("--since", type=int, metavar="N", default=None,
                        help="In --build-dossiers mode, aggregate and synthesize only from "
                             "extracts with number >= N. Use after a new session "
                             "(e.g. --since 11 when extract_011.md is the new chunk) to skip "
                             "historical chunks already rolled into dossiers.")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    parser.add_argument("--campaign-dir", default=None,
                        help="Campaign workspace root (default: $CAMPAIGN_DIR "
                             "or the output file's parent, or CWD). Used to "
                             "locate docs/dossier_proposal.md.")
    parser.add_argument("--require-proposal", action="store_true",
                        help="Refuse to run the synthesize pass unless "
                             "<campaign-dir>/docs/dossier_proposal.md exists "
                             "and has been approved.")
    args = parser.parse_args()

    # Resolve the proposal check BEFORE the synthesize render call.
    if args.require_proposal:
        import os as _os

        from proposal_loader import (
            ProposalNotApproved,
            ProposalRequired,
            require_approved_proposal,
        )
        _planning_campaign_dir = (
            args.campaign_dir
            or _os.environ.get("CAMPAIGN_DIR")
            or (str(Path(args.output).expanduser().resolve().parent.parent)
                if args.output else str(Path.cwd().resolve()))
        )
        try:
            require_approved_proposal(_planning_campaign_dir)
        except (ProposalRequired, ProposalNotApproved) as exc:
            parser.error(str(exc))

    if args.synthesize_only and args.extract_only:
        print("Error: --synthesize-only and --extract-only are mutually exclusive",
              file=sys.stderr)
        sys.exit(1)
    if args.planning_config and args.arc_scores:
        print("Error: --planning-config replaces --arc-scores; pass arc-score files "
              "in the YAML's `arc_score:` keys instead", file=sys.stderr)
        sys.exit(1)
    if args.planning_config and args.build_dossiers:
        print("Error: --planning-config is for the synthesize pass; "
              "--build-dossiers does not use it", file=sys.stderr)
        sys.exit(1)
    if args.extract_only and not args.summaries:
        print("Error: --extract-only requires --summaries", file=sys.stderr)
        sys.exit(1)
    if args.build_dossiers and not args.summaries:
        print("Error: --build-dossiers requires --summaries", file=sys.stderr)
        sys.exit(1)
    if args.since is not None and not args.build_dossiers:
        print("Error: --since only applies in --build-dossiers mode", file=sys.stderr)
        sys.exit(1)
    if not args.build_dossiers and not args.output:
        print("Error: --output is required (unless using --build-dossiers)", file=sys.stderr)
        sys.exit(1)
    if (not args.build_dossiers and not args.planning_config
            and not args.npc and not args.summaries and not args.synthesize_only):
        print("Error: provide at least --planning-config, --npc, or --summaries",
              file=sys.stderr)
        sys.exit(1)
    if args.synthesize_only and not args.extract_dir and not args.npc and not args.planning_config:
        print("Error: --synthesize-only requires --extract-dir, --npc, or --planning-config",
              file=sys.stderr)
        sys.exit(1)

    planning_config: PlanningConfig | None = None
    if args.planning_config:
        planning_config = load_planning_config(
            Path(args.planning_config).expanduser().resolve()
        )

    npc_files = [Path(f).expanduser().resolve() for f in args.npc]
    arc_score_files = [Path(f).expanduser().resolve() for f in args.arc_scores]
    context_files = [Path(f).expanduser().resolve() for f in args.context]

    for f in npc_files + arc_score_files + context_files:
        if not f.exists():
            print(f"Error: file not found: {f}", file=sys.stderr)
            sys.exit(1)

    client = make_client()

    # ── Build-dossiers mode ───────────────────────────────────────────────────
    if args.build_dossiers:
        summaries_text = Path(args.summaries).expanduser().read_text(encoding="utf-8")
        dossier_dir = (
            Path(args.dossier_dir).expanduser().resolve()
            if args.dossier_dir
            else Path.cwd() / "npcs"
        )
        extract_dir = (
            Path(args.extract_dir).expanduser().resolve()
            if args.extract_dir
            else dossier_dir.parent / "planning_extractions"
        )
        print(f"\n[Build dossiers | {len(summaries_text):,} chars | model: {args.model}]")
        print("=" * 60)
        saved = run_build_dossiers(client, summaries_text, args.chunk_size, args.model, extract_dir, dossier_dir,
                                    split_chapters=args.split_chapters, since=args.since,
                                    extract_only=args.extract_only)
        print("=" * 60)
        if args.extract_only:
            return
        print(f"\n{len(saved)} dossier file(s) saved to: {dossier_dir}")
        print("\nNext steps:")
        print("  1. Review and edit the dossier files")
        print(f"  2. Run the planning synthesize pass:")
        npc_args = " ".join(f"--npc {f.name}" for f in saved[:3])
        if len(saved) > 3:
            npc_args += " ..."
        print(f"     python planning.py {npc_args} --output planning.md")
        return

    output = Path(args.output).expanduser().resolve()
    extract_dir = (
        Path(args.extract_dir).expanduser().resolve()
        if args.extract_dir
        else output.parent / "planning_extractions"
    )

    # ── Extract pass ──────────────────────────────────────────────────────────
    if args.summaries and not args.synthesize_only:
        summaries_text = Path(args.summaries).expanduser().read_text(encoding="utf-8")
        print(f"\n[Pass 1: Extract NPC/faction info | {len(summaries_text):,} chars | model: {args.model}]")
        print("=" * 60)
        extract_files = run_extract_pipeline(
            client, summaries_text,
            extract_system=EXTRACT_SYSTEM,
            model=args.model,
            extract_dir=extract_dir,
            chunk_size=args.chunk_size,
            split_chapters=args.split_chapters,
            split_label="session",
        )
        print(f"Extractions saved to: {extract_dir}")

        if args.extract_only:
            print(f"\n[Extract-only mode — stopping before synthesis]")
            print(f"Review files in: {extract_dir}")
            print(f"When ready, re-run with --synthesize-only --extract-dir {extract_dir} "
                  f"plus the same --planning-config (or --npc/--arc-scores)/--context args.")
            return
    elif args.synthesize_only:
        extract_files = sorted(extract_dir.glob("extract_*.md"))
        if not extract_files:
            print(f"Error: no extract_*.md files found in {extract_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Synthesize-only | {len(extract_files)} extraction(s) from {extract_dir}]")
    else:
        extract_files = []

    # ── Synthesize pass ───────────────────────────────────────────────────────
    sources = []
    if planning_config:
        bound_arc = sum(1 for e in planning_config.npcs + planning_config.factions
                        if e.arc_score is not None)
        trackless = sum(1 for e in planning_config.npcs + planning_config.factions
                        if e.trackless)
        sources.append(
            f"{len(planning_config.npcs)} NPC(s) + {len(planning_config.factions)} faction(s) "
            f"from planning config ({bound_arc} bound arc, {trackless} trackless)"
        )
    if npc_files:
        kind = "extra unbound NPC dossier(s)" if planning_config else "NPC dossier(s)"
        sources.append(f"{len(npc_files)} {kind}")
    if arc_score_files:
        sources.append(f"{len(arc_score_files)} arc score doc(s)")
    if extract_files:
        sources.append(f"{len(extract_files)} session extraction(s)")
    if context_files:
        sources.append(f"{len(context_files)} context file(s)")

    print(f"\n[Pass 2: Synthesize | {', '.join(sources)} | model: {args.model}]")
    print("=" * 60)
    if planning_config:
        planning_doc = run_synthesize_with_config(
            client, planning_config, npc_files,
            extract_files, context_files, args.model,
        )
    else:
        planning_doc = run_synthesize(
            client, npc_files, arc_score_files, extract_files, context_files, args.model
        )
    print("=" * 60)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(planning_doc.strip() + "\n", encoding="utf-8")
    print(f"\nPlanning document saved to: {output}")
    if extract_files and not args.synthesize_only:
        print(f"Extractions kept in: {extract_dir}")
        print("(Re-run with --synthesize-only to re-synthesize without re-extracting)\n")


if __name__ == "__main__":
    main()
