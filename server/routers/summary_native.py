"""summary_native routes — grounding-doc drafts built from reviewed summaries.

Every run route shells out to ``console_script("summary_native")`` and streams
it through the grounding router's SSE helper (feature 031, Principle VI: the UI
invokes the CLI and never reimplements it). Defaults resolve from
``<config>/grounding.yaml``'s ``summary_native`` group at the route edge; a
route takes sentinels (``""`` / ``None``), never a default literal, and the
declared defaults live in ``pipelines/summary_native/schema.py`` (Principle XII).

``--registry``, ``--canon`` and ``--out-root`` are deliberately never passed:
they are campaign-layout paths set once, so the CLI resolves its own defaults
(contracts/http.md, "Deliberately CLI-only").

The read-only routes (``/chapters``, ``/report``, ``/drafts``) only list files
and read a JSON the CLI wrote. None of them parses summary content or calls a
model.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from pipelines.summary_native import schema
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

@router.get("/chapters")
def get_chapters(request: Request, summaries_dir: str = ""):
    """The chapter numbers present, from filename prefixes only.

    Mirrors the CLI's own listing (top-level ``*.md``, ``PREFIX_RE``) so the
    range picker offers exactly the values ``--since``/``--until`` accept. The
    content of a file is never opened here.
    """
    directory = schema.resolve_under(Path.cwd(), _require_dir(_run_config(request), summaries_dir))
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
    drafts = range_dir / "drafts"
    if not range_dir.is_dir():
        raise HTTPException(status_code=404, detail="no output for this range yet: run Build")
    out = []
    for doc in schema.DOCS:
        for status, suffix in (("draft", "draft"), ("incomplete", "incomplete")):
            p = drafts / f"{doc}.{suffix}.md"
            if p.is_file():
                out.append({
                    "doc": doc,
                    "path": schema.display_path(p, Path.cwd()),
                    "status": status,
                    "bytes": p.stat().st_size,
                })
    return out


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
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    cmd = _base_cmd("synth", doc, directory, lo, hi)

    if world_state.strip():
        cmd += ["--world-state", world_state.strip()]
    if campaign_state.strip():
        cmd += ["--campaign-state", campaign_state.strip()]
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
    cmd += ["--parts", str(_pick_num(parts, run.parts))]
    if max_tokens is not None:
        cmd += ["--max-tokens", str(max_tokens)]
    if dump_only:
        cmd.append("--dump-only")
    if force:
        cmd.append("--force")

    cmd += selection_cli_args(resolve_selection(
        request, request_model=model,
        service=_selection_for(request, _SERVICE_NAME), service_name=_SERVICE_NAME,
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
