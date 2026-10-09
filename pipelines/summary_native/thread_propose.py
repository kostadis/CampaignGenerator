"""thread-propose: group the thread notes no ratified thread claims, for the GM to rule on (spec 034, R5).

This is the model step of the thread proposals (with ``extract``, ``synth`` and ``audit``) and it reaches a
model only through ``campaignlib`` (``client_from_args``, ``stream_api``). Code does everything around the
call (Principle II):

1. ``thread_attach`` attaches every note whose name equals a ratified title or alias, so only the notes no
   thread claims are sent;
2. the model sees ``id | ch | tag | name | text`` rows of those notes and the ratified threads, and returns
   groupings as JSON: a suggestion, never a decision;
3. ``thread_check`` removes whatever the notes and the registry do not support, and every unattached note the
   groupings leave out becomes a single-note proposal;
4. the proposals are merged into the proposals file, keeping every ruling the GM has recorded.

The input is split into chapter-ordered batches by ``--max-input-chars``. Every batch sees the same ratified
threads and its own notes, and nothing else: no batch sees another batch's output, so no model output is the
input of a later call.

**This module never writes the thread registry.** It reads it. Only ``thread_registry``'s verbs, driven by the
GM's ratification, write it (FR-009d); ``tests/test_thread_registry_groups.py`` asserts so.

Layout, under ``<range_dir>/state/``::

    threads/attach.json          code: note id -> thread id | "ambiguous" | null
    threads/propose.NN.user.md   the prompt of batch NN
    threads/propose.NN.out.md    the model's raw output for batch NN
    threads/propose_report.md    what was dropped and why, stale rulings, ambiguous names
    runs/<stamp>/record.json     the run record (and propose.system.md)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from campaignlib import client_from_args, stream_api
from campaignlib.api.client import resolve_cli_model
from campaignlib.thread_registry import check_registry, load_registry
from campaignlib.util import atomic_write_text
from pipelines.summary_native import context, corpus, freshness, notes, schema, synth, thread_attach, thread_check
from pipelines.summary_native.freshness import check_fresh

EXIT_REFUSED = synth.EXIT_REFUSED
EXIT_MODEL_FAILED = synth.EXIT_MODEL_FAILED
EXIT_BLOCKING = synth.EXIT_BLOCKING

SYSTEM_PROMPT = "state.thread_propose.system.md"
REPORT_FILE = "propose_report.md"


def load_system() -> str:
    return (context.PROMPT_DIR / SYSTEM_PROMPT).read_text(encoding="utf-8")


def render_part(client, system: str, user: str, model: str | None, max_tokens: int) -> str:
    """The one model call in this module. Silent: the caller prints one progress line per batch."""
    return stream_api(client, system, user, model, max_tokens=max_tokens, silent=True)


def _cell(text: str) -> str:
    """A prompt row is ``a | b | c``: a pipe or a newline inside a field would shift the columns."""
    return " ".join(str(text).replace("|", "/").split())


# ── The prompt ──────────────────────────────────────────────────────────────


def thread_rows(registry: dict, att: thread_attach.Attachment) -> list[str]:
    """One row per ratified thread: ``id | title | aliases | status | latest note``.

    The latest note is the latest attached checked note of the range, else the thread's last log row.
    """
    out = []
    for t in registry.get("threads") or []:
        tid = t.get("id") or ""
        state = att.threads.get(tid)
        if state is not None:
            latest = f"ch {state.latest.first_chapter} {state.latest.tag}: {thread_check.note_body(state.latest)}"
        elif t.get("log"):
            row = max(t["log"], key=lambda r: r.get("chapter") or 0)
            latest = f"ch {row.get('chapter')} {row.get('change')}: {row.get('summary') or ''}"
        else:
            latest = "(no note)"
        aliases = "; ".join(t.get("aliases") or []) or "-"
        out.append(" | ".join(_cell(x) for x in (tid, t.get("title") or tid, aliases, t.get("status") or "open", latest)))
    return out


def note_row(n: notes.Note) -> str:
    return " | ".join(_cell(x) for x in (
        n.note_id, n.first_chapter, n.tag or "", thread_check.note_name(n), thread_check.note_body(n)))


def build_user(ratified: list[str], rows: list[str]) -> str:
    """One batch's prompt: the ratified threads, then its notes in chapter order."""
    return (
        "RATIFIED THREADS (id | title | aliases | status | latest note):\n"
        + ("\n".join(ratified) if ratified else "(none)")
        + "\n\nTHREAD NOTES (id | ch | tag | name | text), in chapter order:\n"
        + "\n".join(rows)
        + "\n\nWrite the JSON object now.\n"
    )


