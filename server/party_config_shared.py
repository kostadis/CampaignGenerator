"""Shared party configuration data models and I/O logic.

This module contains the core data structures and YAML handling logic
used by both server/routers/ensemble.py (web API) and party.py (CLI).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass
class PartyCharacter:
    name: str
    sheet: Path
    backstory: Optional[Path] = None
    dossier: Optional[Path] = None
    arc_score: Optional[Path] = None
    trackless: bool = False  # True when arc_score is explicitly null in config


@dataclass
class PartyConfig:
    characters: List[PartyCharacter] = field(default_factory=list)


def load_party_config(path: Path) -> PartyConfig:
    """Read a party config YAML file, validate every referenced file, and
    return a PartyConfig.

    The YAML shape is:

        characters:
          - name: Brewbarry
            sheet: docs/party/brewbarry.md
            backstory: docs/Backstory - Brewbarry.md   # optional
            dossier: docs/ensemble/merged_dossiers/npc_brewbarry.md  # optional
            arc_score: docs/tracking/brewbarry-score.md # optional
          - name: Vukradin
            sheet: docs/party/Vukradin.md
            arc_score: null   # intentionally trackless — first-class state

    `dossier` is the character's own ensemble-built current-state dossier
    (from facts_to_state.py's merged_dossiers/) — narrative facts pulled from
    actual play (relationships, decisions, arc progression) that the static
    sheet/backstory don't carry. Which dossier file belongs to which PC is a
    campaign-specific attribution decision, so it is always an explicit,
    human-authored mapping here — never inferred by name-matching.

    Distinction: `arc_score: null` (trackless by design) vs the key being
    absent (unspecified — treated the same as omitted for now, but the
    config author can audit it later).

    Paths resolve against the config file's parent directory. Every
    referenced file must exist — raises ValueError on a missing file or
    malformed config (callers that want CLI-style exit-on-error should
    catch this and sys.exit themselves).
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML in {path}: {e}")

    base = path.parent
    chars_raw = raw.get("characters") or []
    if not isinstance(chars_raw, list) or not chars_raw:
        raise ValueError(f"{path} must define a non-empty 'characters' list")

    def _resolve(rel: str, field_name: str, char_name: str) -> Path:
        p = (base / rel).expanduser().resolve()
        if not p.exists():
            raise ValueError(f"party config references missing file for "
                              f"{char_name}.{field_name}: {p}")
        return p

    characters: List[PartyCharacter] = []
    for entry in chars_raw:
        if not isinstance(entry, dict):
            raise ValueError(f"each character entry in {path} must be a mapping")
        name = entry.get("name")
        sheet_rel = entry.get("sheet")
        if not name or not sheet_rel:
            raise ValueError(f"character entry in {path} missing 'name' or 'sheet': {entry}")
        sheet = _resolve(sheet_rel, "sheet", name)
        backstory = _resolve(entry["backstory"], "backstory", name) if entry.get("backstory") else None
        dossier = _resolve(entry["dossier"], "dossier", name) if entry.get("dossier") else None

        # arc_score distinguishes three cases:
        #   key absent → arc_score=None, trackless=False
        #   key present, value null → arc_score=None, trackless=True
        #   key present, value path → arc_score=Path, trackless=False
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

        characters.append(PartyCharacter(
            name=str(name), sheet=sheet, backstory=backstory, dossier=dossier,
            arc_score=arc_score, trackless=trackless,
        ))

    return PartyConfig(characters=characters)
