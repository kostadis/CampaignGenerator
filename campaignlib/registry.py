"""registry.py — campaign entity registry loader.

The entity registry (``<campaign-dir>/docs/entity_registry.yaml``) is meant to
become the SINGLE authority for entity identity — canonical spelling, known
aliases, and the anti-merge guards (``distinct``, ``rejected_aliases``) that
today live scattered across dossier frontmatter, ``aliases.json``,
``.alias_decisions.json``, module inventories, and ``.dedup_state.json``.

This module is the LOADER library only: parse the YAML, validate its
identity invariants, and expose projections shaped exactly like the
consumers that already exist (``synthesise_world_state.load_aliases``,
``campaignlib.npc.load_alias_map``, the ``**bold**``-span inventory markdown
that ``facts_to_state.load_known_names`` and ``spell_canon.inventory_tokens``
parse). It is NOT a CLI and does not write the file — a later packet adds the
CLI and any importers that populate it from the existing scattered stores.

On-disk contract::

    version: 1
    campaign: out-of-the-abyss
    entities:
      - name: Ilvara Mizzrym         # canonical spelling — authoritative
        type: npc                    # npc|location|faction|item|deity|event|concept
        aliases: [Ilvara, Mistress Ilvara]
        provenance: module           # module|supplement|on_the_fly
        source: OotA                 # source id; omit for on_the_fly
        scope: persistent            # persistent|chapter-N|scene
        note: senior drow priestess
    distinct:                        # anti-merge guards: ruled DIFFERENT entities
      - [Topsy, Turvy]
    rejected_aliases:                # settled negatives; never re-propose
      - [Shoor, Stool]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from campaignlib.textproc import norm_subject

VALID_TYPES = {"npc", "location", "faction", "item", "deity", "event", "concept"}
VALID_PROVENANCE = {"module", "supplement", "on_the_fly", None}

_CHAPTER_SCOPE_RE = re.compile(r"^chapter-\d+$")

# Readable section headings for inventory_markdown(), keyed by entity type.
_TYPE_HEADINGS = {
    "npc": "NPCs",
    "location": "Locations",
    "faction": "Factions",
    "item": "Items",
    "deity": "Deities",
    "event": "Events",
    "concept": "Concepts",
}


@dataclass
class Entity:
    name: str
    type: str
    aliases: list[str] = field(default_factory=list)
    provenance: str | None = None
    source: str | None = None
    scope: str = "persistent"
    note: str | None = None


@dataclass
class Registry:
    version: int
    campaign: str | None
    entities: list[Entity]
    distinct: list[list[str]] = field(default_factory=list)
    rejected_aliases: list[list[str]] = field(default_factory=list)
    source_path: Path | None = None  # stashed for find_registry() callers

    # ── projections consumed by existing pipelines ──────────────────────

    def alias_to_canonical(self) -> dict[str, str]:
        """Flat ``{variant: canonical}``, RAW (non-normalized) strings.

        Canonicals self-map. This is the same shape
        ``synthesise_world_state.load_aliases`` produces when reading an
        ``aliases.json`` projected from this registry.
        """
        flat: dict[str, str] = {}
        for e in self.entities:
            flat[e.name] = e.name
            for alias in e.aliases:
                flat[alias] = e.name
        return flat

    def canonical_to_aliases(self) -> dict[str, list[str]]:
        """``{canonical_name: [aliases]}`` — same shape as ``npc.load_alias_map``."""
        return {e.name: list(e.aliases) for e in self.entities}

    def known_names(self, extra=()) -> set[str]:
        """Normalized (``norm_subject``) set of every name and alias.

        Also applies the ``facts_to_state.load_known_names`` first-token
        rule: for any multi-word name/alias whose first word is >= 4 chars,
        that first word's normalized form is added too (catches short-name
        fact subjects, e.g. "Adabra" from "Adabra Gwynn").

        This method does NOT read party.yaml / player-character names — the
        registry file itself has no notion of PCs. Callers pass PC names (or
        any other out-of-band known names) via ``extra``; wiring that up
        from party.yaml is Phase 2's job, not this loader's.
        """
        known: set[str] = set()
        for e in self.entities:
            for s in [e.name, *e.aliases]:
                key = norm_subject(s)
                if key:
                    known.add(key)
                parts = s.split()
                if len(parts) > 1 and len(parts[0]) >= 4:
                    known.add(norm_subject(parts[0]))
        for x in extra:
            known.add(norm_subject(x))
        return known

    def inventory_markdown(self, types: "list[str] | None" = None) -> str:
        """Render a markdown inventory grouped by type, one bullet per entity.

        ``types``, if given, restricts output to those entity types.

        CRITICAL FORMATTING: each canonical name and each alias gets its OWN
        ``**bold**`` span, with `` / `` separators OUTSIDE the bold markers
        — never ``**Name / Alias**``. ``facts_to_state._BOLD_RE`` and
        ``spell_canon.inventory_tokens`` both operate on whole bold spans (the
        latter additionally splits on ``/``); a slash INSIDE a span would let
        two distinct names bleed into one garbage combined token.
        """
        wanted = set(types) if types else None
        by_type: dict[str, list[Entity]] = {}
        for e in self.entities:
            if wanted is not None and e.type not in wanted:
                continue
            by_type.setdefault(e.type, []).append(e)

        lines: list[str] = []
        for t in sorted(by_type):
            heading = _TYPE_HEADINGS.get(t, t.capitalize())
            lines.append(f"## {heading}")
            lines.append("")
            for e in by_type[t]:
                spans = " / ".join(f"**{s}**" for s in [e.name, *e.aliases])
                line = f"- {spans}"
                if e.note:
                    line += f" — {e.note}"
                lines.append(line)
            lines.append("")
        return "\n".join(lines).rstrip("\n") + "\n"


def _valid_scope(scope: str) -> bool:
    return scope in ("persistent", "scene") or bool(_CHAPTER_SCOPE_RE.match(scope or ""))


def _validate(reg: Registry) -> None:
    """Enforce the registry's identity invariants; raise ValueError on any violation."""
    owner: dict[str, int] = {}  # normalized string -> index of the owning entity

    for idx, e in enumerate(reg.entities):
        if e.type not in VALID_TYPES:
            raise ValueError(
                f"entity {e.name!r} has invalid type {e.type!r}; "
                f"must be one of {sorted(VALID_TYPES)}"
            )
        if e.provenance not in VALID_PROVENANCE:
            raise ValueError(
                f"entity {e.name!r} has invalid provenance {e.provenance!r}; "
                f"must be one of {sorted(p for p in VALID_PROVENANCE if p)} or omitted"
            )
        if not _valid_scope(e.scope):
            raise ValueError(
                f"entity {e.name!r} has invalid scope {e.scope!r}; "
                f"must be 'persistent', 'scene', or 'chapter-<int>'"
            )

        for s in [e.name, *e.aliases]:
            key = norm_subject(s)
            if not key:
                continue
            if key in owner and owner[key] != idx:
                other = reg.entities[owner[key]]
                raise ValueError(
                    f"identity collision: {s!r} (normalized {key!r}) is claimed by "
                    f"both {other.name!r} and {e.name!r} — every name/alias must "
                    f"resolve to exactly one entity"
                )
            owner[key] = idx

    for pair in reg.distinct:
        if len(pair) != 2:
            raise ValueError(f"distinct pair must have exactly 2 members: {pair!r}")
        a, b = pair
        idx_a = owner.get(norm_subject(a))
        idx_b = owner.get(norm_subject(b))
        if idx_a is not None and idx_a == idx_b:
            raise ValueError(
                f"distinct pair {pair!r} both resolve to entity "
                f"{reg.entities[idx_a].name!r} — cannot be declared both DIFFERENT "
                f"(distinct) and the SAME entity (aliased together)"
            )


