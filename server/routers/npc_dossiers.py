"""NPC dossiers routes (spec 032, US5): link, draft, verify, compose and publish.

Every run route shells out to ``console_script("summary_native")`` and streams it
through the grounding router's SSE helper (Principle VI: the UI invokes the CLI and
never reimplements it). argv is built only in the ``_build_*_cmd`` functions.

Defaults resolve at the route edge: this service's own knobs from
``NpcDossiersConfigService`` (``<config>/npc_dossiers.yaml``), and the corpus paths
and chapter range from ``grounding.yaml summary_native`` (``GroundingConfigService``).
A route takes sentinels (``""`` / ``None``), never a default literal; every default is
declared once in ``pipelines/summary_native/schema.py`` (Principle XII).

Principle X: ``/run/draft`` and ``/run/publish`` refuse with a 400 (no process
spawned) unless the request carries an explicit ``select``; a chapter range is
likewise never assumed.

Principle IX: the UI only mechanises CLI runs. Every read route is read-only, and no
route writes under the authored directory (``tests/test_npc_dossiers_routes.py``
asserts it). The migration has no route: it is an operator CLI, run deliberately.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from campaignlib.selection import ModelSelection
from campaignlib.players_config import PLAYERS_CONFIG_FILENAME
from pipelines.summary_native import npc_authored, npc_compose, npc_link, npc_publish, npc_slug, resolve, schema
from pipelines.summary_native.freshness import check_link_fresh, manual_sha
from server.npc_dossiers_config import NpcDossiersConfig, NpcDossiersConfigService
from server.platform_config_service import resolve_selection, selection_cli_args
from server.routers.grounding import _service as _grounding_service
from server.routers.grounding import _sse_response
from server.routers.summary_native import (
    _pick_num,
    _require_dir,
    _require_range,
    _run_config,
    chapter_listing,
)
from server.subprocess_runner import console_script
from server.scheduler_status import project_latest

router = APIRouter()

#: ``resolve_selection``'s ``service_name`` and the owner of the override.
_SERVICE_NAME = "npc_dossiers"

DRAFT_SELECTS = ("all", "narrowed")
PUBLISH_SELECTS = ("named", "all", "authored_all")
FILE_KINDS = ("evidence", "draft", "gm", "published")

_STEM_RE = re.compile(r"\A[A-Za-z0-9_.-]+\Z")
_DROPPED_RE = re.compile(r"^- \[manual (\d+)\] (.*)$")


# ── Resolution helpers ──────────────────────────────────────────────────────

def _config_service(request: Request) -> NpcDossiersConfigService:
    return NpcDossiersConfigService(_grounding_service(request).config_path_base)


def _npc_config(request: Request) -> NpcDossiersConfig:
    return _config_service(request).resolved()


def _names(values: list[str] | None) -> list[str]:
    return [n.strip() for n in (values or []) if n.strip()]


def _range_dir(request: Request, since: int, until: int) -> Path:
    """The NPC output folder for a range: ``<npc_root>/chNNN-NNN``."""
    root = schema.resolve_under(Path.cwd(), _npc_config(request).npc_root)
    return root / f"ch{since:03d}-{until:03d}"


def _stem(stem: str) -> str:
    if not _STEM_RE.match(stem or "") or stem in (".", ".."):
        raise HTTPException(status_code=400, detail=f"invalid NPC stem {stem!r}")
    return stem


def _base_cmd(command: str, summaries_dir: str, since: int, until: int) -> list[str]:
    return [
        console_script("summary_native"), command,
        "--summaries-dir", summaries_dir,
        "--since", str(since),
        "--until", str(until),
    ]


# ── argv builders (the only place argv is built) ────────────────────────────

def _build_link_cmd(summaries_dir: str, since: int, until: int, *, force: bool = False) -> list[str]:
    cmd = _base_cmd("npc-link", summaries_dir, since, until)
    if force:
        cmd.append("--force")
    return cmd


def _build_draft_cmd(
    summaries_dir: str, since: int, until: int, *,
    select: str,
    names: list[str],
    recent_chapters: int | None,
    recurring_min: int | None,
    max_tokens: int,
    mode: str,
    chunk_chars: int,
    dump_only: bool,
    force: bool,
    selection_args: list[str],
    endpoints: list[str] | None = None,
    parallel: int | None = None,
    resume: str | None = None,
) -> list[str]:
    cmd = _base_cmd("npc-draft", summaries_dir, since, until)
    if select == "all":
        cmd.append("--all")
    else:
        if names:
            cmd += ["--name", *names]
        if recent_chapters is not None:
            cmd += ["--recent-chapters", str(recent_chapters)]
        if recurring_min is not None:
            cmd += ["--recurring-min", str(recurring_min)]
    cmd += ["--mode", mode, "--chunk-chars", str(chunk_chars), "--max-tokens", str(max_tokens)]
    if dump_only:
        cmd.append("--dump-only")
    if force:
        cmd.append("--force")
    cmd += selection_args
    if endpoints:
        cmd += ["--endpoints", *endpoints]
    if parallel is not None:
        cmd += ["--parallel", str(parallel)]
    if resume is not None:
        cmd += ["--resume", resume] if resume else ["--resume"]
    return cmd


def _build_verify_cmd(summaries_dir: str, since: int, until: int, *, names: list[str], parallel: int | None = None,
                      resume: str | None = None) -> list[str]:
    cmd = _base_cmd("npc-verify", summaries_dir, since, until)
    if names:
        cmd += ["--name", *names]
    if parallel is not None:
        cmd += ["--parallel", str(parallel)]
    if resume is not None:
        cmd += ["--resume", resume] if resume else ["--resume"]
    return cmd


def _build_compose_cmd(
    summaries_dir: str, since: int, until: int, *, names: list[str], init: list[str],
) -> list[str]:
    cmd = _base_cmd("npc-compose", summaries_dir, since, until)
    if names:
        cmd += ["--name", *names]
    if init:
        cmd += ["--init", *init]
    return cmd


def _build_publish_cmd(
    summaries_dir: str, since: int, until: int, *,
    select: str, names: list[str], source: str, force: bool,
) -> list[str]:
    cmd = _base_cmd("npc-publish", summaries_dir, since, until)
    if select == "all":
        cmd.append("--all")
    elif select == "authored_all":
        cmd.append("--authored-all")
    else:
        cmd += ["--name", *names]
    if source:
        cmd += ["--source", source]
    if force:
        cmd.append("--force")
    return cmd


# ── Config ──────────────────────────────────────────────────────────────────

@router.get("/config")
def get_config(request: Request) -> NpcDossiersConfig:
    return _npc_config(request)


@router.put("/config")
def put_config(request: Request, body: NpcDossiersConfig) -> NpcDossiersConfig:
    """Replace the document. The model is strict, so an unknown key is a 422."""
    return _config_service(request).put_config(body)


# ── Read-only ───────────────────────────────────────────────────────────────

@router.get("/chapters")
def get_chapters(request: Request, summaries_dir: str = ""):
    """Same shape as ``/api/grounding/summary-native/chapters`` (shared helper)."""
    return chapter_listing(
        schema.resolve_under(Path.cwd(), _require_dir(_run_config(request), summaries_dir))
    )


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _dropped_manual(verify_md: Path) -> list[dict]:
    """The manual edits a verification reports as dropped, read from ``<stem>.verify.md``."""
    try:
        lines = verify_md.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    out: list[dict] = []
    for i, line in enumerate(lines):
        m = _DROPPED_RE.match(line)
        if m and i + 1 < len(lines) and "DROPPED" in lines[i + 1]:
            out.append({"n": int(m.group(1)), "text": m.group(2)})
    return out


def _draft_header_field(draft: Path, label: str) -> str | None:
    try:
        first = draft.read_text(encoding="utf-8").split("\n", 1)[0]
    except (OSError, UnicodeDecodeError):
        return None
    m = re.search(rf"\| {re.escape(label)}: (\S+)", first)
    return m.group(1) if m else None


def _published(root: Path, slug: str) -> bool:
    target = root / schema.NPCS_DIR / f"{slug}.md"
    try:
        return target.is_file() and target.read_text(encoding="utf-8").startswith(schema.PUBLISH_HEADER_PREFIX)
    except (OSError, UnicodeDecodeError):
        return False


def _link_stale(request: Request, run, root: Path, lo: int, hi: int, npc_dir: Path) -> bool:
    """True when ``npc-draft`` would refuse the link output as stale: the CLI's own check
    (corpus manifest, registry, canon, word list, players and evidence shas)."""
    out_root = schema.resolve_under(root, run.out_root)
    cfg = run.model_dump(mode="json")
    try:
        registry = resolve.resolve_registry_path(root, None, cfg)
        canon = resolve.resolve_canon_path(root, out_root, None, cfg)
    except resolve.PathRefusal:
        return True  # the CLI refuses outright on these, so the link cannot be called fresh
    players = _grounding_service(request).config_path_base / PLAYERS_CONFIG_FILENAME
    evidence = {e.stem: e.sha256 for e in npc_link.read_evidence_files(npc_dir)}
    return check_link_fresh(
        npc_dir, out_root / f"ch{lo:03d}-{hi:03d}", registry, canon, evidence, players,
    ) is not None


@router.get("/state")
def get_state(request: Request, since: int | None = None, until: int | None = None):
    """Per-NPC state, read from files on disk only: no model, no CLI, no summary parsing."""
    run = _run_config(request)
    lo, hi = _require_range(run, since, until)
    npc_dir = _range_dir(request, lo, hi)
    root = Path.cwd()
    out = {"range": f"{lo}-{hi}", "linked": False, "link_stale": False,
           "warnings": {"ambiguous": 0, "generic_unruled": 0}, "npcs": []}
    manifest = _read_json(npc_dir / npc_link.LINK_MANIFEST)
    if not (isinstance(manifest, dict) and manifest.get("kind") == "npc_link"):
        return out
    out["linked"] = True
    out["link_stale"] = _link_stale(request, run, root, lo, hi, npc_dir)
    report = _read_json(npc_dir / npc_link.LINK_REPORT_JSON)
    counts = (report or {}).get("counts") or {}
    out["warnings"] = {
        "ambiguous": int(counts.get("ambiguous", 0)),
        "generic_unruled": int(counts.get("generic_unruled", 0)),
    }

    draft_dir = npc_dir / npc_compose.DRAFT_DIR
    gm_dir = npc_dir / npc_compose.GM_DIR
    runs = {}
    for rec in sorted((npc_dir / "runs").glob("*/record.json")):
        data = _read_json(rec)
        if isinstance(data, dict):
            runs[rec.parent.name] = data
    index = _read_json(draft_dir / "index.json")
    index = index if isinstance(index, dict) else {}

    for ev in npc_link.read_evidence_files(npc_dir):
        slug = npc_slug.slug_for(ev.subject)
        authored_file = npc_compose.authored_path_for(root, ev.subject)
        try:
            manual = npc_authored.load_manual(authored_file, ev.subject)
        except npc_authored.AuthoredError:
            manual = None  # malformed: the CLI will say why; the page does not guess
        draft_md = draft_dir / f"{ev.stem}.md"
        if draft_md.is_file():
            status = "drafted"
            recorded = (runs.get((index.get(ev.stem) or {}).get("run_id") or "") or {}).get("npcs", {}).get(ev.stem) or {}
            stale_evidence = recorded.get("evidence_sha256") not in (None, ev.sha256)
            stale_manual = manual is not None and _draft_header_field(draft_md, "manual sha256") not in (
                None, manual_sha(manual))
            if stale_evidence or stale_manual:
                status = "stale"
        elif (draft_dir / f"{ev.stem}.incomplete.md").is_file():
            status = "incomplete"
        else:
            status = "none"
        out["npcs"].append({
            "stem": ev.stem,
            "subject": ev.subject,
            "global": ev.global_,
            "exclusion": ev.exclusion,
            "n_entries": ev.n_entries,
            "n_scenes": ev.n_scenes,
            "n_moments": ev.n_moments,
            "first_seen": ev.first_seen,
            "last_seen": ev.last_seen,
            "draft": status,
            "published": _published(root, slug),
            "verify": npc_publish.read_verdict(npc_dir, ev.stem) or "none",
            "authored": authored_file.is_file(),
            "composed": (gm_dir / f"{ev.stem}.md").is_file(),
            "manual_dropped": _dropped_manual(draft_dir / f"{ev.stem}.verify.md"),
        })
    return out


@router.get("/report/link")
def get_link_report(request: Request, since: int | None = None, until: int | None = None):
    lo, hi = _require_range(_run_config(request), since, until)
    path = _range_dir(request, lo, hi) / npc_link.LINK_REPORT_JSON
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not linked yet: run Link")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"{path.name}: unreadable report: {exc}") from exc


@router.get("/report/verify/{stem}")
def get_verify_report(request: Request, stem: str, since: int | None = None, until: int | None = None):
    lo, hi = _require_range(_run_config(request), since, until)
    stem = _stem(stem)
    npc_dir = _range_dir(request, lo, hi)
    path = npc_dir / npc_compose.DRAFT_DIR / f"{stem}.verify.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{stem}: not verified yet: run Verify")
    return {
        "stem": stem,
        "verdict": npc_publish.read_verdict(npc_dir, stem) or "none",
        "markdown": path.read_text(encoding="utf-8"),
        "manual_dropped": _dropped_manual(path),
    }


@router.get("/file")
def get_file(
    request: Request,
    since: int | None = None,
    until: int | None = None,
    kind: str = "",
    stem: str = "",
):
    """A file's text, for display only. No write route exists for any of these."""
    if kind not in FILE_KINDS:
        raise HTTPException(status_code=400, detail=f"unknown kind {kind!r}; choose one of: {', '.join(FILE_KINDS)}")
    lo, hi = _require_range(_run_config(request), since, until)
    stem = _stem(stem)
    npc_dir = _range_dir(request, lo, hi)
    if kind == "evidence":
        path = npc_dir / npc_link.EVIDENCE_DIR / f"{stem}.md"
    elif kind == "gm":
        path = npc_dir / npc_compose.GM_DIR / f"{stem}.md"
    elif kind == "draft":
        path = npc_dir / npc_compose.DRAFT_DIR / f"{stem}.md"
        if not path.is_file():
            path = npc_dir / npc_compose.DRAFT_DIR / f"{stem}.incomplete.md"
    else:
        subject = next((e.subject for e in npc_link.read_evidence_files(npc_dir) if e.stem == stem), None)
        if subject is None:
            raise HTTPException(status_code=404, detail=f"{stem}: no evidence for this NPC in range")
        path = Path.cwd() / schema.NPCS_DIR / f"{npc_slug.slug_for(subject)}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{kind} file for {stem} does not exist yet")
    try:
        return {"kind": kind, "stem": stem, "path": schema.display_path(path, Path.cwd()),
                "text": path.read_text(encoding="utf-8")}
    except (OSError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"{path.name}: unreadable: {exc}") from exc


