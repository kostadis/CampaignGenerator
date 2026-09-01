"""FastAPI application — serves the Vue frontend and API routes."""

import argparse
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.platform_config_service import ConfigError, PlatformConfigService
from server.routers import (
    config_routes, connections, ensemble, grounding, prep,
    scene_editor, setup, planning_routes, party_routes, players_routes,
    projections, integrations, narration_wiki,
)

app = FastAPI(title="CampaignGenerator")

# CORS for Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Selection refusal (feature 003) ─────────────────────────────────────────
# A run whose resolved model cannot be served by its resolved backend is
# refused BEFORE any subprocess is spawned, rather than being retargeted at a
# model the operator did not choose.
#
# There is no handler to register here: IncompatibleSelection subclasses
# HTTPException(409), so FastAPI's built-in handler renders it wherever the
# router is mounted. An app-level handler in this module would only cover apps
# this module builds — several test fixtures mount routers on a bare FastAPI()
# and would have got an unhandled 500 instead of a refusal.


# ── API routers ──────────────────────────────────────────────────────────────
 
app.include_router(config_routes.router, prefix="/api/config", tags=["config"])
app.include_router(grounding.router, prefix="/api/grounding", tags=["grounding"])
app.include_router(ensemble.router, prefix="/api/ensemble", tags=["ensemble"])
app.include_router(prep.router, prefix="/api/prep", tags=["prep"])
app.include_router(setup.router, prefix="/api/setup", tags=["setup"])
app.include_router(scene_editor.router, prefix="/api/editor", tags=["editor"])
app.include_router(connections.router, prefix="/api/connections", tags=["connections"])
app.include_router(planning_routes.router, prefix="/api/planning", tags=["planning"])
app.include_router(party_routes.router, prefix="/api/party", tags=["party"])
app.include_router(players_routes.router, prefix="/api/players", tags=["players"])
app.include_router(projections.router, prefix="/api/projections", tags=["projections"])
app.include_router(integrations.router, prefix="/api/integrations", tags=["integrations"])
app.include_router(narration_wiki.router, prefix="/api/narration-wiki", tags=["narration-wiki"])

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
    flags must NOT persist to disk. ``PlatformConfigService.resolved()``
    applies them on top of the persisted values for this process only.

    ``--session-dir`` is the only flag left that produces an override (per
    O1 in docs/config/platform-isolation.md): the twelve ``session_doc.*``
    flags this used to map were silent no-ops — the section they targeted had
    left the shared config document, so ``resolved()`` was routing them into
    a phantom key nothing ever read. They were deleted from argparse rather
    than wired to a real consumer, since the Session Doc Editor already has
    its own per-campaign persisted config (``session_doc.yaml``) for exactly
    these fields.

    An override aimed at a section with no consumer is now a boot-time
    ``ConfigError`` rather than a value quietly swept aside — see
    ``platform_config_service._BOOT_OVERRIDE_SECTIONS``.
    """
    flag_map = {
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
    return overrides


# ── CLI entry point ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="CampaignGenerator web UI server")
    parser.add_argument("--campaign-dir", metavar="DIR",
                        help="Campaign root directory (contains docs/, voice/, examples/, summaries/)")
    parser.add_argument("--session-dir", metavar="DIR",
                        help="Session directory inside summaries/ — auto-derives all paths")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--config-dir", metavar="DIR", default="config",
                        help="Configuration subdirectory within campaign (default: 'config')")
    args = parser.parse_args()

    # Boot overrides are computed once, up front, from the parsed CLI args —
    # see _boot_overrides_from_args for which flags qualify (--session-dir
    # only, as of O1 in docs/config/platform-isolation.md).
    #
    # Session-path derivation from --session-dir happens once, inside
    # PlatformConfigService.resolved() / SessionEditorConfigService — driven
    # entirely by the `runtime.session_dir` boot override captured above.
    # There is no second, main.py-local derivation to keep in sync.
    boot_overrides = _boot_overrides_from_args(args)

    # Construct the platform service. Every router reaches it (and, through
    # it, the residual UIStateService) via app.state.platform; if no
    # campaign directory can be determined, fail loudly rather than fall
    # back to a synthetic default.
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
        app.state.platform = PlatformConfigService(
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
            # The documents a ConfigError can actually come from, in the
            # order the service loads them. This used to name ui_state.yaml,
            # which the server has not read since
            # docs/config/ui-state-retirement.md — pointing a GM at a file
            # that cannot be the cause is worse than naming none.
            f"Fix the offending file in {campaign_dir_for_service}/{args.config_dir}/ "
            f"(config.yaml or platform.yaml) and relaunch.\n{bar}\n",
            file=sys.stderr,
        )
        sys.exit(1)
    for warning in app.state.platform.load_warnings:
        print(f"  config: {warning}")

    os.chdir(app.state.platform.campaign_dir)

    print(f"  CampaignGenerator UI")
    print(f"  Campaign:    {app.state.platform.campaign_dir}")
    resolved_session_dir = app.state.platform.resolved()["runtime"].get("session_dir")
    if resolved_session_dir:
        print(f"  Session:     {resolved_session_dir}")
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
