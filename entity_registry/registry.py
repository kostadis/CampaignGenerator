#!/usr/bin/env python3
"""registry — CLI for the campaign entity registry (docs/entity_registry.yaml).

This is the write side of ``campaignlib.registry`` (the loader/validator
library). Its subcommands:

  init    <campaign_dir>                 create an empty registry
  add     <campaign_dir> --name ... --type ...   add one entity, with a
                                          fuzzy typo guard against existing
                                          names/aliases before it lands
  alias   <campaign_dir> --to ... variant [variant ...]   non-interactive
                                          counterpart to add's interactive
                                          "[1] same entity" choice: attach one
                                          or more surface forms as aliases of
                                          an existing entity (looked up by its
                                          canonical name OR an existing alias)
  merge   <campaign_dir> --into ... other [other ...]   fold one or more
                                          EXISTING entities into a target (they
                                          are the same thing) — the positive
                                          counterpart to mark-distinct; refuses
                                          if a distinct/rejected guard says they
                                          are separate. This is how a GM resolves
                                          grouping drift where two spellings each
                                          registered as their own entity.
  project <campaign_dir>                 write aliases.json and
                                          entity_inventory.md projections
                                          consumed by existing pipelines
                                          (synthesise_world_state.load_aliases,
                                          spell_canon.inventory_tokens, ...)
  import-inventory <campaign_dir> <md>   merge entities from an inventory
                                          markdown file (``## Heading`` sections
                                          of ``- **Name** / **Alias** — note``
                                          bullets), e.g. a module inventory or
                                          ``entity_inventory.md``
  import-dedup <campaign_dir> <json>     merge NPC entities + anti-merge
                                          guards from a ``.dedup_state.json``
                                          file
  import-frontmatter <campaign_dir> <dossier_dir>  merge NPC entities from
                                          dossier frontmatter
                                          (``campaignlib.npc.load_alias_map``);
                                          fills gaps for singleton dossiers
                                          that no dedup cluster ever touched
  import-alias-decisions <campaign_dir> <json>   ENRICH-ONLY: add aliases to
                                          entities that are already
                                          registered, from approved
                                          ``.alias_decisions.json`` groups;
                                          never creates a new entity (approved
                                          canonicals are often generic/garbage
                                          strings with no reliable type)
  check   <campaign_dir>                 surface drift between the registry
                                          and the legacy scattered stores
                                          (``.dedup_state.json``, an inventory
                                          markdown, ``.alias_decisions.json``);
                                          reports only — never resolves it

Recommended import order (why order matters):

    init -> import-inventory -> import-dedup -> import-frontmatter
         -> import-alias-decisions -> check -> [GM resolves: merge /
            alias / mark-distinct / mark-rejected] -> project

``import-inventory`` goes first because a module/campaign inventory carries
real entity TYPES and the module's canonical spellings. ``import-dedup``
goes next and is NPC-only (it blanket-types everything ``npc``) — running it
before ``import-inventory`` would clobber an inventory-sourced type (e.g. a
``deity`` or ``location`` that also shows up in a dedup cluster) and would
let a dedup-cluster's file-stem spelling win over the inventory's authoritative
spelling instead of just adding as an alias. ``import-frontmatter`` runs
after dedup so it only fills gaps (singleton dossiers no dedup cluster ever
grouped) rather than fighting dedup's merge decisions. ``import-alias-decisions``
runs last among importers because it is enrich-only: it can only attach
aliases to entities the earlier steps already created, so decisions whose
canonical is not yet registered are reported as unmatched rather than
guessed into existence. ``check`` runs after all imports (and again anytime
after a GM edits the registry by hand) to surface any grouping the legacy
stores disagree with, before ``project`` republishes ``aliases.json`` and
``entity_inventory.md`` for downstream pipelines to consume.

No API calls are made anywhere in this module.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from . import spell_canon
from campaignlib.npc import load_alias_map
from campaignlib.party import load_pc_names
from campaignlib.registry import (
    Entity,
    Registry,
    find_registry,
    load_registry,
    save_registry,
    validate,
)
from campaignlib.textproc import norm_subject

NEAR_MISS_THRESHOLD = 0.85


def _registry_path(campaign_dir: Path) -> Path:
    return Path(campaign_dir) / "docs" / "entity_registry.yaml"


# ── init ─────────────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = _registry_path(campaign_dir)
    if path.exists():
        print(f"Error: registry already exists at {path}", file=sys.stderr)
        return 1

    path.parent.mkdir(parents=True, exist_ok=True)
    campaign = args.campaign or campaign_dir.resolve().name
    reg = Registry(version=1, campaign=campaign, entities=[])
    save_registry(reg, path)
    print(f"Wrote {path}")
    return 0


# ── add ──────────────────────────────────────────────────────────────────────

def _near_misses(new_name: str, reg: Registry, threshold: float) -> list[tuple[Entity, str, float]]:
    """[(entity, matched_string, ratio)] for every existing name/alias that is
    close to (but not an exact normalized match of) ``new_name``."""
    new_key = norm_subject(new_name)
    matches: list[tuple[Entity, str, float]] = []
    for e in reg.entities:
        for candidate in [e.name, *e.aliases]:
            cand_key = norm_subject(candidate)
            if cand_key == new_key:
                continue  # exact collision — handled separately
            ratio = SequenceMatcher(None, new_key, cand_key).ratio()
            if ratio >= threshold:
                matches.append((e, candidate, ratio))
    return matches


def _has_exact_collision(new_name: str, reg: Registry) -> Entity | None:
    new_key = norm_subject(new_name)
    for e in reg.entities:
        for candidate in [e.name, *e.aliases]:
            if norm_subject(candidate) == new_key:
                return e
    return None


def cmd_add(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = find_registry(campaign_dir)
    if path is None:
        print(
            f"Error: no registry at {_registry_path(campaign_dir)} — "
            f"run `registry init {campaign_dir}` first",
            file=sys.stderr,
        )
        return 1

    reg = load_registry(path)

    collision = _has_exact_collision(args.name, reg)
    if collision is not None:
        print(
            f"Error: {args.name!r} normalizes the same as existing entity "
            f"{collision.name!r} — this would be an identity collision",
            file=sys.stderr,
        )
        return 1

    new_entity = Entity(
        name=args.name,
        type=args.type,
        aliases=list(args.aliases or []),
        provenance=args.provenance,
        source=args.source,
        scope=args.scope or "persistent",
        note=args.note,
    )

    near = _near_misses(args.name, reg, NEAR_MISS_THRESHOLD)

    if near and not args.yes:
        print(f"'{args.name}' looks similar to existing name(s):")
        for e, matched, ratio in near:
            print(f"    {matched!r} (entity {e.name!r}, similarity {ratio:.2f})")
        print(f'  [1] same entity — add "{args.name}" as an alias of {near[0][0].name}')
        print(f'  [2] different entity — add "{args.name}" as new')
        print("  [3] abort (likely a typo)")
        choice = input("Choice [1/2/3]: ").strip()

        if choice == "1":
            target = near[0][0]
            target.aliases.append(args.name)
            try:
                validate(reg)
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
            save_registry(reg, path)
            print(f"Added {args.name!r} as an alias of {target.name!r}")
            return 0
        elif choice == "3":
            print("Aborted — nothing written.")
            return 1
        elif choice != "2":
            print(f"Error: unrecognized choice {choice!r} — aborting, nothing written", file=sys.stderr)
            return 1
        # choice == "2" falls through to the plain-add path below

    reg.entities.append(new_entity)
    try:
        validate(reg)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    save_registry(reg, path)
    print(f"Added {args.name!r} ({args.type}) to {path}")
    return 0


# ── project ──────────────────────────────────────────────────────────────────

def cmd_project(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = find_registry(campaign_dir)
    if path is None:
        print(f"Error: no registry at {_registry_path(campaign_dir)}", file=sys.stderr)
        return 1

    reg = load_registry(path)
    docs_dir = path.parent

    aliases_path = docs_dir / "aliases.json"
    aliases_path.write_text(
        json.dumps(reg.canonical_to_aliases(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    inventory_path = docs_dir / "entity_inventory.md"
    header = "<!-- GENERATED from docs/entity_registry.yaml — do not hand-edit. Regenerate with: registry project -->\n\n"
    inventory_path.write_text(header + reg.inventory_markdown(), encoding="utf-8")

    print(f"Wrote {aliases_path} (do not hand-edit — generated from entity_registry.yaml)")
    print(f"Wrote {inventory_path}")
    return 0


# ── shared merge helper ─────────────────────────────────────────────────────
#
# Every importer (import-inventory, import-dedup, and later packets'
# import-alias-decisions / import-frontmatter) funnels new entity data through
# _merge_entity so there is exactly one place that guarantees the resulting
# registry still passes campaignlib.registry.validate() — no importer can ever
# introduce an identity collision.

def _find_owner(reg: Registry, key: str) -> "int | None":
    """Index of the entity in ``reg.entities`` whose name or an alias
    normalizes to ``key`` (already a ``norm_subject`` value), else None."""
    if not key:
        return None
    for idx, e in enumerate(reg.entities):
        if norm_subject(e.name) == key:
            return idx
        for alias in e.aliases:
            if norm_subject(alias) == key:
                return idx
    return None


def _merge_entity(
    reg: Registry,
    *,
    name: str,
    type: str,
    aliases=(),
    provenance=None,
    source=None,
    scope="persistent",
    note=None,
) -> "list[str]":
    """Merge one incoming entity record into ``reg`` in place.

    Never introduces an identity collision: any incoming alias already owned
    by a *different* entity is skipped and reported instead of merged.
    Returns a list of human-readable conflict strings (empty == clean merge).
    """
    conflicts: list[str] = []
    name_key = norm_subject(name)
    existing_idx = _find_owner(reg, name_key)

    if existing_idx is not None:
        entity = reg.entities[existing_idx]
        if entity.type != type:
            conflicts.append(
                f"{name!r}: incoming type {type!r} conflicts with existing "
                f"type {entity.type!r} for entity {entity.name!r} — keeping "
                f"{entity.type!r}"
            )
        for alias in aliases:
            alias_key = norm_subject(alias)
            if not alias_key or alias_key == norm_subject(entity.name):
                continue
            owner_idx = _find_owner(reg, alias_key)
            if owner_idx is not None and owner_idx != existing_idx:
                conflicts.append(
                    f"alias {alias!r} already belongs to entity "
                    f"{reg.entities[owner_idx].name!r}; skipped for "
                    f"{entity.name!r}"
                )
                continue
            if owner_idx is None:
                entity.aliases.append(alias)
        if entity.provenance is None and provenance is not None:
            entity.provenance = provenance
        if entity.source is None and source is not None:
            entity.source = source
        if entity.note is None and note is not None:
            entity.note = note
        return conflicts

    # Not found as an existing name/alias anywhere in the registry.
    survivors: list[str] = []
    seen_keys = {name_key}
    for alias in aliases:
        alias_key = norm_subject(alias)
        if not alias_key or alias_key in seen_keys:
            continue
        owner_idx = _find_owner(reg, alias_key)
        if owner_idx is not None:
            conflicts.append(
                f"alias {alias!r} already belongs to entity "
                f"{reg.entities[owner_idx].name!r}; skipped for new entity "
                f"{name!r}"
            )
            continue
        survivors.append(alias)
        seen_keys.add(alias_key)

    reg.entities.append(
        Entity(
            name=name,
            type=type,
            aliases=survivors,
            provenance=provenance,
            source=source,
            scope=scope,
            note=note,
        )
    )
    return conflicts


def _add_distinct_pair(reg: Registry, a: str, b: str) -> None:
    """Append ``[a, b]`` to ``reg.distinct`` unless an equal-by-norm pair is
    already present (order-independent, case/punctuation-independent)."""
    key = {norm_subject(a), norm_subject(b)}
    for pair in reg.distinct:
        if len(pair) == 2 and {norm_subject(pair[0]), norm_subject(pair[1])} == key:
            return
    reg.distinct.append([a, b])


def _add_rejected_group(reg: Registry, members: "list[str]") -> None:
    """Append ``members`` to ``reg.rejected_aliases`` unless an equal-by-norm
    group (same members, any order) is already present."""
    key = {norm_subject(m) for m in members}
    for group in reg.rejected_aliases:
        if {norm_subject(m) for m in group} == key:
            return
    reg.rejected_aliases.append(list(members))


def _guard_blocks_merge(reg: Registry, target: Entity, other: Entity) -> "str | None":
    """Reason string if folding ``other`` into ``target`` would override a
    standing anti-merge guard, else None.

    A guard blocks the merge when a ``distinct`` pair (or a ``rejected_aliases``
    group) links one of ``target``'s names/aliases to one of ``other``'s — i.e.
    the GM has already ruled these two entities are NOT the same. ``validate``
    catches the ``distinct`` case indirectly (a distinct pair resolving to one
    entity), but not ``rejected_aliases``; more importantly a merge must refuse
    *before* mutating rather than silently trip an invariant, so the two guards
    are checked here explicitly."""
    target_keys = {norm_subject(s) for s in [target.name, *target.aliases]}
    other_keys = {norm_subject(s) for s in [other.name, *other.aliases]}
    for pair in reg.distinct:
        if len(pair) == 2:
            pk = {norm_subject(pair[0]), norm_subject(pair[1])}
            if pk & target_keys and pk & other_keys:
                return f"they are marked distinct ({pair!r})"
    for group in reg.rejected_aliases:
        gk = {norm_subject(m) for m in group}
        if gk & target_keys and gk & other_keys:
            return f"they share a rejected-aliases group ({group!r})"
    return None


# ── import-inventory ─────────────────────────────────────────────────────────

# Ordered keyword table for mapping a "## Heading" to an entity type: first
# substring match (case-insensitive) against the lowercased heading wins.
_HEADING_TYPE_KEYWORDS = [
    ("npc", "npc"),
    ("deit", "deity"),
    ("god", "deity"),
    ("location", "location"),
    ("place", "location"),
    ("plane", "concept"),
    ("cosmolog", "concept"),
    ("item", "item"),
    ("spell", "item"),
    ("artifact", "item"),
    ("book", "item"),
    ("weapon", "item"),
    ("faction", "faction"),
    ("title", "faction"),
    ("rank", "faction"),
    ("order", "faction"),
    ("guild", "faction"),
    ("event", "event"),
    ("concept", "concept"),
    ("date", "event"),
]

_SECTION_HEADING_RE = re.compile(r"^## (.+)$", re.MULTILINE)
_BOLD_SPAN_RE = re.compile(r"\*\*([^*]+)\*\*")


def _split_sections(text: str) -> "list[tuple[str, str]]":
    """[(heading_text, body_text)] for each ``## `` section in ``text``."""
    matches = list(_SECTION_HEADING_RE.finditer(text))
    sections = []
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((heading, text[start:end]))
    return sections