# ── Runs (SSE) ──────────────────────────────────────────────────────────────

@router.get("/run/link")
async def run_link(
    request: Request,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    force: bool = False,
):
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    return _sse_response(_build_link_cmd(directory, lo, hi, force=force))


@router.get("/run/draft")
async def run_draft(
    request: Request,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    select: str = "",
    name: list[str] | None = Query(default=None),
    recent_chapters: int | None = None,
    recurring_min: int | None = None,
    max_tokens: int | None = None,
    mode: str = "",
    chunk_chars: int | None = None,
    dump_only: bool = False,
    force: bool = False,
    model: str | None = None,
    backend: str | None = None,
    endpoints: list[str] | None = Query(default=None),
    parallel: int | None = None,
    resume: str | None = None,
):
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    if select not in DRAFT_SELECTS:
        raise HTTPException(
            status_code=400,
            detail=(
                "choose which NPCs to draft: pass ?select=all (every global NPC with "
                "evidence in range) or ?select=narrowed (the UI never assumes either)"
            ),
        )
    cfg = _npc_config(request)
    names = _names(name)
    recent, recurring = recent_chapters, recurring_min
    if select == "narrowed" and not names and recent is None and recurring is None:
        # "narrowed" with nothing to narrow by would make the CLI draft every NPC; fall
        # back to the stored thresholds so the run is still the narrow one that was chosen.
        recent, recurring = cfg.recent_chapters, cfg.recurring_min
    if mode and mode not in schema.DRAFT_MODES:
        raise HTTPException(status_code=400, detail=f"unknown mode {mode!r}; choose one of: {', '.join(schema.DRAFT_MODES)}")
    if parallel is not None and parallel < 1:
        raise HTTPException(status_code=400, detail="parallel must be at least 1")
    if resume is not None and (force or dump_only):
        raise HTTPException(status_code=400, detail="--resume cannot be combined with --force or --dump-only")
    chunk = _pick_num(chunk_chars, cfg.draft.chunk_chars)
    if chunk < 1:
        raise HTTPException(status_code=400, detail="chunk_chars must be a positive integer")
    resolved = resolve_selection(
        request, request_model=model, request_backend=backend,
        service=_config_service(request).get_selection(), service_name=_SERVICE_NAME,
    )
    urls = _names(endpoints)
    if urls and resolved.backend != schema.DEFAULT_DRAFT_BACKEND:
        raise HTTPException(status_code=400, detail=f"--endpoints applies to --backend dgx only, not {resolved.backend}")
    cmd = _build_draft_cmd(
        directory, lo, hi,
        select=select, names=names, recent_chapters=recent, recurring_min=recurring,
        max_tokens=_pick_num(max_tokens, cfg.max_tokens),
        mode=mode or cfg.draft.mode, chunk_chars=chunk,
        dump_only=dump_only, force=force,
        selection_args=selection_cli_args(resolved),
        endpoints=urls, parallel=parallel, resume=resume,
    )
    return _sse_response(cmd)