def plan_batches(ratified: list[str], rows: list[str], max_chars: int) -> list[list[int]]:
    """Indexes of ``rows`` per batch: chapter order kept, each prompt at most ``max_chars`` where possible.

    A batch always holds at least one note, so a limit smaller than one note still makes progress.
    """
    base = len(build_user(ratified, []))
    batches: list[list[int]] = []
    current: list[int] = []
    size = base
    for i, row in enumerate(rows):
        add = len(row) + 1
        if current and size + add > max_chars:
            batches.append(current)
            current, size = [], base
        current.append(i)
        size += add
    if current:
        batches.append(current)
    return batches


# ── Report ──────────────────────────────────────────────────────────────────


def report_md(counts: dict, lines: list[str], stale: list[str], att: thread_attach.Attachment, batches: list[dict]) -> str:
    out = [
        "# Thread proposals report", "",
        f"{counts['notes']} thread notes: {counts['attached']} attached to {counts['threads']} ratified threads by exact "
        f"title or alias, {counts['unattached']} unattached. {counts['groups']} group proposals "
        f"({counts['single']} single), {counts['dropped']} dropped.",
        "", "## Batches", "",
    ]
    out += [f"- batch {b['index']}: {b['notes']} notes, {b['chars']} characters, {b['status']}" for b in batches] or [
        "- (no notes were sent to a model)"]
    out += ["", "## Dropped and changed by the code check", ""]
    out += [f"- {ln}" for ln in lines] or ["- (nothing)"]
    out += ["", "## Stale rulings", ""]
    out += [f"- {ln}" for ln in stale] or ["- (none)"]
    out += ["", "## Ambiguous names (claimed by more than one thread, never attached)", ""]
    out += [f"- {name}: {', '.join(ids)}" for name, ids in sorted(att.ambiguous.items())] or ["- (none)"]
    return "\n".join(out) + "\n"


