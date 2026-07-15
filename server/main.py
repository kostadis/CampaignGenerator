"""FastAPI application — serves the Vue frontend and API routes."""

import argparse
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.config import derive_campaign_paths, derive_session_paths
from server.config_service import CampaignConfigService, ConfigError
from server.routers import (
    config_routes, connections, ensemble, experimental, grounding, prep,
    scene_editor, session_workflow, setup, planning_routes,
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
app.include_router(ensemble.router, prefix="/api/ensemble", tags=["ensemble"])
app.include_router(prep.router, prefix="/api/prep", tags=["prep"])
app.include_router(setup.router, prefix="/api/setup", tags=["setup"])
app.include_router(experimental.router, prefix="/api/experimental", tags=["experimental"])
app.include_router(scene_editor.router, prefix="/api/editor", tags=["editor"])
app.include_router(connections.router, prefix="/api/connections", tags=["connections"])
app.include_router(planning_routes.router, prefix="/api/planning", tags=["planning"])

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
    (looking for the nearest one with a ``config.yaml`` or
    ``<config-dir>/config.yaml``), then CWD if it has one. Returns ``None``
    when no campaign directory can be determined — callers must fail loudly
    rather than fall back to a synthetic default.
    """
    config_dir = getattr(args, "config_dir", "config") or "config"

    # Check explicit --campaign-dir
    if getattr(args, "campaign_dir", None):
        return Path(args.campaign_dir).expanduser().resolve()

    # Check --session-dir parents for config.yaml (top-level or <config_dir>/)
    if getattr(args, "session_dir", None):
        sd = Path(args.session_dir).expanduser().resolve()
        for parent in (sd, *sd.parents):
            if (parent / "config.yaml").exists() or (parent / config_dir / "config.yaml").exists():
                return parent

    # Check CWD for config.yaml (top-level or <config_dir>/)
    if (Path.cwd() / "config.yaml").exists() or (Path.cwd() / config_dir / "config.yaml").exists():
        return Path.cwd().resolve()

    # No campaign directory could be determined.
    return None


def _boot_overrides_from_args(args) -> dict:
    """Translate CLI flags into dotted-key overrides for the service.

    These overrides are in-memory only — per the unification plan, CLI
    flags must NOT persist to disk. The service applies them on top of
    the loaded ui_state for the lifetime of this process.
    """
    flag_map = {
        "session": "session_doc.session",
        "extract_dir": "session_doc.scene_extractions_dir",
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
    parser.add_argument("--config-dir", metavar="DIR", default="config",
                        help="Configuration subdirectory within campaign (default: 'config')")
    args = parser.parse_args()

    # Capture boot overrides from the RAW, user-typed flags BEFORE the
    # session-dir derivation block below backfills defaults into args. A value
    # derived from --session-dir is NOT a user override, and boot overrides win
    # permanently at resolved() time — so promoting derived paths to overrides
    # makes every session_doc field (scene_extractions_dir, party, voice_dir,
    # …) impossible to change from the UI: the persisted ui_state value is
    # clobbered on every read. Only genuinely-typed flags belong here (the same
    # reason --host/--port are excluded inside _boot_overrides_from_args).
    boot_overrides = _boot_overrides_from_args(args)

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
            args.extract_dir = derived.get("scene_extractions_dir", "")
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
        "scene_extractions_dir": _resolve(args.extract_dir) or "",
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

    # Initialize editor with config
    scene_editor.init_editor_config(config)

    # Construct the unified config service. Routers read everything through
    # it; if no campaign directory can be determined, fail loudly rather
    # than fall back to a synthetic default.
    campaign_dir_for_service = _resolve_campaign_dir_for_service(args)
    if campaign_dir_for_service is None:
        print(
            "Could not determine the campaign directory. Pass --campaign-dir "
            "/path/to/campaign, or cd into a campaign directory containing "
            "config/config.yaml.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        app.state.config_service = CampaignConfigService(
            campaign_dir_for_service,
            config_dir=args.config_dir,
            boot_overrides=boot_overrides,
        )
    except ConfigError as exc:
        bar = "=" * 72
        print(
            f"\n{bar}\nERROR: config service failed to initialize.\n"
            f"  campaign_dir: {campaign_dir_for_service}\n"
            f"  cause: {exc}\n"
            f"Fix the offending file (likely {campaign_dir_for_service}/ui_state.yaml) "
            f"and relaunch.\n{bar}\n",
            file=sys.stderr,
        )
        sys.exit(1)
    for warning in app.state.config_service.load_warnings:
        print(f"  config: {warning}")

    os.chdir(app.state.config_service.campaign_dir)

    print(f"  CampaignGenerator UI")
    if config["session"]:
        print(f"  Session:     {config['session']}")
    if config["scene_extractions_dir"]:
        print(f"  Extractions: {config['scene_extractions_dir']}")
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
