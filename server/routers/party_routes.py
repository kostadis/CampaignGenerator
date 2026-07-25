"""API routes for the isolated party roster configuration.

Phase 5 of ``docs/config/grounding-isolation.md``. Replaces
``config_routes.py``'s ``GET/PUT /api/config/party-yaml`` pair, which took the
target file path as a browser-supplied parameter.

Mirrors ``planning_routes.py``, including its two shipped-bug lessons: the
prefix is supplied by ``main.py``'s ``include_router`` (setting it here too
mounts everything at ``/api/party/api/party/*``), and an emptied roster reads
back as ``[]`` rather than a 400.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from campaignlib.party_config import PartyCharacter
from ..party_config_service import PartyConfigService
from campaignlib.selection import ModelSelection
from ..platform_config_service import require_platform, resolve_selection

# NOTE: the "/api/party" prefix comes from main.py's include_router, matching
# every sibling router. Do not also set prefix= here.
router = APIRouter(tags=["party"])


def get_party_service(request: Request) -> PartyConfigService:
    """Per-request DI, matching ``planning_routes.get_planning_service``."""
    return PartyConfigService(require_platform(request))


@router.get("/characters")
def list_characters(service: PartyConfigService = Depends(get_party_service)):
    """All PCs. Each carries ``missing_files`` — see the service docstring (D4)."""
    return service.get_characters()


@router.put("/characters")
def replace_characters(
    characters: list[PartyCharacter],
    service: PartyConfigService = Depends(get_party_service),
):
    """Replace the whole roster in one atomic write.

    The editor edits the table as a unit (row order is meaningful), so this is
    the endpoint it uses — not a delete-all-then-recreate loop.
    """
    return service.replace_all(characters)


@router.post("/characters", status_code=status.HTTP_201_CREATED)
def create_character(
    character: PartyCharacter,
    service: PartyConfigService = Depends(get_party_service),
):
    return service.create_character(character)


@router.get("/characters/{name}")
def get_character(name: str, service: PartyConfigService = Depends(get_party_service)):
    return service.get_character(name)


@router.put("/characters/{name}")
def update_character(
    name: str,
    character: PartyCharacter,
    service: PartyConfigService = Depends(get_party_service),
):
    return service.update_character(name, character)


@router.delete("/characters/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_character(
    name: str, service: PartyConfigService = Depends(get_party_service)
):
    service.delete_character(name)
    return None


# ── Model/backend selection (feature 003) ──────────────────────────────────
# GET/PUT/DELETE this service's own override, plus a read-only "what would a
# run actually use" preview. The preview makes the resolved selection and its
# ORIGIN visible before tokens are spent (FR-012), and reports an incompatible
# pair WITHOUT raising, so the UI can show the reason and offer the fix rather
# than the operator discovering it as a failed run.


@router.get("/selection")
def get_party_selection(service: PartyConfigService = Depends(get_party_service)):
    return service.get_selection().model_dump()


@router.put("/selection")
async def put_party_selection(request: Request, service: PartyConfigService = Depends(get_party_service)):
    partial = await request.json()
    if not isinstance(partial, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    try:
        selection = ModelSelection.model_validate(partial)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return service.set_selection(selection).model_dump()


@router.delete("/selection")
def delete_party_selection(service: PartyConfigService = Depends(get_party_service)):
    """Clear the override — the service returns to the platform selection with
    no further operator action (FR-013)."""
    return service.set_selection(ModelSelection()).model_dump()


@router.get("/selection/resolved")
def get_party_resolved_selection(request: Request, service: PartyConfigService = Depends(get_party_service)):
    sel = service.get_selection()
    return resolve_selection(
        request,
        service=None if sel.is_empty() else sel,
        service_name="party",
        raise_on_incompatible=False,
    ).as_dict()
