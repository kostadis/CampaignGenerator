"""API routes for the isolated player roster configuration — feature 009.

Mirrors ``party_routes.py``, including its two shipped-bug lessons: the prefix
is supplied by ``main.py``'s ``include_router`` (setting it here too mounts
everything at ``/api/players/api/players/*``), and an emptied roster reads back
as ``[]`` rather than a 400.

Two deliberate differences from every sibling router:

* **No ``/selection`` routes.** This service spends no tokens, so it has no
  model or backend override.
* **A ``/check`` route.** Read-only, and the same finder the ``players`` CLI
  uses, so the page and the command line cannot disagree about whether a
  campaign is coherent.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from campaignlib.players_config import Player
from ..players_config_service import PlayersConfigService
from ..platform_config_service import require_platform

# NOTE: the "/api/players" prefix comes from main.py's include_router, matching
# every sibling router. Do not also set prefix= here.
router = APIRouter(tags=["players"])


def get_players_service(request: Request) -> PlayersConfigService:
    """Per-request DI, matching ``party_routes.get_party_service``."""
    return PlayersConfigService(require_platform(request))


@router.get("/players")
def list_players(service: PlayersConfigService = Depends(get_players_service)):
    """Every player. Each carries ``problems`` — see the service docstring's
    lenient/strict split."""
    return service.get_players()


@router.put("/players")
def replace_players(
    players: list[Player],
    service: PlayersConfigService = Depends(get_players_service),
):
    """Replace the whole roster in one atomic write.

    The page edits the table as a unit (row order is meaningful), so this is
    the endpoint it uses — not a delete-all-then-recreate loop.
    """
    return service.replace_all(players)


@router.post("/players", status_code=status.HTTP_201_CREATED)
def create_player(
    player: Player,
    service: PlayersConfigService = Depends(get_players_service),
):
    return service.create_player(player)


@router.get("/players/{player_id}")
def get_player(
    player_id: str, service: PlayersConfigService = Depends(get_players_service)
):
    return service.get_player(player_id)


@router.put("/players/{player_id}")
def update_player(
    player_id: str,
    player: Player,
    service: PlayersConfigService = Depends(get_players_service),
):
    return service.update_player(player_id, player)


@router.delete("/players/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_player(
    player_id: str, service: PlayersConfigService = Depends(get_players_service)
):
    service.delete_player(player_id)
    return None


# ── Coherence check ────────────────────────────────────────────────────────
# Read-only. Reports; corrects nothing. Deliberately reuses the engine CLI's
# finder rather than re-deriving the rules here — a router that reimplements
# pipeline logic is the Split-Brain the constitution's Principle VI names.


@router.get("/check")
def check(request: Request):
    """Report drift without spending a token or calling a model.

    Wired here so the surface is complete from the start; the finder itself
    arrives with user story 5. Until then this is an honest 501 rather than an
    empty report, because "no findings" and "not implemented" must not look the
    same to the page.
    """
    try:
        from pipelines.workspace.players import collect_findings
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="the players coherence check is not implemented yet",
        ) from None
    try:
        return collect_findings(require_platform(request).campaign_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
