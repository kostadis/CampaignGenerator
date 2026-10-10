"""Draft one dossier per selected global NPC (spec 032 T022-T024, research R8/R9).

This is the ONLY 032 module that calls a model, and only through ``campaignlib``
(``client_from_args``, ``stream_api``), exactly as ``synth`` does. The model renders
inside a structure the GM already reviewed: the evidence dossier written by ``npc-link``,
the numbered Manual edits, and a fixed outline. Its output is checked against the outline
and is never written as a draft unless complete.

Secrets never reach a prompt, structurally: authored data is read only through
``npc_authored.load_manual`` (via ``_load_manuals``), which cannot return ``secrets``. This
module never opens an authored file itself (guarded by ``tests/test_npc_draft_no_secrets.py``).

Selection reads ``global`` / ``exclusion`` from the evidence frontmatter ``npc-link`` wrote;
it does not recompute them.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from campaignlib import client_from_args, stream_api
from campaignlib.api.client import resolve_cli_model
from campaignlib.util import atomic_write_text
from pipelines.summary_native import context, corpus, npc_authored, npc_check, npc_chunked, npc_compose, npc_forms
from pipelines.summary_native import npc_link, npc_slug, npc_verify, schema, select, synth, validate
from pipelines.summary_native.freshness import check_fresh, check_link_fresh, manual_sha, sha_file as _sha_file
from pipelines.summary_native.scheduler import EndpointState, Scheduler, SchedulerResult, WorkItem

EXIT_REFUSED = synth.EXIT_REFUSED
EXIT_INCOMPLETE = synth.EXIT_INCOMPLETE
EXIT_MODEL_FAILED = synth.EXIT_MODEL_FAILED
EXIT_BLOCKING = synth.EXIT_BLOCKING

DRAFT_DIR = "draft"
GM_DIR = "gm"
RUNS_DIR = "runs"
INDEX_FILE = "index.json"
NOT_IN_RANGE = "no evidence in range"
NARROWED_OUT = "narrowed out"


class DraftRefusal(Exception):
    """A request that cannot be honoured (CLI exit 2); the message is user-facing."""


#: Raised by the Manual-edit reader for a malformed or mismatched file. Aliased under a
#: neutral name so the loop below never mentions authored data (guard tests read it that way).
ManualEditError = npc_authored.AuthoredError


# ── Selection (T022) ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DraftSelection:
    range: str
    mode: str  # "all" | "narrowed"
    named: tuple[str, ...]
    recent_chapters: int | None
    recurring_min: int | None
    included: tuple[dict, ...]  # {stem, subject, reason}
    excluded: tuple[dict, ...]  # {stem|name, reason}

    def to_json(self) -> str:
        data = {
            "range": self.range,
            "mode": self.mode,
            "named": list(self.named),
            "recent_chapters": self.recent_chapters,
            "recurring_min": self.recurring_min,
            "included": list(self.included),
            "excluded": list(self.excluded),
        }
        return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def exclusion_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.excluded:
            counts[e["reason"]] = counts.get(e["reason"], 0) + 1
        return dict(sorted(counts.items()))


def select_global(
    evidence: list[npc_link.EvidenceFile],
    named: tuple[str, ...] | list[str] = (),
    recent_chapters: int | None = None,
    recurring_min: int | None = None,
    all_flag: bool = False,
    *,
    range_until: int,
    range_text: str,
    registry_npcs: tuple[str, ...] = (),
    registry_aliases: dict[str, str] | None = None,
    default_recent: int = schema.DEFAULT_RECENT_CHAPTERS,
    default_recurring: int = schema.DEFAULT_RECURRING_MIN,
) -> DraftSelection:
    """Choose the global NPCs to draft and record why every other NPC is out.

    With no narrowing flag the mode is ``all``. ``named`` alone takes exactly those NPCs;
    ``recent_chapters`` / ``recurring_min`` apply 031's ``select_dossiers`` rules (recent or
    recurring, plus any named) within the global NPCs. ``registry_npcs`` are the registry's
    NPC names; one with no evidence dossier is excluded ``no evidence in range``.
    ``registry_aliases`` maps a casefolded exact registry alias to its canonical name, so
    ``--name Ilvara`` finds ``Ilvara Mizzrym``; nothing is guessed beyond that.
    Raises ``DraftRefusal`` for ``--all`` with a narrowing flag, an ineligible name, or an
    empty selection.
    """
    named = tuple(named)
    narrowing = bool(named) or recent_chapters is not None or recurring_min is not None
    if all_flag and narrowing:
        raise DraftRefusal("--all cannot be combined with --name, --recent-chapters or --recurring-min")
    by_subject = {e.subject.casefold(): e for e in evidence}
    globals_ = [e for e in evidence if e.global_]

    chosen: dict[str, str] = {}  # stem -> reason
    if not narrowing:
        chosen = {e.stem: "all" for e in globals_}
    else:
        aliases = registry_aliases or {}
        for name in named:
            key = name.strip().casefold()
            e = by_subject.get(key) or by_subject.get(aliases.get(key, "").casefold())
            if e is None:
                canon = aliases.get(key, name.strip())
                reason = NOT_IN_RANGE if any(r.casefold() == canon.casefold() for r in registry_npcs) else "not in registry"
                raise DraftRefusal(f"--name {name}: not a global NPC ({reason})")
            if not e.global_:
                raise DraftRefusal(f"--name {name}: not a global NPC ({e.exclusion})")
            chosen.setdefault(e.stem, "named")
        if recent_chapters is not None or recurring_min is not None:
            dossiers = [
                select.Dossier(e.stem, e.subject, "npc", e.n_entries, e.first_seen, e.last_seen, e.path)
                for e in globals_
            ]
            sel = select.select_dossiers(
                dossiers,
                range_until,
                default_recent if recent_chapters is None else recent_chapters,
                default_recurring if recurring_min is None else recurring_min,
                (),
            )
            for item in sel.items:
                chosen.setdefault(item.dossier.stem, item.reason)

    have = {e.subject.casefold() for e in evidence}
    excluded: list[dict] = []
    for e in evidence:
        if not e.global_:
            excluded.append({"stem": e.stem, "reason": e.exclusion or "not global"})
        elif e.stem not in chosen:
            excluded.append({"stem": e.stem, "reason": NARROWED_OUT})
    for r in sorted(set(registry_npcs)):
        if r.casefold() not in have:
            excluded.append({"name": r, "reason": NOT_IN_RANGE})
    included = [
        {"stem": e.stem, "subject": e.subject, "reason": chosen[e.stem]} for e in evidence if e.stem in chosen
    ]
    selection = DraftSelection(
        range=range_text,
        mode="narrowed" if narrowing else "all",
        named=named,
        recent_chapters=recent_chapters,
        recurring_min=recurring_min,
        included=tuple(included),
        excluded=tuple(sorted(excluded, key=lambda d: (d["reason"], d.get("stem") or d.get("name") or ""))),
    )
    if not included:
        counts = ", ".join(f"{n} {r}" for r, n in selection.exclusion_counts().items()) or "no NPCs at all"
        raise DraftRefusal(f"the selection is empty ({counts})")
    return selection


# ── Prompts (T023) ──────────────────────────────────────────────────────────


def load_system() -> str:
    return (context.PROMPT_DIR / f"{schema.NPC_OUTLINE}.system.md").read_text(encoding="utf-8")


def build_prompt(evidence_md: str, header: str, manual: list[str], headings: list[str] | None = None) -> tuple[str, str]:
    """``(system, user)``. ``evidence_md`` is the evidence body verbatim; ``header`` the
    computed header block shown as read-only context; ``manual`` the numbered edits."""
    headings = headings if headings is not None else synth.load_outline(schema.NPC_OUTLINE)
    edits = "\n".join(f"[manual {n}] {text}" for n, text in enumerate(manual, 1)) if manual else "(none)"
    user = (
        "READ-ONLY HEADER (computed from the evidence; context only, do not copy or restate it):\n\n"
        f"{header}\n"
        "EVIDENCE (verbatim; every item names the NPC; a mention is not a presence):\n\n"
        f"{evidence_md}\n"
        "GM MANUAL EDITS:\n\n"
        f"{edits}\n\n"
        "OUTLINE: write exactly these `##` sections, in this order, and nothing else at that level:\n\n"
        + "\n".join(headings)
        + "\n"
    )
    return load_system(), user


def draft_key(
    system: str, user: str, backend: str, model: str, max_tokens: int, mode: str = "one-shot", chunk_chars: int | None = None
) -> str:
    """Hash of everything that decides a draft. In chunked mode ``system`` and ``user`` stand for
    every map prompt plus the reduce system prompt (see ``chunked_key_inputs``)."""
    sha = lambda t: hashlib.sha256(t.encode("utf-8")).hexdigest()  # noqa: E731
    payload = {
        "system_sha": sha(system),
        "user_sha": sha(user),
        "backend": backend,
        "model": model,
        "max_tokens": max_tokens,
        "mode": mode,
        "chunk_chars": chunk_chars,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def chunked_key_inputs(map_prompts: list[tuple[str, str]], reduce_system: str, headings: list[str]) -> tuple[str, str]:
    """``(system, user)`` for ``draft_key``: the map and reduce system prompts and every map user prompt."""
    system = npc_chunked.load_map_system() + "\n--reduce--\n" + reduce_system + "\n--outline--\n" + "\n".join(headings)
    return system, "\n--chunk--\n".join(u for _, u in map_prompts)


def strip_model_header(text: str) -> tuple[str, bool]:
    """Drop anything before the first ``## `` line (a title, front matter, a comment, chatter).

    The header is inserted by code (FR-015); a model-written one is removed and reported.
    """
    lines = text.splitlines(keepends=True)
    first = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), None)
    if first is None or first == 0:
        return text, False
    if not "".join(lines[:first]).strip():
        return "".join(lines[first:]), False
    return "".join(lines[first:]), True


def render_part(client, system: str, user: str, model: str, max_tokens: int) -> str:
    """The one model call in this module. Silent: callers print one progress line per call
    instead of streaming the model's text to stdout."""
    return stream_api(client, system, user, model, max_tokens=max_tokens, silent=True)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _refuse(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return EXIT_REFUSED


def _load_manuals(root: Path, selected: list[dict]) -> dict[str, list[str]]:
    """``{stem: manual edits}`` for the selected NPCs. The one place authored data is read,
    and only the Manual edits (``load_manual``); a missing file means none."""
    return {
        s["stem"]: npc_authored.load_manual(npc_compose.authored_path_for(root, s["subject"]), s["subject"])
        for s in selected
    }


def _check_slugs(selected: list[dict]) -> None:
    clash = npc_slug.slug_collisions([s["subject"] for s in selected])
    if clash:
        parts = [f"{slug}: {', '.join(names)}" for slug, names in clash.items()]
        raise DraftRefusal(
            "two selected NPCs share a slug and would share one authored file; drafting refused for both ("
            + "; ".join(parts)
            + ")"
        )


def _read_index(draft_dir: Path) -> dict:
    p = draft_dir / INDEX_FILE
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _dumps(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _attempts_json(attempts: list) -> list[dict]:
    """Make nested scheduler failure envelopes safe for the durable JSON record."""
    return [asdict(attempt) for attempt in attempts]


def _new_run_dir(runs_root: Path, stamp: str) -> Path:
    return synth._new_run_dir(runs_root, stamp)


def _healthy_endpoints(endpoints: list[str], model: str | None) -> tuple[list[str], list[str]]:
    """Late import keeps the NPC model boundary independent of extract internals."""
    from pipelines.summary_native.extract import healthy_endpoints
    return healthy_endpoints(endpoints, model)


@dataclass
class _RemoteDispatch:
    """Operation-owned adapter over the shared endpoint scheduler.

    The scheduler owns endpoint assignment and failover.  This adapter owns the
    already-resolved clients and deliberately exposes values only by stable work
    item id, so draft assembly never follows completion order.
    """

    scheduler: Scheduler
    clients: dict[str, object]
    attempts: list = field(default_factory=list)
    serial: bool = False
    probe: object | None = None

    def run(self, items: list[WorkItem], render):
        if self.serial:
            result = SchedulerResult()
            for item in items:
                partial = self.scheduler.run([item], lambda candidate, endpoint: render(candidate, self.clients[endpoint]))
                result.values.update(partial.values)
                result.failures.update(partial.failures)
                result.attempts.extend(partial.attempts)
                if partial.failures:
                    break
        else:
            result = self.scheduler.run(items, lambda item, endpoint: render(item, self.clients[endpoint]), probe=self.probe)
        self.attempts.extend(result.attempts)
        return result


def _remote_dispatch(args) -> _RemoteDispatch:
    configured = list(dict.fromkeys(getattr(args, "endpoints", None) or ()))
    if configured:
        healthy, _quarantined = _healthy_endpoints(configured, args.model)
        if not healthy:
            raise DraftRefusal("no healthy endpoint")
        clients = {endpoint: client_from_args(args, endpoint=endpoint) for endpoint in healthy}
        limit = getattr(getattr(args, "concurrency", None), "value", getattr(args, "parallel", None) or 1)
    else:
        # A single implicit backend client retains the historical call order.
        # Explicit endpoint sets use the resolved independent endpoint bound.
        clients = {"default": client_from_args(args)}
        limit = 1
    def probe(endpoint):
        raw = endpoint.url or endpoint.endpoint_id
        return bool(_healthy_endpoints([raw], args.model)[0])
    return _RemoteDispatch(
        Scheduler([EndpointState(endpoint, limit, url=endpoint) for endpoint in clients]), clients,
        serial=not configured, probe=probe if configured else None,
    )


def _resume_draft_record(npc_range_dir: Path, requested: str, selection: DraftSelection, keys: dict[str, str], args) -> tuple[Path, dict]:
    """Select one compatible NPC draft journal without treating it as completion truth."""
    records: list[tuple[Path, dict]] = []
    for path in sorted((npc_range_dir / RUNS_DIR).glob("*/record.json"), reverse=True):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if value.get("operation", "npc-draft") != "npc-draft":
            continue
        records.append((path, value))
    if requested:
        records = [(path, value) for path, value in records if value.get("run_id") == requested]
        if len(records) != 1:
            raise DraftRefusal(f"no compatible NPC draft run named {requested!r}")
    else:
        records = [(path, value) for path, value in records if value.get("status") in {"running", "incomplete", "interrupted"}]
        if len(records) != 1:
            raise DraftRefusal("resume requires exactly one compatible incomplete NPC draft run; pass --resume RUN_ID")
    path, record = records[0]
    selected = [entry["stem"] for entry in selection.included]
    if record.get("range") != {"since": int(selection.range.split("-")[0]), "until": int(selection.range.split("-")[1])}:
        raise DraftRefusal("resume run has a different chapter range")
    if record.get("backend") != resolve_cli_model(args, legacy_default=None).backend or record.get("model") != args.model:
        raise DraftRefusal("resume run has a different backend or model")
    if record.get("mode") != args.mode or record.get("chunk_chars") != (args.chunk_chars if args.mode == "chunked" else None):
        raise DraftRefusal("resume run has different draft options")
    if list(record.get("npcs", {})) != selected or any(record["npcs"][stem].get("draft_key") != keys[stem] for stem in selected):
        raise DraftRefusal("resume run selection or inputs are stale")
    return path, record


# ── The draft loop (T024) ───────────────────────────────────────────────────


@dataclass
class _Outcome:
    status: str
    problems: list[str] = field(default_factory=list)


def run_draft(
    args,
    *,
    root: Path,
    range_dir: Path,
    npc_range_dir: Path,
    report: validate.ValidationReport,
    registry_path: Path | None,
    canon_path: Path | None,
    players_path: Path | None = None,
    registry_npcs: tuple[str, ...] = (),
    registry_aliases: dict[str, str] | None = None,
    recent_chapters: int | None,
    recurring_min: int | None,
    default_recent: int = schema.DEFAULT_RECENT_CHAPTERS,
    default_recurring: int = schema.DEFAULT_RECURRING_MIN,
    now=None,
) -> int:
    now = now or _utcnow
    if report.blocking_count:
        print(report.to_markdown(), end="")
        print("validation has blocking problems; fix the summaries, then build --force", file=sys.stderr)
        return EXIT_BLOCKING
    if registry_path is None:
        return _refuse(
            "no global NPCs are declared (no entity registry found); build a registry with "
            "`registry init` / `registry import-inventory`"
        )
    try:
        manifest = corpus.load_manifest(range_dir, require_complete=True)
    except corpus.CorpusError as e:
        return _refuse(f"{e}; run `summary_native build`")
    stale = check_fresh(report, range_dir, root, manifest, registry_path)
    if stale:
        return _refuse(stale)

    evidence = npc_link.read_evidence_files(npc_range_dir)
    link_problem = check_link_fresh(
        npc_range_dir, range_dir, registry_path, canon_path, {e.stem: e.sha256 for e in evidence}, players_path
    )
    if link_problem:
        return _refuse(link_problem)

    since, until = int(manifest["range"]["since"]), int(manifest["range"]["until"])
    try:
        selection = select_global(
            evidence,
            tuple(args.name or ()),
            recent_chapters,
            recurring_min,
            bool(args.all),
            range_until=until,
            range_text=f"{since}-{until}",
            registry_npcs=registry_npcs,
            registry_aliases=registry_aliases,
            default_recent=default_recent,
            default_recurring=default_recurring,
        )
        selected = [dict(s) for s in selection.included]
        _check_slugs(selected)
        manuals = _load_manuals(root, selected)
    except (DraftRefusal, ManualEditError) as e:
        return _refuse(str(e))

    by_stem = {e.stem: e for e in evidence}
    headings = synth.load_outline(schema.NPC_OUTLINE)
    template_sha = corpus.sha256_file(context.PROMPT_DIR / f"{schema.NPC_OUTLINE}.outline.yaml")
    backend = resolve_cli_model(args, legacy_default=None).backend
    mode, chunk_chars = args.mode, args.chunk_chars
    chunked = mode == "chunked"
    prompts: dict[str, tuple[str, str]] = {}  # one-shot: stem -> (system, user)
    chunk_plan: dict[str, list] = {}  # chunked: stem -> chunks (lists of Chapter)
    map_prompts: dict[str, list[tuple[str, str]]] = {}
    keys: dict[str, str] = {}
    reduce_system = npc_chunked.load_reduce_system() if chunked else ""
    for s in selected:
        ev = by_stem[s["stem"]]
        if chunked:
            chunks = npc_chunked.make_chunks(npc_check.split_chapters(ev.body), chunk_chars)
            chunk_plan[s["stem"]] = chunks
            map_prompts[s["stem"]] = [npc_chunked.map_prompt(s["subject"], c, manuals[s["stem"]]) for c in chunks]
            system, user = chunked_key_inputs(map_prompts[s["stem"]], reduce_system, headings)
        else:
            system, user = build_prompt(ev.body, ev.header, manuals[s["stem"]], headings)
            prompts[s["stem"]] = (system, user)
        keys[s["stem"]] = draft_key(system, user, backend, args.model, args.max_tokens, mode, chunk_chars if chunked else None)

    started = now()
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    run_dir = npc_range_dir / RUNS_DIR / run_id

    record = {
        "run_id": run_id,
        "operation": "npc-draft",
        "status": "running",
        "range": {"since": since, "until": until},
        "backend": backend,
        "model": args.model,
        "mode": mode,
        "chunk_chars": chunk_chars if chunked else None,
        "max_tokens": args.max_tokens,
        "corpus_manifest_sha256": corpus.sha256_file(range_dir / "manifest.json"),
        "link_manifest_sha256": corpus.sha256_file(npc_range_dir / npc_link.LINK_MANIFEST),
        "registry_sha256": _sha_file(registry_path),
        "canon_sha256": _sha_file(canon_path),
        "wordlist_sha256": npc_forms.load_wordlist()[1],
        "template_sha256": template_sha,
        "prompt_sha256": {
            "one_shot": corpus.sha256_file(context.PROMPT_DIR / f"{schema.NPC_OUTLINE}.system.md"),
            "map": corpus.sha256_file(context.PROMPT_DIR / f"{schema.NPC_OUTLINE}.map.system.md"),
            "reduce": corpus.sha256_file(context.PROMPT_DIR / f"{schema.NPC_OUTLINE}.reduce.system.md"),
        },
        "selection": "selection.json",
        "npcs": {
            stem: {
                "draft_key": keys[stem],
                "evidence_sha256": by_stem[stem].sha256,
                "manual_sha256": manual_sha(manuals[stem]),
                "status": "pending",
                "problems": [],
            }
            for stem in keys
        },
        "started": started.isoformat(timespec="seconds"),
        "finished": None,
        "stopped_at": None,
    }

    if args.resume is not None:
        try:
            path, record = _resume_draft_record(npc_range_dir, args.resume, selection, keys, args)
        except DraftRefusal as e:
            return _refuse(str(e))
        run_dir, run_id = path.parent, record["run_id"]
    else:
        run_dir = _new_run_dir(npc_range_dir / RUNS_DIR, run_id)
        run_id = run_dir.name
        record["run_id"] = run_id
        atomic_write_text(run_dir / "selection.json", selection.to_json())
        for stem, (system, user) in prompts.items():
            atomic_write_text(run_dir / f"{stem}.system.md", system)
            atomic_write_text(run_dir / f"{stem}.user.md", user)
        for stem, mps in map_prompts.items():
            for n, (system, user) in enumerate(mps, 1):
                atomic_write_text(run_dir / f"{stem}.map{n:02d}.system.md", system)
                atomic_write_text(run_dir / f"{stem}.map{n:02d}.user.md", user)

    def save_record() -> None:
        atomic_write_text(run_dir / "record.json", _dumps(record))

    if args.dump_only:
        for n in record["npcs"].values():
            n["status"] = "dump-only"
        record["finished"] = now().isoformat(timespec="seconds")
        save_record()
        print(f"[--dump-only: prompts written to {run_dir}; no model call]")
        return 0

    draft_dir = npc_range_dir / DRAFT_DIR
    index = _read_index(draft_dir)
    todo = [
        s["stem"] for s in selected
        if args.force or index.get(s["stem"], {}).get("draft_key") != keys[s["stem"]]
        or not (draft_dir / f"{s['stem']}.md").is_file()
    ]
    dispatcher = None
    if todo:
        try:
            dispatcher = _remote_dispatch(args)
        except SystemExit as e:
            msg = str(e.code) if isinstance(e.code, str) else f"backend setup failed (exit {e.code})"
            record["stopped_at"] = {"error": msg}
            record["finished"] = now().isoformat(timespec="seconds")
            save_record()
            return _refuse(msg)
        except (ValueError, RuntimeError, ImportError) as e:
            record["stopped_at"] = {"error": str(e)}
            record["finished"] = now().isoformat(timespec="seconds")
            save_record()
            return _refuse(str(e))

    # Materialize the entire selected remote operation before any call.  These
    # identities are persisted as observability data; draft files remain the
    # authority for completion.
    work_items: list[WorkItem] = []
    if chunked:
        ordinal = 0
        for s in selected:
            stem = s["stem"]
            if stem not in todo:
                continue
            for n, _chunk in enumerate(chunk_plan[stem], 1):
                work_items.append(WorkItem(f"{stem}:map:{n:03d}", ordinal, "npc-draft", keys[stem]))
                ordinal += 1
            work_items.append(WorkItem(f"{stem}:reduce", ordinal, "npc-draft", keys[stem]))
            ordinal += 1
    else:
        work_items = [WorkItem(s["stem"], n, "npc-draft", keys[s["stem"]]) for n, s in enumerate(selected) if s["stem"] in todo]
    record["work_items"] = [
        {"item_id": item.item_id, "ordinal": item.ordinal, "operation": item.operation,
         "compatibility_key": item.compatibility_key}
        for item in work_items
    ]

    outcomes: dict[str, _Outcome] = {}
    verify_ctx = None
    verify_json: dict[str, dict] = {}
    exit_code = 0
    one_shot_outputs: dict[str, str] = {}
    one_shot_failures = {}
    if todo and not chunked:
        assert dispatcher is not None
        result = dispatcher.run(
            work_items,
            lambda item, client: render_part(client, prompts[item.item_id][0], prompts[item.item_id][1], args.model, args.max_tokens),
        )
        record["attempts"] = _attempts_json(dispatcher.attempts)
        record["endpoints"] = [e.__dict__ for e in dispatcher.scheduler.endpoints]
        one_shot_outputs = result.values
        one_shot_failures = result.failures
    for s in selected:
        stem, subject = s["stem"], s["subject"]
        if stem not in todo:
            outcomes[stem] = _Outcome("skipped-unchanged")
            record["npcs"][stem]["status"] = "skipped-unchanged"
            print(f"{subject}: skipped (unchanged)")
        else:
            try:
                if chunked:
                    out, detail = _draft_chunked(
                        dispatcher, subject, stem, by_stem[stem], manuals[stem], chunk_plan[stem], map_prompts[stem],
                        reduce_system, headings, args, run_dir,
                    )
                    record["npcs"][stem]["chunked"] = detail
                else:
                    if stem in one_shot_failures:
                        raise _CallFailed("draft", RuntimeError(one_shot_failures[stem].message))
                    out = one_shot_outputs[stem]
                    print(f"{subject}: draft 0.0s", flush=True)
            except Exception as e:
                stage = getattr(e, "stage", None)
                record["npcs"][stem]["status"] = "failed"
                record["stopped_at"] = {"stem": stem, "error": f"{type(e).__name__}: {e}"}
                if stage:
                    record["stopped_at"] = {"stem": stem, "stage": stage, "error": str(e)}
                if dispatcher is not None:
                    record["attempts"] = _attempts_json(dispatcher.attempts)
                    record["endpoints"] = [endpoint.__dict__ for endpoint in dispatcher.scheduler.endpoints]
                record["status"] = "incomplete"
                record["finished"] = now().isoformat(timespec="seconds")
                save_record()
                print(f"{subject}: failed", file=sys.stderr)
                print(
                    f"Error: model call failed for {subject}{' at ' + stage if stage else ''}: "
                    f"{e if stage else f'{type(e).__name__}: {e}'} "
                    f"(see {schema.display_path(run_dir / 'record.json', root)})",
                    file=sys.stderr,
                )
                return EXIT_MODEL_FAILED
            atomic_write_text(run_dir / f"{stem}.out.md", out)  # chunked: the assembled body
            body, stripped = strip_model_header(out)
            if stripped:
                print(f"warning: {subject}: the model wrote its own header; stripped (the header is computed)", file=sys.stderr)
            problems = synth.check_outline(body if body.endswith("\n") else body + "\n", headings)
            record["npcs"][stem]["problems"] = problems
            ev = by_stem[stem]
            rng_name = f"ch{since:03d}-{until:03d}"
            draft_dir.mkdir(parents=True, exist_ok=True)
            if problems:
                prov = (
                    f"<!-- summary_native npc draft INCOMPLETE | npc: {subject} | range: {rng_name} "
                    f"| run: {run_id} -->\n"
                )
                atomic_write_text(draft_dir / f"{stem}.incomplete.md", prov + ev.header + "\n" + body)
                outcomes[stem] = _Outcome("incomplete", problems)
                record["npcs"][stem]["status"] = "incomplete"
                missing = "; ".join(problems)
                print(f"{subject}: incomplete (missing: {missing})")
                exit_code = EXIT_INCOMPLETE
            else:
                prov = (
                    f"<!-- summary_native npc draft | npc: {subject} | range: {rng_name} | run: {run_id} "
                    f"| draft_key: {keys[stem]} | manual sha256: {record['npcs'][stem]['manual_sha256']} "
                    f"| model: {args.model} | backend: {backend} -->\n"
                )
                body = body if body.endswith("\n") else body + "\n"
                atomic_write_text(draft_dir / f"{stem}.md", prov + ev.header + "\n" + body)
                (draft_dir / f"{stem}.incomplete.md").unlink(missing_ok=True)
                index[stem] = {"draft_key": keys[stem], "run_id": run_id}
                atomic_write_text(draft_dir / INDEX_FILE, _dumps(index))
                outcomes[stem] = _Outcome("drafted")
                record["npcs"][stem]["status"] = "drafted"
                print(f"{subject}: drafted")
        if outcomes[stem].status in ("drafted", "skipped-unchanged") and (draft_dir / f"{stem}.md").is_file():
            if verify_ctx is None:
                verify_ctx = npc_verify.load_context(root, report)
            result = npc_verify.verify_draft(draft_dir, stem, subject, by_stem[stem], manuals[stem], verify_ctx)
            verify_json[stem] = result.to_dict()
            record["npcs"][stem]["verify"] = {"verdict": result.verdict, "counts": result.counts}
            print(f"  verify: {result.summary_line()}")
            for m in result.manual:
                if not m.cited:
                    print(f'warning: {subject}: manual edit {m.n} dropped \u2014 "{m.text}"', file=sys.stderr)
        _compose(root, npc_range_dir, stem, subject)
    verdicts = [v["verdict"] for v in verify_json.values()]
    failed = verdicts.count(npc_verify.FAIL)
    detail = ""
    if failed:
        totals = {k: sum(v["counts"].get(k, 0) for v in verify_json.values()) for k in npc_verify.FAIL_CODES}
        detail = " (" + ", ".join(f"{k} {n}" for k, n in totals.items() if n) + ")"
    print(f"verified {len(verdicts)} drafts: {len(verdicts) - failed} pass, {failed} fail{detail}")
    record["finished"] = now().isoformat(timespec="seconds")
    record["status"] = "completed" if exit_code == 0 else "incomplete"
    if dispatcher is not None:
        record["attempts"] = _attempts_json(dispatcher.attempts)
        record["endpoints"] = [e.__dict__ for e in dispatcher.scheduler.endpoints]
    save_record()
    if verify_json:
        atomic_write_text(run_dir / "verify.json", _dumps(verify_json))
    return exit_code


# ── Chunked drafting (T062) ─────────────────────────────────────────────────


class _CallFailed(Exception):
    """A map or reduce call failed; ``stage`` says which (``map03``, ``reduce``)."""

    def __init__(self, stage: str, cause: BaseException):
        super().__init__(f"{type(cause).__name__}: {cause}")
        self.stage = stage


def _timed_call(client, stage: str, system: str, user: str, args, label: str = "") -> tuple[str, float]:
    """One model call; prints ``<label> <secs>s`` when it returns (e.g. ``Jimjar: map 3/6 (ch 016-027) 34.6s``)."""
    t0 = time.monotonic()
    try:
        out = render_part(client, system, user, args.model, args.max_tokens)
    except Exception as e:  # noqa: BLE001 - any backend error is a model failure (exit 4)
        raise _CallFailed(stage, e) from e
    secs = time.monotonic() - t0
    if label:
        print(f"{label} {secs:.1f}s", flush=True)
    return out, secs


def _draft_chunked(
    dispatcher: _RemoteDispatch, subject: str, stem: str, ev, manual: list[str], chunks: list, map_prompts: list[tuple[str, str]],
    reduce_system: str, headings: list[str], args, run_dir: Path,
) -> tuple[str, dict]:
    """Map calls, code check, stitch, reduce call, assembly. Returns ``(assembled body, detail)``.

    Run files: ``<stem>.mapNN.out.md``, ``<stem>.reduce.{system,user,out}.md``, ``<stem>.drops.md``.
    """
    results, per_chunk, detail_chunks = [], [], []
    map_items = [WorkItem(f"{stem}:map:{n:03d}", n - 1, "npc-draft") for n in range(1, len(chunks) + 1)]
    mapped = dispatcher.run(
        map_items,
        lambda item, client: render_part(client, *map_prompts[item.ordinal], args.model, args.max_tokens),
    )
    if mapped.failures:
        failed = next(item for item in map_items if item.item_id in mapped.failures)
        raise _CallFailed(f"map{failed.ordinal + 1:02d}", RuntimeError(mapped.failures[failed.item_id].message))
    for n, (chunk, _prompt) in enumerate(zip(chunks, map_prompts), 1):
        raw = mapped.values[f"{stem}:map:{n:03d}"]
        secs = 0.0
        print(f"{subject}: map {n}/{len(chunks)} (ch {npc_chunked.chunk_range(chunk)}) {secs:.1f}s", flush=True)
        atomic_write_text(run_dir / f"{stem}.map{n:02d}.out.md", raw)
        res = npc_chunked.check_map(raw, npc_check.EvidenceIndex.of(chunk), len(manual))
        results.append(res)
        rng = npc_chunked.chunk_range(chunk)
        per_chunk.append((rng, res))
        detail_chunks.append({"n": n, "chapters": rng, "chars": len(npc_chunked.chunk_text(chunk)), "secs": round(secs, 1), **res.counts()})
    atomic_write_text(run_dir / f"{stem}.drops.md", npc_chunked.render_drops_md(subject, per_chunk))
    stitched = npc_chunked.stitch(results)
    detail = {"chunks": detail_chunks, "stitched": {h: len(v) for h, v in stitched.items()}}
    if not chunks:
        return "", {**detail, "reduce": None}
    rsys, ruser = npc_chunked.reduce_prompt(subject, ev.header, npc_chunked.render_notes(stitched), chunks[-1], manual, headings)
    atomic_write_text(run_dir / f"{stem}.reduce.system.md", rsys)
    atomic_write_text(run_dir / f"{stem}.reduce.user.md", ruser)
    reduce_item = WorkItem(f"{stem}:reduce", len(chunks), "npc-draft")
    reduced = dispatcher.run(
        [reduce_item],
        lambda _item, client: render_part(client, rsys, ruser, args.model, args.max_tokens),
    )
    if reduced.failures:
        raise _CallFailed("reduce", RuntimeError(reduced.failures[reduce_item.item_id].message))
    raw, secs = reduced.values[reduce_item.item_id], 0.0
    print(f"{subject}: reduce {secs:.1f}s", flush=True)
    atomic_write_text(run_dir / f"{stem}.reduce.out.md", raw)
    detail["reduce"] = {"secs": round(secs, 1), "prompt_chars": len(ruser)}
    return npc_chunked.assemble(headings, stitched, raw), detail


def _compose(root: Path, npc_range_dir: Path, stem: str, subject: str) -> None:
    """Compose the GM dossier for one NPC (drafted, skipped or incomplete), warning on a hand-edit."""
    draft = npc_range_dir / DRAFT_DIR / f"{stem}.md"
    res = npc_compose.compose_gm(
        draft if draft.is_file() else None,
        npc_compose.authored_path_for(root, subject),
        npc_range_dir / GM_DIR / f"{stem}.md",
        subject,
        stem,
    )
    if res.hand_edited:
        print(npc_compose.hand_edit_warning(res, root), file=sys.stderr)
