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
feeds the VTT panel. It is NOT the deleted
`session-roleplay.md` synthesised-summary chain.
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from server.subprocess_runner import python_exe, stream_subprocess

# ── Module-level state ──────────────────────────────────────────────────────
# CONFIG is a derived view of the unified config service's resolved
# session_doc state, refreshed before every editor request via the
# _refresh_config_from_service router dependency.

CONFIG: dict = {}
SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent  # CampaignGenerator/

# Typed-field name → legacy CONFIG-dict-key. Used by _refresh and PUT to keep
# the two namespaces in sync.
_TYPED_TO_CONFIG_KEY: dict[str, str] = {
    "roleplay_dir": "roleplay_extract_dir",
    "summary_dir": "summary_extract_dir",
    "examples_dir": "examples",
}
_CONFIG_TO_TYPED_KEY: dict[str, str] = {v: k for k, v in _TYPED_TO_CONFIG_KEY.items()}


def _refresh_config_from_service(request: Request) -> None:
    """Sync CONFIG from the unified service before each request.

    The service is the single source of truth; CONFIG is a back-compat
    materialization so the existing helpers (and legacy scripts) keep reading
    from a flat dict.
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
    """Seed CONFIG from main.py startup."""
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
    """Stage 2 output dir."""
    if CONFIG.get("scene_extractions_dir"):
        return Path(CONFIG["scene_extractions_dir"]).expanduser()
    return None


def _narration_dir() -> Path | None:
    """Stage 3 output dir."""
    if CONFIG.get("narration_dir"):
        return Path(CONFIG["narration_dir"]).expanduser()
    return None


def _narration_file_for_scene(n: int) -> Path | None:
    """Glob the new-flow per-scene narration file for scene n."""
    nd = _narration_dir()
    if not nd or not nd.is_dir():
        return None
    matches = sorted(
        f for f in nd.glob(f"session_doc_scene_{n:02d}_*.md")
        if not f.name.endswith(".scrubbed.md")
    )
    return matches[0] if matches else None


def _scrubbed_for_scene(n: int) -> bool:
    """True iff a `.scrubbed.md` sibling exists for scene n's narration file."""
    narr = _narration_file_for_scene(n)
    if narr is None:
        return False
    return narr.with_name(narr.stem + ".scrubbed.md").exists()


def _activity_jsonl_path() -> Path | None:
    """``<session_dir>/.cg/activity.jsonl`` — created on first write."""
    sd = _session_dir()
    if sd is None:
        return None
    return sd / ".cg" / "activity.jsonl"


def _narrate_knobs_snapshot() -> dict:
    """Capture the Stage-④ knobs at the moment a narration is produced.

    Stashed alongside each narration file so the Review screen can show
    "which flags were applied to this scene" without consulting the
    activity log.
    """
    return {
        "narrate_tokens": CONFIG.get("narrate_tokens"),
        "prose_mode": bool(CONFIG.get("prose_mode")),
        "reflections": bool(CONFIG.get("reflections")),
        "narration_genre": CONFIG.get("narration_genre"),
        "backend": CONFIG.get("backend") or "anthropic",
    }


def _record_activity(*, stage: str, rc: int | None,
                     scene: int | None = None,
                     knobs: dict | None = None,
                     outputs: list[str] | None = None) -> None:
    """Append one JSON line to ``<session_dir>/.cg/activity.jsonl``.

    Best-effort: any failure is swallowed so a broken sidecar never
    stops the SSE stream from completing.
    """
    try:
        path = _activity_jsonl_path()
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
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    from session_doc import parse_plan

    nd = _narration_dir()
    plan_path: Path | None = None
    if nd and (nd / "plan.md").exists():
        plan_path = nd / "plan.md"

    if plan_path is None:
        return _scenes_from_extractions()

    sections = parse_plan(plan_path.read_text(encoding="utf-8"), total_chunks=99)
    result = []
    for i, s in enumerate(sections, 1):
        ext = _scene_extraction_file_new(i, s.get("scene", ""))
        ext_path = ext if ext else None
        ext_name = ext.name if ext else ""
        narr_path = _narration_file_for_scene(i)
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
            "has_scrubbed": _scrubbed_for_scene(i),
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
            "has_scrubbed": _scrubbed_for_scene(idx),
            "filename": f.name,
            "reviewed": _reviewed_for_path(f),
        })
    return result


