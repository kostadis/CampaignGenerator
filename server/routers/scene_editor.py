"""Scene editor API routes.

Drives the four-stage pipeline:

1. Stage 1 — `enhance_summary.py` produces the enriched session-summary.md.
2. Stage 2 — `scene_extract.py` produces per-scene verbatim quote files
   (NN_<slug>.md) under `scene_extractions_dir`.
3. Stage 3 — `session_doc.py --per-scene-output` writes one narration file
   per scene (`session_doc_scene_NN_<slug>.md`) under `narration_dir`.
4. Stage 4 — `assemble.py` concatenates the narrations into the final doc.

`roleplay_extract_dir` (typed `roleplay_dir`) points at the kept
`vtt_roleplay_extractions/` directory produced by `vtt_summary.py` — it
feeds the VTT panel and the quote ledger. It is NOT the deleted
`session-roleplay.md` synthesised-summary chain.
"""

import re
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from server.subprocess_runner import python_exe, stream_subprocess

# ── Module-level state ──────────────────────────────────────────────────────
# CONFIG is a derived view of the unified config service's resolved
# session_doc state, refreshed before every editor request via the
# _refresh_config_from_service router dependency. When the service is
# unavailable (legacy boot path with no config.yaml), CONFIG holds whatever
# init_editor_config() seeded at startup. Other modules (ledger.py) still
# import CONFIG directly; the refresh dependency keeps it in sync.

CONFIG: dict = {}
SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent  # CampaignGenerator/

# Typed-field name → legacy CONFIG-dict-key. Used by _refresh and PUT to keep
# the two namespaces in sync. Anything not listed maps 1:1.
_TYPED_TO_CONFIG_KEY: dict[str, str] = {
    "roleplay_dir": "roleplay_extract_dir",
    "summary_dir": "summary_extract_dir",
    "examples_dir": "examples",
}
_CONFIG_TO_TYPED_KEY: dict[str, str] = {v: k for k, v in _TYPED_TO_CONFIG_KEY.items()}


def _refresh_config_from_service(request: Request) -> None:
    """Sync CONFIG from the unified service before each request.

    The service is the single source of truth; CONFIG is a back-compat
    materialization so the existing helpers (and ledger.py) keep reading
    from a flat dict. No-op when the service isn't wired (legacy boot).
    """
    service = getattr(request.app.state, "config_service", None)
    if service is None:
        return
    resolved = service.resolved()
    sd = resolved["ui"]["session_doc"]
    for typed_key, value in sd.items():
        if value is None:
            continue
        config_key = _TYPED_TO_CONFIG_KEY.get(typed_key, typed_key)
        CONFIG[config_key] = value
    if "work_dir" not in CONFIG:
        CONFIG["work_dir"] = str(service.campaign_dir)


router = APIRouter(dependencies=[Depends(_refresh_config_from_service)])


def init_editor_config(config: dict) -> None:
    """Seed CONFIG from main.py startup.

    When the unified service is wired, ``_refresh_config_from_service``
    overlays the resolved view on top of this seed before every request.
    When it isn't (no config.yaml in the campaign), this remains the only
    path that populates CONFIG — same behaviour as before the refactor.
    """
    CONFIG.update(config)


def _config_to_typed_payload(payload: dict) -> dict:
    """Translate a CONFIG-shaped PUT body into typed ui.session_doc keys."""
    out: dict = {}
    for k, v in payload.items():
        typed_key = _CONFIG_TO_TYPED_KEY.get(k, k)
        out[typed_key] = v
    return out


@router.get("/config")
def api_get_config():
    """Return the current editor CONFIG."""
    return dict(CONFIG)


@router.put("/config")
async def api_put_config(request: Request):
    """Update the editor CONFIG at runtime (from the frontend).

    Writes flow through the unified service when available so the typed
    ``ui.session_doc`` section stays canonical and survives restarts.
    The local CONFIG dict is still updated so module-level helpers see
    the change immediately within this request lifetime.
    """
    data = await request.json()
    CONFIG.update(data)
    service = getattr(request.app.state, "config_service", None)
    if service is not None:
        try:
            service.update_section("session_doc", _config_to_typed_payload(data))
        except Exception as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=400,
            )
    return {"ok": True}


