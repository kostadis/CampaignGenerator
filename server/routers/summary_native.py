"""summary_native routes — grounding-doc drafts built from reviewed summaries.

Every run route shells out to ``console_script("summary_native")`` and streams
it through the grounding router's SSE helper (feature 031, Principle VI: the UI
invokes the CLI and never reimplements it). Defaults resolve from
``<config>/grounding.yaml``'s ``summary_native`` group at the route edge; a
route takes sentinels (``""`` / ``None``), never a default literal, and the
declared defaults live in ``pipelines/summary_native/schema.py`` (Principle XII).

``--registry``, ``--canon`` and ``--out-root`` are deliberately never passed:
they are campaign-layout paths with no per-run UI control (GM ruling). The CLI
reads ``grounding.yaml``'s ``summary_native`` group itself (``out_root``,
``canon_file``, ``registry``), so the config file is where they change
(contracts/http.md, "Deliberately CLI-only").

The read-only routes (``/chapters``, ``/report``, ``/drafts``) only list files
and read a JSON the CLI wrote. None of them parses summary content or calls a
model.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from campaignlib.players_config import PLAYERS_CONFIG_FILENAME
from pipelines.summary_native import freshness, notes, resolve, schema
from server.grounding_config_shared import SummaryNativeRun
from server.platform_config_service import resolve_selection, selection_cli_args
from server.routers.grounding import (
    _pick,
    _selection_for,
    _service,
    _sse_response,
)
from server.subprocess_runner import console_script

router = APIRouter()

#: ``resolve_selection``'s ``service_name`` and the owner of the override.
_SERVICE_NAME = "summary_native"


# ── Resolution helpers ──────────────────────────────────────────────────────

def _run_config(request: Request) -> SummaryNativeRun:
    return _service(request).resolved().summary_native


def _pick_num(explicit: int | float | None, stored: int | float | None):
    """Explicit request value wins; ``None`` (not ``0``) means "not supplied".

    ``recent_chapters=0`` ("every chapter") and ``parts=0`` ("one call") are
    meaningful values, so unlike ``grounding._pick`` a zero is an answer.
    """
    return explicit if explicit is not None else stored


def _require_doc(doc: str) -> str:
    if doc not in schema.DOCS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown doc {doc!r}; choose one of: {', '.join(schema.DOCS)}",
        )
    return doc


def _require_dir(run: SummaryNativeRun, explicit: str) -> str:
    value = _pick((explicit or "").strip(), run.summaries_dir)
    if not value or not str(value).strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "no summaries directory: pass ?summaries_dir= or set "
                "grounding.yaml summary_native.summaries_dir"
            ),
        )
    return str(value).strip()


def _require_range(run: SummaryNativeRun, since: int | None, until: int | None) -> tuple[int, int]:
    lo = _pick_num(since, run.range_since)
    hi = _pick_num(until, run.range_until)
    if lo is None or hi is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "choose a chapter range: pass ?since= and ?until=, or set "
                "grounding.yaml summary_native.range_since and range_until "
                "(the UI never assumes all chapters)"
            ),
        )
    return lo, hi


def _base_cmd(command: str, doc: str | None, summaries_dir: str, since: int, until: int) -> list[str]:
    cmd = [console_script("summary_native"), command]
    if doc:
        cmd.append(doc)
    return cmd + [
        "--summaries-dir", summaries_dir,
        "--since", str(since),
        "--until", str(until),
    ]


def _range_dir(run: SummaryNativeRun, since: int, until: int) -> Path:
    return schema.resolve_under(Path.cwd(), run.out_root) / f"ch{since:03d}-{until:03d}"


# ── Read-only ───────────────────────────────────────────────────────────────

def chapter_listing(directory: Path) -> dict:
    """The chapter numbers present in ``directory``, from filename prefixes only.

    Mirrors the CLI's own listing (top-level ``*.md``, ``PREFIX_RE``) so the
    range picker offers exactly the values ``--since``/``--until`` accept. The
    content of a file is never opened here. Shared with the NPC dossiers router.
    """
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail=f"{directory}: not a directory")
    by_chapter: dict[int, list[str]] = {}
    for p in sorted(directory.iterdir()):
        if not (p.is_file() and p.suffix == ".md"):
            continue
        m = schema.PREFIX_RE.match(p.name)
        if m:
            by_chapter.setdefault(int(m.group(1)), []).append(p.name)
    return {
        "present": sorted(by_chapter),
        "files": [
            {"chapter": ch, "path": name}
            for ch in sorted(by_chapter)
            for name in by_chapter[ch]
        ],
        "duplicate_chapters": [ch for ch in sorted(by_chapter) if len(by_chapter[ch]) > 1],
    }


@router.get("/chapters")
def get_chapters(request: Request, summaries_dir: str = ""):
    """The chapter numbers present (see :func:`chapter_listing`)."""
    return chapter_listing(
        schema.resolve_under(Path.cwd(), _require_dir(_run_config(request), summaries_dir))
    )


@router.get("/report")
def get_report(request: Request, since: int | None = None, until: int | None = None):
    run = _run_config(request)
    lo, hi = _require_range(run, since, until)
    path = _range_dir(run, lo, hi) / "validation_report.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no validation report yet: run Validate")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"{path}: unreadable report: {exc}") from exc


@router.get("/drafts")
def get_drafts(request: Request, since: int | None = None, until: int | None = None):
    run = _run_config(request)
    lo, hi = _require_range(run, since, until)
    range_dir = _range_dir(run, lo, hi)
    if not range_dir.is_dir():
        raise HTTPException(status_code=404, detail="no output for this range yet: run Build")
    out = []
    for doc in schema.DOCS:
        for status, suffix in (("draft", "draft"), ("incomplete", "incomplete")):
            p = schema.draft_dir(range_dir, doc) / f"{doc}.{suffix}.md"
            if p.is_file():
                out.append({
                    "doc": doc,
                    "path": schema.display_path(p, Path.cwd()),
                    "status": status,
                    "bytes": p.stat().st_size,
                })
    # Reports the chunked build writes beside its notes and drafts (spec 033).
    state_drafts = schema.draft_dir(range_dir, "world_state")
    reports = [
        ("drops", freshness.notes_dir(range_dir) / "drops.md"),
        ("npc_status_report", state_drafts / "npc_status_report.md"),
        ("canon_events_timeline", state_drafts / schema.TIMELINE_FILE),
        ("budget_report", state_drafts / "budget_report.json"),
    ]
    reports += [(f"reference/{p.stem}", p) for p in sorted((state_drafts / "reference").glob("*.md"))]
    for name, p in reports:
        if p.is_file():
            out.append({"doc": name, "path": schema.display_path(p, Path.cwd()), "status": "report", "bytes": p.stat().st_size})
    return out


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _extract_block(request: Request, run: SummaryNativeRun, lo: int, hi: int) -> dict:
    """The checked notes' state, read from ``state/notes/`` only: no model, no CLI, no summary parsing."""
    root = Path.cwd()
    range_dir = _range_dir(run, lo, hi)
    mp = freshness.notes_dir(range_dir) / freshness.NOTES_MANIFEST
    m = _read_json(mp)
    block: dict = {"present": False, "complete": False, "stale": False, "stale_reason": None,
                   "chunks": [], "totals": {"chunks": 0, "checked": 0, "kept": 0, "dropped": 0},
                   "outliers": [], "drops_file": None}
    if not (isinstance(m, dict) and m.get("kind") == "state_notes"):
        return block
    chunks = [c for c in m.get("chunks", []) if isinstance(c, dict)]
    outliers = notes.outliers_of([(c["chapters"], int(c.get("dropped", 0))) for c in chunks])
    block.update({
        "present": True,
        "complete": bool(m.get("complete")),
        "backend": m.get("backend"),
        "model": m.get("model"),
        "chunk_chars": m.get("chunk_chars"),
        "absent_chapters": m.get("absent_chapters", []),
        "chunks": [
            {"index": c["index"], "chapters": c["chapters"], "status": c.get("status"),
             "kept": int(c.get("kept", 0)), "dropped": int(c.get("dropped", 0)),
             "outlier": c["chapters"] in outliers}
            for c in chunks
        ],
        "totals": {
            "chunks": len(chunks),
            "checked": sum(1 for c in chunks if c.get("status") == "checked"),
            "kept": sum(int(c.get("kept", 0)) for c in chunks),
            "dropped": sum(int(c.get("dropped", 0)) for c in chunks),
        },
        "outliers": outliers,
    })
    drops = freshness.notes_dir(range_dir) / "drops.md"
    if drops.is_file():
        block["drops_file"] = schema.display_path(drops, root)
    # Freshness is the CLI's own check (corpus manifest, registry, players.yaml).
    try:
        registry = resolve.resolve_registry_path(root, None, run.model_dump(mode="json"))
    except resolve.PathRefusal as e:
        block.update(stale=True, stale_reason=str(e))
        return block
    players = _service(request).config_path_base / PLAYERS_CONFIG_FILENAME
    reason = freshness.check_notes_fresh(range_dir, registry, players)
    block.update(stale=reason is not None, stale_reason=reason)
    return block


