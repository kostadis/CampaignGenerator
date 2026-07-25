"""Planning configuration — models and YAML I/O for ``<config>/planning.yaml``.

Phase 1 of ``docs/config/grounding-isolation.md``. Mirrors
:mod:`campaignlib.party_config` field for field; see that module's docstring
for the authored-vs-resolved split and the strict-vs-lenient rule, which apply
identically here.

Three duplicate definitions collapse into this one. Before it,
``PlanningEntry``/``PlanningConfig`` existed as dataclasses in
``server/planning_config_shared.py`` **and again**, verbatim, as local
dataclasses in ``pipelines/grounding/planning.py`` — which also imported the
server copies, so the imported names were shadowed and dead.

The round-trip bug this fixes is concrete rather than theoretical:
``save_planning_config`` wrote ``str(entry.dossier)`` where ``dossier`` was the
absolute ``Path`` the loader had resolved, so every edit through
``PlanningConfigService`` rewrote the GM's relative references as
machine-specific absolute ones.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from campaignlib.util import atomic_write_text

PLANNING_CONFIG_FILENAME = "planning.yaml"


def _as_authored(v: Any) -> Any:
    """Accept a ``Path`` at the boundary, store the string.

    Callers that already hold a ``Path`` (the CLI, tests) shouldn't have to
    stringify it, but there is exactly one internal representation so a
    load/save round-trip cannot rewrite what the GM authored.
    """
    return str(v) if isinstance(v, Path) else v


AuthoredPath = Annotated[str | None, BeforeValidator(_as_authored)]

#: Per-entry path fields, in the order they are rendered and reported.
PATH_FIELDS: tuple[str, ...] = ("dossier", "arc_score")


class PlanningEntry(BaseModel):
    """One NPC or faction, with paths exactly as authored.

    A single unified model serves both collections — the shipped
    ``planning-isolation.md`` implementation already deviated from its own spec
    this way, and the only real difference is that ``dossier`` is required for
    NPCs and optional for factions, which is a per-collection validation rule
    rather than a different shape.

    ``arc_score`` + ``trackless`` carry the same three states documented on
    :class:`campaignlib.party_config.PartyCharacter`.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    dossier: AuthoredPath = None
    arc_score: AuthoredPath = None
    trackless: bool = False


class PlanningConfig(BaseModel):
    """Root model — the ``<config>/planning.yaml`` shape."""

    model_config = ConfigDict(extra="forbid")

    npcs: list[PlanningEntry] = Field(default_factory=list)
    factions: list[PlanningEntry] = Field(default_factory=list)


class ResolvedEntry(BaseModel):
    """A :class:`PlanningEntry` with its paths resolved against a base dir."""

    model_config = ConfigDict(extra="forbid")

    name: str
    dossier: Path | None = None
    arc_score: Path | None = None
    trackless: bool = False


def _parse_entry(entry: Any, kind: str, path: Path) -> PlanningEntry:
    if not isinstance(entry, dict):
        raise ValueError(f"each {kind} entry in {path} must be a mapping")
    name = entry.get("name")
    if not name:
        raise ValueError(f"{kind} entry in {path} missing 'name': {entry}")

    dossier = entry.get("dossier")
    if kind == "npc" and not dossier:
        raise ValueError(f"npc entry {name!r} in {path} missing 'dossier'")

    if "arc_score" in entry:
        trackless = entry["arc_score"] is None
        arc_score = None if trackless else str(entry["arc_score"])
    else:
        trackless = False
        arc_score = None

    return PlanningEntry(
        name=str(name),
        dossier=str(dossier) if dossier else None,
        arc_score=arc_score,
        trackless=trackless,
    )


def load_planning_config(path: Path) -> PlanningConfig:
    """Load ``planning.yaml`` and validate its *shape* only.

    Missing file or empty document → empty :class:`PlanningConfig`, for the
    same reason :func:`campaignlib.party_config.load_party_config` does it.
    Malformed YAML or a structurally invalid entry raises ``ValueError``.
    """
    if not path.exists():
        return PlanningConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not raw:
        return PlanningConfig()
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top level must be a mapping")

    npcs_raw = raw.get("npcs") or []
    factions_raw = raw.get("factions") or []
    if not isinstance(npcs_raw, list) or not isinstance(factions_raw, list):
        raise ValueError(f"{path} must define 'npcs' and/or 'factions' as lists")

    return PlanningConfig(
        npcs=[_parse_entry(e, "npc", path) for e in npcs_raw],
        factions=[_parse_entry(e, "faction", path) for e in factions_raw],
    )


def save_planning_config(path: Path, cfg: PlanningConfig) -> None:
    """Write ``cfg`` to ``path`` atomically, preserving paths as authored.

    Empty collections are omitted rather than written as ``npcs: []``, matching
    the shape the loader and the hand-authored files use.
    """

    def _entry_dict(entry: PlanningEntry) -> dict[str, Any]:
        out: dict[str, Any] = {"name": entry.name}
        if entry.dossier:
            out["dossier"] = entry.dossier
        if entry.trackless:
            out["arc_score"] = None
        elif entry.arc_score:
            out["arc_score"] = entry.arc_score
        return out

    data: dict[str, Any] = {}
    if cfg.npcs:
        data["npcs"] = [_entry_dict(e) for e in cfg.npcs]
    if cfg.factions:
        data["factions"] = [_entry_dict(e) for e in cfg.factions]

    atomic_write_text(
        path,
        yaml.safe_dump(
            data, default_flow_style=False, sort_keys=False, allow_unicode=True
        ),
    )


def missing_files(cfg: PlanningConfig, base: Path) -> dict[str, list[str]]:
    """Report referenced files that do not exist, as ``{name: [field, …]}``."""
    report: dict[str, list[str]] = {}
    for entry in [*cfg.npcs, *cfg.factions]:
        absent = [
            field
            for field in PATH_FIELDS
            if (rel := getattr(entry, field))
            and not (base / rel).expanduser().exists()
        ]
        if absent:
            report[entry.name] = absent
    return report


def resolve_entries(
    entries: list[PlanningEntry], base: Path, *, require_files: bool = True
) -> list[ResolvedEntry]:
    """Resolve each entry's paths against ``base``.

    ``base`` is the caller's to supply — see
    :func:`campaignlib.party_config.resolve_party_config` for why it is not
    derived from the config file's own location.
    """
    base = Path(base)

    def _resolve(rel: str | None, field: str, who: str) -> Path | None:
        if not rel:
            return None
        p = (base / rel).expanduser().resolve()
        if require_files and not p.exists():
            raise ValueError(
                f"planning config references missing file for {who}.{field}: {p}"
            )
        return p

    return [
        ResolvedEntry(
            name=e.name,
            dossier=_resolve(e.dossier, "dossier", e.name),
            arc_score=_resolve(e.arc_score, "arc_score", e.name),
            trackless=e.trackless,
        )
        for e in entries
    ]
