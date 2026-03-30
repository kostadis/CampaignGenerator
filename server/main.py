"""FastAPI application — serves the Vue frontend and API routes."""

import argparse
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.config import derive_campaign_paths, derive_session_paths, save_ui_config
from server.routers import (
    config_routes, connections, experimental, grounding, ledger, prep,
    scene_editor, session_workflow, setup,
)

app = FastAPI(title="CampaignGenerator")

# CORS for Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routers ──────────────────────────────────────────────────────────────

app.include_router(config_routes.router, prefix="/api/config", tags=["config"])
app.include_router(session_workflow.router, prefix="/api/workflow", tags=["workflow"])
app.include_router(grounding.router, prefix="/api/grounding", tags=["grounding"])
app.include_router(prep.router, prefix="/api/prep", tags=["prep"])
app.include_router(setup.router, prefix="/api/setup", tags=["setup"])
app.include_router(experimental.router, prefix="/api/experimental", tags=["experimental"])
app.include_router(scene_editor.router, prefix="/api/editor", tags=["editor"])
app.include_router(ledger.router, prefix="/api/ledger", tags=["ledger"])
app.include_router(connections.router, prefix="/api/connections", tags=["connections"])

# ── Static files (Vue build) ────────────────────────────────────────────────

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    # Serve actual static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    # SPA catch-all: any non-API path serves index.html so Vue Router handles it
    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str):
        # Serve actual files (favicon.svg, icons.svg, etc.) if they exist
        file_path = FRONTEND_DIST / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIST / "index.html")


# ── CLI entry point ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="CampaignGenerator web UI server")
    parser.add_argument("--campaign-dir", metavar="DIR",
                        help="Campaign root directory (contains docs/, voice/, examples/, summaries/)")
    parser.add_argument("--session-dir", metavar="DIR",
                        help="Session directory inside summaries/ — auto-derives all paths")
    parser.add_argument("--session", metavar="FILE",
                        help="Session recap file")
    parser.add_argument("--extract-dir", metavar="DIR")
    parser.add_argument("--roleplay-extract-dir", metavar="DIR")
    parser.add_argument("--output-dir", metavar="DIR")
    parser.add_argument("--party", metavar="FILE")
    parser.add_argument("--voice-dir", metavar="DIR")
    parser.add_argument("--summary-extract-dir", metavar="DIR")
    parser.add_argument("--session-summary", metavar="FILE")
    parser.add_argument("--roleplay-summary", metavar="FILE")
    parser.add_argument("--context", nargs="+", metavar="FILE")
    parser.add_argument("--characters", metavar="NAMES")
    parser.add_argument("--examples", metavar="DIR")
    parser.add_argument("--narrate-tokens", type=int, metavar="N")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    # Derive paths from campaign-dir + session-dir
    if args.session_dir:
        sd = Path(args.session_dir).expanduser().resolve()
        cd = ""
        if args.campaign_dir:
            cd = str(Path(args.campaign_dir).expanduser().resolve())
        derived = derive_campaign_paths(cd, str(sd))

        if not args.session:
            args.session = derived.get("gm_recap") or derived.get("session", "")
        if not args.extract_dir:
            args.extract_dir = derived.get("extract_dir", "")
        if not args.roleplay_extract_dir:
            args.roleplay_extract_dir = derived.get("roleplay_extract_dir", "")
        if not args.summary_extract_dir:
            args.summary_extract_dir = derived.get("summary_extract_dir", "")
        if not args.output_dir:
            args.output_dir = derived.get("output_dir", "")
        if not args.session_summary and derived.get("session_summary"):
            args.session_summary = derived["session_summary"]
        if not args.roleplay_summary and derived.get("roleplay_summary"):
            args.roleplay_summary = derived["roleplay_summary"]
        if not args.party and derived.get("party"):
            args.party = derived["party"]
        if not args.voice_dir and derived.get("voice_dir"):
            args.voice_dir = derived["voice_dir"]
        if not args.examples and derived.get("examples_dir"):
            args.examples = derived["examples_dir"]
        if not args.context and derived.get("context"):
            args.context = derived["context"]
        if not args.characters:
            args.characters = derived.get("characters")

        # Persist to ui_config.yaml so the frontend picks up the values
        ui_vals = {"session_dir": str(sd)}
        if cd:
            ui_vals["campaign_dir"] = cd
        save_ui_config(ui_vals)

    def _resolve(val: str | None) -> str | None:
        if not val:
            return None
        return str(Path(val).expanduser().resolve())

    config = {
        "session": _resolve(args.session) or "",
        "extract_dir": _resolve(args.extract_dir) or "",
        "roleplay_extract_dir": _resolve(args.roleplay_extract_dir) or "",
        "output_dir": _resolve(args.output_dir) or str(Path(".").resolve()),
        "party": _resolve(args.party),
        "voice_dir": _resolve(args.voice_dir),
        "summary_extract_dir": _resolve(args.summary_extract_dir),
        "session_summary": _resolve(args.session_summary),
        "roleplay_summary": _resolve(args.roleplay_summary),
        "context": [str(Path(f).expanduser().resolve()) for f in args.context] if args.context else [],
        "characters": args.characters,
        "examples": _resolve(args.examples),
        "narrate_tokens": args.narrate_tokens,
        "work_dir": str(Path(".").resolve()),
    }

    # Initialize editor and ledger with config
    scene_editor.init_editor_config(config)
    ledger.init_ledger_config(config)

    print(f"  CampaignGenerator UI")
    if config["session"]:
        print(f"  Session:     {config['session']}")
    if config["extract_dir"]:
        print(f"  Extractions: {config['extract_dir']}")
    if config["output_dir"]:
        print(f"  Output:      {config['output_dir']}")
    print(f"  Open http://{args.host}:{args.port} in your browser")
    if FRONTEND_DIST.is_dir():
        print(f"  Serving frontend from {FRONTEND_DIST}")
    else:
        print(f"  No frontend build found — run: cd frontend && npm run build")
        print(f"  (For development, run: cd frontend && npm run dev)")
    print()

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
