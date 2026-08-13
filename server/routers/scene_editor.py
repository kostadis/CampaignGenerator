"""Scene editor API routes.

Drives the four-stage pipeline:

1. Stage 1 — `enhance_summary` produces the enriched session-summary.md.
2. Stage 2 — `scene_extract` produces per-scene verbatim quote files
   (NN_<slug>.md) under `scene_extractions_dir`.
3. Stage 3 — `session_doc.py --per-scene-output` writes one narration file
   per scene (`session_doc_scene_NN_<slug>.md`) under `narration_dir`.
4. Stage 4 — `assemble` concatenates the narrations into the final doc.

The raw `.vtt` is an INPUT to stages 1 and 2 (`_vtt_path` resolves it from
`cfg.vtt` or globs the session dir). The retired `vtt_summary` chain —
`vtt_roleplay_extractions/`, the `/vtt` route and its read-only panel —
is gone; nothing here reads a pre-extracted roleplay directory.
"""

import json
import re
import subprocess
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from campaignlib import wiring_get
from campaignlib.party_config import PARTY_CONFIG_FILENAME

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from server.backend_forwarding import backend_cli_args
from server.platform_config_service import resolve_selection, selection_cli_args
from server.platform_config_shared import ModelSelection
from server.session_editor_config_shared import ProfileEntry
from server.session_editor_config_service import (
    ResolvedEditorConfig,
    SessionEditorConfigService,
)
from server.subprocess_runner import (
    console_script,
    sse_error_stream,
    stream_subprocess,
)


