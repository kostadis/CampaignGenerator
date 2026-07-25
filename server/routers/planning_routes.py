"""API routes for isolated planning configuration management.

Provides resource-oriented endpoints for managing NPCs and factions
in the planning configuration, isolated from the general config service.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from typing import List
from ..planning_config_service import PlanningConfigService, PlanningEntry
from campaignlib.selection import ModelSelection
from ..platform_config_service import require_platform, resolve_selection

# NOTE: the "/api/planning" prefix is supplied by main.py's include_router,
# matching every sibling router. Do not also set prefix= here or the routes
# get mounted at /api/planning/api/planning/* (a 404 for all callers).
router = APIRouter(tags=["planning"])


def get_planning_service(request: Request) -> PlanningConfigService:
    """Dependency to get the planning config service for a request.

    ``require_platform`` (server/platform_config_service.py) is the one
    shared "fetch app.state.platform or 503" accessor. This function used
    to duplicate that check inline — before that, via the now-deleted
    ``server.config.get_campaign_dir_from_request`` — see
    ``docs/config/platform-isolation.md`` Phase 4.
    """
    platform = require_platform(request)
    return PlanningConfigService(platform)


# ============================================================================
# NPC Endpoints
# ============================================================================

@router.get("/npcs", response_model=List[PlanningEntry])
def list_npcs(service: PlanningConfigService = Depends(get_planning_service)):
    """Get all NPCs."""
    return service.get_npcs()


@router.post("/npcs", response_model=PlanningEntry, status_code=status.HTTP_201_CREATED)
def create_npc(npc: PlanningEntry, service: PlanningConfigService = Depends(get_planning_service)):
    """Create a new NPC."""
    return service.create_npc(npc)


@router.get("/npcs/{name}", response_model=PlanningEntry)
def get_npc(name: str, service: PlanningConfigService = Depends(get_planning_service)):
    """Get a specific NPC by name."""
    return service.get_npc(name)


@router.put("/npcs/{name}", response_model=PlanningEntry)
def update_npc(name: str, npc: PlanningEntry, service: PlanningConfigService = Depends(get_planning_service)):
    """Update an existing NPC."""
    return service.update_npc(name, npc)


@router.delete("/npcs/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_npc(name: str, service: PlanningConfigService = Depends(get_planning_service)):
    """Delete an NPC by name."""
    service.delete_npc(name)
    return None


# ============================================================================
# Faction Endpoints (mirrored)
# ============================================================================

@router.get("/factions", response_model=List[PlanningEntry])
def list_factions(service: PlanningConfigService = Depends(get_planning_service)):
    """Get all factions."""
    return service.get_factions()


@router.post("/factions", response_model=PlanningEntry, status_code=status.HTTP_201_CREATED)
def create_faction(faction: PlanningEntry, service: PlanningConfigService = Depends(get_planning_service)):
    """Create a new faction."""
    return service.create_faction(faction)


@router.get("/factions/{name}", response_model=PlanningEntry)
def get_faction(name: str, service: PlanningConfigService = Depends(get_planning_service)):
    """Get a specific faction by name."""
    return service.get_faction(name)


@router.put("/factions/{name}", response_model=PlanningEntry)
def update_faction(name: str, faction: PlanningEntry, service: PlanningConfigService = Depends(get_planning_service)):
    """Update an existing faction."""
    return service.update_faction(name, faction)


@router.delete("/factions/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_faction(name: str, service: PlanningConfigService = Depends(get_planning_service)):
    """Delete a faction by name."""
    service.delete_faction(name)
    return None


# ── Model/backend selection (feature 003) ──────────────────────────────────
# GET/PUT/DELETE this service's own override, plus a read-only "what would a
# run actually use" preview. The preview makes the resolved selection and its
# ORIGIN visible before tokens are spent (FR-012), and reports an incompatible
# pair WITHOUT raising, so the UI can show the reason and offer the fix rather
# than the operator discovering it as a failed run.


@router.get("/selection")
def get_planning_selection(service: PlanningConfigService = Depends(get_planning_service)):
    return service.get_selection().model_dump()


@router.put("/selection")
async def put_planning_selection(request: Request, service: PlanningConfigService = Depends(get_planning_service)):
    partial = await request.json()
    if not isinstance(partial, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    try:
        selection = ModelSelection.model_validate(partial)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return service.set_selection(selection).model_dump()


@router.delete("/selection")
def delete_planning_selection(service: PlanningConfigService = Depends(get_planning_service)):
    """Clear the override — the service returns to the platform selection with
    no further operator action (FR-013)."""
    return service.set_selection(ModelSelection()).model_dump()


@router.get("/selection/resolved")
def get_planning_resolved_selection(request: Request, service: PlanningConfigService = Depends(get_planning_service)):
    sel = service.get_selection()
    return resolve_selection(
        request,
        service=None if sel.is_empty() else sel,
        service_name="planning",
        raise_on_incompatible=False,
    ).as_dict()