# ── Path helpers ────────────────────────────────────────────────────────────

def _slugify(s: str) -> str:
    """Match campaignlib._slugify so filename lookups round-trip."""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _session_dir() -> Path | None:
    """Directory holding the session's gm-assist + VTT + outputs."""
    if CONFIG.get("session"):
        return Path(CONFIG["session"]).expanduser().parent
    if CONFIG.get("work_dir"):
        return Path(CONFIG["work_dir"]).expanduser()
    return None


def _session_summary_path() -> Path | None:
    """Path to the Stage-1 enriched summary."""
    if CONFIG.get("session_summary"):
        return Path(CONFIG["session_summary"]).expanduser()
    sd = _session_dir()
    if sd:
        return sd / "session-summary.md"
    return None


def _vtt_path() -> Path | None:
    """Path to the raw .vtt — explicit CONFIG['vtt'] or first *.vtt in session dir."""
    if CONFIG.get("vtt"):
        return Path(CONFIG["vtt"]).expanduser()
    sd = _session_dir()
    if sd and sd.is_dir():
        vtts = sorted(sd.glob("*.vtt"))
        if vtts:
            return vtts[0]
    return None


def _scene_extractions_dir() -> Path | None:
    """Stage 2 output dir. Prefer new key; fall back to old extract_dir."""
    if CONFIG.get("scene_extractions_dir"):
        return Path(CONFIG["scene_extractions_dir"]).expanduser()
    if CONFIG.get("extract_dir"):
        return Path(CONFIG["extract_dir"]).expanduser()
    return None


def _narration_dir() -> Path | None:
    """Stage 3 output dir. Prefer new key; fall back to old output_dir."""
    if CONFIG.get("narration_dir"):
        return Path(CONFIG["narration_dir"]).expanduser()
    if CONFIG.get("output_dir"):
        return Path(CONFIG["output_dir"]).expanduser()
    return None


def _using_new_flow() -> bool:
    """True when the new pipeline's plan / per-scene narration is in play."""
    nd = _narration_dir()
    if nd and (nd / "plan.md").exists():
        return True
    sx = _scene_extractions_dir()
    if sx and any(sx.glob("[0-9][0-9]_*.md")):
        # New-flow files are NN_<slug>.md (no narrator). Old-flow files are
        # NN_<narrator>_<slug>.md. Distinguish by frontmatter — new-flow files
        # have `source: gmassist` from scene_extract.py.
        for f in sx.glob("[0-9][0-9]_*.md"):
            head = f.read_text(encoding="utf-8", errors="replace")[:200]
            if "source: gmassist" in head:
                return True
    return False


def _narration_file_for_scene(n: int) -> Path | None:
    """Glob the new-flow per-scene narration file for scene n."""
    nd = _narration_dir()
    if not nd or not nd.is_dir():
        return None
    matches = sorted(nd.glob(f"session_doc_scene_{n:02d}_*.md"))
    return matches[0] if matches else None


def _scene_extraction_file_new(n: int, scene_name: str) -> Path | None:
    """New-flow scene file. Prefer the cleaned scaffold
    (`NN_<slug>.scaffold.md`) when it exists; otherwise return the
    Stage-2 source file (`NN_<slug>.md`). The scaffold is what the
    user edits and what Narrate consumes; the Stage-2 file is the
    expensive LLM source that we never overwrite."""
    sx = _scene_extractions_dir()
    if not sx:
        return None
    slug = _slugify(scene_name) or f"scene_{n}"
    scaffold = sx / f"{n:02d}_{slug}.scaffold.md"
    if scaffold.exists():
        return scaffold
    return sx / f"{n:02d}_{slug}.md"