def _get_extraction_path(n: int) -> Path | None:
    scenes = _load_scenes()
    if n < 1 or n > len(scenes):
        return None
    s = scenes[n - 1]
    return _scene_extraction_file_new(n, s.get("scene", ""))


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
    """Stage 3: sd_narrate.py for a single scene.

    Phase 5 of SessionDocRefactor: session_doc.py is gone. We point at
    sd_narrate.py and pass plan.md explicitly via --plan (instead of the
    old --plan-file). --context lives on sd_consistency now; sd_narrate
    has --context for the --reflections code path only.
    """
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

    plan_path = nd / "plan.md"
    if not plan_path.exists():
        return None, "plan.md not found — run Plan & Check first"

    cmd = [
        python_exe(),
        str(SCRIPT_DIR / "sd_narrate.py"),
        str(summary),
        "--plan", str(plan_path),
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
        # --reflections needs --context to draw on; without it the flag is a no-op
        for ctx in CONFIG.get("context") or []:
            if ctx:
                cmd += ["--context", ctx]
    if CONFIG.get("narration_genre"):
        cmd += ["--narration-genre", CONFIG["narration_genre"]]
    return cmd


def _llm_env() -> dict[str, str]:
    """Translate the typed backend choice into env vars campaignlib.make_client honors.

    Returned dict is merged into the subprocess env by stream_subprocess.
    Empty dict (backend == "anthropic") means "no overrides — Anthropic API
    via the default code path". Only narrate + scrub routes call this; the
    Stage 1/2/Plan routes pass nothing because their LLM paths use tool-use
    and the OpenAI-compat adapter does not support tools.
    """
    if CONFIG.get("backend") != "dgx":
        return {}
    return {
        "DGX_ENDPOINT": CONFIG.get("dgx_endpoint") or "http://localhost:8000",
        "DGX_MODEL": CONFIG.get("dgx_model") or "Qwen/Qwen2.5-14B-Instruct-AWQ",
    }


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/pipeline-status")
def api_pipeline_status():
    """Per-stage readiness based on output-vs-input mtimes.

    Read-only; cheap (just a handful of file stats). The frontend
    renders these as the header status strip.
    """
    summary = _session_summary_path()
    vtt = _vtt_path()
    gm = Path(CONFIG["session"]).expanduser() if CONFIG.get("session") else None
    sx = _scene_extractions_dir()
    nd = _narration_dir()

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
    scenes = _load_scenes()
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
            narr = _narration_file_for_scene(s["index"])
            if narr is None or not narr.exists():
                continue
            narr_files.append(narr)
            ext_path = _scene_extraction_file_new(s["index"], s.get("scene", ""))
            if ext_path and ext_path.exists():
                if ext_path.stat().st_mtime > narr.stat().st_mtime:
                    any_stale = True
        newest = max(narr_files, key=lambda f: f.stat().st_mtime) if narr_files else None
        narrate_status.update({
            "status": "warn" if any_stale else "ok",
            "ago": _ago_string(newest.stat().st_mtime) if newest else None,
            "mtime": newest.stat().st_mtime if newest else None,
        })

    return {
        "enhance": enhance_status,
        "extract": extract_status,
        "plan": plan_status,
        "narrate": narrate_status,
    }


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
    path = _narration_file_for_scene(n)
    if path is None or not path.exists():
        return JSONResponse({"exists": False}, status_code=404)
    return {"exists": True}


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
    summary = _session_summary_path()
    outputs = [str(summary)] if summary else []

    def _done(rc: int | None) -> None:
        _record_activity(stage="enhance", rc=rc,
                         knobs={"batch": bool(batch)},
                         outputs=outputs)

    return StreamingResponse(
        stream_subprocess(result, cwd=CONFIG.get("work_dir"),
                          on_complete=_done),
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
    sx = _scene_extractions_dir()

    def _done(rc: int | None) -> None:
        outputs = [str(sx)] if sx else []
        _record_activity(stage="extract", rc=rc,
                         knobs={"batch": bool(batch), "force": bool(force)},
                         outputs=outputs)

    return StreamingResponse(
        stream_subprocess(result, cwd=CONFIG.get("work_dir"),
                          on_complete=_done),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/narrate/{n}")
async def api_narrate(n: int):
    result = _build_narrate_cmd(n)
    if isinstance(result, tuple):
        _, err = result
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    knobs = _narrate_knobs_snapshot()

    def _done(rc: int | None) -> None:
        narr = _narration_file_for_scene(n)
        if rc == 0:
            _write_knobs_sidecar(narr, knobs)
        outputs = [str(narr)] if narr else []
        _record_activity(stage="narrate", rc=rc, scene=n,
                         knobs=knobs, outputs=outputs)

    return StreamingResponse(
        stream_subprocess(result, cwd=CONFIG.get("work_dir"),
                          env_extra=_llm_env(), on_complete=_done),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/scrub/{n}")
async def api_scrub(n: int):
    """Scrub a single scene's narration.

    Resolves the scene file server-side via `_narration_file_for_scene` so
    `scrub_mechanics.py` needs no scene-aware CLI surface. Explicitly
    refuses already-scrubbed files (the glob in `_narration_file_for_scene`
    matches both `*.md` and `*.scrubbed.md`; today lexicographic order puts
    the un-scrubbed source first but that's a fragile accident).
    """
    path = _narration_file_for_scene(n)
    if path is None or not path.exists():
        return JSONResponse(
            {"ok": False, "error": f"no narration file for scene {n}"},
            status_code=400,
        )
    if path.name.endswith(".scrubbed.md"):
        return JSONResponse(
            {"ok": False,
             "error": f"refusing to scrub already-scrubbed file: {path.name}"},
            status_code=400,
        )
    cmd = [python_exe(), str(SCRIPT_DIR / "scrub_mechanics.py"), str(path)]
    if CONFIG.get("scrub_tokens"):
        cmd += ["--max-tokens", str(CONFIG["scrub_tokens"])]

    def _done(rc: int | None) -> None:
        scrubbed = path.with_name(path.stem + ".scrubbed.md")
        _record_activity(stage="scrub", rc=rc, scene=n,
                         outputs=[str(scrubbed)])

    return StreamingResponse(
        stream_subprocess(cmd, cwd=CONFIG.get("work_dir"),
                          env_extra=_llm_env(), on_complete=_done),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/scrub-all")
async def api_scrub_all():
    """Scrub every session_doc_scene_*.md in narration_dir.

    `scrub_mechanics.collect_targets` already filters out `.scrubbed.md`
    files so re-runs don't recurse into their own output.
    """
    nd = _narration_dir()
    if nd is None or not nd.is_dir():
        return JSONResponse(
            {"ok": False, "error": "narration_dir not configured"},
            status_code=400,
        )
    cmd = [python_exe(), str(SCRIPT_DIR / "scrub_mechanics.py"), str(nd)]
    if CONFIG.get("scrub_tokens"):
        cmd += ["--max-tokens", str(CONFIG["scrub_tokens"])]

    def _done(rc: int | None) -> None:
        _record_activity(stage="scrub_all", rc=rc, outputs=[str(nd)])

    return StreamingResponse(
        stream_subprocess(cmd, cwd=CONFIG.get("work_dir"),
                          env_extra=_llm_env(), on_complete=_done),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _build_consistency_cmd() -> list[str] | tuple[None, str]:
    """Phase 5 — sd_consistency.py for Pass 1.

    Runs only if --context is configured; otherwise the editor skips
    consistency entirely and just runs sd_plan.
    """
    summary = _session_summary_path()
    if summary is None or not summary.exists():
        return None, "session-summary.md not found — run Stage 1 first"
    nd = _narration_dir()
    if nd is None:
        return None, "narration_dir not configured"
    nd.mkdir(parents=True, exist_ok=True)

    context = [c for c in (CONFIG.get("context") or []) if c]
    if not context:
        return None, "no --context files configured"

    cmd = [
        python_exe(),
        str(SCRIPT_DIR / "sd_consistency.py"),
        str(summary),
        "--out", str(nd / "consistency_report.md"),
    ]
    for ctx in context:
        cmd += ["--context", ctx]
    return cmd


def _build_plan_cmd() -> list[str] | tuple[None, str]:
    """Phase 5 — sd_plan.py for Pass 3.

    --context no longer lives here — consistency is its own explicit
    stage (see _build_consistency_cmd). The /plan endpoint chains
    consistency → plan when context files are configured.
    """
    sx_dir = _scene_extractions_dir()
    if sx_dir is None:
        return None, "scene_extractions_dir not configured"
    nd = _narration_dir()
    if nd is None:
        return None, "narration_dir not configured"
    nd.mkdir(parents=True, exist_ok=True)

    characters = CONFIG.get("characters")
    if not characters:
        return None, "characters not configured (sd_plan needs --characters)"

    cmd = [
        python_exe(),
        str(SCRIPT_DIR / "sd_plan.py"),
        "--scene-extractions", str(sx_dir),
        "--characters", characters,
        "--out", str(nd / "plan.md"),
    ]
    if CONFIG.get("party"):
        cmd += ["--party", CONFIG["party"]]
    # session-summary.md as the authoritative event log when present
    summary = _session_summary_path()
    if summary is not None and summary.exists():
        cmd += ["--session-summary", str(summary)]
    return cmd


@router.get("/plan")
async def api_plan():
    """Run sd_consistency.py (if --context configured) then sd_plan.py.

    Both subprocesses stream into the same SSE response; the user sees
    one "Plan & Check" run with consistency output appearing first when
    relevant. Phase 5's chosen consistency-UX option A: auto-chain.
    """
    plan_result = _build_plan_cmd()
    if isinstance(plan_result, tuple):
        _, err = plan_result
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    consistency_result = _build_consistency_cmd()
    # consistency is optional — a tuple here means "skip, no --context"
    nd = _narration_dir()

    def _done(rc: int | None) -> None:
        outputs: list[str] = []
        if nd is not None:
            for name in ("consistency_report.md", "plan.md"):
                p = nd / name
                if p.exists():
                    outputs.append(str(p))
        _record_activity(stage="plan", rc=rc, outputs=outputs)

    async def _stream_chained():
        """Stream consistency stdout (if applicable), then plan stdout."""
        from server.subprocess_runner import stream_subprocess as _stream

        if not isinstance(consistency_result, tuple):
            async for chunk in _stream(consistency_result,
                                        cwd=CONFIG.get("work_dir")):
                yield chunk
        async for chunk in _stream(plan_result,
                                    cwd=CONFIG.get("work_dir"),
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
def api_activity(limit: int = 200):
    """Return the most recent N rows from ``activity.jsonl``."""
    path = _activity_jsonl_path()
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
def api_scene_roster():
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

    scenes = _load_scenes()
    roster: list[dict] = []
    for s in scenes:
        idx = s["index"]
        narr_path = _narration_file_for_scene(idx)
        ext_path = _scene_extraction_file_new(idx, s.get("scene", ""))
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
def api_raw(n: int):
    path = _narration_file_for_scene(n)
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
        return JSONResponse({"ok": False, "error": "narration_dir not configured"}, status_code=400)

    matches = sorted(nd.glob("session_doc_scene_*.md"))
    if not matches:
        return JSONResponse({"ok": False, "error": "no narrated scenes found"}, status_code=400)

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


@router.post("/open/{file_type}/{n}")
def api_open(file_type: str, n: int):
    if file_type == "extraction":
        path = _get_extraction_path(n)
    elif file_type == "output" or file_type == "narration":
        path = _narration_file_for_scene(n)
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
