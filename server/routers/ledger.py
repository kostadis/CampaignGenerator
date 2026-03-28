"""Quote Ledger API routes — sync, query, and assign quotes to scenes."""

import sys
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from quote_ledger import QuoteLedger

# Module-level ledger instance
_LEDGER: QuoteLedger | None = None
_CONFIG: dict = {}


def init_ledger_config(config: dict) -> None:
    """Set the CONFIG reference. Called from main.py startup."""
    _CONFIG.update(config)


def _get_ledger() -> QuoteLedger:
    global _LEDGER
    if _LEDGER is None:
        db_path = Path(_CONFIG["extract_dir"]) / "quote_ledger.db"
        _LEDGER = QuoteLedger(db_path)
    return _LEDGER


def _load_scenes() -> list[dict]:
    """Reuse scene loading from scene_editor."""
    from server.routers.scene_editor import _load_scenes
    return _load_scenes()


@router.post("/sync")
def api_ledger_sync():
    ledger = _get_ledger()
    scenes = _load_scenes()
    result = ledger.sync(
        roleplay_dir=Path(_CONFIG["roleplay_extract_dir"]),
        extract_dir=Path(_CONFIG["extract_dir"]),
        scenes=scenes,
    )
    return result


@router.get("/quotes")
def api_ledger_quotes():
    global _LEDGER
    if _LEDGER is None:
        return {"scenes": [], "unassigned": []}
    scenes = _load_scenes()
    return _LEDGER.get_quotes_grouped(scenes)


@router.post("/assign")
async def api_ledger_assign(request: Request):
    global _LEDGER
    if _LEDGER is None:
        return JSONResponse({"ok": False, "error": "ledger not synced"}, status_code=400)
    data = await request.json()
    quote_id = data["quote_id"]
    scene_index = data.get("scene_index")
    ok = _LEDGER.assign(quote_id, scene_index)
    return {"ok": ok}
