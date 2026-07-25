"""API routes for the isolated party roster configuration.

Phase 5 of ``docs/config/grounding-isolation.md``. Replaces
``config_routes.py``'s ``GET/PUT /api/config/party-yaml`` pair, which took the
target file path as a browser-supplied parameter.

Mirrors ``planning_routes.py``, including its two shipped-bug lessons: the
prefix is supplied by ``main.py``'s ``include_router`` (setting it here too
mounts everything at ``/api/party/api/party/*``), and an emptied roster reads
back as ``[]`` rather than a 400.
"""

from fastapi import APIRouter, Depends, Request, status

from campaignlib.party_config import PartyCharacter
from ..party_config_service import PartyConfigService
from ..platform_config_service import require_platform

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
