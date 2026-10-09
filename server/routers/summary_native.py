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
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Query, Request

from campaignlib.players_config import PLAYERS_CONFIG_FILENAME
from campaignlib.projection_config import PROJECTION_CONFIG_FILENAME, load_projection_config
from pipelines.summary_native import annotate, audit_select, freshness, notes, resolve, schema, thread_attach
from server.grounding_config_shared import SummaryNativeRun
from server.platform_config_service import resolve_selection, selection_cli_args
from server.routers.grounding import (
    _pick,
    _service,
    _sse_response,
)
from server.subprocess_runner import console_script

_ENDPOINT_BACKENDS = frozenset({"dgx"})  # the only backend that takes --endpoints

router = APIRouter()

#: ``resolve_selection``'s ``service_name`` and the owner of the override.
_SERVICE_NAME = "summary_native"


# ── Resolution helpers ──────────────────────────────────────────────────────

def _run_config(request: Request) -> SummaryNativeRun:
    return _service(request).resolved().summary_native


def _pick_num(explicit: int | float | None, stored: int | float | None):
    """Explicit request value wins; ``None`` (not ``0``) means "not supplied".

    ``recent_chapters=0`` ("every chapter") is a meaningful value, so unlike
    ``grounding._pick`` a zero is an answer.
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
        ("key_npcs_report", state_drafts / "key_npcs_report.md"),
        ("annotations", state_drafts / annotate.REPORT_FILE),
        ("canon_events_timeline", state_drafts / schema.TIMELINE_FILE),
        ("budget_report", state_drafts / "budget_report.json"),
        ("audit", freshness.audit_dir(range_dir) / "audit.md"),
        # party and planning (spec 034)
        ("party_report", state_drafts / "party_report.md"),
        ("planning_npcs_report", state_drafts / "planning_npcs_report.md"),
        ("threads_report", state_drafts / "threads_report.md"),
        ("arc_report", state_drafts / "arc_report.md"),
        ("budget_report_party", state_drafts / schema.budget_report_file("party")),
        ("budget_report_planning", state_drafts / schema.budget_report_file("planning")),
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


def _audit_block(request: Request, run: SummaryNativeRun, lo: int, hi: int) -> dict:
    """The tracking audit's state, read from ``state/audit/`` only: counts from ``audit.json``, and
    freshness from the CLI's own check against the track files the audit was run with."""
    root = Path.cwd()
    range_dir = _range_dir(run, lo, hi)
    defaults = _default_track_files(request)
    block: dict = {"present": False, "complete": False, "stale": False, "stale_reason": None,
                   "counts": None, "audit_file": None, "track_files": defaults}
    if not freshness.audit_exists(range_dir):
        return block
    ad = freshness.audit_dir(range_dir)
    data = _read_json(ad / "audit.json")
    items = _read_json(ad / "items.json")
    if not (isinstance(data, dict) and data.get("kind") == "audit"):
        return block
    counts = data.get("counts") or audit_select.counts_of(data.get("verdicts") or [])
    block.update({
        "present": True,
        "complete": not counts.get("not_judged"),
        "counts": counts,
        "summary": audit_select.summary_line(counts),
        "backend": items.get("backend") if isinstance(items, dict) else None,
        "model": items.get("model") if isinstance(items, dict) else None,
        "candidates": items.get("candidates") if isinstance(items, dict) else None,
        "audit_file": schema.display_path(ad / "audit.md", root) if (ad / "audit.md").is_file() else None,
        # the files the audit was run with (names), which campaign_state's freshness check compares
        "track_files_run": [n for n, _ in (items.get("track_files_sha256") or [])] if isinstance(items, dict) else [],
    })
    # Stale against the configured track files, the same comparison `synth campaign_state` makes.
    reason = freshness.check_audit_fresh(range_dir, [root / t for t in defaults])
    block.update(stale=reason is not None, stale_reason=reason)
    return block


def _threads_block(request: Request, run: SummaryNativeRun, lo: int, hi: int) -> dict:
    """The ratified-thread counts of the last planning build, from ``state/threads/attach.json`` and the
    proposals file only: no model, no CLI, no summary parsing. ``present`` is false before a planning build."""
    range_dir = _range_dir(run, lo, hi)
    block: dict = {"present": False, "ratified_in_range": None, "open": None, "dormant": None,
                   "unattached": None, "ambiguous": None, "pending_groups": None}
    data = _read_json(thread_attach.threads_dir(range_dir) / thread_attach.ATTACH_FILE)
    if isinstance(data, dict) and data.get("kind") == "thread_attach":
        threads = data.get("threads") or {}
        counts = data.get("counts") or {}
        block.update(
            present=True,
            ratified_in_range=len(threads),
            open=sum(1 for t in threads.values() if t.get("open")),
            dormant=sum(1 for t in threads.values() if t.get("dormant")),
            unattached=int(counts.get("unattached", 0)),
            ambiguous=len(data.get("ambiguous") or {}),
        )
    # Group proposals the GM has not ruled on yet (the file is not range-scoped, as the Threads page shows it).
    try:
        stores = load_projection_config(_service(request).config_path_base / PROJECTION_CONFIG_FILENAME).stores
        proposals = (_read_yaml(schema.resolve_under(Path.cwd(), stores.thread_proposals)) or {}).get("proposals") or []
        block["pending_groups"] = sum(
            1 for p in proposals if isinstance(p, dict) and p.get("key") and p.get("status", "pending") == "pending")
    except (ValueError, OSError, AttributeError, TypeError):
        pass
    return block


