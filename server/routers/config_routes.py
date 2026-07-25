"""Config API routes — runtime/local updates, path helpers, model registry.

All persistence flows through ``PlatformConfigService`` (``app.state.
platform``). There is no fallback to a raw ``ui_config.yaml`` — when the
service is not initialized the routes return ``503``.

``PUT /section/{name}`` used to live here: the generic write door into
``ui_state.yaml``'s ``ui.<section>`` blobs. It is gone with the rest of that
tier (``docs/config/ui-state-retirement.md``) — it had no client. Every
service that once wrote through it owns its own document now
(``session_doc.yaml``, ``ensemble.yaml``, ``grounding.yaml``, ``party.yaml``,
``planning.yaml``, ``platform.yaml``), each with its own typed route.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.config import DEFAULT_MODEL, MODELS, api_key_present, path_exists
from server.platform_config_service import PlatformConfigService, require_platform

router = APIRouter()

# require_platform (server/platform_config_service.py) is the one shared
# "fetch app.state.platform or 503" accessor — see its docstring for the
# duplicate copies it replaced. Kept as a local alias here so the four
# in-file call sites below don't need touching; new routers should import
# require_platform directly instead of adding a fifth copy of this alias.
_require_service = require_platform


# ── GET / — typed/resolved view + metadata ─────────────────────────────────


@router.get("/")
def get_config(request: Request):
    """Return current configuration: the typed/resolved view plus metadata."""
    service = _require_service(request)
    resolved = service.resolved()
    return {
        "campaign_dir": str(service.campaign_dir),
        "config_path": str(service.config_path),
        "local_config_path": str(service.local_config_path),
        "resolved": resolved,
        "tracked": service.tracked,
        "local": service.local.model_dump(mode="json"),
        "migration_warnings": list(service.load_warnings),
    }


# ``ui_state_path`` and ``schema_version`` left this body with
# ``ui_state.yaml`` itself. The former was rendered by Settings.vue; the
# latter versioned a document that no longer exists.


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


# ── Path discovery (narrowed, O2) ───────────────────────────────────────────


@router.get("/campaign-paths")
def get_campaign_paths(campaign_dir: str, session_dir: str):
    """Filesystem discovery for the Session Config screen — see
    ``PlatformConfigService.discover_campaign_paths`` (O2, docs/config/
    platform-isolation.md) for what this does and does not return.

    Note this is a bare ``@staticmethod`` call, not ``_require_service`` —
    this endpoint is how ``SessionConfig.vue`` discovers paths for a
    campaign BEFORE it becomes ``app.state.platform`` (there may be no live
    service for this ``campaign_dir`` yet).

    ``GET /api/config/session-paths`` (a one-line wrapper with no frontend
    caller — verified by grepping ``apiFetch`` call sites) was deleted
    alongside this narrowing.
    """
    return PlatformConfigService.discover_campaign_paths(campaign_dir, session_dir)


@router.get("/path-status")
def get_path_status(path: str):
    """Check if a file or directory exists."""
    return {"exists": path_exists(path)}


# GET/PUT /party-yaml lived here until Phase 5 of docs/config/
# grounding-isolation.md. They took the target file as a browser-supplied
# `path` parameter, re-implemented the three-state arc_score encoding in raw
# YAML, validated nothing beyond "name and sheet are non-empty", and wrote via
# a bare write_text. The roster is now owned by PartyConfigService and served
# at /api/party/characters — one implementation, a declared path, atomic
# writes.



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
