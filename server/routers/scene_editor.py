"""Scene editor API routes — ported from session_doc_ui.py Flask routes.

Handles scene listing, extraction file I/O, narration streaming, assembly,
and Typora integration.
"""

import json
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from server.subprocess_runner import python_exe, stream_subprocess

router = APIRouter()

# ── Module-level state ──────────────────────────────────────────────────────
# Populated by init_editor_config() at startup

CONFIG: dict = {}
SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent  # CampaignGenerator/


def init_editor_config(config: dict) -> None:
    """Set the editor CONFIG from main.py startup."""
    CONFIG.update(config)


@router.get("/config")
def api_get_config():
    """Return the current editor CONFIG."""
    return dict(CONFIG)


@router.put("/config")
async def api_put_config(request: Request):
    """Update the editor CONFIG at runtime (from the frontend)."""
    data = await request.json()
    CONFIG.update(data)
    return {"ok": True}


# ── Helpers (ported from session_doc_ui.py) ──────────────────────────────────

def _load_scenes() -> list[dict]:
    """Parse plan.md and return scene metadata."""
    if not CONFIG.get("extract_dir"):
        return []
    # Import here to avoid circular imports at module level
    sys.path.insert(0, str(SCRIPT_DIR))
    from session_doc import estimate_narration_tokens, extraction_filename, parse_plan

    plan_path = Path(CONFIG["extract_dir"]) / "plan.md"
    if not plan_path.exists():
        return []
    sections = parse_plan(plan_path.read_text(encoding="utf-8"), total_chunks=99)
    result = []
    for i, s in enumerate(sections, 1):
        fname = extraction_filename(i, s["narrator"], s.get("scene", ""))
        extract_path = Path(CONFIG["extract_dir"]) / fname
        output_path = Path(CONFIG["output_dir"]) / f"scene{i}.md"
        result.append({
            "index": i,
            "narrator": s["narrator"],
            "scene": s.get("scene", ""),
            "focus": s.get("focus", ""),
            "chunk_start": s["chunk_start"],
            "chunk_end": s["chunk_end"],
            "has_extraction": extract_path.exists(),
            "has_output": output_path.exists(),
            "filename": fname,
        })
    return result


def _get_extraction_path(n: int) -> Path | None:
    scenes = _load_scenes()
    if n < 1 or n > len(scenes):
        return None
    return Path(CONFIG["extract_dir"]) / scenes[n - 1]["filename"]


def _get_roleplay_path(n: int) -> Path | None:
    ext_path = _get_extraction_path(n)
    if ext_path is None:
        return None
    return ext_path.with_name(ext_path.stem + "_roleplay.md")


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
    session_stem = Path(CONFIG["session"]).stem
    return Path(CONFIG["output_dir"]) / f"{session_stem}-doc.md"


def _build_extract_cmd() -> list[str]:
    cmd = [
        python_exe(),
        str(SCRIPT_DIR / "session_doc.py"),
        CONFIG["session"],
        "--roleplay-extract-dir", CONFIG["roleplay_extract_dir"],
        "--by-scene",
        "--extract-dir", CONFIG["extract_dir"],
        "--extract-only",
        "--output", "/dev/null",
    ]
    for flag, key in [("--party", "party"), ("--voice-dir", "voice_dir"),
                      ("--summary-extract-dir", "summary_extract_dir"),
                      ("--session-summary", "session_summary"),
                      ("--characters", "characters")]:
        if CONFIG.get(key):
            cmd += [flag, CONFIG[key]]
    for ctx in CONFIG.get("context") or []:
        cmd += ["--context", ctx]
    if CONFIG.get("examples"):
        cmd += ["--examples", CONFIG["examples"]]
    return cmd


