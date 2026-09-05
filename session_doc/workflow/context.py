"""Resolve existing campaign declarations once for a production run."""
from pathlib import Path
import re

import yaml
from campaignlib.party_config import load_party_config, resolve_party_config
from campaignlib.players_config import load_players_config
from .storage import WorkflowError


def narrator_selection(party_config: Path, campaign: Path, names: list[str] | None):
    party = resolve_party_config(load_party_config(party_config), campaign, require_files=False)
    declared = [c.name for c in party.characters]
    chosen = declared if names is None else names
    if not chosen or len(set(chosen)) != len(chosen):
        raise WorkflowError("narrator selection must be nonempty and unique")
    invalid = sorted(set(chosen) - set(declared))
    if invalid:
        raise WorkflowError("narrators must exactly match declared characters: " + ", ".join(invalid))
    return party, chosen


def resolve_context(engine, state, stage, options):
    config_dir = Path(state.config).parent
    paths = {}
    evidence = []
    roster = []
    identity = []
    warnings = []
    for key in ("party-config", "players-config"):
        path = Path(options.get(key) or config_dir / (key.removesuffix("-config") + ".yaml"))
        if not path.is_absolute():
            path = engine.campaign / path
        if path.is_file():
            engine.source(str(path))
            paths[key] = str(path)
            evidence.append(engine.store.preserve(path, label="configuration"))
    if "party-config" in paths:
        party, roster = narrator_selection(Path(paths["party-config"]), engine.campaign, options.get("characters"))
        for char in party.characters:
            for key in ("voice", "examples", "sheet"):
                path = getattr(char, key)
                if path and path.is_file():
                    engine.source(str(path))
                    evidence.append(engine.store.preserve(path, label="configuration"))
                elif path:
                    warnings.append(f"missing {key}: {path}")
        for path in party.shared_examples:
            engine.source(str(path))
            evidence.append(engine.store.preserve(path, label="configuration"))
    elif stage in {"plan", "narrate", "identify"}:
        raise WorkflowError("declared party.yaml is required for this production stage")
    if "players-config" in paths:
        players = load_players_config(Path(paths["players-config"]))
        identity = [p.model_dump() for p in players.players]
    elif stage == "identify":
        raise WorkflowError("players.yaml is required; unknown speakers remain unresolved")
    overrides = engine.store.session / "player_overrides.yaml"
    if overrides.exists():
        raw = yaml.safe_load(overrides.read_text())
        if not isinstance(raw, dict) or set(raw) != {"schema_version", "speakers"} or raw["schema_version"] != 1 or not isinstance(raw["speakers"], dict):
            raise WorkflowError("player_overrides.yaml requires schema_version: 1 and a speakers mapping")
        known = {p["id"] for p in identity}
        for speaker, player in raw["speakers"].items():
            if player is not None and player not in known:
                raise WorkflowError(f"unknown player override: {speaker} -> {player}")
        evidence.append(engine.store.preserve(overrides, label="configuration"))
        paths["player_overrides"] = raw
    if stage in {"plan", "narrate"}:
        genre = options.get("narration-genre-file")
        if not genre:
            editor = config_dir / "session_doc.yaml"
            if editor.exists():
                raw = yaml.safe_load(editor.read_text()) or {}
                genre = raw.get("paths", {}).get("genre_file")
                evidence.append(engine.store.preserve(editor, label="configuration"))
        if not genre:
            raise WorkflowError("genre rulebook is required; set paths.genre_file or narration-genre-file")
        path = Path(genre)
        if not path.is_absolute():
            path = engine.campaign / path
        engine.source(str(path))
        if not path.is_file():
            raise WorkflowError(f"missing genre rulebook: {path}")
        paths["narration-genre-file"] = str(path)
        evidence.append(engine.store.preserve(path, label="configuration"))
    return {"paths": paths, "characters": roster, "players": identity, "warnings": warnings}, evidence


def transcript_identity(data: str, players: list[dict], overrides: dict | None = None):
    """Report identities without guessing a character from a human speaker."""
    cues = []
    seen = set()
    speaker_ids = {name: p["id"] for p in players for name in p["display_names"]}
    speaker_ids.update(overrides or {})
    for block in re.split(r"\r?\n\s*\r?\n", data):
        lines = block.strip().splitlines()
        timestamp = next((i for i, line in enumerate(lines) if " --> " in line), None)
        if timestamp is None:
            continue
        cue_id = lines[timestamp - 1] if timestamp else lines[timestamp]
        if cue_id in seen:
            raise WorkflowError(f"duplicate cue identity: {cue_id}")
        seen.add(cue_id)
        text = "\n".join(lines[timestamp + 1:])
        match = re.match(r"(?:<v\s+([^>]+)>|([^:\n]+):)", text)
        speaker = (match.group(1) or match.group(2)).strip() if match else None
        cues.append({"cue_id": cue_id, "speaker": speaker, "player_id": speaker_ids.get(speaker), "character": None, "attribution": "unresolved"})
    return cues