# ── Helpers (ported from session_doc_ui.py) ──────────────────────────────────

def _load_scenes() -> list[dict]:
    """Return scene metadata.

    New flow: if narration_dir/plan.md exists, parse it (scenes get narrators).
    Otherwise derive a bare scene list from the Stage-2 extraction filenames
    (NN_<slug>.md) and their `scene:` frontmatter — no narrator until first
    Narrate run generates plan.md via Pass 3.

    Old flow: read extract_dir/plan.md and use NN_<narrator>_<slug>.md naming.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    from session_doc import extraction_filename, parse_plan

    new_flow = _using_new_flow()

    # Prefer new-flow plan location, fall back to old.
    plan_path: Path | None = None
    nd = _narration_dir()
    if nd and (nd / "plan.md").exists():
        plan_path = nd / "plan.md"
    elif CONFIG.get("extract_dir"):
        candidate = Path(CONFIG["extract_dir"]) / "plan.md"
        if candidate.exists():
            plan_path = candidate

    # New flow with no plan.md yet — derive scenes from the Stage-2 files.
    if plan_path is None and new_flow:
        return _scenes_from_extractions()

    if plan_path is None or not plan_path.exists():
        return []

    sections = parse_plan(plan_path.read_text(encoding="utf-8"), total_chunks=99)
    result = []
    for i, s in enumerate(sections, 1):
        if new_flow:
            ext = _scene_extraction_file_new(i, s.get("scene", ""))
            ext_path = ext if ext else None
            ext_name = ext.name if ext else ""
            narr_path = _narration_file_for_scene(i)
            has_output = narr_path is not None and narr_path.exists()
        else:
            fname = extraction_filename(i, s["narrator"], s.get("scene", ""))
            ext_dir = CONFIG.get("extract_dir")
            ext_path = Path(ext_dir) / fname if ext_dir else None
            ext_name = fname
            out_dir = CONFIG.get("output_dir")
            has_output = bool(out_dir and (Path(out_dir) / f"scene{i}.md").exists())
        result.append({
            "index": i,
            "narrator": s["narrator"],
            "scene": s.get("scene", ""),
            "focus": s.get("focus", ""),
            "chunk_start": s["chunk_start"],
            "chunk_end": s["chunk_end"],
            "has_extraction": bool(ext_path and ext_path.exists()),
            "has_output": has_output,
            "filename": ext_name,
            "reviewed": _reviewed_for_path(ext_path),
        })
    return result


def _scenes_from_extractions() -> list[dict]:
    """Bare scene list derived from Stage-2 NN_<slug>.md files (no narrator)."""
    sx = _scene_extractions_dir()
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
        narr_path = _narration_file_for_scene(idx)
        result.append({
            "index": idx,
            "narrator": "",  # filled in once plan.md is generated
            "scene": scene_name,
            "focus": "",
            "chunk_start": idx,
            "chunk_end": idx,
            "has_extraction": True,
            "has_output": narr_path is not None and narr_path.exists(),
            "filename": f.name,
            "reviewed": _reviewed_for_path(f),
        })
    return result


def _get_extraction_path(n: int) -> Path | None:
    scenes = _load_scenes()
    if n < 1 or n > len(scenes):
        return None
    s = scenes[n - 1]
    if _using_new_flow():
        return _scene_extraction_file_new(n, s.get("scene", ""))
    return Path(CONFIG["extract_dir"]) / s["filename"] if CONFIG.get("extract_dir") else None


def _reviewed_marker_path(n: int) -> Path | None:
    """Sidecar marker file capturing the GM's "order looks right" approval.

    Lives next to the extraction file as `<extraction>.reviewed`. The
    file's existence is the signal; its contents are an empty string.
    Sidecar (rather than frontmatter mutation) so the human-edited
    extraction never gets rewritten by the toggle.
    """
    ext_path = _get_extraction_path(n)
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


def _assembled_output_path() -> Path:
    """Where assemble.py writes its output."""
    session_stem = Path(CONFIG["session"]).stem
    sd = _session_dir() or Path.cwd()
    return sd / f"{session_stem}-doc.md"


# ── Command builders ────────────────────────────────────────────────────────

def _build_enhance_cmd(batch: bool = False) -> list[str] | tuple[None, str]:
    """Stage 1: enhance_summary.py {vtt} --gmassist {session} --output {summary}.

    Returns the command list, or (None, error_message) on misconfig.
    Pass `batch=True` to forward `--batch` so the script uses the Message
    Batches API (50% off list price; the script's poll-progress lines flow
    over the same SSE stream).
    """
    vtt = _vtt_path()
    if vtt is None or not vtt.exists():
        return None, "no .vtt file resolved (set CONFIG['vtt'] or place a *.vtt in the session dir)"
    if not CONFIG.get("session"):
        return None, "CONFIG['session'] (gm-assist.md) is required"
    summary = _session_summary_path()
    if summary is None:
        return None, "could not resolve session-summary.md output path"
    cmd = [
        python_exe(),
        str(SCRIPT_DIR / "enhance_summary.py"),
        str(vtt),
        "--gmassist", CONFIG["session"],
        "--output", str(summary),
    ]
    if batch:
        cmd.append("--batch")
    return cmd


def _build_reextract_cmd(batch: bool = False,
                         force: bool = False) -> list[str] | tuple[None, str]:
    """Stage 2: scene_extract.py {vtt} --summary {summary} --output-dir {sx_dir}.

    Pass `batch=True` to forward `--batch` so per-scene calls are submitted
    as one Message Batch (50% off + cache hits compound).

    Pass `force=True` to forward `--force` so existing per-scene files are
    overwritten (with .prev snapshot) instead of skipped. The UI sets this
    when the user clicks the Re-Extract button — clicking it should mean
    "do the work."
    """
    vtt = _vtt_path()
    if vtt is None or not vtt.exists():
        return None, "no .vtt file resolved"
    summary = _session_summary_path()
    if summary is None or not summary.exists():
        return None, "session-summary.md not found — run Stage 1 (Enhance Summary) first"
    sx_dir = _scene_extractions_dir()
    if sx_dir is None:
        return None, "scene_extractions_dir not configured"
    cmd = [
        python_exe(),
        str(SCRIPT_DIR / "scene_extract.py"),
        str(vtt),
        "--summary", str(summary),
        "--output-dir", str(sx_dir),
    ]
    if CONFIG.get("dossier_dir"):
        cmd += ["--dossier-dir", CONFIG["dossier_dir"]]
    # Pass party.md so scene_extract.py can rewrite Zoom display names to
    # character / GM labels deterministically before the LLM sees the VTT.
    # `party` is the synthesized party.md path (set by the Party Document
    # page); the player→character map is parsed from its `**<Class>,
    # Player: <Player>**` lines.
    if CONFIG.get("party"):
        cmd += ["--party", CONFIG["party"]]
    # GM player name lives in ui.session_doc.gm_player (typed). The
    # _refresh_config_from_service router dependency syncs CONFIG before
    # this handler runs, so reading from CONFIG always sees the
    # service-resolved value — no separate ui_config.yaml load needed.
    gm_player = (CONFIG.get("gm_player") or "").strip()
    if gm_player:
        cmd += ["--gm-player", gm_player]
    if batch:
        cmd.append("--batch")
    if force:
        cmd.append("--force")
    return cmd


def _build_narrate_cmd(scene_num: int) -> list[str] | tuple[None, str]:
    """Stage 3: session_doc.py --scene-extractions ... --per-scene-output ... --scene N."""
    summary = _session_summary_path()
    if summary is None or not summary.exists():
        return None, "session-summary.md not found — run Stage 1 first"
    sx_dir = _scene_extractions_dir()
    if sx_dir is None:
        return None, "scene_extractions_dir not configured"
    nd = _narration_dir()
    if nd is None:
        return None, "narration_dir not configured"
    nd.mkdir(parents=True, exist_ok=True)

    cmd = [
        python_exe(),
        str(SCRIPT_DIR / "session_doc.py"),
        str(summary),
        "--scene-extractions", str(sx_dir),
        "--per-scene-output", str(nd),
        "--scene", str(scene_num),
    ]
    for flag, key in [("--party", "party"), ("--voice-dir", "voice_dir"),
                      ("--characters", "characters"),
                      ("--examples", "examples_dir")]:
        if CONFIG.get(key):
            cmd += [flag, CONFIG[key]]
    if CONFIG.get("narrate_tokens"):
        cmd += ["--narrate-tokens", str(CONFIG["narrate_tokens"])]
    if CONFIG.get("prose_mode"):
        cmd += ["--prose-mode"]
    if CONFIG.get("reflections"):
        cmd += ["--reflections"]
    if CONFIG.get("narration_genre"):
        cmd += ["--narration-genre", CONFIG["narration_genre"]]
    for ctx in CONFIG.get("context") or []:
        if ctx:
            cmd += ["--context", ctx]
    if CONFIG.get("use_enhanced_sections", True):
        enhanced_path = nd / "enhanced_sections.md"
        if enhanced_path.exists():
            cmd += ["--enhanced-sections", str(enhanced_path)]
    plan_path = nd / "plan.md"
    if plan_path.exists():
        cmd += ["--plan-file", str(plan_path)]
    return cmd


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/scenes")
def api_scenes():
    return _load_scenes()


@router.get("/extraction/{n}")
def api_get_extraction(n: int):
    sys.path.insert(0, str(SCRIPT_DIR))
    from session_doc import estimate_narration_tokens

    scenes = _load_scenes()
    if n < 1 or n > len(scenes):
        return JSONResponse({"exists": False, "content": ""}, status_code=404)
    s = scenes[n - 1]
    path = _get_extraction_path(n)
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
async def api_save_extraction(n: int, request: Request):
    path = _get_extraction_path(n)
    if path is None:
        return JSONResponse({"ok": False}, status_code=404)
    data = await request.json()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data["content"], encoding="utf-8")
    return {"ok": True}


@router.get("/extraction/{n}/prev")
def api_get_prev_extraction(n: int):
    """Return the snapshotted prior extraction (`NN_<slug>.md.prev`), if any.

    Written by `scene_extract.py --force` when a re-run produces content
    that differs from what's already on disk. The frontend uses this to
    render a diff against the current extraction so the GM can see what
    changed across re-runs.

    The .prev always pairs with the raw `NN_<slug>.md` Stage-2 output
    (never the user-edited `NN_<slug>.scaffold.md`) — the diff view shows
    what the LLM changed across runs, not what the GM edited locally.
    """
    sx = _scene_extractions_dir()
    if sx is None:
        return JSONResponse({"exists": False, "content": ""}, status_code=404)
    scenes = _load_scenes()
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
def api_get_reviewed(n: int):
    """True iff the GM has marked scene n's extraction as order-reviewed."""
    marker = _reviewed_marker_path(n)
    if marker is None:
        return JSONResponse({"reviewed": False}, status_code=404)
    return {"reviewed": marker.exists()}