def _resolve_heading_type(heading: str, overrides: dict) -> "str | None":
    for key, typ in overrides.items():
        if key.lower() == heading.lower():
            return typ
    lower = heading.lower()
    for keyword, typ in _HEADING_TYPE_KEYWORDS:
        if keyword in lower:
            return typ
    return None


def _parse_bullet(line: str) -> "tuple[str, list[str], str | None] | None":
    """Parse one ``- **Name** / **Alias** — note`` bullet line.

    Returns ``(name, aliases, note)`` or None if the bullet has no bold span.
    """
    body = line.strip()
    if body.startswith("- "):
        body = body[2:]

    note = None
    if " — " in body:
        main_part, _, note_part = body.rpartition(" — ")
        body = main_part
        note = note_part.strip() or None

    spans = [s.strip() for s in _BOLD_SPAN_RE.findall(body)]
    spans = [s for s in spans if s]
    if not spans:
        return None
    name, *aliases = spans
    return name, aliases, note


def cmd_import_inventory(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = find_registry(campaign_dir)
    if path is None:
        print(
            f"Error: no registry at {_registry_path(campaign_dir)} — "
            f"run `registry init {campaign_dir}` first",
            file=sys.stderr,
        )
        return 1

    reg = load_registry(path)
    text = Path(args.md).read_text(encoding="utf-8")

    overrides: dict = {}
    for item in (args.heading_type or []):
        if "=" not in item:
            print(f"Error: --heading-type must be 'Heading=type', got {item!r}", file=sys.stderr)
            return 1
        heading, _, typ = item.partition("=")
        overrides[heading.strip()] = typ.strip()

    added = updated = skipped = 0
    all_conflicts: list[str] = []

    for heading, body in _split_sections(text):
        bullets = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("- ")]
        typ = _resolve_heading_type(heading, overrides)
        if typ is None:
            print(
                f"WARNING: no type mapping for heading {heading!r} "
                f"({len(bullets)} bullet(s)) — skipping",
                file=sys.stderr,
            )
            skipped += len(bullets)
            continue

        for bullet in bullets:
            parsed = _parse_bullet(bullet)
            if parsed is None:
                continue
            name, aliases, note = parsed
            existed = _find_owner(reg, norm_subject(name)) is not None
            conflicts = _merge_entity(
                reg,
                name=name,
                type=typ,
                aliases=aliases,
                provenance=args.provenance,
                source=args.source,
                note=note,
            )
            all_conflicts.extend(conflicts)
            if existed:
                updated += 1
            else:
                added += 1

    print(f"import-inventory: {added} added, {updated} updated, {skipped} skipped", file=sys.stderr)
    for c in all_conflicts:
        print(f"  conflict: {c}", file=sys.stderr)

    save_registry(reg, path)
    return 0