def _read_yaml(path: Path):
    """A YAML file as data, or ``None`` when it is absent."""
    import yaml

    if not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@router.get("/state")
def get_state(request: Request, since: int | None = None, until: int | None = None):
    """What is on disk for the range, per step (read-only; files only)."""
    run = _run_config(request)
    lo, hi = _require_range(run, since, until)
    range_dir = _range_dir(run, lo, hi)
    drafts = schema.draft_dir(range_dir, "world_state")
    budgets = _read_json(drafts / "budget_report.json")
    missing = _read_json(range_dir / schema.STATE_DIR / schema.missing_dossiers_file("world_state"))
    planning_missing = _read_json(range_dir / schema.STATE_DIR / schema.missing_dossiers_file("planning"))
    return {
        "range": f"{lo}-{hi}",
        "extract": _extract_block(request, run, lo, hi),
        "audit": _audit_block(request, run, lo, hi),
        # {section: {budget, words, over}} from the last world_state build, or null
        "world_budgets": budgets if isinstance(budgets, dict) else None,
        # {doc: {later, since, unverified, removed, lines}} from each document's last annotate step
        "annotations": annotate.read_counts(drafts),
        # [{name, state}]: the selected NPCs the latest world_state build found without a usable dossier
        # ([] when none, null before any build); `missing_dossiers_refused` says whether that build stopped
        "missing_dossiers": missing.get("npcs") if isinstance(missing, dict) else None,
        "missing_dossiers_refused": bool(missing.get("refused")) if isinstance(missing, dict) else False,
        # the same for planning's NPC Dossiers (its own file: one document's refusal is not the other's)
        "planning_missing_dossiers": planning_missing.get("npcs") if isinstance(planning_missing, dict) else None,
        "planning_missing_dossiers_refused": bool(planning_missing.get("refused")) if isinstance(planning_missing, dict) else False,
        # {present, ratified_in_range, open, dormant, unattached, ambiguous, pending_groups} from the last planning build
        "threads": _threads_block(request, run, lo, hi),
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
    party_config: str = "",
    planning_config: str = "",
    audit: list[str] | None = Query(default=None),
    name: list[str] | None = Query(default=None),
    recent_chapters: int | None = None,
    recurring_min: int | None = None,
    max_tokens: int | None = None,
    dump_only: bool = False,
    force: bool = False,
    model: str | None = None,
    claude_code_effort: str | None = None,
    fallback_npc_lines: bool = False,
):
    _require_doc(doc)
    # The retired parameters are not declared (FastAPI would ignore an undeclared one), so a request carrying
    # any of them is refused here, with the CLI's words naming the replacement (spec 034 FR-024).
    for retired, refusal in schema.RETIRED_SYNTH_FLAGS.items():
        if retired in request.query_params:
            raise HTTPException(status_code=400, detail=refusal)
    run = _run_config(request)
    if fallback_npc_lines and doc not in ("world_state", "planning"):
        raise HTTPException(
            status_code=400, detail=f"--fallback-npc-lines {schema.FALLBACK_NPC_LINES_REFUSAL}, not {doc}")
    if doc == "party":
        # party selects no NPCs, so the flags that choose them are refused here with the CLI's words
        # (a party run carries neither a stored nor a schema-default value of them either).
        for flag, given in (
            ("--name", any(n.strip() for n in (name or []))),
            ("--recent-chapters", recent_chapters is not None),
            ("--recurring-min", recurring_min is not None),
        ):
            if given:
                raise HTTPException(
                    status_code=400, detail=f"{flag} does not apply to party: {schema.PARTY_SELECTION_REFUSAL}")
    # Every document is built one call per section from the checked notes; the CLI refuses these flags and
    # so does the route, with the CLI's words.
    if any(a.strip() for a in (audit or [])):
        raise HTTPException(
            status_code=400,
            detail=schema.STATE_AUDIT_REFUSAL if doc == "campaign_state"
            else f"--audit applies to campaign_state only, not {doc}",
        )
    if doc == "campaign_state" and any(n.strip() for n in (name or [])):
        raise HTTPException(
            status_code=400, detail="--name does not apply to campaign_state: it has no Key NPCs section")
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    cmd = _base_cmd("synth", doc, directory, lo, hi)

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

    # campaign_state has no Key NPCs section and party selects no NPCs, so the CLI refuses the selection flags for them
    if doc not in ("campaign_state", "party"):
        cmd += ["--recent-chapters", str(_pick_num(recent_chapters, run.recent_chapters))]
        cmd += ["--recurring-min", str(_pick_num(recurring_min, run.recurring_min))]
    if max_tokens is not None:
        cmd += ["--max-tokens", str(max_tokens)]
    if dump_only:
        cmd.append("--dump-only")
    if force:
        cmd.append("--force")
    if fallback_npc_lines:  # per run, never from config
        cmd.append("--fallback-npc-lines")

    # The prose step has its own backend/model block (grounding.yaml summary_native.prose).
    cmd += selection_cli_args(resolve_selection(
        request, request_model=model, service=run.prose, service_name=f"{_SERVICE_NAME}.prose",
        request_claude_code_effort=(claude_code_effort or "").strip() or None,
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
    endpoints: list[str] | None = Query(default=None),
    parallel: int | None = None,
):
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    urls = [e.strip() for e in (endpoints or []) if e.strip()]
    if parallel is not None and parallel < 1:
        raise HTTPException(status_code=400, detail=f"parallel must be at least 1, got {parallel}")
    cmd = _base_cmd("extract", None, directory, lo, hi)
    cmd += ["--chunk-chars", str(_pick_num(chunk_chars, run.extract.chunk_chars))]
    if max_tokens is not None:
        cmd += ["--max-tokens", str(max_tokens)]
    if dump_only:
        cmd.append("--dump-only")
    if force:
        cmd.append("--force")
    # Endpoints are machine wiring, never stored in grounding.yaml: a request value rides on top of
    # the stored backend/model and reaches the command as `--endpoints A B` (the CLI's own spelling).
    service = run.extract
    if urls:
        service = SimpleNamespace(backend=run.extract.backend, model=run.extract.model, endpoints=tuple(urls))
    resolved = resolve_selection(
        request, request_model=model, service=service, service_name=f"{_SERVICE_NAME}.extract",
    )
    if urls and resolved.backend not in _ENDPOINT_BACKENDS:
        raise HTTPException(status_code=400, detail=f"--endpoints applies to --backend dgx only, not {resolved.backend}")
    cmd += selection_cli_args(resolved)
    if parallel is not None:
        cmd += ["--parallel", str(parallel)]
    return _sse_response(cmd)


@router.get("/run/audit")
async def run_audit(
    request: Request,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    track_file: list[str] | None = Query(default=None),
    candidates: int | None = None,
    max_tokens: int | None = None,
    dump_only: bool = False,
    force: bool = False,
    model: str | None = None,
    endpoints: list[str] | None = Query(default=None),
    parallel: int | None = None,
):
    """The tracking audit. Its judge uses the extraction backend family (``summary_native.extract``) and
    the same endpoint wiring as ``/run/extract``; ``track_file`` repeats ``--track-file`` and, when
    absent, the CLI reads ``grounding.yaml campaign_state.track_files`` itself."""
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    urls = [e.strip() for e in (endpoints or []) if e.strip()]
    files = [t.strip() for t in (track_file or []) if t.strip()]
    if parallel is not None and parallel < 1:
        raise HTTPException(status_code=400, detail=f"parallel must be at least 1, got {parallel}")
    if candidates is not None and candidates < 1:
        raise HTTPException(status_code=400, detail=f"candidates must be at least 1, got {candidates}")
    if not files and not _default_track_files(request):
        raise HTTPException(
            status_code=400,
            detail="no track files: pass ?track_file= or set grounding.yaml campaign_state.track_files",
        )
    cmd = _base_cmd("audit", None, directory, lo, hi)
    for f in files:
        cmd += ["--track-file", f]
    if candidates is not None:
        cmd += ["--candidates", str(candidates)]
    if max_tokens is not None:
        cmd += ["--max-tokens", str(max_tokens)]
    if dump_only:
        cmd.append("--dump-only")
    if force:
        cmd.append("--force")
    service = run.extract
    if urls:
        service = SimpleNamespace(backend=run.extract.backend, model=run.extract.model, endpoints=tuple(urls))
    resolved = resolve_selection(
        request, request_model=model, service=service, service_name=f"{_SERVICE_NAME}.extract",
    )
    if urls and resolved.backend not in _ENDPOINT_BACKENDS:
        raise HTTPException(status_code=400, detail=f"--endpoints applies to --backend dgx only, not {resolved.backend}")
    cmd += selection_cli_args(resolved)
    if parallel is not None:
        cmd += ["--parallel", str(parallel)]
    return _sse_response(cmd)


def _default_track_files(request: Request) -> list[str]:
    """``grounding.yaml campaign_state.track_files``: the audit's default."""
    return list(_service(request).resolved().campaign_state.track_files)


@router.get("/run/annotate/{doc}")
async def run_annotate(
    request: Request,
    doc: str,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    dry_run: bool = False,
):
    _require_doc(doc)
    if doc not in schema.STATE_DOCS:
        raise HTTPException(
            status_code=400,
            detail=f"annotate applies to {' and '.join(schema.STATE_DOCS)} only, not {doc}",
        )
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    cmd = _base_cmd("annotate", doc, directory, lo, hi)
    if dry_run:
        cmd.append("--dry-run")
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