@router.get("/state")
def get_state(request: Request, since: int | None = None, until: int | None = None):
    """What is on disk for the range, per step (read-only; files only)."""
    run = _run_config(request)
    lo, hi = _require_range(run, since, until)
    budgets = _read_json(schema.draft_dir(_range_dir(run, lo, hi), "world_state") / "budget_report.json")
    return {
        "range": f"{lo}-{hi}",
        "extract": _extract_block(request, run, lo, hi),
        # {section: {budget, words, over}} from the last world_state build, or null
        "world_budgets": budgets if isinstance(budgets, dict) else None,
    }


# ── Runs (SSE) ──────────────────────────────────────────────────────────────

@router.get("/run/validate")
async def run_validate(
    request: Request,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    dup_threshold: float | None = None,
):
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    cmd = _base_cmd("validate", None, directory, lo, hi)
    cmd += ["--dup-threshold", str(_pick_num(dup_threshold, run.dup_threshold))]
    return _sse_response(cmd)


@router.get("/run/build")
async def run_build(
    request: Request,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    dup_threshold: float | None = None,
    force: bool = False,
):
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    cmd = _base_cmd("build", None, directory, lo, hi)
    cmd += ["--dup-threshold", str(_pick_num(dup_threshold, run.dup_threshold))]
    if force:
        cmd.append("--force")
    return _sse_response(cmd)