# ── import-dedup ─────────────────────────────────────────────────────────────

def _stem_to_name(filename: str) -> str:
    """``ilvara_mizzrym.md`` -> ``Ilvara Mizzrym``; ``asha.md`` -> ``Asha``."""
    stem = filename
    if stem.endswith(".md"):
        stem = stem[: -len(".md")]
    parts = re.split(r"[_-]+", stem)
    return " ".join(p.capitalize() for p in parts if p)


def _dedup_cluster_group(cluster: dict) -> "tuple[str, list[str]] | None":
    """(canonical_name, aliases) for one NON-split confirmed dedup cluster.

    Returns None for a split cluster (``canonical`` contains ``(split)`` or
    ``+``) — those intentionally name DIFFERENT entities and are handled by
    the caller's split-specific branch, not by this shared grouping helper.
    Shared by ``cmd_import_dedup`` (which merges the group into the registry)
    and ``cmd_check`` (which only verifies the group already resolves to one
    registry entity, never merging).
    """
    canonical = cluster.get("canonical", "") or ""
    if "(split)" in canonical or "+" in canonical:
        return None
    files = cluster.get("files", []) or []
    aliases_recorded = cluster.get("aliases_recorded", []) or []
    canonical_name = _stem_to_name(canonical)
    alias_files = [f for f in files if f != canonical]
    aliases = [_stem_to_name(f) for f in alias_files] + list(aliases_recorded)
    return canonical_name, aliases


def _confirmed_canon_map(data: dict) -> "dict[str, str]":
    """``{member_file: canonical_file}`` for every NON-split confirmed cluster.

    Two files sharing a canonical are confirmed the SAME entity — used to
    collapse a rejected cluster so its guard never contradicts a confirmed
    merge. Split clusters name DIFFERENT entities, so they contribute no
    equivalence."""
    canon: dict[str, str] = {}
    for cluster in data.get("clusters_confirmed", []) or []:
        canonical = cluster.get("canonical", "") or ""
        if "(split)" in canonical or "+" in canonical:
            continue
        for f in cluster.get("files", []) or []:
            canon[f] = canonical
    return canon


def _distinct_rejected_reps(
    reg: Registry, files: "list[str]", confirmed_canon: "dict[str, str]"
) -> "list[str]":
    """Collapse a rejected dedup cluster's member files to one representative
    NAME per DISTINCT entity.

    A rejected cluster means "not all of these are one entity" — NOT that every
    pair is distinct. Two members collapse together when they are confirmed the
    same (same ``confirmed_canon`` file) OR already resolve to the same registry
    entity (e.g. an inventory alias). Emitting a flat rejected_aliases group over
    the raw files would forbid a pair the data elsewhere confirms as duplicates
    (the ``{aliinka, plinki, pliinki} ⊃ confirmed {plinki, pliinki}`` bug);
    collapsing first keeps the guard only across the entities actually ruled
    apart. The representative is the registry's canonical name when a member
    resolves, else the member's own file-stem name."""
    n = len(files)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        parent[find(i)] = find(j)

    names = [_stem_to_name(f) for f in files]
    owners = [_find_owner(reg, norm_subject(nm)) for nm in names]
    for i in range(n):
        for j in range(i + 1, n):
            same_confirmed = (
                confirmed_canon.get(files[i]) is not None
                and confirmed_canon.get(files[i]) == confirmed_canon.get(files[j])
            )
            same_entity = owners[i] is not None and owners[i] == owners[j]
            if same_confirmed or same_entity:
                union(i, j)

    reps: dict[int, str] = {}
    for i in range(n):
        root = find(i)
        if root not in reps:
            reps[root] = reg.entities[owners[i]].name if owners[i] is not None else names[i]
    return list(reps.values())


def _distinct_rejected_reps_by_name(reg: Registry, names: "list[str]") -> "list[str]":
    """Collapse a rejected alias-decision cluster's candidate NAMES to one
    representative per DISTINCT registry entity.

    Same principle as :func:`_distinct_rejected_reps` (the #140 dedup fix): a
    rejected group means "not all of these are one entity", NOT that every pair
    is distinct. ``import-alias-decisions`` runs LAST — after import-dedup /
    import-frontmatter and after this file's own approved groups are applied —
    so by the time the rejected loop runs every candidate that IS a confirmed
    duplicate already resolves to the same registry entity. Two members collapse
    when they share a registry owner (or are the same surface form when neither
    is registered); the guard is then recorded only across the entities actually
    ruled apart. Without this a flat rejected group forbids a pair the same
    file's approved decisions (or dedup) confirm as one — e.g. rejected
    ``{Corbin, Harbin, Harbin Wester, Townmaster}`` must never forbid
    ``Harbin ↔ Harbin Wester``. The representative is the registry's canonical
    name when a member resolves, else the candidate's own name."""
    n = len(names)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        parent[find(i)] = find(j)

    keys = [norm_subject(nm) for nm in names]
    owners = [_find_owner(reg, k) for k in keys]
    for i in range(n):
        for j in range(i + 1, n):
            same_entity = owners[i] is not None and owners[i] == owners[j]
            same_key = keys[i] == keys[j]
            if same_entity or same_key:
                union(i, j)

    reps: dict[int, str] = {}
    for i in range(n):
        root = find(i)
        if root not in reps:
            reps[root] = reg.entities[owners[i]].name if owners[i] is not None else names[i]
    return list(reps.values())


