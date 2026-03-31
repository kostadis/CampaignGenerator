"""Quote Ledger API routes — sync, query, assign, auto-assign, generate extraction."""

import json
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


def init_ledger_config(config: dict) -> None:
    """Legacy: called from main.py startup. Config now comes from scene_editor.CONFIG."""
    pass


def _get_ledger() -> QuoteLedger:
    global _LEDGER
    cfg = _config()
    db_path = Path(cfg["extract_dir"]) / "quote_ledger.db"
    # Re-create if extract_dir changed (different session)
    if _LEDGER is not None and _LEDGER.db_path != db_path:
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
    ledger = _get_ledger()
    scenes = _load_scenes()
    result = ledger.sync(
        roleplay_dir=Path(_config()["roleplay_extract_dir"]),
        extract_dir=Path(_config()["extract_dir"]),
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


# ── Auto-assign (Claude SSE) ─────────────────────────────────────────────

AUTO_ASSIGN_SYSTEM = """\
You assign verbatim VTT quotes to narrative scenes.

Given a list of scenes (with narrator, name, focus, and chunk range) and a list
of unassigned quotes (with id, speaker, character, context, and text), assign
each quote to the single most appropriate scene based on:
- The quote's context and content
- The scene's focus and chunk range
- Character alignment (the scene's narrator or other characters present)

Output ONLY a JSON array of objects: [{"quote_id": <int>, "scene_index": <int>}, ...]
Include only quotes you can confidently assign. Omit quotes that don't clearly
fit any scene. Do not wrap in markdown code blocks.
"""


async def _stream_auto_assign() -> AsyncGenerator[str, None]:
    """Call Claude to assign unassigned quotes to scenes, stream progress."""
    import asyncio

    ledger = _get_ledger()
    scenes = _load_scenes()
    all_quotes = ledger.get_all_quotes()
    unassigned = [q for q in all_quotes if q["scene_index"] is None]

    if not unassigned:
        yield _sse_event("No unassigned quotes to assign.\n")
        yield _sse_done(0)
        return

    if not scenes:
        yield _sse_event("No scenes found. Run scene extraction first.\n")
        yield _sse_done(1)
        return

    yield _sse_event(f"Assigning {len(unassigned)} quotes to {len(scenes)} scenes...\n")

    # Build prompt
    scene_lines = []
    for s in scenes:
        scene_lines.append(
            f"Scene {s['index']}: narrator={s['narrator']}, "
            f"name=\"{s.get('scene', '')}\", focus=\"{s.get('focus', '')}\", "
            f"chunks={s['chunk_start']}-{s['chunk_end']}"
        )

    quote_lines = []
    for q in unassigned:
        text_preview = q["quote_text"][:200]
        quote_lines.append(
            f"[id={q['id']}] {q['character']} ({q['context']}): \"{text_preview}\""
        )

    user_prompt = (
        "## Scenes\n" + "\n".join(scene_lines) +
        "\n\n## Quotes to Assign\n" + "\n".join(quote_lines)
    )

    yield _sse_event("Calling Claude for assignment...\n")

    # Call Claude API (sync, in thread to not block event loop)
    try:
        from campaignlib import make_client, call_api
        client = make_client()
        model = _config().get("model", "claude-sonnet-4-6")

        response = await asyncio.to_thread(
            call_api, client, AUTO_ASSIGN_SYSTEM, user_prompt, model, 8192
        )

        yield _sse_event("Parsing response...\n")

        # Parse JSON response
        # Strip any markdown code fences if present
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        assignments = json.loads(text)
        if not isinstance(assignments, list):
            yield _sse_event(f"Unexpected response format: {type(assignments)}\n")
            yield _sse_done(1)
            return

        # Group by scene and bulk assign
        from collections import defaultdict
        by_scene: dict[int, list[int]] = defaultdict(list)
        for a in assignments:
            by_scene[a["scene_index"]].append(a["quote_id"])

        total = 0
        for scene_idx, quote_ids in by_scene.items():
            count = ledger.bulk_assign(quote_ids, scene_idx)
            total += count
            scene = next((s for s in scenes if s["index"] == scene_idx), None)
            label = f"Scene {scene_idx}"
            if scene:
                label += f": {scene['narrator']}"
                if scene.get("scene"):
                    label += f" — {scene['scene']}"
            yield _sse_event(f"  {label}: {count} quotes assigned\n")

        yield _sse_event(f"\nDone — {total} quotes assigned to {len(by_scene)} scenes.\n")
        yield _sse_done(0)

    except Exception as e:
        yield _sse_event(f"Error: {e}\n")
        yield _sse_done(1)


@router.get("/auto-assign")
async def api_auto_assign():
    return StreamingResponse(
        _stream_auto_assign(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Generate extraction (Claude SSE) ─────────────────────────────────────

GENERATE_EXTRACTION_SYSTEM = """\
You are extracting character moments for a D&D session narrative.

Given:
- A scene's narrator, name, and focus
- Verbatim VTT quotes assigned to this scene
- The GM's recap text covering this scene

Produce a scene extraction file with:

1. Dialogue exchanges — use the verbatim quotes provided, attributed correctly
   Format: Speaker: "exact quote text"
2. Action beats — what the characters did physically (from the recap)
3. Environmental moments — setting, atmosphere (from the recap)

Format each moment as:
**[brief scene label]**
[dialogue lines]
[action/environment description]
[one sentence: what this moment felt like or cost]

Keep everything in chronological order.
IMPORTANT: Use ONLY the provided quotes for dialogue. Do not invent dialogue.
Output only the extracted moments. No preamble, no commentary.
"""


async def _stream_generate_extraction(scene_num: int) -> AsyncGenerator[str, None]:
    """Generate a full extraction file from assigned quotes + recap."""
    import asyncio

    ledger = _get_ledger()
    scenes = _load_scenes()

    if scene_num < 1 or scene_num > len(scenes):
        yield _sse_event(f"Invalid scene number: {scene_num}\n")
        yield _sse_done(1)
        return

    scene = scenes[scene_num - 1]
    quotes = ledger.get_scene_quotes(scene_num)

    if not quotes:
        yield _sse_event(f"No quotes assigned to Scene {scene_num}. Assign quotes first.\n")
        yield _sse_done(1)
        return

    yield _sse_event(f"Generating extraction for Scene {scene_num}: "
                     f"{scene['narrator']} — {scene.get('scene', '')} "
                     f"({len(quotes)} quotes)...\n")

    # Build quote text
    quote_block = []
    for q in quotes:
        quote_block.append(f"{q['character']}: \"{q['quote_text']}\"")
        if q.get("context"):
            quote_block.append(f"  [{q['context']}]")

    # Load recap text for this scene's chunk range
    recap_text = ""
    session_path = _config().get("session")
    if session_path and Path(session_path).exists():
        full_recap = Path(session_path).read_text(encoding="utf-8")
        # Try to extract the relevant scene section from the recap
        from session_doc import extract_section_text
        scene_name = scene.get("scene", "")
        if scene_name:
            recap_text = extract_section_text(full_recap, scene_name)
        if not recap_text:
            # Fall back to Summary + Memorable Moments
            recap_text = extract_section_text(full_recap, "Summary")
            mm = extract_section_text(full_recap, "Memorable Moments")
            if mm:
                recap_text += "\n\n## Memorable Moments\n" + mm

    user_prompt = (
        f"## Scene {scene_num}\n"
        f"Narrator: {scene['narrator']}\n"
        f"Scene: {scene.get('scene', 'N/A')}\n"
        f"Focus: {scene.get('focus', 'N/A')}\n\n"
        f"## Assigned Quotes\n" + "\n".join(quote_block)
    )
    if recap_text:
        user_prompt += f"\n\n## GM Recap Context\n{recap_text}"

    yield _sse_event("Calling Claude...\n\n")

    try:
        from campaignlib import make_client
        client = make_client()
        model = _config().get("model", "claude-sonnet-4-6")

        # Stream the response
        chunks: list[str] = []
        response_gen = await asyncio.to_thread(
            lambda: client.messages.stream(
                model=model,
                max_tokens=8192,
                system=GENERATE_EXTRACTION_SYSTEM,
                messages=[{"role": "user", "content": user_prompt}],
            )
        )

        with response_gen as stream:
            for text in stream.text_stream:
                chunks.append(text)
                yield _sse_event(text)

        full_response = "".join(chunks)

        # Save extraction file
        from session_doc import extraction_filename
        fname = extraction_filename(scene_num, scene["narrator"], scene.get("scene", ""))
        extract_path = Path(_config()["extract_dir"]) / fname
        extract_path.write_text(full_response, encoding="utf-8")

        yield _sse_event(f"\n\nSaved to {fname}\n")
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
