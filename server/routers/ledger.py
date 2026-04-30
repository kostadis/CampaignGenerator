"""Quote Ledger API routes — sync, query, assign, auto-assign, generate extraction."""

import json
import re
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter()

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from quote_ledger import QuoteLedger

# Module-level ledger instance
_LEDGER: QuoteLedger | None = None


def _config() -> dict:
    """Return the editor CONFIG — single source of truth for paths."""
    from server.routers.scene_editor import CONFIG
    return CONFIG


def _ledger_dir() -> Path:
    """Where the ledger db lives — prefer new-flow scene_extractions_dir."""
    from server.routers.scene_editor import _scene_extractions_dir
    sx = _scene_extractions_dir()
    if sx is not None:
        return sx
    cfg = _config()
    return Path(cfg["extract_dir"])


def _filename_for_scene_new(idx: int, _narrator: str, scene_name: str) -> str:
    """Stage 2 filename: NN_<slug>.md (no narrator)."""
    slug = re.sub(r"[^a-z0-9]+", "_", (scene_name or "").lower()).strip("_") or f"scene_{idx}"
    return f"{idx:02d}_{slug}.md"


def init_ledger_config(config: dict) -> None:
    """Legacy: called from main.py startup. Config now comes from scene_editor.CONFIG."""
    pass


def _get_ledger() -> QuoteLedger:
    global _LEDGER
    db_path = _ledger_dir() / "quote_ledger.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Re-create if dir changed or the db file was deleted under us
    if _LEDGER is not None and (_LEDGER.db_path != db_path or not db_path.exists()):
        _LEDGER.close()
        _LEDGER = None
    if _LEDGER is None:
        _LEDGER = QuoteLedger(db_path)
    return _LEDGER


def _load_scenes() -> list[dict]:
    """Reuse scene loading from scene_editor."""
    from server.routers.scene_editor import _load_scenes
    return _load_scenes()


def _sse_event(data: str) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _sse_done(returncode: int = 0) -> str:
    return f"event: done\ndata: {json.dumps({'returncode': returncode})}\n\n"


# ── Existing endpoints ────────────────────────────────────────────────────