def cmd_import_dedup(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = find_registry(campaign_dir)
    if path is None:
        print(
            f"Error: no registry at {_registry_path(campaign_dir)} — "
            f"run `registry init {campaign_dir}` first",
            file=sys.stderr,
        )
        return 1

    reg = load_registry(path)
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))

    added = updated = skipped = 0
    all_conflicts: list[str] = []

    for cluster in data.get("clusters_confirmed", []):
        canonical = cluster.get("canonical", "") or ""
        files = cluster.get("files", []) or []
        aliases_recorded = cluster.get("aliases_recorded", []) or []

        if "(split)" in canonical or "+" in canonical:
            marker = re.sub(r"\s*\(split\)\s*$", "", canonical).strip()
            piece_files = [p.strip() for p in marker.split("+") if p.strip()]
            piece_names = [_stem_to_name(p) for p in piece_files]

            if aliases_recorded:
                print(
                    f"WARNING: split cluster {canonical!r} has aliases_recorded "
                    f"{aliases_recorded!r} — ambiguous which sub-entity owns "
                    f"them; not attaching",
                    file=sys.stderr,
                )

            for piece_name in piece_names:
                existed = _find_owner(reg, norm_subject(piece_name)) is not None
                conflicts = _merge_entity(reg, name=piece_name, type="npc")
                all_conflicts.extend(conflicts)
                if existed:
                    updated += 1
                else:
                    added += 1

            for a, b in itertools.combinations(piece_names, 2):
                _add_distinct_pair(reg, a, b)
            continue

        canonical_name, aliases = _dedup_cluster_group(cluster)

        existed = _find_owner(reg, norm_subject(canonical_name)) is not None
        conflicts = _merge_entity(reg, name=canonical_name, type="npc", aliases=aliases)
        all_conflicts.extend(conflicts)
        if existed:
            updated += 1
        else:
            added += 1

    confirmed_canon = _confirmed_canon_map(data)
    for cluster in data.get("clusters_rejected", []):
        files = cluster.get("files", []) or []
        if not files:
            continue
        # A rejected cluster means "not all of these are one entity" — NOT that
        # every pair is distinct. Collapse members that are confirmed the same
        # (or already merged in the registry) BEFORE recording the guard, so it
        # never forbids a pair a confirmed cluster marks as duplicates
        # (e.g. rejected {aliinka, plinki, pliinki} ⊃ confirmed {plinki, pliinki}
        # must guard only Aliinka vs Plinki, never Plinki vs Pliinki).
        reps = _distinct_rejected_reps(reg, files, confirmed_canon)
        if len(reps) >= 2:
            _add_rejected_group(reg, reps)
        else:
            print(
                f"WARNING: rejected cluster {[_stem_to_name(f) for f in files]!r} "
                f"collapses to a single entity {reps!r} — its members are confirmed "
                f"duplicates / already merged, so no anti-merge guard is added",
                file=sys.stderr,
            )

    # clusters_deferred: intentionally skipped (not yet a settled decision).
    # pc_files_skipped (if present at all): intentionally never read — PCs
    # live in party.yaml, not the entity registry.

    print(f"import-dedup: {added} added, {updated} updated, {skipped} skipped", file=sys.stderr)
    for c in all_conflicts:
        print(f"  conflict: {c}", file=sys.stderr)

    save_registry(reg, path)
    return 0


# ── import-frontmatter ───────────────────────────────────────────────────────