def _build_narrate_cmd(scene_num: int) -> list[str]:
    cmd = [
        python_exe(),
        str(SCRIPT_DIR / "session_doc.py"),
        CONFIG["session"],
        "--roleplay-extract-dir", CONFIG["roleplay_extract_dir"],
        "--by-scene",
        "--from-extractions", CONFIG["extract_dir"],
        "--scene", str(scene_num),
        "--output", str(Path(CONFIG["output_dir"]) / f"scene{scene_num}.md"),
    ]
    for flag, key in [("--party", "party"), ("--voice-dir", "voice_dir"),
                      ("--summary-extract-dir", "summary_extract_dir")]:
        if CONFIG.get(key):
            cmd += [flag, CONFIG[key]]
    local_rp = _get_roleplay_path(scene_num)
    if local_rp and local_rp.exists():
        cmd += ["--roleplay-summary", str(local_rp)]
    elif CONFIG.get("roleplay_summary"):
        cmd += ["--roleplay-summary", CONFIG["roleplay_summary"]]
    if CONFIG.get("narrate_tokens"):
        cmd += ["--narrate-tokens", str(CONFIG["narrate_tokens"])]
    return cmd


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/scenes")
def api_scenes():
    return _load_scenes()


@router.get("/extraction/{n}")
def api_get_extraction(n: int):
    sys.path.insert(0, str(SCRIPT_DIR))
    from session_doc import estimate_narration_tokens

    path = _get_extraction_path(n)
    if path is None:
        return JSONResponse({"exists": False, "content": ""}, status_code=404)
    if not path.exists():
        return {"exists": False, "content": "", "scene_label": f"Scene {n}"}
    content = path.read_text(encoding="utf-8")
    scenes = _load_scenes()
    s = scenes[n - 1] if n <= len(scenes) else {}
    label = s.get("narrator", "")
    if s.get("scene"):
        label += f" — {s['scene']}"
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
    path.write_text(data["content"], encoding="utf-8")
    return {"ok": True}


@router.get("/roleplay/{n}")
def api_get_roleplay(n: int):
    local_path = _get_roleplay_path(n)
    if local_path is None:
        return JSONResponse({"exists": False, "content": "", "is_local": False}, status_code=404)
    if local_path.exists():
        return {"exists": True, "content": local_path.read_text(encoding="utf-8"),
                "is_local": True}
    global_path = CONFIG.get("roleplay_summary")
    if global_path and Path(global_path).exists():
        return {"exists": True, "content": Path(global_path).read_text(encoding="utf-8"),
                "is_local": False}
    return {"exists": False, "content": "", "is_local": False}


@router.put("/roleplay/{n}")
async def api_save_roleplay(n: int, request: Request):
    local_path = _get_roleplay_path(n)
    if local_path is None:
        return JSONResponse({"ok": False}, status_code=404)
    data = await request.json()
    local_path.write_text(data["content"], encoding="utf-8")
    return {"ok": True}


@router.get("/output/{n}")
def api_get_output(n: int):
    path = Path(CONFIG["output_dir"]) / f"scene{n}.md"
    if not path.exists():
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


@router.get("/extract")
async def api_extract():
    cmd = _build_extract_cmd()
    return StreamingResponse(
        stream_subprocess(cmd, cwd=CONFIG.get("work_dir")),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/narrate/{n}")
async def api_narrate(n: int):
    cmd = _build_narrate_cmd(n)
    return StreamingResponse(
        stream_subprocess(cmd, cwd=CONFIG.get("work_dir")),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/raw/{n}")
def api_raw(n: int):
    path = Path(CONFIG["output_dir"]) / f"scene{n}.md"
    if not path.exists():
        return {"exists": False}
    lines = path.read_text(encoding="utf-8").splitlines()
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
    scenes = _load_scenes()
    if not scenes:
        return JSONResponse({"ok": False, "error": "no plan loaded"}, status_code=400)

    parts = []
    missing = []
    for s in scenes:
        p = Path(CONFIG["output_dir"]) / f"scene{s['index']}.md"
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
    elif file_type == "roleplay":
        path = _get_roleplay_path(n)
        if path and not path.exists():
            global_path = CONFIG.get("roleplay_summary")
            content = Path(global_path).read_text(encoding="utf-8") if global_path and Path(global_path).exists() else ""
            path.write_text(content, encoding="utf-8")
    elif file_type == "output":
        path = Path(CONFIG["output_dir"]) / f"scene{n}.md"
    elif file_type == "assembled":
        path = _assembled_output_path()
    else:
        return JSONResponse({"ok": False}, status_code=400)

    if path and path.exists():
        _open_in_typora(path)
        return {"ok": True}
    return JSONResponse({"ok": False, "error": "file not found"}, status_code=404)