def load_registry(path) -> Registry:
    """Parse and validate an entity_registry.yaml file; raise ValueError on any
    invariant violation (see module docstring for the on-disk contract)."""
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    entities = [
        Entity(
            name=e["name"],
            type=e.get("type"),
            aliases=list(e.get("aliases") or []),
            provenance=e.get("provenance"),
            source=e.get("source"),
            scope=e.get("scope") or "persistent",
            note=e.get("note"),
        )
        for e in (data.get("entities") or [])
    ]
    distinct = [list(pair) for pair in (data.get("distinct") or [])]
    rejected_aliases = [list(pair) for pair in (data.get("rejected_aliases") or [])]

    reg = Registry(
        version=data.get("version", 1),
        campaign=data.get("campaign"),
        entities=entities,
        distinct=distinct,
        rejected_aliases=rejected_aliases,
        source_path=path,
    )
    _validate(reg)
    return reg


def find_registry(campaign_dir) -> "Path | None":
    """Return ``<campaign_dir>/docs/entity_registry.yaml`` if it exists, else None."""
    p = Path(campaign_dir) / "docs" / "entity_registry.yaml"
    return p if p.is_file() else None


def _entity_to_dict(e: Entity) -> dict:
    """Ordered dict for one entity, omitting unset/default fields (see dump_registry)."""
    d: dict = {"name": e.name, "type": e.type}
    if e.aliases:
        d["aliases"] = list(e.aliases)
    if e.provenance is not None:
        d["provenance"] = e.provenance
    if e.source is not None:
        d["source"] = e.source
    if e.scope != "persistent":
        d["scope"] = e.scope
    if e.note is not None:
        d["note"] = e.note
    return d


def dump_registry(reg: Registry) -> str:
    """Serialize a Registry to YAML text that ``load_registry`` round-trips exactly.

    Field order per entity: name, type, aliases, provenance, source, scope,
    note. Keys with a None value (or an empty ``aliases`` list) are omitted;
    ``scope`` is omitted when it is the default ``"persistent"`` since
    ``load_registry`` defaults it back on load. Top-level order is version,
    campaign, entities, then distinct/rejected_aliases only if non-empty.
    ``source_path`` is runtime-only and is never emitted.
    """
    data: dict = {
        "version": reg.version,
        "campaign": reg.campaign,
        "entities": [_entity_to_dict(e) for e in reg.entities],
    }
    if reg.distinct:
        data["distinct"] = [list(pair) for pair in reg.distinct]
    if reg.rejected_aliases:
        data["rejected_aliases"] = [list(pair) for pair in reg.rejected_aliases]
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)


def save_registry(reg: Registry, path) -> None:
    """Write ``dump_registry(reg)`` to ``path`` (utf-8)."""
    Path(path).write_text(dump_registry(reg), encoding="utf-8")