@router.get("/run/synth/{doc}")
async def run_synth(
    request: Request,
    doc: str,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    world_state: str = "",
    campaign_state: str = "",
    party_config: str = "",
    planning_config: str = "",
    audit: list[str] | None = Query(default=None),
    name: list[str] | None = Query(default=None),
    recent_chapters: int | None = None,
    recurring_min: int | None = None,
    parts: int | None = None,
    max_tokens: int | None = None,
    dump_only: bool = False,
    force: bool = False,
    model: str | None = None,
):
    _require_doc(doc)
    run = _run_config(request)
    chunked = doc in schema.STATE_DOCS
    if chunked:
        # world_state and campaign_state write one call per section from the checked notes; the CLI
        # refuses these flags and so does the route, with the CLI's words.
        if parts:
            raise HTTPException(status_code=400, detail=schema.STATE_PARTS_REFUSAL.format(doc=doc))
        if any(a.strip() for a in (audit or [])):
            raise HTTPException(
                status_code=400,
                detail=schema.STATE_AUDIT_REFUSAL if doc == "campaign_state"
                else f"--audit applies to campaign_state only, not {doc}",
            )
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    cmd = _base_cmd("synth", doc, directory, lo, hi)

    if world_state.strip():
        cmd += ["--world-state", world_state.strip()]
    if campaign_state.strip():
        cmd += ["--campaign-state", campaign_state.strip()]
    # --party-config / --planning-config default to <config>/party.yaml and
    # <config>/planning.yaml inside the CLI; passed only when the request names one.
    if party_config.strip():
        cmd += ["--party-config", party_config.strip()]
    if planning_config.strip():
        cmd += ["--planning-config", planning_config.strip()]
    # --audit defaults to campaign_state.track_files inside the CLI; the route
    # passes it only when the request names files.
    files = [a.strip() for a in (audit or []) if a.strip()]
    if files:
        cmd += ["--audit", *files]
    subjects = [n.strip() for n in (name or []) if n.strip()]
    if subjects:
        cmd += ["--name", *subjects]

    cmd += ["--recent-chapters", str(_pick_num(recent_chapters, run.recent_chapters))]
    cmd += ["--recurring-min", str(_pick_num(recurring_min, run.recurring_min))]
    if not chunked:
        cmd += ["--parts", str(_pick_num(parts, run.parts))]
    if max_tokens is not None:
        cmd += ["--max-tokens", str(max_tokens)]
    if dump_only:
        cmd.append("--dump-only")
    if force:
        cmd.append("--force")

    if chunked:
        # The prose step has its own backend/model block (grounding.yaml summary_native.prose).
        service, service_name = run.prose, f"{_SERVICE_NAME}.prose"
    else:
        service, service_name = _selection_for(request, _SERVICE_NAME), _SERVICE_NAME
    cmd += selection_cli_args(resolve_selection(
        request, request_model=model, service=service, service_name=service_name,
    ))
    return _sse_response(cmd)


@router.get("/run/extract")
async def run_extract(
    request: Request,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    chunk_chars: int | None = None,
    max_tokens: int | None = None,
    dump_only: bool = False,
    force: bool = False,
    model: str | None = None,
):
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    cmd = _base_cmd("extract", None, directory, lo, hi)
    cmd += ["--chunk-chars", str(_pick_num(chunk_chars, run.extract.chunk_chars))]
    if max_tokens is not None:
        cmd += ["--max-tokens", str(max_tokens)]
    if dump_only:
        cmd.append("--dump-only")
    if force:
        cmd.append("--force")
    cmd += selection_cli_args(resolve_selection(
        request, request_model=model, service=run.extract, service_name=f"{_SERVICE_NAME}.extract",
    ))
    return _sse_response(cmd)


@router.get("/run/compare/{doc}")
async def run_compare(
    request: Request,
    doc: str,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
):
    _require_doc(doc)
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    cmd = _base_cmd("compare", doc, directory, lo, hi)
    cmd += ["--live", f"docs/{doc}.md"]
    return _sse_response(cmd)
