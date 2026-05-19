"""Config API routes — typed section/runtime/local updates, path helpers.

All persistence flows through ``CampaignConfigService``. There is no
fallback to a raw ``ui_config.yaml`` — when the service is not initialized
the routes return ``503``. The flat-key overlay in ``GET /`` keeps the
un-reshaped Pinia store working; it's computed per-request from the
service's resolved view, not read from disk.
"""

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.config import (
    DEFAULT_MODEL,
    MODELS,
    api_key_present,
    derive_campaign_paths,
    derive_session_paths,
    path_exists,
)
from server.config_service import flatten_resolved_to_legacy
from server.config_models import SCHEMA_VERSION, UI_SECTION_NAMES

router = APIRouter()


def _require_service(request: Request):
    service = getattr(request.app.state, "config_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="config service not initialized — campaign_dir not resolved at boot",
        )
    return service


# ── GET / — typed view + flat-key overlay for legacy frontend code ─────────


@router.get("/")
def get_config(request: Request):
    """Return current configuration.

    Includes both the typed/resolved view and a flat overlay of legacy keys
    at the top level for un-reshaped frontend code. The overlay is computed
    per-request from ``service.resolved()`` so boot overrides flow through
    without disk persistence.
    """
    service = _require_service(request)
    resolved = service.resolved()
    legacy = flatten_resolved_to_legacy(resolved)
    new_shape = {
        "campaign_dir": str(service.campaign_dir),
        "config_path": str(service.config_path),
        "ui_state_path": str(service.ui_state_path),
        "local_config_path": str(service.local_config_path),
        "schema_version": SCHEMA_VERSION,
        "resolved": resolved,
        "tracked": service.tracked,
        "local": service.local.model_dump(mode="json"),
        "migration_warnings": list(service.load_warnings),
    }
    # Spread legacy flat keys first; new-shape fields take precedence on any
    # collision so the authoritative paths and metadata win.
    return {**legacy, **new_shape}


# ── Typed section update ───────────────────────────────────────────────────


class SectionUpdate(BaseModel):
    values: dict


@router.put("/section/{name}")
def put_config_section(name: str, update: SectionUpdate, request: Request):
    """Merge ``update.values`` into ``ui.<name>`` and persist."""
    service = _require_service(request)
    if name not in UI_SECTION_NAMES:
        raise HTTPException(
            status_code=404,
            detail=f"unknown UI section {name!r}; valid: {', '.join(UI_SECTION_NAMES)}",
        )
    service.update_section(name, update.values)
    return {"ok": True}


# ── Runtime updates (session_dir, default_model) ───────────────────────────


class RuntimeUpdate(BaseModel):
    values: dict


@router.put("/runtime")
def put_config_runtime(update: RuntimeUpdate, request: Request):
    """Merge ``update.values`` into ``runtime`` and persist."""
    service = _require_service(request)
    try:
        service.update_runtime(update.values)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


# ── Local (machine-only) updates ───────────────────────────────────────────


class LocalUpdate(BaseModel):
    values: dict


@router.put("/local")
def put_config_local(update: LocalUpdate, request: Request):
    """Merge ``update.values`` into ``.campaigngenerator.local.yaml``.

    Top-level keys are ``server`` (host/port) and ``nav`` (transient
    browser state). Anything else is rejected by the typed model.
    """
    service = _require_service(request)
    try:
        service.update_local(update.values)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


# ── Path-derivation helpers (unchanged) ────────────────────────────────────


@router.get("/campaign-paths")
def get_campaign_paths(campaign_dir: str, session_dir: str):
    """Derive all paths from campaign directory + session directory."""
    return derive_campaign_paths(campaign_dir, session_dir)


@router.get("/session-paths")
def get_session_paths(session_dir: str):
    """Derive sub-paths from a session directory (legacy)."""
    return derive_session_paths(session_dir)


@router.get("/path-status")
def get_path_status(path: str):
    """Check if a file or directory exists."""
    return {"exists": path_exists(path)}


@router.get("/party-yaml")
def get_party_yaml(path: str):
    """Load a party config YAML.

    Returns the parsed `characters` list (with arc_score=null preserved as
    null) and the resolved file path. If the file does not exist, returns
    an empty character list so the UI can offer a 'create new' flow.
    """
    p = Path(path).expanduser().resolve() if path else None
    if not p or not path:
        raise HTTPException(status_code=400, detail="path is required")
    if not p.exists():
        return {"path": str(p), "exists": False, "characters": []}
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"invalid YAML: {e}")
    chars = raw.get("characters") or []
    if not isinstance(chars, list):
        raise HTTPException(status_code=400,
                            detail="'characters' must be a list")

    # Normalize: arc_score key always present (null when trackless / unspecified).
    out = []
    for c in chars:
        if not isinstance(c, dict):
            continue
        out.append({
            "name": c.get("name", ""),
            "sheet": c.get("sheet", ""),
            "backstory": c.get("backstory") or "",
            # Distinguish three cases for arc_score on the wire:
            #   present + null → trackless=True
            #   present + path → trackless=False, arc_score=path
            #   absent         → trackless=False, arc_score=""
            "arc_score": c.get("arc_score") if c.get("arc_score") else "",
            "trackless": "arc_score" in c and c.get("arc_score") is None,
        })
    return {"path": str(p), "exists": True, "characters": out}


class PartyYamlSave(BaseModel):
    path: str
    characters: list[dict]