def _sse_error(message: str):
    """StreamingResponse that delivers a precondition failure over SSE.

    Used instead of a 400 JSONResponse for endpoints the frontend opens with
    an EventSource — see ``sse_error_stream`` for why the body must stream.
    """
    return StreamingResponse(
        sse_error_stream(message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ── Config dependencies ─────────────────────────────────────────────────────
# Every route reads its config through a request-scoped ResolvedEditorConfig
# (server/session_editor_config_service.py) injected via Depends — no
# process-global mutable state. See docs/config/session-editor-isolation.md.

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent  # CampaignGenerator/


def get_editor_service(request: Request) -> SessionEditorConfigService:
    """Build the session-editor config service for this request.

    Mirrors ``config_routes._require_service``: 503 when the platform
    config service hasn't been initialized (campaign_dir not resolved at
    boot) rather than silently falling back to a default.
    """
    platform = getattr(request.app.state, "platform", None)
    if platform is None:
        raise HTTPException(
            status_code=503,
            detail="config service not initialized — campaign_dir not resolved at boot",
        )
    return SessionEditorConfigService(platform)


def get_editor_config(
    service: SessionEditorConfigService = Depends(get_editor_service),
) -> ResolvedEditorConfig:
    """Request-scoped, read-only resolved editor config."""
    return service.resolved_editor_config()


router = APIRouter()


def _serialize_resolved(cfg: ResolvedEditorConfig) -> dict:
    """Wire shape for a resolved editor config — the single source of truth
    for both ``GET /api/editor/config`` and the profile-activate response,
    so the two never drift apart."""
    return {
        "paths": cfg.paths.model_dump(),
        "narrate": cfg.narrate.model_dump(),
        "scrub": cfg.scrub.model_dump(),
        "roster": cfg.roster.model_dump(),
        "backends": cfg.backends.model_dump(by_alias=True),
        "session_name": cfg.session_name,
        "profiles": [p.model_dump() for p in cfg.profiles],
        "active_profile": cfg.active_profile,
        "model": cfg.model,
        "work_dir": cfg.work_dir,
        "campaign_dir": cfg.campaign_dir,
        "config_dir": cfg.config_dir,
        "vtt": cfg.vtt,
        "session_dir": cfg.session_dir,
        # Display-only summary of the genre rulebook file (#276 fix 2). The UI
        # shows path + counts + a preview; it does not offer to edit the file,
        # because a browser textarea is what flattened 88 lines into one (#249).
        "genre": asdict(cfg.genre) if cfg.genre is not None else None,
    }


@router.get("/config")
def api_get_config(cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """Return the resolved editor config, grouped."""
    return _serialize_resolved(cfg)


@router.put("/config")
async def api_put_config(
    request: Request,
    service: SessionEditorConfigService = Depends(get_editor_service),
):
    """Update the editor config at runtime (from the frontend).

    The single editor-config write door: the body is a grouped
    ``SessionEditorConfig`` partial (any nested subset of ``paths`` /
    ``narrate`` / ``scrub`` / ``roster`` / ``backends`` / ``session_name`` /
    ``profiles`` / ``active_profile``), merged into the stored config by
    ``SessionEditorConfigService.update_config``.
    """
    data = await request.json()
    try:
        service.update_config(data)
    except HTTPException as exc:
        return JSONResponse(
            {"ok": False, "error": str(exc.detail)},
            status_code=exc.status_code,
        )
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": str(exc)},
            status_code=400,
        )
    return {"ok": True}


# ── Profile endpoints (the one sub-collection) ──────────────────────────────
# Server-side profile activation (O2, locked decision): activating mirrors
# the profile's narrate/backend knobs into the stored config on the server
# (SessionEditorConfigService.activate_profile) and returns the re-resolved
# editor config — the same shape GET /api/editor/config returns.


@router.get("/profiles", response_model=list[ProfileEntry])
def api_list_profiles(
    service: SessionEditorConfigService = Depends(get_editor_service),
):
    """List all saved Narrate-knob presets."""
    return service.list_profiles()


@router.post(
    "/profiles", response_model=ProfileEntry, status_code=status.HTTP_201_CREATED
)
def api_create_profile(
    entry: ProfileEntry,
    service: SessionEditorConfigService = Depends(get_editor_service),
):
    """Create a new profile. 409 if a profile with this name already exists."""
    return service.create_profile(entry)


@router.get("/profiles/{name}", response_model=ProfileEntry)
def api_get_profile(
    name: str, service: SessionEditorConfigService = Depends(get_editor_service)
):
    """Get a single profile by name. 404 if missing."""
    return service.get_profile(name)


@router.put("/profiles/{name}", response_model=ProfileEntry)
def api_update_profile(
    name: str,
    entry: ProfileEntry,
    service: SessionEditorConfigService = Depends(get_editor_service),
):
    """Replace an existing profile. 400 on URL/body name mismatch, 404 if missing."""
    return service.update_profile(name, entry)


@router.delete("/profiles/{name}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_profile(
    name: str, service: SessionEditorConfigService = Depends(get_editor_service)
):
    """Delete a profile by name. 404 if missing."""
    service.delete_profile(name)
    return None


@router.post("/profiles/{name}/activate")
def api_activate_profile(
    name: str, service: SessionEditorConfigService = Depends(get_editor_service)
):
    """Mirror a profile's knobs into the stored config (server-side, O2) and
    return the re-resolved editor config — same JSON shape as
    ``GET /api/editor/config``. 404 if the profile doesn't exist."""
    service.activate_profile(name)
    return _serialize_resolved(service.resolved_editor_config())


# ── Path helpers ────────────────────────────────────────────────────────────

def _slugify(s: str) -> str:
    """Match campaignlib._slugify so filename lookups round-trip."""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _session_dir(cfg: ResolvedEditorConfig) -> Path | None:
    """Directory holding the session's gm-assist + VTT + outputs.

    Prefers the parent of the saved gm-assist recap (``session_recap``) —
    that's the directory the editor is actually working in. Falls back to
    the platform's resolved ``runtime.session_dir`` (populated at boot via
    ``--session-dir`` even before a recap has been saved), and only then to
    ``work_dir`` (the campaign root) as a last resort — previously this
    skipped straight from ``session_recap`` to ``work_dir``, so VTT/summary
    auto-detection scanned the campaign root instead of the session dir
    whenever no recap had been saved yet.
    """
    if cfg.paths.session_recap:
        return Path(cfg.paths.session_recap).expanduser().parent
    if cfg.session_dir:
        return Path(cfg.session_dir).expanduser()
    if cfg.work_dir:
        return Path(cfg.work_dir).expanduser()
    return None


def _session_summary_path(cfg: ResolvedEditorConfig) -> Path | None:
    """Path to the Stage-1 enriched summary."""
    if cfg.paths.session_summary:
        return Path(cfg.paths.session_summary).expanduser()
    sd = _session_dir(cfg)
    if sd:
        return sd / "session-summary.md"
    return None


def _vtt_path(cfg: ResolvedEditorConfig) -> Path | None:
    """Path to the raw .vtt — explicit cfg.vtt or first *.vtt in session dir."""
    if cfg.vtt:
        return Path(cfg.vtt).expanduser()
    sd = _session_dir(cfg)
    if sd and sd.is_dir():
        vtts = sorted(sd.glob("*.vtt"))
        if vtts:
            return vtts[0]
    return None


def _scene_extractions_dir(cfg: ResolvedEditorConfig) -> Path | None:
    """Stage 2 output dir."""
    if cfg.paths.scene_extractions_dir:
        return Path(cfg.paths.scene_extractions_dir).expanduser()
    return None


def _narration_dir(cfg: ResolvedEditorConfig) -> Path | None:
    """Stage 3 output dir."""
    if cfg.paths.narration_dir:
        return Path(cfg.paths.narration_dir).expanduser()
    return None


def _narration_file_for_scene(cfg: ResolvedEditorConfig, n: int) -> Path | None:
    """Glob the new-flow per-scene narration file for scene n."""
    nd = _narration_dir(cfg)
    if not nd or not nd.is_dir():
        return None
    matches = sorted(
        f for f in nd.glob(f"session_doc_scene_{n:02d}_*.md")
        if not f.name.endswith(".scrubbed.md")
    )
    return matches[0] if matches else None


def _scrubbed_for_scene(cfg: ResolvedEditorConfig, n: int) -> bool:
    """True iff a `.scrubbed.md` sibling exists for scene n's narration file."""
    narr = _narration_file_for_scene(cfg, n)
    if narr is None:
        return False
    return narr.with_name(narr.stem + ".scrubbed.md").exists()


def _activity_jsonl_path(cfg: ResolvedEditorConfig) -> Path | None:
    """``<session_dir>/.cg/activity.jsonl`` — created on first write."""
    sd = _session_dir(cfg)
    if sd is None:
        return None
    return sd / ".cg" / "activity.jsonl"


def _narrate_knobs_snapshot(cfg: ResolvedEditorConfig) -> dict:
    """Capture the Stage-④ knobs at the moment a narration is produced.

    Stashed alongside each narration file so the Review screen can show
    "which flags were applied to this scene" without consulting the
    activity log.
    """
    snapshot = {
        "narrate_tokens": cfg.narrate.tokens,
        "prose_mode": bool(cfg.narrate.prose_mode),
        "reflections": bool(cfg.narrate.reflections),
        "narration_genre_file": cfg.paths.genre_file,
        "backend": cfg.backends.active or "anthropic",
    }
    # Record which rulebook was used, by identity rather than by copy (#276
    # fix 2). This field used to hold the whole genre document, so every
    # per-scene sidecar carried its own 16K duplicate; the digest answers the
    # question that mattered ("same rulebook as that other run?") and also
    # reveals a file edited between two runs, which a path alone cannot.
    if cfg.genre is not None and cfg.genre.exists:
        snapshot["narration_genre_sha"] = cfg.genre.sha256
        snapshot["narration_genre_lines"] = cfg.genre.lines
    return snapshot


def _record_activity(cfg: ResolvedEditorConfig, *, stage: str, rc: int | None,
                     scene: int | None = None,
                     knobs: dict | None = None,
                     outputs: list[str] | None = None) -> None:
    """Append one JSON line to ``<session_dir>/.cg/activity.jsonl``.

    Best-effort: any failure is swallowed so a broken sidecar never
    stops the SSE stream from completing.
    """
    try:
        path = _activity_jsonl_path(cfg)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "rc": rc,
        }
        if scene is not None:
            entry["scene"] = scene
        if knobs is not None:
            entry["knobs"] = knobs
        if outputs:
            entry["outputs"] = outputs
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _write_knobs_sidecar(narration_path: Path | None, knobs: dict) -> None:
    """``session_doc_scene_NN_<slug>.knobs.json`` next to the narration."""
    if narration_path is None:
        return
    try:
        sidecar = narration_path.with_name(narration_path.stem + ".knobs.json")
        sidecar.write_text(json.dumps(knobs, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def _ago_string(ts: float) -> str:
    """Human-friendly elapsed time. ts is a POSIX mtime."""
    import time
    delta = max(0.0, time.time() - ts)
    if delta < 90:
        return f"{int(delta)}s"
    minutes = delta / 60
    if minutes < 90:
        return f"{int(minutes)}m"
    hours = minutes / 60
    if hours < 36:
        return f"{int(hours)}h"
    days = hours / 24
    return f"{int(days)}d"


def _stage_status(output: Path | None,
                  inputs: list[Path],
                  *,
                  output_must_exist: bool = True) -> dict:
    """Compare output mtime against input mtimes.

    Returns ``{"status": ok|warn|cold, "ago": str|None, "mtime": float|None}``.
    The ``bad`` state (last run failed) isn't tracked yet — we'd need to
    record subprocess exit codes for that. Phase 3 wires it in.
    """
    if output is None or not output.exists():
        return {"status": "cold", "ago": None, "mtime": None}
    out_mtime = output.stat().st_mtime
    in_mtimes = [p.stat().st_mtime for p in inputs if p.exists()]
    status = "ok"
    if in_mtimes and max(in_mtimes) > out_mtime:
        status = "warn"
    if not output_must_exist:
        status = "ok"
    return {
        "status": status,
        "ago": _ago_string(out_mtime),
        "mtime": out_mtime,
    }


def _scene_extraction_file_new(cfg: ResolvedEditorConfig, n: int, scene_name: str) -> Path | None:
    """New-flow scene file. Prefer the cleaned scaffold
    (`NN_<slug>.scaffold.md`) when it exists; otherwise return the
    Stage-2 source file (`NN_<slug>.md`). The scaffold is what the
    user edits and what Narrate consumes; the Stage-2 file is the
    expensive LLM source that we never overwrite."""
    sx = _scene_extractions_dir(cfg)
    if not sx:
        return None
    slug = _slugify(scene_name) or f"scene_{n}"
    scaffold = sx / f"{n:02d}_{slug}.scaffold.md"
    if scaffold.exists():
        return scaffold
    exact = sx / f"{n:02d}_{slug}.md"
    if exact.exists():
        return exact

    # Index fallback. sd_plan retitles scenes, so a plan title need not
    # slugify to the stage-2 filename it was derived from ("The Statue
    # Returned, a Quest Begun" vs 05_the_return_of_the_meliamne_statue...).
    # Without this the file reads as missing, has_extraction goes False and
    # the editor greys out Narrate for a scene the CLI would narrate fine —
    # sd_narrate already does "name match, fallback to index". The NN_ prefix
    # is unique per scene, so matching on it cannot mis-resolve.
    scaffolds = sorted(sx.glob(f"{n:02d}_*.scaffold.md"))
    if scaffolds:
        return scaffolds[0]
    plains = sorted(
        p for p in sx.glob(f"{n:02d}_*.md")
        if not p.name.endswith(".scaffold.md")
    )
    if plains:
        return plains[0]

    # Genuinely absent — return the slug path so .exists() callers behave
    # exactly as before.
    return exact


# ── Helpers (ported from session_doc_ui.py) ──────────────────────────────────

def _load_scenes(cfg: ResolvedEditorConfig) -> list[dict]:
    """Return scene metadata.

    New flow: if narration_dir/plan.md exists, parse it (scenes get narrators).
    Otherwise derive a bare scene list from the Stage-2 extraction filenames
    (NN_<slug>.md) and their `scene:` frontmatter — no narrator until first
    Narrate run generates plan.md via Pass 3.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    from session_doc import parse_plan

    nd = _narration_dir(cfg)
    plan_path: Path | None = None
    if nd and (nd / "plan.md").exists():
        plan_path = nd / "plan.md"

    if plan_path is None:
        return _scenes_from_extractions(cfg)

    sections = parse_plan(plan_path.read_text(encoding="utf-8"), total_chunks=99)
    result = []
    for i, s in enumerate(sections, 1):
        ext = _scene_extraction_file_new(cfg, i, s.get("scene", ""))
        ext_path = ext if ext else None
        ext_name = ext.name if ext else ""
        narr_path = _narration_file_for_scene(cfg, i)
        has_output = narr_path is not None and narr_path.exists()
        result.append({
            "index": i,
            "narrator": s["narrator"],
            "scene": s.get("scene", ""),
            "focus": s.get("focus", ""),
            "chunk_start": s["chunk_start"],
            "chunk_end": s["chunk_end"],
            "has_extraction": bool(ext_path and ext_path.exists()),
            "has_output": has_output,
            "has_scrubbed": _scrubbed_for_scene(cfg, i),
            "filename": ext_name,
            "reviewed": _reviewed_for_path(ext_path),
        })
    return result


def _scenes_from_extractions(cfg: ResolvedEditorConfig) -> list[dict]:
    """Bare scene list derived from Stage-2 NN_<slug>.md files (no narrator)."""
    sx = _scene_extractions_dir(cfg)
    if not sx or not sx.is_dir():
        return []
    files = sorted(
        f for f in sx.glob("[0-9][0-9]_*.md")
        if not f.name.endswith(".scaffold.md")
    )
    result = []
    for f in files:
        try:
            idx = int(f.name[:2])
        except ValueError:
            continue
        scene_name = ""
        head = f.read_text(encoding="utf-8", errors="replace")[:400]
        if head.startswith("---\n"):
            for line in head.split("\n"):
                if line.startswith("scene:"):
                    scene_name = line.split(":", 1)[1].strip()
                    break
        if not scene_name:
            scene_name = f.stem[3:].replace("_", " ").title()
        narr_path = _narration_file_for_scene(cfg, idx)
        result.append({
            "index": idx,
            "narrator": "",  # filled in once plan.md is generated
            "scene": scene_name,
            "focus": "",
            "chunk_start": idx,
            "chunk_end": idx,
            "has_extraction": True,
            "has_output": narr_path is not None and narr_path.exists(),
            "has_scrubbed": _scrubbed_for_scene(cfg, idx),
            "filename": f.name,
            "reviewed": _reviewed_for_path(f),
        })
    return result


def _get_extraction_path(cfg: ResolvedEditorConfig, n: int) -> Path | None:
    scenes = _load_scenes(cfg)
    if n < 1 or n > len(scenes):
        return None
    s = scenes[n - 1]
    return _scene_extraction_file_new(cfg, n, s.get("scene", ""))


def _reviewed_marker_path(cfg: ResolvedEditorConfig, n: int) -> Path | None:
    """Sidecar marker file capturing the GM's "order looks right" approval.

    Lives next to the extraction file as `<extraction>.reviewed`. The
    file's existence is the signal; its contents are an empty string.
    Sidecar (rather than frontmatter mutation) so the human-edited
    extraction never gets rewritten by the toggle.
    """
    ext_path = _get_extraction_path(cfg, n)
    if ext_path is None:
        return None
    return ext_path.with_name(ext_path.name + ".reviewed")


def _reviewed_for_path(ext_path: Path | None) -> bool:
    if ext_path is None:
        return False
    return ext_path.with_name(ext_path.name + ".reviewed").exists()


def _open_in_typora(filepath: Path) -> None:
    try:
        win = subprocess.check_output(
            ["wslpath", "-w", str(filepath.resolve())]
        ).decode().strip()
        subprocess.Popen(["powershell.exe", "-c", f'Start-Process "{win}"'])
        print(f"  Opening: {win}")
    except Exception as e:
        print(f"  Warning: could not open file: {e}", file=sys.stderr)


def _assembled_output_path(cfg: ResolvedEditorConfig) -> Path:
    """Where assemble writes its output."""
    session_stem = Path(cfg.paths.session_recap).stem
    sd = _session_dir(cfg) or Path.cwd()
    return sd / f"{session_stem}-doc.md"




# ── Command builders ────────────────────────────────────────────────────────

def _editor_service_selection(cfg: ResolvedEditorConfig):
    """The Session Doc Editor's own selection, as a ModelSelection-shaped view.

    The editor stores a profile per backend (``backends.<name>``) plus which
    one is ``active``; feature 003's service tier is that active profile. The
    dgx profile falls back to wiring for model/endpoint, as it always has.

    Returns ``None`` when the editor has nothing of its own to say, so the
    seam falls straight through to the platform selection.
    """
    active = cfg.backends.active
    prof = {
        "anthropic": cfg.backends.anthropic,
        "claude-code": cfg.backends.claude_code,
        "dgx": cfg.backends.dgx,
        "openrouter": cfg.backends.openrouter,
    }[active]

    model = (prof.model or "").strip() or None
    endpoint = (prof.endpoint or "").strip() or None
    if active == "dgx":
        model = model or wiring_get("dgx_model")
        endpoint = endpoint or wiring_get("dgx_endpoint")

    # `prof.batch` (005-ui-batch-selection) must ride along here — this is
    # the ONE place the active profile is translated into the ModelSelection
    # shape `resolve_selection` consumes, for both the actual run
    # (`_selection_args`) and the preview (`get_editor_resolved_selection`).
    # Dropping it here would silently discard the operator's stored batch
    # choice from every editor run and its own preview alike.
    return ModelSelection(backend=active, model=model, batch=prof.batch), endpoint


def _selection_args(request, cfg: ResolvedEditorConfig, *,
                    allow_openai_compat: bool = True) -> list[str]:
    """Resolve this editor run's selection and render it as CLI flags.

    Feature 003 replaced the ``_model_args`` + ``_backend_flags`` pair with
    one seam call. Those two split the job by backend — ``_model_args``
    emitted ``--model`` for anthropic/claude-code and deliberately nothing
    for dgx/openrouter, where ``_backend_flags`` supplied its own — which
    worked, but meant the rule lived in two places and neither could see the
    whole pair. ``resolve_selection`` sees both halves and emits exactly one
    ``--model`` (contract guarantee C1).

    ``allow_openai_compat=False`` (the plan routes) still suppresses the DGX
    OpenAI-compat adapter, whose shape can't serve routes that may use
    tool-use. Preserved exactly: those routes fall back to the script's own
    argparse default rather than being retargeted, which is what they did
    before 003. This is the one path that deliberately does not forward a
    resolved selection, and it is a behaviour-preserving carve-out rather
    than an oversight.

    The batch flag (005-ui-batch-selection, T029) rides the same seam now
    instead of the bespoke ``?batch=1``/checkbox mechanism this replaces —
    ``_editor_service_selection`` already folds ``prof.batch`` into the
    ``ModelSelection`` passed to ``resolve_selection`` above, so ``resolved``
    carries the right value (and already raises ``IncompatibleSelection``,
    naming batch, before any subprocess is built — that part predates this
    change). What was missing was emitting the flag: mirrors
    ``ensemble.py::_backend_args`` — ``--backend``/``--endpoint`` still come
    from ``backend_cli_args`` called directly with the editor's own SINGULAR
    ``endpoint`` (``resolved.endpoint`` is unset here by construction, since
    ``_editor_service_selection`` builds a plain ``ModelSelection`` with no
    endpoint field — the ensemble twin has the same reason for not routing
    its plural ``endpoints`` through ``resolved`` either), while ``--model``
    and the batch flag come from ``selection_cli_args`` via a throwaway copy
    of ``resolved`` with ``backend`` forced to ``"anthropic"`` so that call
    contributes only those two flags — ``backend_cli_args("anthropic", ...)``
    short-circuits to ``[]`` regardless of endpoint, so this never emits a
    second, wrongly-shaped ``--backend``/``--endpoint`` pair.
    """
    service, endpoint = _editor_service_selection(cfg)

    if service.backend == "dgx" and not allow_openai_compat:
        return []

    resolved = resolve_selection(
        request,
        service=service,
        service_name="session_doc",
    )
    args = backend_cli_args(resolved.backend, endpoint=endpoint)
    args += selection_cli_args(replace(resolved, backend="anthropic"))
    return args


def _editor_resolved_batch(request, cfg: ResolvedEditorConfig) -> bool:
    """Whether this editor run's resolved selection has batch on.

    Used only to log an honest value in the activity-log knob snapshot
    (``_record_activity``'s ``knobs={"batch": ...}``) now that batch is no
    longer a route query param a caller hands in directly (T029). By the
    time a route reaches this (inside its SSE `on_complete` callback,
    always after ``_selection_args`` has already run once for the same
    request/cfg without raising) the selection is known compatible, so this
    recomputation is redundant-but-cheap rather than a second chance to
    refuse.
    """
    service, _endpoint = _editor_service_selection(cfg)
    return resolve_selection(
        request,
        service=service,
        service_name="session_doc",
        raise_on_incompatible=False,
    ).batch



def _party_config_path(cfg: ResolvedEditorConfig) -> Path | None:
    """The campaign's ``<config>/party.yaml``, or ``None`` if absent.

    Resolved by *declaration*, not configured and not probed. Track 0 of
    ``docs/config/grounding-isolation.md`` (GM directive, 2026-07-24) makes
    ``<campaign>/config/`` the one location for config documents — a
    ``party.yaml`` anywhere else is a migration input for
    ``migrate_config.sh``, not a supported alternative. Adding an
    ``EditorPaths.party_config`` field here would recreate exactly the second
    location Track 0 deleted, and ``tests/test_config_location.py`` guards
    against the list-of-candidates shape that caused it.

    Mirrors ``PlatformConfigService.config_path_base`` (``campaign_dir /
    config_dir``) rather than ``campaignlib.constants.config_path``, so a
    campaign that has renamed its config directory is still honoured.

    This is what makes the sheet-frontmatter roster (#265) reachable from the
    Session Doc Editor at all: the readers take ``--party-config``, the editor
    only ever passed ``--party``, so ``args.party_config`` was always ``None``
    for UI runs and the per-character diagnostics never ran.
    """
    p = Path(cfg.campaign_dir) / cfg.config_dir / PARTY_CONFIG_FILENAME
    return p if p.exists() else None


def _party_args(cfg: ResolvedEditorConfig) -> list[str] | tuple[None, str]:
    """``--party``/``--party-config`` for the two builders that read a roster
    (``_build_reextract_cmd``, ``_build_narrate_cmd``), or ``(None, reason)``.

    ``--party`` alone is fatal downstream since #265 deleted the ``party.md``
    roster fallback, so emitting it without a resolvable ``party.yaml`` would
    hand the GM a subprocess crash and a message naming a flag the UI does not
    expose. Refuse here instead, where the editor turns ``(None, reason)`` into
    a readable error.

    Dropping ``--party`` would be worse than refusing: it also gates VTT
    speaker normalisation and ``enhance_summary``'s wrong-VTT pre-flight, so a
    silent omission would quietly disable both.

    Not for ``sd_plan`` — it takes ``--party`` as raw prompt text and has no
    ``--party-config`` argument at all.
    """
    if not cfg.paths.party:
        return []
    party_config = _party_config_path(cfg)
    if party_config is None:
        return None, (
            f"{Path(cfg.campaign_dir) / cfg.config_dir / PARTY_CONFIG_FILENAME} "
            "not found. The roster comes from each character's sheet frontmatter "
            "(#265) and party.md is no longer read for it, so this file is "
            "required. Create it, then run: sheet_frontmatter --apply <sheet>.md"
        )
    return ["--party", cfg.paths.party, "--party-config", str(party_config)]


def _examples_args(cfg: ResolvedEditorConfig, plan_path: Path
                   ) -> list[str] | tuple[None, str]:
    """``--examples``/``--characters``, or ``(None, reason)`` (#301).

    Refused here rather than forwarded, for the reason ``_party_args``
    refuses: the editor turns ``(None, reason)`` into readable text, where the
    subprocess's stderr reaches the GM only as a failed run.

    Two conditions:

    - the declared directory does not exist (a typo, and a silent one —
      ``_load_examples`` returns ``(None, {})`` for a missing path, which is
      indistinguishable from "no examples configured");
    - a per-character file is about to reach **every** narrator because the
      roster does not name its character. That is the #301 bleed, and it is
      keyed off the plan's narrators rather than the file names alone, so a
      campaign whose examples are all house style — toee's
      ``political_maneuvering.md`` and friends — is not refused for it.

    A directory that exists but holds no examples is NOT refused: like
    ``voice/``, ``examples/`` is created empty by ``new_workspace`` and
    ``PlatformConfigService.derive`` fills ``examples_dir`` in from its mere
    existence, so that state is the tool's doing rather than a GM's.
    """
    args: list[str] = []
    if cfg.roster.characters:
        args += ["--characters", cfg.roster.characters]
    if not cfg.paths.examples_dir:
        return args

    examples_dir = Path(cfg.paths.examples_dir).expanduser()
    if not examples_dir.is_dir():
        return None, (
            f"examples_dir {examples_dir} is not a directory. Pass 5 would "
            f"render with no style examples. Fix the path in Session Config, "
            f"or clear it to render without them."
        )

    sys.path.insert(0, str(SCRIPT_DIR))
    from session_doc import parse_plan
    from session_doc.examples import examples_routing_problems

    characters = [c.strip() for c in (cfg.roster.characters or "").split(",") if c.strip()]
    sections = parse_plan(plan_path.read_text(encoding="utf-8"), total_chunks=99)
    problems = examples_routing_problems(
        examples_dir, characters, [s["narrator"] for s in sections]
    )
    if problems:
        return None, (
            f"{problems[0]} Set Characters in Session Config to every "
            f"narrating character (currently {cfg.roster.characters!r}), or "
            f"rename the file so it is not per-character."
        )
    return args + ["--examples", cfg.paths.examples_dir]


def _build_enhance_cmd(request, cfg: ResolvedEditorConfig) -> list[str] | tuple[None, str]:
    """Stage 1: enhance_summary {vtt} --gmassist {session} --output {summary}.

    Returns the command list, or (None, error_message) on misconfig.

    The batch flag (Message Batches API; 50% off list price; the script's
    poll-progress lines flow over the same SSE stream) is no longer a param
    here — the bespoke checkbox that used to supply one is retired
    (005-ui-batch-selection, T029). ``_selection_args`` forwards it whenever
    the resolved selection's batch is true, the same way every other
    service's run command picks it up.
    """
    vtt = _vtt_path(cfg)
    if vtt is None or not vtt.exists():
        return None, "no .vtt file resolved (set CONFIG['vtt'] or place a *.vtt in the session dir)"
    if not cfg.paths.session_recap:
        return None, "CONFIG['session'] (gm-assist.md) is required"
    summary = _session_summary_path(cfg)
    if summary is None:
        return None, "could not resolve session-summary.md output path"
    cmd = [
        console_script("enhance_summary"),
        str(vtt),
        "--gmassist", cfg.paths.session_recap,
        "--output", str(summary),
    ]
    cmd += _selection_args(request, cfg)
    # Deliberately no --party/--party-config. enhance_summary gates its whole
    # roster block on `if party_path is not None`, so --party-config alone is
    # inert, and adding --party would newly switch on speaker-attribution
    # checking in Stage 1 — a behaviour change, not plumbing. Tracked at #265.
    return cmd


def _quote_report_path(cfg: ResolvedEditorConfig) -> Path | None:
    nd = _narration_dir(cfg)
    return (nd / "quote_report.md") if nd else None


def _quote_report_json_path(cfg: ResolvedEditorConfig) -> Path | None:
    """The typed sidecar beside ``_quote_report_path`` (#264).

    ``sd_verify_quotes`` writes it as ``out_path.with_suffix(".json")`` next
    to the markdown report, so this is always ``quote_report.md`` ->
    ``quote_report.json`` for the same narration dir.
    """
    nd = _narration_dir(cfg)
    return (nd / "quote_report.json") if nd else None


def _load_quote_report_json(md_path: Path | None) -> dict | None:
    """Parsed ``quote_report.json`` beside ``md_path``, or ``None``.

    ``None`` covers "no md path given", "no sidecar on disk", "unreadable",
    and "not valid JSON" alike — every one of those must read as "we could not
    tell", never as an empty-but-known report.
    """
    if md_path is None:
        return None
    json_path = md_path.with_suffix(".json")
    if not json_path.exists():
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _parse_quote_report_counts(path: Path | None) -> dict:
    """Per-verdict counts from a quote report's ``quote_report.json`` sidecar.

    Returns ``None`` for each count when the sidecar is missing or unparseable
    rather than zero — "no unverified quotes" and "we could not tell" must not
    look the same to the status strip, since the second is a reason to look and
    the first is a reason not to.

    The markdown table is *not* read. A regex over it was a compatibility shim
    for narration dirs that ran verify before ``sd_verify_quotes`` wrote the
    sidecar; it has been deleted (#264). A pre-sidecar report therefore now
    reads as "could not tell" and the status strip goes amber, which is the
    honest answer — re-run verify to get counts back.
    """
    empty = {"verified": None, "near": None, "unverified": None,
             "unscored": None, "exempt": None}
    data = _load_quote_report_json(path)
    if data is None:
        return empty
    counts = data.get("counts")
    if not isinstance(counts, dict) or not counts:
        return empty
    return {k: counts.get(k) for k in empty}


def _parse_quote_report_refusals(path: Path | None) -> int | None:
    """How many spans the #250 contract refused. ``None`` when unknown.

    ``None`` rather than ``0`` for the same reason the verdict counts do it: a
    report written before refusals existed, or one that could not be read, must
    not be reported as a run that found none.

    Reads the JSON sidecar's ``refusals.total`` (#264) and nothing else; the
    regex over the markdown sentence was the same compatibility shim as in
    ``_parse_quote_report_counts`` and was deleted with it. The sidecar also
    carries a ``refusals.by_rule`` breakdown (R1/R3 counts) that this function
    does not surface — doing so would mean changing this function's return type
    or the ``/status`` route's response shape, both out of scope here; a future
    caller that wants the breakdown should read the JSON sidecar directly via
    ``_load_quote_report_json``.
    """
    data = _load_quote_report_json(path)
    if data is None:
        return None
    refusals = data.get("refusals")
    if isinstance(refusals, dict) and isinstance(refusals.get("total"), int):
        return refusals["total"]
    return None


def _build_verify_cmd(request, cfg: ResolvedEditorConfig,
                      target: str = "both") -> list[str] | tuple[None, str]:
    """sd_verify_quotes --vtt {vtt} [--summary …] [--scene-extractions …].

    Deliberately does NOT call ``_selection_args``: verification calls no
    model, so there is no backend to route and no batch to honour. Forwarding
    a model selection here would advertise a token cost this command cannot
    incur — and a batch flag would be actively wrong, since Message Batches is
    an Anthropic API concept and nothing here reaches the API.
    """
    vtt = _vtt_path(cfg)
    if vtt is None or not vtt.exists():
        return None, ("no .vtt resolved — set it on the Editor Config page or "
                      "place a *.vtt in the session dir")

    cmd = [console_script("sd_verify_quotes"), "--vtt", str(vtt)]

    want_summary = target in ("summary", "both")
    want_scenes = target in ("scenes", "both")
    added = False

    if want_summary:
        summary = _session_summary_path(cfg)
        if summary is not None and summary.exists():
            cmd += ["--summary", str(summary)]
            added = True
        elif target == "summary":
            return None, "session-summary.md not found — run Enhance Summary first"

    if want_scenes:
        sx = _scene_extractions_dir(cfg)
        if sx is not None and sx.is_dir() and any(sx.glob("[0-9][0-9]_*.md")):
            cmd += ["--scene-extractions", str(sx)]
            added = True
        elif target == "scenes":
            return None, "no scene extraction files found — run Extract Quotes first"

    if not added:
        return None, ("nothing to verify — neither session-summary.md nor scene "
                      "extractions exist yet")

    report = _quote_report_path(cfg)
    if report is None:
        return None, "could not resolve the narration dir for the report"
    cmd += ["--out", str(report),
            "--threshold", str(cfg.verify.threshold),
            "--min-tokens", str(cfg.verify.min_tokens)]
    if cfg.verify.report_only:
        cmd += ["--report-only"]
    return cmd


def _build_reextract_cmd(request, cfg: ResolvedEditorConfig,
                         force: bool = False) -> list[str] | tuple[None, str]:
    """Stage 2: scene_extract {vtt} --summary {summary} --output-dir {sx_dir}.

    The batch flag (per-scene calls submitted as one Message Batch — 50% off
    + cache hits compound) is forwarded by ``_selection_args`` from the
    resolved selection, same as Stage 1 — no local param anymore (T029).

    Pass `force=True` to forward `--force` so existing per-scene files are
    overwritten (with .prev snapshot) instead of skipped. The UI sets this
    when the user clicks the Re-Extract button — clicking it should mean
    "do the work."
    """
    vtt = _vtt_path(cfg)
    if vtt is None or not vtt.exists():
        return None, "no .vtt file resolved"
    summary = _session_summary_path(cfg)
    if summary is None or not summary.exists():
        return None, "session-summary.md not found — run Stage 1 (Enhance Summary) first"
    sx_dir = _scene_extractions_dir(cfg)
    if sx_dir is None:
        return None, "scene_extractions_dir not configured"
    cmd = [
        console_script("scene_extract"),
        str(vtt),
        "--summary", str(summary),
        "--output-dir", str(sx_dir),
    ]
    cmd += _selection_args(request, cfg)
    # Pass party.md so scene_extract can rewrite Zoom display names to
    # character / GM labels deterministically before the LLM sees the VTT.
    # `party` is the synthesized party.md path (set by the Party Document
    # page), but it only GATES that rewrite — the player→character map itself
    # comes from --party-config, i.e. each character's sheet frontmatter
    # (#265). Hence both flags or neither, which _party_args enforces.
    party_args = _party_args(cfg)
    if isinstance(party_args, tuple):
        return party_args
    cmd += party_args
    # GM player name lives in cfg.roster.gm_player, resolved per-request
    # from the session editor config service — always the current value.
    gm_player = (cfg.roster.gm_player or "").strip()
    if gm_player:
        cmd += ["--gm-player", gm_player]
    if force:
        cmd.append("--force")
    return cmd


def _build_narrate_cmd(request, cfg: ResolvedEditorConfig, scene_num: int) -> list[str] | tuple[None, str]:
    """Stage 3: sd_narrate for a single scene.

    Phase 5 of SessionDocRefactor: session_doc.py is gone. We point at
    sd_narrate and pass plan.md explicitly via --plan (instead of the
    old --plan-file). --context lives on sd_consistency now; sd_narrate
    has --context for the --reflections code path only.

    The batch flag was never forwarded here even after the bespoke checkbox
    existed (it only ever reached enhance/extract) — ``_selection_args``
    below now forwards it whenever the resolved selection's batch is true,
    for the first time (005-ui-batch-selection). ``session_doc`` is a
    `degraded`-capability service in the batch map (data-model.md): the
    handoff-threaded scenes can only submit as sequential one-item batches,
    not one grouped batch, so this is slower than a normal batched run for
    the same 50% discount — the KnobDrawer degradation note states that
    trade-off before the run.
    """
    summary = _session_summary_path(cfg)
    if summary is None or not summary.exists():
        return None, "session-summary.md not found — run Stage 1 first"
    sx_dir = _scene_extractions_dir(cfg)
    if sx_dir is None:
        return None, "scene_extractions_dir not configured"
    nd = _narration_dir(cfg)
    if nd is None:
        return None, "narration_dir not configured"
    nd.mkdir(parents=True, exist_ok=True)

    plan_path = nd / "plan.md"
    if not plan_path.exists():
        return None, "plan.md not found — run Plan & Check first"

    cmd = [
        console_script("sd_narrate"),
        str(summary),
        "--plan", str(plan_path),
        "--scene-extractions", str(sx_dir),
        "--per-scene-output", str(nd),
        "--scene", str(scene_num),
    ]
    cmd += _selection_args(request, cfg)
    party_args = _party_args(cfg)
    if isinstance(party_args, tuple):
        return party_args
    cmd += party_args
    if cfg.paths.voice_dir:
        cmd += ["--voice-dir", cfg.paths.voice_dir]
    examples_args = _examples_args(cfg, plan_path)
    if isinstance(examples_args, tuple):
        return examples_args
    cmd += examples_args
    if cfg.narrate.tokens:
        cmd += ["--narrate-tokens", str(cfg.narrate.tokens)]
    if cfg.narrate.prose_mode:
        cmd += ["--prose-mode"]
    if cfg.narrate.reflections:
        cmd += ["--reflections"]
        # --reflections needs --context to draw on; without it the flag is a no-op
        for ctx in cfg.narrate.context or []:
            if ctx:
                cmd += ["--context", ctx]
    if cfg.paths.genre_file:
        # Pass the path, not the text (#276 fix 2). Resolution already happened
        # at the route edge, so the copyable command stays fully explicit and
        # sd_narrate reads the same file the UI previewed.
        cmd += ["--narration-genre-file", cfg.paths.genre_file]
    return cmd


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/pipeline-status")
def api_pipeline_status(cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """Per-stage readiness based on output-vs-input mtimes.

    Read-only; cheap (just a handful of file stats). The frontend
    renders these as the header status strip.
    """
    summary = _session_summary_path(cfg)
    vtt = _vtt_path(cfg)
    gm = Path(cfg.paths.session_recap).expanduser() if cfg.paths.session_recap else None
    sx = _scene_extractions_dir(cfg)
    nd = _narration_dir(cfg)

    # ① Enhance: inputs are VTT + gm-assist; output is session-summary.md.
    enhance_inputs: list[Path] = []
    if vtt is not None:
        enhance_inputs.append(vtt)
    if gm is not None:
        enhance_inputs.append(gm)
    enhance_status = _stage_status(summary, enhance_inputs)

    # ② Extract: inputs are VTT + session-summary; outputs are NN_*.md
    # in scene_extractions_dir. We pick the OLDEST per-scene mtime so the
    # stage is "stale" if ANY extraction is older than its inputs.
    extract_status: dict
    if sx is None or not sx.is_dir():
        extract_status = {"status": "cold", "ago": None, "mtime": None}
    else:
        ext_files = [
            f for f in sx.glob("[0-9][0-9]_*.md")
            if not f.name.endswith(".scaffold.md")
            and not f.name.endswith(".prev")
            and not f.name.endswith(".reviewed")
        ]
        if not ext_files:
            extract_status = {"status": "cold", "ago": None, "mtime": None}
        else:
            ext_mtimes = [f.stat().st_mtime for f in ext_files]
            oldest_ext = min(ext_files, key=lambda f: f.stat().st_mtime)
            extract_inputs = []
            if vtt is not None:
                extract_inputs.append(vtt)
            if summary is not None:
                extract_inputs.append(summary)
            status = _stage_status(oldest_ext, extract_inputs)
            status["count"] = len(ext_files)
            status["newest_mtime"] = max(ext_mtimes)
            extract_status = status

    # ③ Plan: input is session-summary; output is narration_dir/plan.md.
    plan_output = (nd / "plan.md") if nd else None
    plan_status = _stage_status(plan_output,
                                [summary] if summary else [])

    # ④ Narrate: scene-level. count_done = how many narration files exist;
    # count_total = number of scenes in the plan (or extraction count if
    # no plan yet). Status is the "stalest" of all narrated scenes vs.
    # their per-scene extraction mtimes.
    scenes = _load_scenes(cfg)
    count_total = len(scenes)
    count_done = sum(1 for s in scenes if s.get("has_output"))
    narrate_status: dict = {
        "count_done": count_done,
        "count_total": count_total,
    }
    if count_total == 0 or count_done == 0:
        narrate_status.update({"status": "cold", "ago": None, "mtime": None})
    else:
        narr_files: list[Path] = []
        any_stale = False
        for s in scenes:
            if not s.get("has_output"):
                continue
            narr = _narration_file_for_scene(cfg, s["index"])
            if narr is None or not narr.exists():
                continue
            narr_files.append(narr)
            ext_path = _scene_extraction_file_new(cfg, s["index"], s.get("scene", ""))
            if ext_path and ext_path.exists():
                if ext_path.stat().st_mtime > narr.stat().st_mtime:
                    any_stale = True
        newest = max(narr_files, key=lambda f: f.stat().st_mtime) if narr_files else None
        narrate_status.update({
            "status": "warn" if any_stale else "ok",
            "ago": _ago_string(newest.stat().st_mtime) if newest else None,
            "mtime": newest.stat().st_mtime if newest else None,
        })

    # ⑤ Verify: output is narration/quote_report.md; inputs are the VTT and
    # every artifact it describes. Counts come from the quote_report.json
    # sidecar beside it (#264) so the strip can show what was found, not just
    # when it ran — a report with no sidecar reads as unknown, hence warn.
    verify_report = _quote_report_path(cfg)
    verify_inputs: list[Path] = []
    if vtt is not None:
        verify_inputs.append(vtt)
    if summary is not None:
        verify_inputs.append(summary)
    if sx is not None and sx.is_dir():
        verify_inputs.extend(sx.glob("[0-9][0-9]_*.md"))
    verify_status = _stage_status(verify_report, verify_inputs)
    counts = _parse_quote_report_counts(verify_report)
    verify_status.update(counts)
    refused = _parse_quote_report_refusals(verify_report)
    verify_status["refused"] = refused
    if verify_status["status"] != "cold":
        checked = sum(v for v in counts.values() if isinstance(v, int))
        if counts.get("unverified") is None:
            # An unreadable report is not a passing one.
            verify_status["status"] = "warn"
        elif checked == 0:
            # A run that checked NOTHING is not a clean run. The report says so
            # itself ("Nothing was checked — this is not the same as everything
            # passing"), and the strip has to agree: the wrong input file, or a
            # summary using inline "…" where the parser wants > "…" blockquotes,
            # both land here with all-zero counts and would otherwise read green.
            verify_status["status"] = "warn"
        elif refused is None:
            # Same None-vs-0 rule the verdict counts get. A sidecar written
            # before refusals existed knows nothing about them, and "unknown"
            # must not render as "none refused".
            verify_status["status"] = "warn"
        elif counts["unverified"] > 0 or refused > 0:
            # Stale and has-findings both mean unfinished business here; the
            # counts tell the two apart. A refusal counts: a run with nothing
            # unverified and a dozen refused spans is not a clean run, and
            # showing it green is how the contract gets quietly ignored.
            verify_status["status"] = "warn"

    return {
        "enhance": enhance_status,
        "extract": extract_status,
        "plan": plan_status,
        "narrate": narrate_status,
        "verify": verify_status,
    }


@router.get("/scenes")
def api_scenes(cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    return _load_scenes(cfg)


@router.get("/extraction/{n}")
def api_get_extraction(n: int, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    sys.path.insert(0, str(SCRIPT_DIR))
    from session_doc import estimate_narration_tokens

    scenes = _load_scenes(cfg)
    if n < 1 or n > len(scenes):
        return JSONResponse({"exists": False, "content": ""}, status_code=404)
    s = scenes[n - 1]
    path = _get_extraction_path(cfg, n)
    label = s.get("narrator", "")
    if s.get("scene"):
        label += f" — {s['scene']}"
    if path is None or not path.exists():
        return {"exists": False, "content": "", "scene_label": label}
    content = path.read_text(encoding="utf-8")
    return {
        "exists": True,
        "content": content,
        "scene_label": label,
        "estimated_tokens": estimate_narration_tokens(content),
    }


@router.put("/extraction/{n}")
async def api_save_extraction(n: int, request: Request, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    path = _get_extraction_path(cfg, n)
    if path is None:
        return JSONResponse({"ok": False}, status_code=404)
    data = await request.json()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data["content"], encoding="utf-8")
    return {"ok": True}


@router.get("/extraction/{n}/prev")
def api_get_prev_extraction(n: int, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """Return the snapshotted prior extraction (`NN_<slug>.md.prev`), if any.

    Written by `scene_extract --force` when a re-run produces content
    that differs from what's already on disk. The frontend uses this to
    render a diff against the current extraction so the GM can see what
    changed across re-runs.

    The .prev always pairs with the raw `NN_<slug>.md` Stage-2 output
    (never the user-edited `NN_<slug>.scaffold.md`) — the diff view shows
    what the LLM changed across runs, not what the GM edited locally.
    """
    sx = _scene_extractions_dir(cfg)
    if sx is None:
        return JSONResponse({"exists": False, "content": ""}, status_code=404)
    scenes = _load_scenes(cfg)
    if n < 1 or n > len(scenes):
        return JSONResponse({"exists": False, "content": ""}, status_code=404)
    s = scenes[n - 1]
    slug = _slugify(s.get("scene", "")) or f"scene_{n}"
    raw = sx / f"{n:02d}_{slug}.md"
    prev = raw.with_name(raw.name + ".prev")
    if not prev.exists():
        return {"exists": False, "content": ""}
    return {
        "exists": True,
        "content": prev.read_text(encoding="utf-8"),
        "current": raw.read_text(encoding="utf-8") if raw.exists() else "",
    }


@router.get("/reviewed/{n}")
def api_get_reviewed(n: int, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """True iff the GM has marked scene n's extraction as order-reviewed."""
    marker = _reviewed_marker_path(cfg, n)
    if marker is None:
        return JSONResponse({"reviewed": False}, status_code=404)
    return {"reviewed": marker.exists()}


@router.put("/reviewed/{n}")
async def api_set_reviewed(n: int, request: Request, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """Toggle the order-reviewed marker for scene n.

    Body: ``{ "reviewed": bool }``. When true the sidecar file is
    created (empty); when false it is removed if present. Idempotent.
    """
    marker = _reviewed_marker_path(cfg, n)
    if marker is None:
        return JSONResponse({"ok": False}, status_code=404)
    data = await request.json()
    if data.get("reviewed"):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch(exist_ok=True)
    else:
        if marker.exists():
            marker.unlink()
    return {"ok": True, "reviewed": marker.exists()}


@router.get("/output/{n}")
def api_get_output(n: int, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    path = _narration_file_for_scene(cfg, n)
    if path is None or not path.exists():
        return JSONResponse({"exists": False}, status_code=404)
    return {"exists": True}


@router.get("/enhance")
async def api_enhance(request: Request, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """Stage 1 — stream enhance_summary output.

    Batch (Message Batches API; 50% off list price; replaces token
    streaming with poll-progress lines) is no longer a `?batch=1` query
    param — it comes from the resolved selection like every other service
    now (005-ui-batch-selection, T029; the bespoke checkbox is retired).
    ``_build_enhance_cmd`` already calls ``_selection_args``, which forwards
    the batch flag when applicable, so there is nothing to add here.
    """
    result = _build_enhance_cmd(request, cfg)
    if isinstance(result, tuple):
        _, err = result
        return _sse_error(err)
    cmd = result
    summary = _session_summary_path(cfg)
    outputs = [str(summary)] if summary else []

    def _done(rc: int | None) -> None:
        _record_activity(cfg, stage="enhance", rc=rc,
                         knobs={"batch": _editor_resolved_batch(request, cfg)},
                         outputs=outputs)

    return StreamingResponse(
        stream_subprocess(cmd, cwd=cfg.work_dir,
                          on_complete=_done),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/verify")
async def api_verify(request: Request, target: str = "both",
                     cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """Quote verification — stream sd_verify_quotes over the configured artifacts.

    ``target`` is ``summary`` | ``scenes`` | ``both`` (default). There is no
    ``batch`` parameter: this command calls no model, so offering one would
    imply a cost it cannot incur.
    """
    if target not in ("summary", "scenes", "both"):
        return _sse_error(f"unknown target {target!r} (expected summary|scenes|both)")

    result = _build_verify_cmd(request, cfg, target=target)
    if isinstance(result, tuple):
        _, err = result
        return _sse_error(err)
    cmd = result
    report = _quote_report_path(cfg)

    def _done(rc: int | None) -> None:
        # rc 1 means "ran, found unverified quotes" — a finding, not a failure.
        _record_activity(cfg, stage="verify", rc=rc,
                         knobs={"target": target,
                                "threshold": cfg.verify.threshold,
                                "report_only": cfg.verify.report_only},
                         outputs=[str(report)] if report else [])

    return StreamingResponse(
        stream_subprocess(cmd, cwd=cfg.work_dir, on_complete=_done),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/extract")
async def api_extract(request: Request, force: int = 0, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """Stage 2 (Re-Extract Quotes) — calls scene_extract.

    Batch comes from the resolved selection now, not a `?batch=1` query
    param (005-ui-batch-selection, T029) — see ``_build_reextract_cmd``,
    which already forwards it via ``_selection_args``. `force=1` forwards
    `--force` so existing per-scene files are overwritten (with .prev
    snapshot) — the UI Re-Extract button always sets this.
    """
    result = _build_reextract_cmd(request, cfg, force=bool(force))
    if isinstance(result, tuple):
        _, err = result
        return _sse_error(err)
    cmd = result
    sx = _scene_extractions_dir(cfg)

    def _done(rc: int | None) -> None:
        outputs = [str(sx)] if sx else []
        _record_activity(cfg, stage="extract", rc=rc,
                         knobs={"batch": _editor_resolved_batch(request, cfg), "force": bool(force)},
                         outputs=outputs)

    return StreamingResponse(
        stream_subprocess(cmd, cwd=cfg.work_dir,
                          on_complete=_done),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/narrate/{n}")
async def api_narrate(n: int, request: Request, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    result = _build_narrate_cmd(request, cfg, n)
    if isinstance(result, tuple):
        _, err = result
        return _sse_error(err)
    cmd = result
    knobs = _narrate_knobs_snapshot(cfg)

    def _done(rc: int | None) -> None:
        narr = _narration_file_for_scene(cfg, n)
        if rc == 0:
            _write_knobs_sidecar(narr, knobs)
        outputs = [str(narr)] if narr else []
        _record_activity(cfg, stage="narrate", rc=rc, scene=n,
                         knobs=knobs, outputs=outputs)

    return StreamingResponse(
        stream_subprocess(cmd, cwd=cfg.work_dir,
                          on_complete=_done),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/scrub/{n}")
async def api_scrub(n: int, request: Request, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """Scrub a single scene's narration.

    Resolves the scene file server-side via `_narration_file_for_scene` so
    `scrub_mechanics` needs no scene-aware CLI surface. Explicitly
    refuses already-scrubbed files (the glob in `_narration_file_for_scene`
    matches both `*.md` and `*.scrubbed.md`; today lexicographic order puts
    the un-scrubbed source first but that's a fragile accident).
    """
    path = _narration_file_for_scene(cfg, n)
    if path is None or not path.exists():
        return _sse_error(f"no narration file for scene {n}")
    if path.name.endswith(".scrubbed.md"):
        return _sse_error(
            f"refusing to scrub already-scrubbed file: {path.name}")
    cmd = [console_script("scrub_mechanics"), str(path)]
    cmd += _selection_args(request, cfg)
    if cfg.scrub.tokens:
        cmd += ["--max-tokens", str(cfg.scrub.tokens)]

    def _done(rc: int | None) -> None:
        scrubbed = path.with_name(path.stem + ".scrubbed.md")
        _record_activity(cfg, stage="scrub", rc=rc, scene=n,
                         outputs=[str(scrubbed)])

    return StreamingResponse(
        stream_subprocess(cmd, cwd=cfg.work_dir,
                          env_extra={"CG_CAMPAIGN_DIR": cfg.campaign_dir,
                                     "CG_CONFIG_DIR": cfg.config_dir},
                          on_complete=_done),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/scrub-all")
async def api_scrub_all(request: Request, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """Scrub every session_doc_scene_*.md in narration_dir.

    `scrub_mechanics.collect_targets` already filters out `.scrubbed.md`
    files so re-runs don't recurse into their own output.
    """
    nd = _narration_dir(cfg)
    if nd is None or not nd.is_dir():
        return _sse_error("narration_dir not configured")
    cmd = [console_script("scrub_mechanics"), str(nd)]
    cmd += _selection_args(request, cfg)
    if cfg.scrub.tokens:
        cmd += ["--max-tokens", str(cfg.scrub.tokens)]

    def _done(rc: int | None) -> None:
        _record_activity(cfg, stage="scrub_all", rc=rc, outputs=[str(nd)])

    return StreamingResponse(
        stream_subprocess(cmd, cwd=cfg.work_dir,
                          env_extra={"CG_CAMPAIGN_DIR": cfg.campaign_dir,
                                     "CG_CONFIG_DIR": cfg.config_dir},
                          on_complete=_done),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _build_consistency_cmd(request, cfg: ResolvedEditorConfig) -> list[str] | tuple[None, str]:
    """Phase 5 — sd_consistency for Pass 1.

    Runs only if --context is configured; otherwise the editor skips
    consistency entirely and just runs sd_plan.
    """
    summary = _session_summary_path(cfg)
    if summary is None or not summary.exists():
        return None, "session-summary.md not found — run Stage 1 first"
    nd = _narration_dir(cfg)
    if nd is None:
        return None, "narration_dir not configured"
    nd.mkdir(parents=True, exist_ok=True)

    context = [c for c in (cfg.narrate.context or []) if c]
    if not context:
        return None, "no --context files configured"

    cmd = [
        console_script("sd_consistency"),
        str(summary),
        "--out", str(nd / "consistency_report.md"),
    ]
    cmd += _selection_args(request, cfg)
    # sd_consistency's --context is nargs="+" (now action="extend", so
    # repeated `--context A --context B` accumulates correctly too — see
    # server/routers/ensemble.py's _cmd_multi for that style). Still keep
    # this LAST: nargs="+" greedily swallows subsequent bare tokens
    # regardless of action, so it would otherwise eat --out/--model.
    cmd += ["--context", *context]
    return cmd


def _build_plan_cmd(request, cfg: ResolvedEditorConfig) -> list[str] | tuple[None, str]:
    """Phase 5 — sd_plan for Pass 3.

    --context no longer lives here — consistency is its own explicit
    stage (see _build_consistency_cmd). The /plan endpoint chains
    consistency → plan when context files are configured.
    """
    sx_dir = _scene_extractions_dir(cfg)
    if sx_dir is None:
        return None, "scene_extractions_dir not configured"
    nd = _narration_dir(cfg)
    if nd is None:
        return None, "narration_dir not configured"
    nd.mkdir(parents=True, exist_ok=True)

    characters = cfg.roster.characters
    if not characters:
        return None, "characters not configured (sd_plan needs --characters)"

    cmd = [
        console_script("sd_plan"),
        "--scene-extractions", str(sx_dir),
        "--characters", characters,
        "--out", str(nd / "plan.md"),
    ]
    cmd += _selection_args(request, cfg)
    if cfg.paths.party:
        cmd += ["--party", cfg.paths.party]
    # session-summary.md as the authoritative event log when present
    summary = _session_summary_path(cfg)
    if summary is not None and summary.exists():
        cmd += ["--session-summary", str(summary)]
    return cmd


@router.get("/plan")
async def api_plan(request: Request, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """Run sd_consistency (if --context configured) then sd_plan.

    Both subprocesses stream into the same SSE response; the user sees
    one "Plan & Check" run with consistency output appearing first when
    relevant. Phase 5's chosen consistency-UX option A: auto-chain.
    """
    plan_result = _build_plan_cmd(request, cfg)
    if isinstance(plan_result, tuple):
        _, err = plan_result
        return _sse_error(err)
    # Forward the selected backend (so a subscription or openrouter pick
    # bills that backend instead of falling back to the metered API), but
    # suppress the DGX OpenAI-compat path — see
    # _backend_flags(allow_openai_compat=...).
    backend_flags = _selection_args(request, cfg, allow_openai_compat=False)
    plan_cmd = plan_result + backend_flags
    consistency_result = _build_consistency_cmd(request, cfg)
    # consistency is optional — a tuple here means "skip, no --context"
    consistency_cmd = (
        consistency_result + backend_flags
        if not isinstance(consistency_result, tuple)
        else consistency_result
    )
    nd = _narration_dir(cfg)

    def _done(rc: int | None) -> None:
        outputs: list[str] = []
        if nd is not None:
            for name in ("consistency_report.md", "plan.md"):
                p = nd / name
                if p.exists():
                    outputs.append(str(p))
        _record_activity(cfg, stage="plan", rc=rc, outputs=outputs)

    async def _stream_chained():
        """Stream consistency stdout (if applicable), then plan stdout."""
        from server.subprocess_runner import stream_subprocess as _stream

        if not isinstance(consistency_cmd, tuple):
            # emit_done=False: this is the FIRST of two chained subprocesses.
            # connectSSE closes the EventSource on the first `done` it sees, so
            # letting consistency emit its terminal `done` would disconnect the
            # client and group-kill the plan subprocess before it writes
            # plan.md. Only the final (plan) stream emits `done`.
            async for chunk in _stream(consistency_cmd,
                                        cwd=cfg.work_dir,
                                        emit_done=False):
                yield chunk
        async for chunk in _stream(plan_cmd,
                                    cwd=cfg.work_dir,
                                    on_complete=_done):
            yield chunk

    return StreamingResponse(
        _stream_chained(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Activity log + scene roster (Review screen data sources) ────────────────


def _read_knobs_sidecar(narration_path: Path | None) -> dict | None:
    """Inverse of ``_write_knobs_sidecar``."""
    if narration_path is None:
        return None
    sidecar = narration_path.with_name(narration_path.stem + ".knobs.json")
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return None


def _narration_preview(narration_path: Path | None, *, max_chars: int = 120) -> str:
    """First ~120 chars of narration prose (frontmatter stripped)."""
    if narration_path is None or not narration_path.exists():
        return ""
    try:
        text = narration_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5:]
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


@router.get("/activity")
def api_activity(limit: int = 200, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """Return the most recent N rows from ``activity.jsonl``."""
    path = _activity_jsonl_path(cfg)
    if path is None or not path.exists():
        return {"entries": []}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {"entries": []}
    tail = lines[-max(0, limit):]
    entries: list[dict] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return {"entries": entries}


@router.get("/scene-roster")
def api_scene_roster(cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """Per-scene roster used by the Review-before-Assemble screen.

    For each scene:
      - lifecycle: {extract, reviewed, narrate, scrub}
      - applied_knobs: from the ``*.knobs.json`` sidecar (or None)
      - preview: first ~120 chars of narration prose, frontmatter stripped
      - tokens: estimated narration tokens (extraction-based)
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from session_doc import estimate_narration_tokens  # type: ignore
    except Exception:
        estimate_narration_tokens = None  # type: ignore

    scenes = _load_scenes(cfg)
    roster: list[dict] = []
    for s in scenes:
        idx = s["index"]
        narr_path = _narration_file_for_scene(cfg, idx)
        ext_path = _scene_extraction_file_new(cfg, idx, s.get("scene", ""))
        knobs = _read_knobs_sidecar(narr_path)
        tokens: int | None = None
        if ext_path and ext_path.exists() and estimate_narration_tokens is not None:
            try:
                tokens = estimate_narration_tokens(ext_path.read_text(encoding="utf-8"))
            except Exception:
                tokens = None
        roster.append({
            "index": idx,
            "narrator": s.get("narrator", ""),
            "scene": s.get("scene", ""),
            "tokens": tokens,
            "lifecycle": {
                "extract": s.get("has_extraction", False),
                "reviewed": s.get("reviewed", False),
                "narrate": s.get("has_output", False),
                "scrub": s.get("has_scrubbed", False),
            },
            "applied_knobs": knobs,
            "preview": _narration_preview(narr_path),
        })
    return {"scenes": roster}


@router.get("/raw/{n}")
def api_raw(n: int, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    path = _narration_file_for_scene(cfg, n)
    if path is None or not path.exists():
        return {"exists": False}
    text = path.read_text(encoding="utf-8")
    # Strip YAML frontmatter so the editor preview shows narration prose.
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5:]
    lines = text.splitlines()
    head = lines[:6]
    tail = lines[-6:] if len(lines) > 12 else []
    sep = ["…"] if tail else []
    preview = "\n".join(head + sep + tail)
    return {"exists": True, "preview": preview, "total_lines": len(lines)}


@router.get("/assembled-exists")
def api_assembled_exists(cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    return {"exists": _assembled_output_path(cfg).exists()}


@router.post("/assemble")
def api_assemble(cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    """Stage 4 — shell out to assemble."""
    nd = _narration_dir(cfg)
    if nd is None or not nd.is_dir():
        return JSONResponse({"ok": False, "error": "narration_dir not configured"}, status_code=400)

    matches = sorted(nd.glob("session_doc_scene_*.md"))
    if not matches:
        return JSONResponse({"ok": False, "error": "no narrated scenes found"}, status_code=400)

    out_path = _assembled_output_path(cfg)
    session_stem = Path(cfg.paths.session_recap).stem
    cmd = [
        console_script("assemble"),
        str(nd),
        "--output", str(out_path),
        "--title", session_stem,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cfg.work_dir)
    if proc.returncode != 0:
        return JSONResponse({
            "ok": False,
            "error": (proc.stderr or proc.stdout or "assemble failed").strip(),
        }, status_code=500)

    return {
        "ok": True,
        "filename": out_path.name,
        "scenes_included": len(matches),
        "scenes_missing": [],
    }


@router.post("/open/{file_type}/{n}")
def api_open(file_type: str, n: int, cfg: ResolvedEditorConfig = Depends(get_editor_config)):
    if file_type == "extraction":
        path = _get_extraction_path(cfg, n)
    elif file_type == "output" or file_type == "narration":
        path = _narration_file_for_scene(cfg, n)
    elif file_type == "summary":
        path = _session_summary_path(cfg)
    elif file_type == "assembled":
        path = _assembled_output_path(cfg)
    else:
        return JSONResponse({"ok": False}, status_code=400)

    if path and path.exists():
        _open_in_typora(path)
        return {"ok": True}
    return JSONResponse({"ok": False, "error": "file not found"}, status_code=404)


# ── Resolved-selection preview (feature 003, FR-012) ───────────────────────


@router.get("/selection/resolved")
def get_editor_resolved_selection(request: Request,
                                  service: SessionEditorConfigService = Depends(get_editor_service)):
    """What an editor run would use, and where each half came from."""
    cfg = service.resolved_editor_config()
    sel, _endpoint = _editor_service_selection(cfg)
    return resolve_selection(
        request,
        service=None if sel.is_empty() else sel,
        service_name="session_doc",
        raise_on_incompatible=False,
    ).as_dict()
