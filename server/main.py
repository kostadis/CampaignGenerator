"""FastAPI application — serves the Vue frontend and API routes."""

import argparse
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.config import derive_campaign_paths, derive_session_paths
from server.config_service import CampaignConfigService, ConfigError
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


# ── Campaign-dir + boot-override helpers (used by main()) ───────────────────


def _resolve_campaign_dir_for_service(args) -> Path | None:
    """Decide which directory the unified config service should anchor to.

    Order: ``--campaign-dir``, then the parents of ``--session-dir``
    (looking for the nearest one with a ``config.yaml``), then CWD if it
    has one. Returns ``None`` if nothing matches; caller should skip
    service construction in that case.
    """
    if getattr(args, "campaign_dir", None):
        return Path(args.campaign_dir).expanduser().resolve()
    if getattr(args, "session_dir", None):
        sd = Path(args.session_dir).expanduser().resolve()
        for parent in (sd, *sd.parents):
            if (parent / "config.yaml").exists():
                return parent
    cwd_cfg = Path.cwd() / "config.yaml"
    if cwd_cfg.exists():
        return Path.cwd().resolve()
    return None


def _boot_overrides_from_args(args) -> dict:
    """Translate CLI flags into dotted-key overrides for the service.

    These overrides are in-memory only — per the unification plan, CLI
    flags must NOT persist to disk. The service applies them on top of
    the loaded ui_state for the lifetime of this process.
    """
    flag_map = {
        "session": "session_doc.session",
        "extract_dir": "session_doc.extract_dir",
        "roleplay_extract_dir": "session_doc.roleplay_dir",
        "output_dir": "session_doc.output_dir",
        "summary_extract_dir": "session_doc.summary_dir",
        "session_summary": "session_doc.session_summary",
        "party": "session_doc.party",
        "voice_dir": "session_doc.voice_dir",
        "examples": "session_doc.examples_dir",
        "characters": "session_doc.characters",
        "narrate_tokens": "session_doc.narrate_tokens",
        "session_dir": "runtime.session_dir",
        # ``--host`` / ``--port`` stay in args for uvicorn but are NOT
        # boot-overrides — argparse can't tell "user typed --port 5000"
        # from the default firing, so including them here would silently
        # clobber a custom port in .campaigngenerator.local.yaml.
    }
    overrides: dict = {}
    for arg_name, dotted in flag_map.items():
        value = getattr(args, arg_name, None)
        if value is None or value == "":
            continue
        overrides[dotted] = value
    if getattr(args, "context", None):
        overrides["session_doc.context"] = list(args.context)
    return overrides


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

        # Note: pre-refactor this also persisted {session_dir, campaign_dir}
        # to ui_config.yaml so the frontend picked them up. That violated the
        # boot-flag-doesn't-persist invariant. Boot flags now flow through
        # CampaignConfigService(boot_overrides=...) and the legacy_values
        # overlay surfaces them to any unmigrated frontend view for the
        # process lifetime.

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
        "context": [str(Path(f).expanduser().resolve()) for f in args.context] if args.context else [],
        "characters": args.characters,
        "examples": _resolve(args.examples),
        "narrate_tokens": args.narrate_tokens,
        "work_dir": str(Path(".").resolve()),
    }

    # Initialize editor and ledger with config
    scene_editor.init_editor_config(config)
    ledger.init_ledger_config(config)

    # ── Step B: construct the unified config service alongside the legacy
    # CONFIG dict. Routers don't read it yet (that's Step D). If construction
    # fails (no config.yaml in the resolved campaign dir, etc.), log and
    # carry on so the legacy boot path keeps working unchanged.
    campaign_dir_for_service = _resolve_campaign_dir_for_service(args)
    if campaign_dir_for_service is not None:
        try:
            app.state.config_service = CampaignConfigService(
                campaign_dir_for_service,
                boot_overrides=_boot_overrides_from_args(args),
            )
            for warning in app.state.config_service.migration_warnings:
                print(f"  config: {warning}")
        except ConfigError as exc:
            app.state.config_service = None
            print(f"  config service: skipped ({exc})")
    else:
        app.state.config_service = None

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