@router.put("/reviewed/{n}")
async def api_set_reviewed(n: int, request: Request):
    """Toggle the order-reviewed marker for scene n.

    Body: ``{ "reviewed": bool }``. When true the sidecar file is
    created (empty); when false it is removed if present. Idempotent.
    """
    marker = _reviewed_marker_path(n)
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
def api_get_output(n: int):
    if _using_new_flow():
        path = _narration_file_for_scene(n)
    else:
        out_dir = CONFIG.get("output_dir")
        path = (Path(out_dir) / f"scene{n}.md") if out_dir else None
    if path is None or not path.exists():
        return JSONResponse({"exists": False}, status_code=404)
    return {"exists": True}


@router.get("/enhanced-sections")
def api_get_enhanced_sections():
    nd = _narration_dir()
    if nd:
        path = nd / "enhanced_sections.md"
        if path.exists():
            return {"exists": True, "content": path.read_text(encoding="utf-8")}
    if CONFIG.get("extract_dir"):
        path = Path(CONFIG["extract_dir"]) / "enhanced_sections.md"
        if path.exists():
            return {"exists": True, "content": path.read_text(encoding="utf-8")}
    return {"exists": False, "content": ""}


@router.get("/vtt")
def api_vtt():
    if not CONFIG.get("roleplay_extract_dir"):
        return {"chunks": []}
    vtt_dir = Path(CONFIG["roleplay_extract_dir"])
    chunks = [
        {"name": f.stem, "content": f.read_text(encoding="utf-8")}
        for f in sorted(vtt_dir.glob("extract_*.md"))
    ]
    return {"chunks": chunks}