def cmd_import_frontmatter(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = find_registry(campaign_dir)
    if path is None:
        print(
            f"Error: no registry at {_registry_path(campaign_dir)} — "
            f"run `registry init {campaign_dir}` first",
            file=sys.stderr,
        )
        return 1

    reg = load_registry(path)
    # importer: read docs/npcs/ dossiers to BUILD the registry — never pass
    # registry_path here (it would return the registry's own aliases and make
    # this import a no-op).
    amap = load_alias_map(args.dossier_dir)

    added = updated = 0
    all_conflicts: list[str] = []

    for canonical, aliases in amap.items():
        existed = _find_owner(reg, norm_subject(canonical)) is not None
        conflicts = _merge_entity(reg, name=canonical, type="npc", aliases=aliases)
        all_conflicts.extend(conflicts)
        if existed:
            updated += 1
        else:
            added += 1

    print(f"import-frontmatter: {added} added, {updated} updated", file=sys.stderr)
    for c in all_conflicts:
        print(f"  conflict: {c}", file=sys.stderr)

    save_registry(reg, path)
    return 0


# ── import-alias-decisions ───────────────────────────────────────────────────

def _split_alias_decisions(data: dict) -> "tuple[list[dict], list[dict]]":
    """(approved, rejected) decision dicts from a parsed .alias_decisions.json.

    Tolerates a missing/null ``decisions`` key (-> both empty). Per the
    on-disk contract there are only two statuses: ``approved`` (always has a
    non-null ``canonical``) and ``rejected`` (always has ``canonical: null``).
    Any decision with an unrecognized shape is silently ignored rather than
    guessed at.
    """
    decisions = data.get("decisions") or []
    approved = [d for d in decisions if d.get("status") == "approved" and d.get("canonical")]
    rejected = [d for d in decisions if d.get("status") == "rejected"]
    return approved, rejected


def cmd_import_alias_decisions(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = find_registry(campaign_dir)
    if path is None:
        print(
            f"Error: no registry at {_registry_path(campaign_dir)} — "
            f"run `registry init {campaign_dir}` first",
            file=sys.stderr,
        )
        return 1

    reg = load_registry(path)
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    approved, rejected = _split_alias_decisions(data)

    enriched = 0
    unmatched: list[str] = []
    all_conflicts: list[str] = []

    for d in approved:
        canonical = d["canonical"]
        candidates = d.get("candidates") or []
        canon_key = norm_subject(canonical)
        owner_idx = _find_owner(reg, canon_key)
        if owner_idx is None:
            # ENRICH-ONLY: an unregistered canonical carries no reliable type
            # (these decisions include generic/garbage canonicals like "stone
            # giants" or "Temple of Lathander's Searing Pain of Justice") —
            # never create an entity from it. Report for the GM to `add` by
            # hand if it's actually worth registering.
            unmatched.append(canonical)
            continue
        existing_type = reg.entities[owner_idx].type
        others = [c for c in candidates if norm_subject(c) != canon_key]
        conflicts = _merge_entity(reg, name=canonical, type=existing_type, aliases=others)
        all_conflicts.extend(conflicts)
        enriched += 1

    rejected_count = 0
    for d in rejected:
        members = d.get("candidates") or []
        if not members:
            continue
        # A rejected cluster means "not all of these are one entity" — NOT that
        # every pair is distinct. import-alias-decisions runs LAST, so confirmed
        # duplicates (from dedup / this file's approved groups) already resolve
        # together; collapse members that share a registry entity BEFORE
        # recording the guard so it never forbids a pair confirmed elsewhere as
        # one (the #140 bug, second home — e.g. rejected {Corbin, Harbin, Harbin
        # Wester, Townmaster} must guard only Corbin vs Harbin Wester, never
        # Harbin vs Harbin Wester).
        reps = _distinct_rejected_reps_by_name(reg, members)
        if len(reps) >= 2:
            _add_rejected_group(reg, reps)
            rejected_count += 1
        else:
            print(
                f"WARNING: rejected group {members!r} collapses to a single "
                f"entity {reps!r} — its members already resolve together, so no "
                f"anti-merge guard is added",
                file=sys.stderr,
            )

    print(
        f"import-alias-decisions: {enriched} enriched, {len(unmatched)} unmatched, "
        f"{rejected_count} rejected-groups",
        file=sys.stderr,
    )
    for c in all_conflicts:
        print(f"  conflict: {c}", file=sys.stderr)
    if unmatched:
        print("Unmatched canonicals (not registered — add by hand if warranted):", file=sys.stderr)
        for u in unmatched:
            print(f"  {u}", file=sys.stderr)

    save_registry(reg, path)
    return 0


# ── check ────────────────────────────────────────────────────────────────────
#
# Surfaces drift between the registry and the legacy scattered stores it is
# meant to replace. Reports only — never merges, never edits the registry.
# Detectors, in order:
#   (a) grouping drift — PRIMARY, exact, high-confidence. A legacy store that
#       encodes GROUPING (dedup clusters, inventory bullets, alias decisions)
#       disagrees with how the registry currently groups those same surface
#       forms.
#   (b) fuzzy near-duplicates — SECONDARY, noisy. Pairwise similarity across
#       every registered name/alias; a GM review surface, not a verdict.
#   (c) presence drift — informational. Names present in a legacy store but
#       absent from the registry, and vice versa.

def _inventory_bullet_groups(text: str) -> "list[list[str]]":
    """[[name, *aliases], ...] for every ``- **Name** / **Alias**`` bullet
    with 2+ bold spans in an inventory markdown file (headings are ignored —
    ``check`` only cares whether the bullet's spans co-resolve, not the type
    a heading would imply)."""
    groups = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        parsed = _parse_bullet(stripped)
        if parsed is None:
            continue
        name, aliases, _note = parsed
        group = [name, *aliases]
        if len(group) >= 2:
            groups.append(group)
    return groups


def _find_inventory_files(campaign_dir: Path) -> "list[Path]":
    docs_dir = campaign_dir / "docs"
    found = []
    for base in (docs_dir, docs_dir / "background"):
        if not base.is_dir():
            continue
        for f in sorted(base.glob("*.md")):
            if "inventory" in f.name.lower():
                found.append(f)
    return found


def _resolved_entity_names(reg: Registry, names: "list[str]") -> "set[str]":
    """Display names (or 'MISSING') that ``names`` resolve to via _find_owner."""
    resolved = set()
    for n in names:
        idx = _find_owner(reg, norm_subject(n))
        resolved.add(reg.entities[idx].name if idx is not None else "MISSING")
    return resolved


def cmd_check(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = _registry_path(campaign_dir)
    if not path.is_file():
        print(
            f"Error: no registry at {path} — run `registry init {campaign_dir}` first",
            file=sys.stderr,
        )
        return 1
    try:
        reg = load_registry(path)
    except Exception as exc:  # noqa: BLE001 — any load/parse/validate failure is a report, not a crash
        print(f"Error: registry at {path} failed to load: {exc}", file=sys.stderr)
        return 1

    grouping_findings: list[str] = []
    fuzzy_findings: list[str] = []
    legacy_display_names: list[str] = []  # for presence drift

    # (a1) dedup grouping drift ------------------------------------------------
    dedup_path = campaign_dir / "docs" / "npcs" / ".dedup_state.json"
    if dedup_path.is_file():
        try:
            dedup_data = json.loads(dedup_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"WARNING: could not parse {dedup_path}: {exc}", file=sys.stderr)
            dedup_data = {}
        for cluster in dedup_data.get("clusters_confirmed", []) or []:
            group = _dedup_cluster_group(cluster)
            if group is None:
                continue  # split cluster — intentionally different entities
            canonical_name, aliases = group
            names = [canonical_name, *aliases]
            legacy_display_names.extend(names)
            resolved = _resolved_entity_names(reg, names)
            if len(resolved) > 1 or "MISSING" in resolved:
                grouping_findings.append(
                    f"dedup groups {names!r} but registry resolves them to "
                    f"{sorted(resolved)}"
                )

    # (a2) inventory grouping drift --------------------------------------------
    for inv_path in _find_inventory_files(campaign_dir):
        text = inv_path.read_text(encoding="utf-8")
        rel = inv_path.relative_to(campaign_dir)
        for group in _inventory_bullet_groups(text):
            legacy_display_names.extend(group)
            resolved = _resolved_entity_names(reg, group)
            if len(resolved) > 1 or "MISSING" in resolved:
                grouping_findings.append(
                    f"inventory {rel} groups {group!r} but registry resolves them "
                    f"to {sorted(resolved)}"
                )

    # (a3) alias-decisions grouping drift --------------------------------------
    decisions_path = campaign_dir / "docs" / "ensemble" / ".alias_decisions.json"
    if decisions_path.is_file():
        try:
            decisions_data = json.loads(decisions_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"WARNING: could not parse {decisions_path}: {exc}", file=sys.stderr)
            decisions_data = {}
        approved, rejected = _split_alias_decisions(decisions_data)
        for d in approved:
            candidates = d.get("candidates") or []
            if len(candidates) < 2:
                continue
            legacy_display_names.extend(candidates)
            resolved = _resolved_entity_names(reg, candidates)
            if len(resolved) > 1 or "MISSING" in resolved:
                grouping_findings.append(
                    f"alias-decisions approved group {candidates!r} but registry "
                    f"resolves them to {sorted(resolved)}"
                )
        for d in rejected:
            members = d.get("candidates") or []
            if len(members) < 2:
                continue
            legacy_display_names.extend(members)
            resolved = _resolved_entity_names(reg, members)
            if len(resolved) == 1 and "MISSING" not in resolved:
                grouping_findings.append(
                    f"alias-decisions rejected group {members!r} but registry "
                    f"merged them into {next(iter(resolved))!r} anyway"
                )

    # (a4) dossier frontmatter grouping drift -----------------------------------
    dossier_dir = campaign_dir / "docs" / "npcs"
    if dossier_dir.is_dir():
        # check: compare dossier frontmatter AGAINST the registry — read dossiers
        # only, never pass registry_path (that would compare the registry to
        # itself and hide the very drift this is meant to surface).
        amap = load_alias_map(dossier_dir)
        for canonical, aliases in amap.items():
            group = [canonical, *aliases]
            if len(group) < 2:
                continue
            legacy_display_names.extend(group)
            resolved = _resolved_entity_names(reg, group)
            if len(resolved) > 1 or "MISSING" in resolved:
                grouping_findings.append(
                    f"dossier frontmatter groups {group!r} but registry resolves "
                    f"them to {sorted(resolved)}"
                )

    # (a5) aliases.json grouping drift ------------------------------------------
    aliases_json_path = campaign_dir / "docs" / "ensemble" / "aliases.json"
    if not aliases_json_path.is_file():
        aliases_json_path = campaign_dir / "docs" / "aliases.json"
    if aliases_json_path.is_file():
        try:
            aliases_data = json.loads(aliases_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"WARNING: could not parse {aliases_json_path}: {exc}", file=sys.stderr)
            aliases_data = {}
        for canonical, variants in aliases_data.items():
            group = [canonical, *variants]
            if len(group) < 2:
                continue
            legacy_display_names.extend(group)
            resolved = _resolved_entity_names(reg, group)
            if len(resolved) > 1 or "MISSING" in resolved:
                grouping_findings.append(
                    f"aliases.json groups {group!r} but registry resolves them "
                    f"to {sorted(resolved)}"
                )

    # (b) fuzzy near-duplicates — suppress settled GM rulings ------------------
    suppressed: set[frozenset] = set()
    for pair in reg.distinct:
        if len(pair) == 2:
            suppressed.add(frozenset(norm_subject(x) for x in pair))
    for group in reg.rejected_aliases:
        keys = [norm_subject(m) for m in group]
        for a, b in itertools.combinations(keys, 2):
            suppressed.add(frozenset((a, b)))

    catalog: list[tuple[str, str, int]] = []  # (display, norm_key, entity_idx)
    for idx, e in enumerate(reg.entities):
        catalog.append((e.name, norm_subject(e.name), idx))
        for alias in e.aliases:
            catalog.append((alias, norm_subject(alias), idx))

    reported_pairs: set[frozenset] = set()
    for (s1, k1, i1), (s2, k2, i2) in itertools.combinations(catalog, 2):
        if i1 == i2 or k1 == k2:
            continue
        pair_key = frozenset((k1, k2))
        if pair_key in suppressed or pair_key in reported_pairs:
            continue
        ratio = SequenceMatcher(None, k1, k2).ratio()
        if ratio >= NEAR_MISS_THRESHOLD:
            reported_pairs.add(pair_key)
            fuzzy_findings.append(
                f"possible fragmentation — review, do not assume: {s1!r} "
                f"(entity {reg.entities[i1].name!r}) vs {s2!r} "
                f"(entity {reg.entities[i2].name!r}), similarity {ratio:.2f}"
            )

    # (c) presence drift — informational ---------------------------------------
    missing_from_registry = sorted(
        {n for n in legacy_display_names if _find_owner(reg, norm_subject(n)) is None}
    )
    missing_from_legacy: list[str] = []
    if legacy_display_names:
        legacy_norms = {norm_subject(n) for n in legacy_display_names}
        registry_norms: dict[str, str] = {}
        for e in reg.entities:
            for s in [e.name, *e.aliases]:
                registry_norms.setdefault(norm_subject(s), s)
        missing_from_legacy = sorted(
            display for key, display in registry_norms.items() if key not in legacy_norms
        )

    # ── report ────────────────────────────────────────────────────────────
    print("=== Grouping drift (primary, high-confidence) ===")
    if grouping_findings:
        for f in grouping_findings:
            print(f"  {f}")
    else:
        print("  none")

    print("\n=== Fuzzy near-duplicates (secondary — review, do not assume) ===")
    if fuzzy_findings:
        for f in fuzzy_findings:
            print(f"  {f}")
    else:
        print("  none")

    print("\n=== Presence drift (informational) ===")
    print(f"  in legacy store(s) but not in registry ({len(missing_from_registry)}):")
    for n in missing_from_registry:
        print(f"    {n}")
    print(f"  in registry but not in any scanned legacy store ({len(missing_from_legacy)}):")
    for n in missing_from_legacy:
        print(f"    {n}")

    print(
        f"\nSummary: {len(grouping_findings)} grouping-drift, "
        f"{len(fuzzy_findings)} fuzzy-near-dup, "
        f"{len(missing_from_registry)} missing-from-registry, "
        f"{len(missing_from_legacy)} missing-from-legacy"
    )

    return 1 if (grouping_findings or fuzzy_findings) else 0


# ── triage-candidates ────────────────────────────────────────────────────────
#
# Deterministically diffs proper nouns found in a campaign's session outputs
# against the registry and emits a queue JSON of UNKNOWN surface forms for
# the (separate, interactive) entity-triage skill to walk with the GM.
# Identity is a precision decision — this command only surfaces candidates;
# it never decides who is who. No API calls.

# Registry candidates are sourced from the ensemble fact analysis
# (_MERGED_JSON_GLOBS) whenever the campaign has one. Raw summaries
# (_SUMMARY_GLOBS) are UPSTREAM of the ensemble — they produce it — so they are
# only a legacy fallback for campaigns that have no ensemble at all. See
# _gather_triage_sources for the auto-detect and the rationale.
_SUMMARY_GLOBS = [
    "summaries/*/session-summary.md",
    "summaries/*/scene_extractions_new/*.md",
    "summaries/*/scene_extractions/*.md",
    "summaries/old/*/scene_extractions*/*.md",
]

# Both are kept on purpose: the top-level merge is the hand-curated known-set,
# and the per-chapter merges surface gaps the curated set is missing.
_MERGED_JSON_GLOBS = [
    "docs/ensemble/per_chapter/*/merged.json",
    "docs/ensemble/merged.json",
]


def _merged_json_text(path: Path) -> "str | None":
    """Concatenated subject+fact text for every fact dict in a merged.json list.

    ``subject`` is a descriptive phrase, not a clean name, so proper nouns are
    tokenized out of the combined text rather than used verbatim. Returns None
    (and lets the caller warn) if the file isn't parseable JSON.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    parts = []
    for fact in data:
        if not isinstance(fact, dict):
            continue
        subject = fact.get("subject") or ""
        fact_text = fact.get("fact") or ""
        parts.append(f"{subject} {fact_text}")
    return "\n".join(parts)


def _gather_triage_sources(campaign_dir: Path, bible: "Path | None") -> "tuple[list[tuple[str, str]], list[str]]":
    """[(source_label, text)] for every source file found, tolerating any/all
    being absent, plus the list of glob patterns (+ bible path) that matched
    at least one file — for the ``generated_from`` field of the queue JSON.

    Source auto-detection: the registry is sourced from the ensemble fact
    analysis (``_MERGED_JSON_GLOBS`` — the hand-curated top-level merge plus the
    per-chapter merges that surface gaps the curated set misses) whenever the
    campaign has an ensemble. Raw summaries are UPSTREAM of the ensemble — they
    *produce* it — so they are deliberately NOT scanned when an ensemble exists;
    scanning them re-derives entities from noisy transcript prose and pulls in
    archived (``summaries/old``) content. Only campaigns with no ensemble at all
    fall back to scanning summaries directly. An explicit ``--bible`` is always
    honored on top of whichever source was selected.
    """
    sources: list[tuple[str, str]] = []
    generated_from: list[str] = []

    def _add_json(patterns: "list[str]") -> None:
        for pattern in patterns:
            matches = sorted(campaign_dir.glob(pattern))
            if matches:
                generated_from.append(pattern)
            for f in matches:
                label = str(f.relative_to(campaign_dir))
                text = _merged_json_text(f)
                if text is None:
                    print(f"WARNING: could not parse {f} as a fact-list JSON", file=sys.stderr)
                    continue
                sources.append((label, text))

    def _add_summaries(patterns: "list[str]") -> None:
        for pattern in patterns:
            matches = sorted(campaign_dir.glob(pattern))
            if matches:
                generated_from.append(pattern)
            for f in matches:
                label = str(f.relative_to(campaign_dir))
                sources.append((label, f.read_text(encoding="utf-8")))

    has_ensemble = any(
        next(campaign_dir.glob(pattern), None) is not None
        for pattern in _MERGED_JSON_GLOBS
    )
    if has_ensemble:
        _add_json(_MERGED_JSON_GLOBS)
    else:
        _add_summaries(_SUMMARY_GLOBS)

    if bible is not None:
        label = str(bible)
        sources.append((label, bible.read_text(encoding="utf-8")))
        generated_from.append(label)

    return sources, generated_from


def _registry_catalog(reg: Registry) -> "list[tuple[str, str, int]]":
    """[(display_string, norm_key, entity_idx)] for every registered name/alias."""
    catalog: list[tuple[str, str, int]] = []
    for idx, e in enumerate(reg.entities):
        catalog.append((e.name, norm_subject(e.name), idx))
        for alias in e.aliases:
            catalog.append((alias, norm_subject(alias), idx))
    return catalog


def _suppressed_pairs(reg: Registry) -> "set[frozenset]":
    """Normalized-key pairs already settled by a GM ruling (distinct or
    rejected-aliases) — a near-miss hint must not re-suggest these."""
    suppressed: set[frozenset] = set()
    for pair in reg.distinct:
        if len(pair) == 2:
            suppressed.add(frozenset(norm_subject(x) for x in pair))
    for group in reg.rejected_aliases:
        keys = [norm_subject(m) for m in group]
        for a, b in itertools.combinations(keys, 2):
            suppressed.add(frozenset((a, b)))
    return suppressed


def _best_near_miss(
    reg: Registry,
    norm_key: str,
    catalog: "list[tuple[str, str, int]]",
    suppressed: "set[frozenset]",
) -> "dict | None":
    """Best-matching registry entity for an unknown surface form's normalized
    key, or None if nothing clears ``NEAR_MISS_THRESHOLD`` or the best match
    is a settled GM ruling (an already-decided distinct pair or rejected
    alias group) — those must not be re-suggested."""
    best: "tuple[float, str, int] | None" = None  # (ratio, matched_norm_key, entity_idx)
    for _display, key, idx in catalog:
        ratio = SequenceMatcher(None, norm_key, key).ratio()
        if best is None or ratio > best[0]:
            best = (ratio, key, idx)
    if best is None or best[0] < NEAR_MISS_THRESHOLD:
        return None
    ratio, matched_key, idx = best
    if frozenset((norm_key, matched_key)) in suppressed:
        return None
    return {"name": reg.entities[idx].name, "ratio": round(ratio, 3)}


def cmd_triage_candidates(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = find_registry(campaign_dir)
    if path is None:
        print(
            f"Error: no registry at {_registry_path(campaign_dir)} — "
            f"run `registry init {campaign_dir}` first",
            file=sys.stderr,
        )
        return 1

    reg = load_registry(path)
    bible = Path(args.bible) if args.bible else None
    sources, generated_from = _gather_triage_sources(campaign_dir, bible)

    total_count: "dict[str, int]" = defaultdict(int)
    source_labels: "dict[str, set[str]]" = defaultdict(set)
    for label, text in sources:
        for surface, n in spell_canon.proper_noun_counts(text, args.min_len).items():
            total_count[surface] += n
            source_labels[surface].add(label)

    known = reg.known_names(extra=load_pc_names(campaign_dir))
    catalog = _registry_catalog(reg)
    suppressed = _suppressed_pairs(reg)

    candidates = []
    for surface, count in total_count.items():
        if count < args.min_count:
            continue
        norm = norm_subject(surface)
        if norm in known:
            continue
        candidates.append({
            "surface": surface,
            "norm": norm,
            "count": count,
            "sources": sorted(source_labels[surface]),
            "near_miss": _best_near_miss(reg, norm, catalog, suppressed),
        })

    candidates.sort(key=lambda c: (-c["count"], c["surface"]))

    payload = {
        "campaign": reg.campaign,
        "generated_from": generated_from,
        "candidates": candidates,
    }
    text_out = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text_out, encoding="utf-8")
    else:
        print(text_out)

    n_hints = sum(1 for c in candidates if c["near_miss"] is not None)
    print(
        f"triage-candidates: {len(candidates)} candidate(s), {n_hints} with near-miss hint(s)",
        file=sys.stderr,
    )
    return 0


# ── mark-distinct / mark-rejected ───────────────────────────────────────────
#
# Validated negative-writers: the (separate) interactive triage skill records
# GM "these are NOT the same entity" rulings through these, not raw YAML
# edits, so every negative still passes through campaignlib.registry.validate.

def cmd_mark_distinct(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = find_registry(campaign_dir)
    if path is None:
        print(
            f"Error: no registry at {_registry_path(campaign_dir)} — "
            f"run `registry init {campaign_dir}` first",
            file=sys.stderr,
        )
        return 1

    reg = load_registry(path)
    _add_distinct_pair(reg, args.name_a, args.name_b)
    save_registry(reg, path)  # raises ValueError (writes nothing) if a/b already resolve to one entity
    print(f"Marked {args.name_a!r} and {args.name_b!r} as distinct entities in {path}")
    return 0


def cmd_mark_rejected(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = find_registry(campaign_dir)
    if path is None:
        print(
            f"Error: no registry at {_registry_path(campaign_dir)} — "
            f"run `registry init {campaign_dir}` first",
            file=sys.stderr,
        )
        return 1
    if len(args.names) < 2:
        print("Error: mark-rejected requires at least 2 names", file=sys.stderr)
        return 1

    reg = load_registry(path)
    _add_rejected_group(reg, args.names)
    save_registry(reg, path)
    print(f"Marked {args.names!r} as a rejected alias group in {path}")
    return 0


# ── alias ────────────────────────────────────────────────────────────────────
#
# Non-interactive counterpart to `add`'s interactive near-miss choice [1]
# ("same entity — add as an alias"). The forthcoming entity-triage skill walks
# `triage-candidates` output with the GM and needs to attach a confirmed
# surface form to an EXISTING entity without answering an input() prompt.
# `--to` may name the entity's canonical spelling or any of its existing
# aliases — either way it resolves through `_find_owner` to one entity. All
# variants are pre-checked before anything is mutated, so a call with N
# variants either lands all N (minus no-op already-attached ones) or writes
# nothing at all.

def cmd_alias(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = find_registry(campaign_dir)
    if path is None:
        print(
            f"Error: no registry at {_registry_path(campaign_dir)} — "
            f"run `registry init {campaign_dir}` first",
            file=sys.stderr,
        )
        return 1

    reg = load_registry(path)

    target_idx = _find_owner(reg, norm_subject(args.to))
    if target_idx is None:
        print(f"Error: no entity matching --to {args.to!r} in the registry", file=sys.stderr)
        return 1
    target = reg.entities[target_idx]

    # Pre-check ALL variants before mutating anything, so a conflict on the
    # 2nd of 3 variants doesn't leave the 1st one partially applied.
    to_append: list[str] = []
    already: list[str] = []
    staged_keys: set[str] = set()
    for variant in args.variants:
        key = norm_subject(variant)
        owner_idx = _find_owner(reg, key)
        if owner_idx == target_idx or key in staged_keys:
            already.append(variant)  # no-op: already the target's name/alias
            continue
        if owner_idx is not None:
            print(
                f"Error: {variant!r} already belongs to a different entity "
                f"{reg.entities[owner_idx].name!r} — refusing to move it "
                f"(mark-distinct if they are truly separate)",
                file=sys.stderr,
            )
            return 1
        to_append.append(variant)
        staged_keys.add(key)

    if not to_append:
        print(f"Nothing to do — all already aliases of {target.name!r}")
        return 0

    target.aliases.extend(to_append)
    try:
        validate(reg)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    save_registry(reg, path)

    print(f"Attached {to_append!r} as alias(es) of {target.name!r} in {path}")
    if already:
        print(f"  (already attached, skipped: {already!r})")
    return 0


# ── merge ──────────────────────────────────────────────────────────────────
#
# The positive counterpart to `mark-distinct` / `mark-rejected`: fold one or
# more EXISTING entities into a target entity (they turn out to be the same
# thing). `alias` deliberately refuses to move a surface form already owned by
# another entity ("mark-distinct if they are truly separate"); `merge` is the
# sanctioned way to reconcile two already-registered spellings into one — the
# operation that "GM resolves grouping drift" means in a Phase 5 migration,
# where an inventory-provenance spelling and a dossier-provenance spelling each
# registered as their own entity. Destructive (removes the folded entities), so
# it is an explicit named verb, not an `alias` auto-merge. Anti-merge guards win
# (a distinct/rejected pair refuses); target wins on a type mismatch (warned);
# all targets are pre-checked so the call is atomic (lands all or writes nothing).

def cmd_merge(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = find_registry(campaign_dir)
    if path is None:
        print(
            f"Error: no registry at {_registry_path(campaign_dir)} — "
            f"run `registry init {campaign_dir}` first",
            file=sys.stderr,
        )
        return 1

    reg = load_registry(path)

    target_idx = _find_owner(reg, norm_subject(args.into))
    if target_idx is None:
        print(f"Error: no entity matching --into {args.into!r} in the registry", file=sys.stderr)
        return 1
    target = reg.entities[target_idx]

    # Pre-check ALL others before mutating anything, so one bad name (missing,
    # or guarded) doesn't leave a partial merge.
    to_merge: list[int] = []
    already: list[str] = []
    seen: set[int] = {target_idx}
    for other in args.others:
        oidx = _find_owner(reg, norm_subject(other))
        if oidx is None:
            print(f"Error: no entity matching {other!r} in the registry", file=sys.stderr)
            return 1
        if oidx == target_idx:
            already.append(other)  # already the target (its name or an alias)
            continue
        if oidx in seen:
            continue  # same other named twice
        blocked = _guard_blocks_merge(reg, target, reg.entities[oidx])
        if blocked:
            print(
                f"Error: refusing to merge {reg.entities[oidx].name!r} into "
                f"{target.name!r} — {blocked}. Remove that guard first if they "
                f"really are the same entity.",
                file=sys.stderr,
            )
            return 1
        to_merge.append(oidx)
        seen.add(oidx)

    if not to_merge:
        print(f"Nothing to do — all already part of {target.name!r}")
        return 0

    target_key = norm_subject(target.name)
    existing_alias_keys = {norm_subject(a) for a in target.aliases}
    merged_names: list[str] = []
    type_warnings: list[str] = []
    for oidx in to_merge:
        other = reg.entities[oidx]
        merged_names.append(other.name)
        if other.type != target.type:
            type_warnings.append(
                f"{other.name!r} was type {other.type!r}, folded into "
                f"{target.name!r} (type {target.type!r})"
            )
        # Every name/alias is unique across entities (validate guarantees), so
        # these strings belonged solely to ``other`` — fold them in, skipping
        # only the target's own name and aliases it already carries.
        for s in [other.name, *other.aliases]:
            skey = norm_subject(s)
            if not skey or skey == target_key or skey in existing_alias_keys:
                continue
            target.aliases.append(s)
            existing_alias_keys.add(skey)
        if target.provenance is None and other.provenance is not None:
            target.provenance = other.provenance
        if target.source is None and other.source is not None:
            target.source = other.source
        if target.note is None and other.note is not None:
            target.note = other.note

    remove = set(to_merge)
    reg.entities = [e for i, e in enumerate(reg.entities) if i not in remove]

    try:
        validate(reg)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    save_registry(reg, path)

    print(f"Merged {merged_names!r} into {target.name!r} in {path}")
    for w in type_warnings:
        print(f"  warning: {w}", file=sys.stderr)
    if already:
        print(f"  (already part of {target.name!r}, skipped: {already!r})")
    return 0


# ── CLI wiring ───────────────────────────────────────────────────────────────

def main(argv: "list[str] | None" = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="create an empty entity registry")
    pi.add_argument("campaign_dir")
    pi.add_argument("--campaign", default=None, help="campaign name (default: campaign_dir basename)")
    pi.set_defaults(func=cmd_init)

    pa = sub.add_parser("add", help="add one entity to the registry")
    pa.add_argument("campaign_dir")
    pa.add_argument("--name", required=True)
    pa.add_argument("--type", required=True)
    pa.add_argument("--aliases", nargs="+", default=None)
    pa.add_argument("--provenance", default=None)
    pa.add_argument("--source", default=None)
    pa.add_argument("--scope", default=None)
    pa.add_argument("--note", default=None)
    pa.add_argument("--yes", action="store_true", help="skip the near-miss prompt; add as new")
    pa.set_defaults(func=cmd_add)

    pp = sub.add_parser("project", help="write aliases.json + entity_inventory.md projections")
    pp.add_argument("campaign_dir")
    pp.set_defaults(func=cmd_project)

    pii = sub.add_parser(
        "import-inventory",
        help="merge entities from an inventory markdown file (## Heading sections of bullets)",
    )
    pii.add_argument("campaign_dir")
    pii.add_argument("md")
    pii.add_argument("--provenance", default=None)
    pii.add_argument("--source", default=None)
    pii.add_argument(
        "--heading-type",
        action="append",
        default=None,
        metavar="Heading=type",
        help='override the type inferred for a heading, e.g. "Outside Candlekeep=location" (repeatable)',
    )
    pii.set_defaults(func=cmd_import_inventory)

    pid = sub.add_parser(
        "import-dedup",
        help="merge NPC entities + anti-merge guards from a .dedup_state.json file",
    )
    pid.add_argument("campaign_dir")
    pid.add_argument("json")
    pid.set_defaults(func=cmd_import_dedup)

    pif = sub.add_parser(
        "import-frontmatter",
        help="merge NPC entities from dossier frontmatter (campaignlib.npc.load_alias_map)",
    )
    pif.add_argument("campaign_dir")
    pif.add_argument("dossier_dir")
    pif.set_defaults(func=cmd_import_frontmatter)

    pad = sub.add_parser(
        "import-alias-decisions",
        help="ENRICH-ONLY: add aliases to already-registered entities from an "
             ".alias_decisions.json file; never creates new entities",
    )
    pad.add_argument("campaign_dir")
    pad.add_argument("json")
    pad.set_defaults(func=cmd_import_alias_decisions)

    pc = sub.add_parser(
        "check",
        help="surface drift between the registry and legacy scattered stores (report-only)",
    )
    pc.add_argument("campaign_dir")
    pc.set_defaults(func=cmd_check)

    ptc = sub.add_parser(
        "triage-candidates",
        help="diff proper nouns in session outputs against the registry; emit an "
             "UNKNOWN-surface-form queue JSON for the entity-triage skill",
    )
    ptc.add_argument("campaign_dir")
    ptc.add_argument("--out", default=None, help="write queue JSON here (default: stdout)")
    ptc.add_argument("--bible", default=None, help="also scan this bible file's text")
    ptc.add_argument("--min-len", type=int, default=spell_canon.DEFAULT_MIN_LEN)
    ptc.add_argument("--min-count", type=int, default=1)
    ptc.set_defaults(func=cmd_triage_candidates)

    pmd = sub.add_parser(
        "mark-distinct",
        help="record NAME_A and NAME_B as DIFFERENT entities (validated write)",
    )
    pmd.add_argument("campaign_dir")
    pmd.add_argument("name_a")
    pmd.add_argument("name_b")
    pmd.set_defaults(func=cmd_mark_distinct)

    pmr = sub.add_parser(
        "mark-rejected",
        help="record NAME... as a rejected (never-merge) alias group (validated write)",
    )
    pmr.add_argument("campaign_dir")
    pmr.add_argument("names", nargs="+")
    pmr.set_defaults(func=cmd_mark_rejected)

    pal = sub.add_parser(
        "alias",
        help="non-interactively attach one or more surface forms as aliases of an "
             "existing entity (looked up by canonical name or existing alias)",
    )
    pal.add_argument("campaign_dir")
    pal.add_argument("--to", required=True, help="canonical name or existing alias of the target entity")
    pal.add_argument("variants", nargs="+", help="surface form(s) to attach as alias(es)")
    pal.set_defaults(func=cmd_alias)

    pmg = sub.add_parser(
        "merge",
        help="fold one or more EXISTING entities into a target entity (they are "
             "the same thing); refuses if they are marked distinct/rejected",
    )
    pmg.add_argument("campaign_dir")
    pmg.add_argument("--into", required=True, help="canonical name or alias of the surviving target entity")
    pmg.add_argument("others", nargs="+", help="canonical name(s) or alias(es) of the entity/entities to fold in")
    pmg.set_defaults(func=cmd_merge)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