@router.put("/party-yaml")
def put_party_yaml(update: PartyYamlSave):
    """Write a party config YAML.

    Each character dict must contain `name` and `sheet`. `backstory` is
    optional. `arc_score` is three-state:
        trackless=True            → emits `arc_score: null`
        arc_score truthy          → emits `arc_score: <path>`
        otherwise                 → arc_score key omitted entirely
    Validates only the shape of the YAML — does NOT verify referenced
    files exist (party.py's loader does that at run time).
    """
    p = Path(update.path).expanduser().resolve()
    if not update.characters:
        raise HTTPException(status_code=400,
                            detail="characters list cannot be empty")

    out_chars = []
    for i, c in enumerate(update.characters):
        name = (c.get("name") or "").strip()
        sheet = (c.get("sheet") or "").strip()
        if not name or not sheet:
            raise HTTPException(
                status_code=400,
                detail=f"character #{i + 1}: 'name' and 'sheet' are required",
            )
        entry: dict = {"name": name, "sheet": sheet}
        backstory = (c.get("backstory") or "").strip()
        if backstory:
            entry["backstory"] = backstory
        if c.get("trackless"):
            entry["arc_score"] = None
        else:
            arc_score = (c.get("arc_score") or "").strip()
            if arc_score:
                entry["arc_score"] = arc_score
        out_chars.append(entry)

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"characters": out_chars}, sort_keys=False),
                 encoding="utf-8")
    return {"ok": True, "path": str(p)}


# ── Planning YAML (NPC + faction dossiers + arc scores) ───────────────────
# Mirrors party-yaml above. Shape:
#   npcs:
#     - name: Adabra
#       dossier: docs/npcs/adabra.md          # required for npcs
#       arc_score: docs/tracking/adabra.md    # absent | null (trackless) | path
#   factions:
#     - name: Kraken Society
#       dossier: docs/factions/kraken.md      # optional
#       arc_score: docs/tracking/echoes.md
# Three-state arc_score and trackless semantics match party.py exactly.


def _read_planning_entries(raw_list: Any) -> list[dict]:
    """Normalize a list of NPC or faction entries from on-disk YAML to the
    UI wire shape: arc_score always present (empty when unset), explicit
    trackless flag, dossier string."""
    if not isinstance(raw_list, list):
        return []
    out = []
    for e in raw_list:
        if not isinstance(e, dict):
            continue
        out.append({
            "name": e.get("name", ""),
            "dossier": e.get("dossier") or "",
            "arc_score": e.get("arc_score") if e.get("arc_score") else "",
            "trackless": "arc_score" in e and e.get("arc_score") is None,
        })
    return out


@router.get("/planning-yaml")
def get_planning_yaml(path: str):
    """Load a planning config YAML.

    Returns ``npcs`` and ``factions`` lists in the UI wire shape (arc_score
    always present, trackless flag set when the on-disk value is null).
    Missing file is not an error — returns empty lists so the UI can offer
    a 'create new' flow.
    """
    p = Path(path).expanduser().resolve() if path else None
    if not p or not path:
        raise HTTPException(status_code=400, detail="path is required")
    if not p.exists():
        return {"path": str(p), "exists": False, "npcs": [], "factions": []}
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"invalid YAML: {e}")
    return {
        "path": str(p),
        "exists": True,
        "npcs": _read_planning_entries(raw.get("npcs") or []),
        "factions": _read_planning_entries(raw.get("factions") or []),
    }


class PlanningYamlSave(BaseModel):
    path: str
    npcs: list[dict] = []
    factions: list[dict] = []


@router.put("/planning-yaml")
def put_planning_yaml(update: PlanningYamlSave):
    """Write a planning config YAML.

    NPC entries require ``name`` and ``dossier``. Faction entries require
    only ``name`` (``dossier`` is optional faction-overview file).
    ``arc_score`` is three-state per the trackless flag (matches party).
    Shape validation only — does not verify referenced files exist
    (planning.py's loader does that at run time).
    """
    p = Path(update.path).expanduser().resolve()
    if not update.npcs and not update.factions:
        raise HTTPException(
            status_code=400,
            detail="planning config must have at least one NPC or faction",
        )

    def _build_entry(c: dict, i: int, kind: str, require_dossier: bool) -> dict:
        name = (c.get("name") or "").strip()
        if not name:
            raise HTTPException(
                status_code=400,
                detail=f"{kind} #{i + 1}: 'name' is required",
            )
        dossier = (c.get("dossier") or "").strip()
        if require_dossier and not dossier:
            raise HTTPException(
                status_code=400,
                detail=f"{kind} #{i + 1} ({name}): 'dossier' is required",
            )
        entry: dict = {"name": name}
        if dossier:
            entry["dossier"] = dossier
        if c.get("trackless"):
            entry["arc_score"] = None
        else:
            arc_score = (c.get("arc_score") or "").strip()
            if arc_score:
                entry["arc_score"] = arc_score
        return entry

    out: dict = {}
    if update.npcs:
        out["npcs"] = [
            _build_entry(c, i, "npc", require_dossier=True)
            for i, c in enumerate(update.npcs)
        ]
    if update.factions:
        out["factions"] = [
            _build_entry(c, i, "faction", require_dossier=False)
            for i, c in enumerate(update.factions)
        ]

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(out, sort_keys=False), encoding="utf-8")
    return {"ok": True, "path": str(p)}


@router.get("/models")
def get_models():
    """Return the list of available Claude models."""
    return {"models": MODELS, "default": DEFAULT_MODEL}


@router.get("/status")
def get_status():
    """Return API key status and working directory."""
    import os
    return {
        "api_key_present": api_key_present(),
        "cwd": os.getcwd(),
    }
