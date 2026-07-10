"""Shared planning configuration data models and I/O logic.

This module contains the core data structures and YAML handling logic
used by both the PlanningConfigService (web API) and planning.py (CLI).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import yaml


@dataclass
class PlanningEntry:
    """Represents a single NPC or faction in the planning configuration.
    
    The arc_score field uses None to represent three distinct states:
    - None (field not set): key absent in YAML -> trackless=False, no track
    - None (explicitly set to None): arc_score: null in YAML -> trackless=True
    - str: arc_score: /path/to/file in YAML -> trackless=False, tracked
    """
    name: str
    dossier: Optional[Path] = None       # NPC entries only; None for factions
    arc_score: Optional[Path] = None
    trackless: bool = False              # True when arc_score is explicitly null


@dataclass
class PlanningConfig:
    """Complete planning configuration containing NPCs and factions."""
    npcs: List[PlanningEntry] = field(default_factory=list)
    factions: List[PlanningEntry] = field(default_factory=list)


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
        key absent      -> arc_score=None, trackless=False
        key present, null -> arc_score=None, trackless=True
        key present, path -> arc_score=Path, trackless=False
    
    NPC entries require `dossier`. Faction entries do not. All paths resolve
    against the config file's parent directory; missing files are a hard error.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {path}: {e}")

    base = path.parent

    def _resolve(rel: str, field_name: str, entry_name: str) -> Path:
        p = (base / rel).expanduser().resolve()
        if not p.exists():
            raise ValueError(f"planning config references missing file for "
                           f"{entry_name}.{field_name}: {p}")
        return p

    def _parse_entry(entry: dict, kind: str) -> PlanningEntry:
        if not isinstance(entry, dict):
            raise ValueError(f"each {kind} entry in {path} must be a mapping")
        name = entry.get("name")
        if not name:
            raise ValueError(f"{kind} entry in {path} missing 'name': {entry}")

        dossier = None
        if kind == "npc":
            dossier_rel = entry.get("dossier")
            if not dossier_rel:
                raise ValueError(f"npc entry {name!r} in {path} missing 'dossier'")
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
        raise ValueError(f"{path} must define 'npcs' and/or 'factions' as lists")
    if not npcs_raw and not factions_raw:
        raise ValueError(f"{path} must define a non-empty 'npcs' or 'factions' list")

    return PlanningConfig(
        npcs=[_parse_entry(e, "npc") for e in npcs_raw],
        factions=[_parse_entry(e, "faction") for e in factions_raw],
    )


def save_planning_config(path: Path, config: PlanningConfig) -> None:
    """Save a PlanningConfig to YAML file at the given path.
    
    The output format matches exactly what load_planning_config expects:
    - NPC entries require dossier field
    - Faction entries have optional dossier
    - arc_score handling:
        * None (not set): key omitted in YAML
        * None (explicit): arc_score: null
        * Path: arc_score: /path/to/file
    """
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    def _build_entry_dict(entry: PlanningEntry) -> dict:
        result = {"name": entry.name}
        
        # Handle dossier
        if entry.dossier is not None:
            result["dossier"] = str(entry.dossier)
            
        # Handle arc_score with three-state logic
        if entry.arc_score is None:
            if entry.trackless:
                # Explicitly trackless -> arc_score: null
                result["arc_score"] = None
            # Else: trackless=False and arc_score=None -> key omitted
        else:
            # arc_score is a Path -> write the path
            result["arc_score"] = str(entry.arc_score)
            
        return result
    
    data = {
        "npcs": [_build_entry_dict(e) for e in config.npcs],
        "factions": [_build_entry_dict(e) for e in config.factions]
    }
    
    # Remove empty lists to match expected format
    if not data["npcs"]:
        data.pop("npcs")
    if not data["factions"]:
        data.pop("factions")
        
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")