def _dumps(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _refuse(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return EXIT_REFUSED


# ── The run ─────────────────────────────────────────────────────────────────


def run_thread_propose(
    args,
    *,
    root: Path,
    range_dir: Path,
    report,
    entity_registry_path: Path | None,
    players_path: Path | None,
    thread_registry_path: Path,
    proposals_path: Path,
    max_input_chars: int,
    now=None,
) -> int:
    now = now or synth._utcnow
    if report.blocking_count:
        print(report.to_markdown(), end="")
        print("validation has blocking problems; fix the summaries, then build --force", file=sys.stderr)
        return EXIT_BLOCKING
    try:
        manifest = corpus.load_manifest(range_dir, require_complete=True)
    except corpus.CorpusError as e:
        return _refuse(f"{e}; run `summary_native build`")
    stale_build = check_fresh(report, range_dir, root, manifest, entity_registry_path)
    if stale_build:
        return _refuse(stale_build)
    since, until = int(manifest["range"]["since"]), int(manifest["range"]["until"])
    extract_cmd = f"summary_native extract --since {since} --until {until}"
    problem = freshness.check_notes_fresh(range_dir, entity_registry_path, players_path, extract_cmd=extract_cmd)
    if problem:
        return _refuse(problem)
    try:
        _, results = notes.load_checked(range_dir)
    except notes.NotesIncomplete as e:
        return _refuse(f"{e}; run `{extract_cmd}`")

    shown_registry = schema.display_path(thread_registry_path, root)
    try:
        registry = load_registry(thread_registry_path)
        registry["threads"] = list(registry.get("threads") or [])
        findings = check_registry(registry)
        prior = thread_check.load_proposals(proposals_path)
    except (OSError, ValueError, AttributeError, TypeError) as e:  # YAML errors are ValueError subclasses
        return _refuse(f"cannot read the thread registry or the proposals file: {e}")
    if findings:
        return _refuse(
            f"the thread registry {shown_registry} fails `thread_registry check`; fix it first:\n  " + "\n  ".join(findings))

    att = thread_attach.attach(results, registry)
    to_model = thread_check.offered(att.unattached, prior)
    ratified = thread_rows(registry, att)
    rows = [note_row(n) for n in to_model]
    batch_ix = plan_batches(ratified, rows, max_input_chars) if rows else []
    users = [build_user(ratified, [rows[i] for i in ix]) for ix in batch_ix]

    system = load_system()
    started = now()
    run_dir = synth._new_run_dir(Path(range_dir) / schema.STATE_DIR / "runs", started.strftime("%Y%m%dT%H%M%SZ"))
    atomic_write_text(run_dir / "propose.system.md", system)
    tdir = thread_attach.threads_dir(range_dir)
    for old in [*tdir.glob("propose.*.user.md"), *tdir.glob("propose.*.out.md")]:
        old.unlink()
    for i, user in enumerate(users, 1):
        atomic_write_text(tdir / f"propose.{i:02d}.user.md", user)

    backend = resolve_cli_model(args, legacy_default=None).backend
    record = {
        "step": "thread-propose",
        "run_id": run_dir.name,
        "range": {"since": since, "until": until},
        "backend": backend,
        "model": args.model,
        "effort": getattr(args, "claude_code_effort", None),
        "max_tokens": args.max_tokens,
        "max_input_chars": max_input_chars,
        "dump_only": bool(args.dump_only),
        "inputs": {
            **freshness.notes_manifest_facts(range_dir, entity_registry_path, players_path),
            "notes_manifest_sha256": freshness.sha_file(freshness.notes_dir(range_dir) / freshness.NOTES_MANIFEST),
            "thread_registry_sha256": freshness.sha_file(thread_registry_path),
            "proposals_sha256_before": freshness.sha_file(proposals_path),
        },
        "system_sha256": corpus.sha256_file(context.PROMPT_DIR / SYSTEM_PROMPT),
        "counts": {"notes": len(att.notes), "attached": len(att.notes) - len(att.unattached),
                   "threads": len(att.threads), "unattached": len(att.unattached), "offered": len(to_model)},
        "batches": [{"index": i, "notes": len(ix), "chars": len(users[i - 1]), "status": "pending"}
                    for i, ix in enumerate(batch_ix, 1)],
        "exit_code": None,
        "started": started.isoformat(timespec="seconds"),
        "finished": None,
    }

    def save_record(code: int) -> int:
        record["exit_code"] = code
        record["finished"] = now().isoformat(timespec="seconds")
        atomic_write_text(run_dir / "record.json", _dumps(record))
        return code

    if args.dump_only:
        print(f"[--dump-only: {len(users)} prompt(s) written to {schema.display_path(tdir, root)}; no model call]")
        return save_record(0)

    thread_attach.write_attach(range_dir, att, (since, until))

    parsed: list = []  # the groups of every batch whose output parsed
    lines: list[str] = []
    if users:
        try:
            client = client_from_args(args)
        except SystemExit as e:  # client_from_args fails fast with SystemExit(message)
            record["error"] = str(e.code)
            save_record(EXIT_REFUSED)
            return _refuse(str(e.code) if isinstance(e.code, str) else f"backend setup failed (exit {e.code})")
        except (ValueError, RuntimeError, ImportError) as e:
            record["error"] = str(e)
            save_record(EXIT_REFUSED)
            return _refuse(str(e))
        for i, ix in enumerate(batch_ix, 1):
            error = ""
            t0 = time.monotonic()
            raw = None
            for attempt in (1, 2):
                try:
                    raw = render_part(client, system, users[i - 1], args.model, args.max_tokens)
                    break
                except Exception as e:  # noqa: BLE001 - any backend error is a failed batch
                    error = f"{type(e).__name__}: {e}"
            if raw is None:
                record["batches"][i - 1]["status"] = "failed"
                record["error"] = f"batch {i}: {error}"
                print(f"Error: batch {i}/{len(batch_ix)} failed after one retry: {error}; no proposal was written",
                      file=sys.stderr)
                return save_record(EXIT_MODEL_FAILED)
            atomic_write_text(tdir / f"propose.{i:02d}.out.md", raw)
            try:
                got = thread_check.parse_groups(raw)
                parsed.extend(got)
                record["batches"][i - 1]["status"] = "ok"
                shown = f"{len(got)} group(s)"
            except thread_check.ThreadJsonError as e:
                lines.append(f"{thread_check.DROPPED} batch {i}: the model's output is {e}; "
                             f"its {len(ix)} notes become single-note proposals")
                record["batches"][i - 1]["status"] = "unparseable"
                shown = "unparseable output"
            print(f"batch {i}/{len(batch_ix)} {time.monotonic() - t0:.0f}s {len(ix)} notes -> {shown}", flush=True)

    attached_ids = {nid: tid for nid, tid in att.by_note.items() if tid not in (None, thread_attach.AMBIGUOUS)}
    groups, check_lines = thread_check.check_groups(
        {"groups": parsed}, att.unattached, registry, prior, attached=attached_ids)
    lines += check_lines
    stale = thread_check.stale_ratified(prior, {n.note_id for n in att.notes}, since, until)
    source = f"summary_native ch{since:03d}-{until:03d} run {run_dir.name}"
    thread_check.merge_proposals(proposals_path, groups, source, scope_ids={n.note_id for n in att.notes})

    singles = sum(1 for g in groups if g["kind"] == "single")
    dropped = sum(1 for ln in lines if ln.startswith(thread_check.DROPPED))
    counts = {**record["counts"], "groups": len(groups), "single": singles, "dropped": dropped}
    record["counts"] = counts
    atomic_write_text(tdir / REPORT_FILE, report_md(counts, lines, stale, att, record["batches"]))
    print(
        f"threads: {counts['notes']} notes — {counts['attached']} attached to {counts['threads']} ratified threads, "
        f"{counts['unattached']} unattached → {counts['groups']} group proposals ({singles} single), "
        f"{dropped} dropped (see {REPORT_FILE})"
    )
    if att.ambiguous:
        print(f"warning: {len(att.ambiguous)} name(s) are claimed by more than one ratified thread and were left "
              f"unattached — see {REPORT_FILE}", file=sys.stderr)
    return save_record(0)