@router.get("/enhance")
async def api_enhance(batch: int = 0):
    """Stage 1 — stream enhance_summary.py output.

    `batch=1` forwards `--batch` to the script (Message Batches API; 50%
    off list price; replaces token streaming with poll-progress lines).
    """
    result = _build_enhance_cmd(batch=bool(batch))
    if isinstance(result, tuple):
        _, err = result
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    return StreamingResponse(
        stream_subprocess(result, cwd=CONFIG.get("work_dir")),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/extract")
async def api_extract(batch: int = 0, force: int = 0):
    """Stage 2 (Re-Extract Quotes) — calls scene_extract.py.

    `batch=1` forwards `--batch` to the script. `force=1` forwards `--force`
    so existing per-scene files are overwritten (with .prev snapshot) — the
    UI Re-Extract button always sets this. Falls back to the old
    Pass-1-to-4 command (no batch / no force support) when the workspace
    is on the legacy flow.
    """
    result = _build_reextract_cmd(batch=bool(batch), force=bool(force))
    if isinstance(result, tuple):
        _, err = result
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    return StreamingResponse(
        stream_subprocess(result, cwd=CONFIG.get("work_dir")),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/narrate/{n}")
async def api_narrate(n: int):
    result = _build_narrate_cmd(n)
    if isinstance(result, tuple):
        _, err = result
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    return StreamingResponse(
        stream_subprocess(result, cwd=CONFIG.get("work_dir")),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _build_plan_cmd() -> list[str] | tuple[None, str]:
    """Run session_doc.py --plan-only against session-summary.md.

    Produces narration_dir/plan.md + enhanced_sections.md +
    consistency_report.md. After this runs once per session,
    per-scene Narrate reuses those cached artifacts and skips
    Pass 1 / Pass 2 / Pass 3.
    """
    if not _using_new_flow():
        return None, "Plan & Check is only available in the new flow"
    summary = _session_summary_path()
    if summary is None or not summary.exists():
        return None, "session-summary.md not found — run Stage 1 first"
    sx_dir = _scene_extractions_dir()
    if sx_dir is None:
        return None, "scene_extractions_dir not configured"
    nd = _narration_dir()
    if nd is None:
        return None, "narration_dir not configured"
    nd.mkdir(parents=True, exist_ok=True)

    cmd = [
        python_exe(),
        str(SCRIPT_DIR / "session_doc.py"),
        str(summary),
        "--scene-extractions", str(sx_dir),
        "--per-scene-output", str(nd),
        "--plan-only",
        "--no-plan-review",
    ]
    for flag, key in [("--party", "party"), ("--voice-dir", "voice_dir"),
                      ("--characters", "characters")]:
        if CONFIG.get(key):
            cmd += [flag, CONFIG[key]]
    for ctx in CONFIG.get("context") or []:
        if ctx:
            cmd += ["--context", ctx]
    return cmd


@router.get("/plan")
async def api_plan():
    result = _build_plan_cmd()
    if isinstance(result, tuple):
        _, err = result
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    return StreamingResponse(
        stream_subprocess(result, cwd=CONFIG.get("work_dir")),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/raw/{n}")
def api_raw(n: int):
    if _using_new_flow():
        path = _narration_file_for_scene(n)
    else:
        out_dir = CONFIG.get("output_dir")
        path = (Path(out_dir) / f"scene{n}.md") if out_dir else None
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
def api_assembled_exists():
    return {"exists": _assembled_output_path().exists()}


@router.post("/assemble")
def api_assemble():
    """Stage 4 — shell out to assemble.py."""
    nd = _narration_dir()
    if nd is None or not nd.is_dir():
        # Fall back to the old in-process concat for legacy flows.
        return _api_assemble_old()

    matches = sorted(nd.glob("session_doc_scene_*.md"))
    if not matches:
        # Old-flow output_dir holds scene{N}.md instead — fall back.
        return _api_assemble_old()

    out_path = _assembled_output_path()
    session_stem = Path(CONFIG["session"]).stem
    cmd = [
        python_exe(),
        str(SCRIPT_DIR / "assemble.py"),
        str(nd),
        "--output", str(out_path),
        "--title", session_stem,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=CONFIG.get("work_dir"))
    if proc.returncode != 0:
        return JSONResponse({
            "ok": False,
            "error": (proc.stderr or proc.stdout or "assemble.py failed").strip(),
        }, status_code=500)

    return {
        "ok": True,
        "filename": out_path.name,
        "scenes_included": len(matches),
        "scenes_missing": [],
    }


def _api_assemble_old():
    """Legacy in-process concat of scene{N}.md files."""
    scenes = _load_scenes()
    if not scenes:
        return JSONResponse({"ok": False, "error": "no plan loaded"}, status_code=400)

    out_dir = CONFIG.get("output_dir")
    if not out_dir:
        return JSONResponse({"ok": False, "error": "output_dir not configured"}, status_code=400)

    parts = []
    missing = []
    for s in scenes:
        p = Path(out_dir) / f"scene{s['index']}.md"
        if p.exists():
            parts.append(p.read_text(encoding="utf-8").strip())
        else:
            missing.append(s["index"])

    if not parts:
        return JSONResponse({"ok": False, "error": "no narrated scenes found"}, status_code=400)

    session_name = Path(CONFIG["session"]).stem
    title_line = f"# {session_name}"

    def strip_header(text: str) -> str:
        lines = text.split("\n")
        while lines and lines[0].strip() in ("", "---", title_line):
            lines.pop(0)
        while lines and lines[-1].strip() in ("", "---"):
            lines.pop()
        return "\n".join(lines)

    stripped = [strip_header(p) for p in parts]
    content = f"{title_line}\n\n---\n\n" + "\n\n---\n\n".join(stripped) + "\n"

    out_path = _assembled_output_path()
    out_path.write_text(content, encoding="utf-8")

    print(f"  Assembled {len(parts)} scenes → {out_path}")
    if missing:
        print(f"  Missing scenes (not yet narrated): {missing}")

    return {
        "ok": True,
        "filename": out_path.name,
        "scenes_included": len(parts),
        "scenes_missing": missing,
    }


@router.post("/open/{file_type}/{n}")
def api_open(file_type: str, n: int):
    if file_type == "extraction":
        path = _get_extraction_path(n)
    elif file_type == "output" or file_type == "narration":
        if _using_new_flow():
            path = _narration_file_for_scene(n)
        else:
            out_dir = CONFIG.get("output_dir")
            path = (Path(out_dir) / f"scene{n}.md") if out_dir else None
    elif file_type == "summary":
        path = _session_summary_path()
    elif file_type == "assembled":
        path = _assembled_output_path()
    else:
        return JSONResponse({"ok": False}, status_code=400)

    if path and path.exists():
        _open_in_typora(path)
        return {"ok": True}
    return JSONResponse({"ok": False, "error": "file not found"}, status_code=404)