@router.get("/run/verify")
async def run_verify(
    request: Request,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    name: list[str] | None = Query(default=None),
    parallel: int | None = None,
    resume: str | None = None,
):
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    if parallel is not None and parallel < 1:
        raise HTTPException(status_code=400, detail="parallel must be at least 1")
    return _sse_response(_build_verify_cmd(directory, lo, hi, names=_names(name), parallel=parallel, resume=resume))


@router.get("/status/{operation}")
def get_scheduler_status(request: Request, operation: str, since: int | None = None, until: int | None = None):
    if operation not in {"draft", "verify"}:
        raise HTTPException(status_code=400, detail="operation must be draft or verify")
    lo, hi = _require_range(_run_config(request), since, until)
    runs = _range_dir(request, lo, hi) / ("verify_runs" if operation == "verify" else "runs")
    return project_latest(runs, f"npc-{operation}")


@router.get("/run/compose")
async def run_compose(
    request: Request,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    name: list[str] | None = Query(default=None),
    init: list[str] | None = Query(default=None),
):
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    return _sse_response(_build_compose_cmd(directory, lo, hi, names=_names(name), init=_names(init)))


@router.get("/run/publish")
async def run_publish(
    request: Request,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    select: str = "",
    name: list[str] | None = Query(default=None),
    source: str = "",
    force: bool = False,
):
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    if select not in PUBLISH_SELECTS:
        raise HTTPException(
            status_code=400,
            detail=(
                "choose what to publish: pass ?select=named (with name), ?select=all or "
                "?select=authored_all (publishing is always an explicit choice)"
            ),
        )
    names = _names(name)
    if select == "named" and not names:
        raise HTTPException(status_code=400, detail="select=named needs at least one name")
    if source and source not in npc_publish.SOURCES:
        raise HTTPException(status_code=400, detail=f"unknown source {source!r}; choose one of: {', '.join(npc_publish.SOURCES)}")
    return _sse_response(_build_publish_cmd(
        directory, lo, hi, select=select, names=names, source=source, force=force,
    ))