@router.post("/sync")
def api_ledger_sync():
    from server.routers.scene_editor import _using_new_flow
    ledger = _get_ledger()
    scenes = _load_scenes()
    result = ledger.sync(
        roleplay_dir=Path(_config()["roleplay_extract_dir"]),
        extract_dir=_ledger_dir(),
        scenes=scenes,
        filename_for_scene=_filename_for_scene_new if _using_new_flow() else None,
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


# ── Bulk endpoints ────────────────────────────────────────────────────────

@router.post("/bulk-assign")
async def api_bulk_assign(request: Request):
    global _LEDGER
    if _LEDGER is None:
        return JSONResponse({"ok": False, "error": "ledger not synced"}, status_code=400)
    data = await request.json()
    count = _LEDGER.bulk_assign(data["quote_ids"], data["scene_index"])
    return {"ok": True, "count": count}


@router.post("/bulk-unassign")
async def api_bulk_unassign(request: Request):
    global _LEDGER
    if _LEDGER is None:
        return JSONResponse({"ok": False, "error": "ledger not synced"}, status_code=400)
    data = await request.json()
    count = _LEDGER.bulk_unassign(data["quote_ids"])
    return {"ok": True, "count": count}


@router.post("/exclusive")
async def api_exclusive(request: Request):
    global _LEDGER
    if _LEDGER is None:
        return JSONResponse({"ok": False, "error": "ledger not synced"}, status_code=400)
    data = await request.json()
    count = _LEDGER.make_exclusive(data["quote_ids"], data["scene_index"])
    return {"ok": True, "count": count}


@router.get("/scene/{n}")
def api_scene_quotes(n: int):
    global _LEDGER
    if _LEDGER is None:
        return {"quotes": []}
    return {"quotes": _LEDGER.get_scene_quotes(n)}


@router.get("/all-quotes")
def api_all_quotes():
    global _LEDGER
    if _LEDGER is None:
        return {"quotes": []}
    return {"quotes": _LEDGER.get_all_quotes()}


# ── Auto-assign (deterministic by chunk range) ───────────────────────────

async def _stream_auto_assign() -> AsyncGenerator[str, None]:
    """Assign unassigned quotes to scenes by chunk range (deterministic)."""
    ledger = _get_ledger()
    scenes = _load_scenes()

    all_quotes = ledger.get_all_quotes()
    unassigned = [q for q in all_quotes if q["scene_index"] is None]

    if not unassigned:
        yield _sse_event("No unassigned quotes to assign.\n")
        yield _sse_done(0)
        return

    if not scenes:
        yield _sse_event("No scenes found. Run extraction first.\n")
        yield _sse_done(1)
        return

    yield _sse_event(
        f"Assigning {len(unassigned)} quotes across {len(scenes)} scenes "
        f"by chunk range...\n"
    )
    result = ledger.chunk_assign(scenes)
    yield _sse_event(f"Assigned {result['assigned']} quotes.\n")
    if result["skipped"]:
        yield _sse_event(
            f"{result['skipped']} quotes skipped "
            f"(chunk not in any scene range).\n"
        )
    yield _sse_done(0)


@router.get("/auto-assign")
async def api_auto_assign():
    return StreamingResponse(
        _stream_auto_assign(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Generate extraction scaffold (deterministic) ──────────────────────────────

import re as _re


def _normalize_speaker(raw: str) -> str:
    """Strip parenthetical player names; normalize GM/DM variants.

    Examples:
      "Thorin (Joe)"   → "Thorin"
      "GM (Gabe)"      → "GM"
      "DM"             → "GM"
    """
    name = _re.sub(r'\s*\([^)]+\)', '', raw).strip()
    if name.upper() in ("GM", "DM"):
        name = "GM"
    return name


def _parse_stage2_scaffold(stage2_text: str) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Parse a Stage-2 file into (beats, quotes).

    `beats` is the list of `- ...` bullet lines from the
    `## Scene summary (from gm-assist, verbatim)` section.

    `quotes` is a list of (speaker, context, quote_text) tuples parsed
    from the `## Verbatim moments` section. We look for blocks shaped:

        **Speaker** — *context*
        > "quote text"
        > "continuation"

    Continuations attach to the preceding speaker block. Sub-scene tag
    headers (`**[Scene tag — ...]**`) are dropped. OOC filtering is
    intentionally NOT applied here — the human prunes by hand.
    """
    lines = stage2_text.splitlines()

    # Split into sections by `## ` headers
    sections: dict[str, list[str]] = {}
    current = ""
    for ln in lines:
        if ln.startswith("## "):
            current = ln[3:].strip().lower()
            sections[current] = []
        elif current:
            sections[current].append(ln)

    # Beats: from the gm-assist section
    beat_section = next(
        (v for k, v in sections.items() if k.startswith("scene summary")),
        []
    )
    beats = [ln for ln in beat_section if ln.strip().startswith("-")]

    # Quotes: from verbatim moments
    moments = next(
        (v for k, v in sections.items() if k.startswith("verbatim moments")),
        []
    )
    quotes: list[tuple[str, str, str]] = []
    speaker = ""
    context = ""
    speaker_re = re.compile(r"^\*\*([^*]+)\*\*\s*(?:—|--|-)?\s*(?:\*([^*]*)\*)?\s*$")
    sub_scene_re = re.compile(r"^\*\*\[.*\]\*\*\s*$")
    for ln in moments:
        s = ln.rstrip()
        if not s:
            continue
        if sub_scene_re.match(s):
            speaker = ""
            context = ""
            continue
        m = speaker_re.match(s)
        if m:
            speaker = m.group(1).strip()
            context = (m.group(2) or "").strip()
            continue
        if s.startswith("> ") or s.startswith(">"):
            quote_text = s.lstrip("> ").strip()
            if quote_text.startswith('"') and quote_text.endswith('"'):
                quote_text = quote_text[1:-1]
            if speaker and quote_text:
                quotes.append((speaker, context, quote_text))
    return beats, quotes


def _scaffold_path_for(scene_num: int, scene_name: str) -> Path:
    """Where Scaffold-from-Stage-2 output is written. Sibling of the
    Stage-2 file with a `.scaffold.md` suffix so the rich Stage-2
    content is never overwritten."""
    base = _filename_for_scene_new(scene_num, "", scene_name)
    return _ledger_dir() / base.replace(".md", ".scaffold.md")


def _stage2_path_for(scene_num: int, scene_name: str) -> Path:
    """Stage-2 file path: scene_extractions_dir/NN_<slug>.md."""
    return _ledger_dir() / _filename_for_scene_new(scene_num, "", scene_name)


async def _stream_generate_extraction(scene_num: int) -> AsyncGenerator[str, None]:
    """Build a deterministic quote scaffold for scene N.

    New flow: parse beats + quotes from the Stage-2 file
    (`NN_<slug>.md`) and re-emit them as a clean beat → quotes layout
    in `NN_<slug>.scaffold.md` (sibling). The Stage-2 source is never
    overwritten.

    Legacy flow fallback: when no Stage-2 file is present, build the
    scaffold from the GM recap + quote ledger as before.
    """
    scenes = _load_scenes()

    if scene_num < 1 or scene_num > len(scenes):
        yield _sse_event(f"Invalid scene number: {scene_num}\n")
        yield _sse_done(1)
        return

    scene = scenes[scene_num - 1]
    narrator = scene["narrator"]
    scene_name = scene.get("scene", "")
    focus = scene.get("focus", "")

    # ── New flow: read beats + quotes from the Stage-2 file ────────────────
    stage2_path = _stage2_path_for(scene_num, scene_name)
    if stage2_path.exists():
        beat_lines, parsed_quotes = _parse_stage2_scaffold(
            stage2_path.read_text(encoding="utf-8")
        )
        yield _sse_event(
            f"Scaffolding Scene {scene_num}: {narrator} — {scene_name} "
            f"(from {stage2_path.name}: {len(beat_lines)} beat(s), "
            f"{len(parsed_quotes)} quote(s))...\n\n"
        )

        lines = [
            f"[Scene {scene_num}] {scene_name}",
            f"Narrator: {narrator}",
            f"Focus: {focus}",
            "",
        ]

        if not beat_lines and not parsed_quotes:
            yield _sse_event(
                f"Stage-2 file {stage2_path.name} has no beats or quotes — "
                "nothing to scaffold.\n"
            )
            yield _sse_done(1)
            return

        if beat_lines:
            for beat in beat_lines:
                lines.append(beat)
                lines.append("")
            if parsed_quotes:
                lines += [
                    "<!-- Move each quote below under the beat where it belongs. -->",
                    "<!-- Remove OOC lines (damage calls, mechanic announcements) before narrating. -->",
                    "",
                    "## Quotes to place",
                    "",
                ]
        else:
            lines += [
                "<!-- No beats found in Stage-2 file. Add action beats as lines",
                "     starting with -, then place quotes under them. -->",
                "",
            ]

        for speaker, ctx, text in parsed_quotes:
            speaker_norm = _normalize_speaker(speaker)
            if ctx:
                lines.append(f"<!-- {ctx} -->")
            lines.append(f'{speaker_norm}: "{text}"')
            lines.append("")

        content = "\n".join(lines)
        scaffold_path = _scaffold_path_for(scene_num, scene_name)
        try:
            scaffold_path.parent.mkdir(parents=True, exist_ok=True)
            scaffold_path.write_text(content, encoding="utf-8")
            yield _sse_event(content)
            yield _sse_event(
                f"\n\n[Saved to {scaffold_path.name}]\n"
                f"Source preserved at {stage2_path.name}. "
                "Place quotes under beats, remove OOC, then narrate."
            )
            yield _sse_done(0)
        except Exception as e:
            yield _sse_event(f"\nError: {e}\n")
            yield _sse_done(1)
        return

    # ── Legacy fallback: no Stage-2 file → use ledger + recap ──────────────
    ledger = _get_ledger()
    quotes = ledger.get_scene_quotes(scene_num)

    yield _sse_event(
        f"Scaffolding Scene {scene_num}: {narrator} — {scene_name} "
        f"(legacy path; ledger has {len(quotes)} quote(s))...\n\n"
    )

    beat_lines: list[str] = []
    cfg = _config()
    recap_path: Path | None = None
    summary_path = cfg.get("session_summary")
    if summary_path and Path(summary_path).exists():
        recap_path = Path(summary_path)
    else:
        session_path = cfg.get("session")
        if session_path and Path(session_path).exists():
            recap_path = Path(session_path)

    if recap_path and scene_name:
        from session_doc import extract_scene_text
        recap_text = extract_scene_text(
            recap_path.read_text(encoding="utf-8"), scene_name
        )
        beat_lines = [
            ln for ln in recap_text.splitlines()
            if ln.strip().startswith("-")
        ]

    lines = [
        f"[Scene {scene_num}] {scene_name}",
        f"Narrator: {narrator}",
        f"Focus: {focus}",
        "",
    ]

    if not beat_lines and not quotes:
        yield _sse_event("No recap beats and no assigned quotes for this scene — nothing to scaffold.\n")
        yield _sse_done(1)
        return

    if beat_lines:
        for beat in beat_lines:
            lines.append(beat)
            lines.append("")
        if quotes:
            lines += [
                "<!-- Move each quote below under the beat where it belongs. -->",
                "<!-- Remove OOC lines (damage calls, mechanic announcements) before narrating. -->",
                "",
                "## Quotes to place",
                "",
            ]
    else:
        lines += [
            "<!-- No recap beats found. Add action beats as lines starting with -,",
            "     then place quotes under them. Remove OOC lines before narrating. -->",
            "",
        ]

    for q in quotes:
        raw_speaker = q.get("character") or q.get("speaker") or "Unknown"
        speaker = _normalize_speaker(raw_speaker)
        text = q["quote_text"]
        context = q.get("context", "")
        if context:
            lines.append(f"<!-- {context} -->")
        lines.append(f'{speaker}: "{text}"')
        lines.append("")

    content = "\n".join(lines)

    try:
        from server.routers.scene_editor import _using_new_flow
        if _using_new_flow():
            fname = _filename_for_scene_new(scene_num, narrator, scene_name)
        else:
            from session_doc import extraction_filename
            fname = extraction_filename(scene_num, narrator, scene_name)
        extract_path = _ledger_dir() / fname
        extract_path.parent.mkdir(parents=True, exist_ok=True)
        extract_path.write_text(content, encoding="utf-8")

        yield _sse_event(content)
        yield _sse_event(
            f"\n\n[Saved to {fname}]\n"
            "Place quotes under beats, remove OOC, then narrate."
        )
        yield _sse_done(0)

    except Exception as e:
        yield _sse_event(f"\nError: {e}\n")
        yield _sse_done(1)


@router.get("/generate-extraction/{n}")
async def api_generate_extraction(n: int):
    return StreamingResponse(
        _stream_generate_extraction(n),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
