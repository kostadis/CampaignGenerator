"""Build (and, later, refresh) the library palace. No LLM, no direct mempalace."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from pipelines.library import SourceUnavailable
from pipelines.library.config import LibraryConfig
from pipelines.library.fetch import fetch_all
from pipelines.library.guard import WING, mark_library_palace, require_library_palace
from pipelines.library.progress import log
from pipelines.library.render import render_book, write_palace_layout
from pipelines.library.select import select_books_report, write_manifest

MANIFEST = "manifest.json"
LEDGER = "library_ledger.json"
SECTIONS = "sections.json"
STAMP = "embedder.json"
RENDERED = "rendered"


@dataclass
class BuildReport:
    selected: int = 0
    indexed: int = 0
    skipped: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    passages: int = 0
    elapsed_s: float = 0.0
    index_bytes: int = 0
    changed: list = field(default_factory=list)
    removed: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def dir_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file()) if Path(p).exists() else 0


def read_json(path: Path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_source_root(config: LibraryConfig) -> None:
    root = Path(config.source_root)
    try:
        ok = root.is_dir() and os.access(root, os.R_OK | os.X_OK)
        if ok:
            next(iter(root.iterdir()), None)
    except OSError:
        ok = False
    if not ok:
        raise SourceUnavailable(
            f"library.source_root {root} is not readable; mount it or fix library.source_root "
            "in ~/.config/hypostasis/hypostasis.yaml (no library was written)"
        )


def embedder_stamp(config: LibraryConfig) -> dict:
    e = config.env
    return {
        "backend": e.get("MEMPALACE_BACKEND"),
        "provider": e.get("MEMPALACE_EMBEDDING_PROVIDER"),
        "model": e.get("MEMPALACE_EMBEDDING_MODEL"),
        "endpoint": e.get("MEMPALACE_EMBEDDING_ENDPOINT"),
        "built_at": now_iso(),
    }


def render_hash(rendered: Path, files: list[str]) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update((Path(rendered) / f).read_bytes())
    return h.hexdigest()


def process_book(book: dict, fetched: dict, rendered: Path) -> tuple[dict, list[dict]]:
    """Render one fetched book. Returns (ledger entry, section records)."""
    entry = {
        "src_size": fetched.get("bytes", 0),
        "src_mtime": fetched.get("src_mtime", 0.0),
        "render_hash": "",
        "files": [],
        "status": "indexed",
        "reason": None,
        "updated_at": now_iso(),
    }
    if fetched.get("status") == "missing":
        entry.update(status="skipped", reason="sidecar missing")
        return entry, []
    try:
        bj = json.loads(Path(fetched["cache_path"]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        entry.update(status="skipped", reason=f"unreadable sidecar: {e}")
        return entry, []
    try:
        recs = render_book(book, bj, rendered)
    except Exception as e:  # one bad book must not sink the build
        shutil.rmtree(Path(rendered) / f"b{book['book_id']}", ignore_errors=True)
        entry.update(status="failed", reason=f"render error: {e}")
        return entry, []
    if not recs:
        shutil.rmtree(Path(rendered) / f"b{book['book_id']}", ignore_errors=True)
        entry.update(status="skipped", reason="no sections")
        return entry, []
    entry["files"] = [r["file"] for r in recs]
    entry["render_hash"] = render_hash(rendered, entry["files"])
    return entry, recs


def _try_delete(client, bid, failures: dict) -> None:
    """Delete a book's drawers; record (never swallow) a failure."""
    try:
        client.delete_room(WING, f"b{bid}")
    except Exception as e:
        failures[int(bid)] = f"could not delete old drawers: {e}"


def _failed_entry(old: dict | None, reason: str) -> dict:
    e = dict(old or {"src_size": 0, "src_mtime": 0.0, "render_hash": "", "files": []})
    e.update(status="failed", reason=reason, updated_at=now_iso())
    return e


def _log_config(what: str, config: LibraryConfig) -> None:
    e = config.env
    log(f"{what}: palace {config.palace}, backend {e.get('MEMPALACE_BACKEND')}, "
        f"model {e.get('MEMPALACE_EMBEDDING_MODEL')}")


def _mine(client, rendered, files) -> None:
    n = "all" if files is None else len(files)
    log(f"mining {n} files into wing {WING} (mempalace output follows)")
    t = time.time()
    if files is None:
        client.mine(rendered, wing=WING)
    else:
        client.mine(rendered, wing=WING, files=files)
    log(f"mined in {time.time() - t:.1f}s")


def build(config: LibraryConfig, *, client) -> BuildReport:
    t0 = time.time()
    _log_config("build", config)
    require_library_palace(config.palace)
    mark_library_palace(config.palace)  # fresh/empty dir accepted above; claim it
    check_source_root(config)
    work = Path(config.work_dir)
    rendered = work / RENDERED

    selected, sel_skipped = select_books_report(config)
    books = [b.to_dict() for b in selected]
    log(f"selection: {len(books)} books selected, {len(sel_skipped)} skipped")
    write_manifest(books, work / MANIFEST)

    # The stamp is written only after a successful mine; until then the
    # library must read as not built.
    (work / STAMP).unlink(missing_ok=True)

    prior = read_json(work / LEDGER, {})
    # A rebuild must not leave drawers of the previous build behind.
    delete_failed: dict[int, str] = {}
    for bid, e in prior.items():
        if e.get("status") in ("indexed", "failed"):
            _try_delete(client, bid, delete_failed)

    if rendered.exists():
        shutil.rmtree(rendered)
    rendered.mkdir(parents=True)
    todo = [b for b in books if b["book_id"] not in delete_failed]
    log(f"fetching {len(todo)} sidecars")
    fetched = {r["book_id"]: r for r in fetch_all(todo, config.cache_dir)}

    report = BuildReport(selected=len(books) + len(sel_skipped), skipped=list(sel_skipped))
    ledger: dict[str, dict] = {}
    records: list[dict] = []
    laid_out: list[dict] = []
    for bid, reason in delete_failed.items():
        ledger[str(bid)] = _failed_entry(prior.get(str(bid)), reason)
        report.failed.append({"book_id": bid, "reason": reason})
    for i, b in enumerate(todo, 1):
        log(f"rendering {i}/{len(todo)} {b.get('title')}")
        entry, recs = process_book(b, fetched[b["book_id"]], rendered)
        ledger[str(b["book_id"])] = entry
        if entry["status"] == "indexed":
            records += recs
            laid_out.append(b)
            report.indexed += 1
            report.changed.append(b["book_id"])
        elif entry["status"] == "skipped":
            report.skipped.append({"book_id": b["book_id"], "reason": entry["reason"]})
        else:
            report.failed.append({"book_id": b["book_id"], "reason": entry["reason"]})
    report.passages = len(records)

    write_palace_layout(rendered, records, laid_out)
    if laid_out:
        try:
            _mine(client, rendered, None)
            mark_library_palace(config.palace)
        except Exception as e:
            for b in laid_out:
                ledger[str(b["book_id"])] = _failed_entry(
                    ledger[str(b["book_id"])], f"mine failed: {e}"
                )
            write_json(work / LEDGER, ledger)
            raise
    write_json(work / LEDGER, ledger)
    write_json(work / STAMP, embedder_stamp(config))
    report.index_bytes = dir_bytes(config.palace)
    report.elapsed_s = round(time.time() - t0, 3)
    log(f"done: {report.indexed}/{report.selected} books, {report.passages} passages, "
        f"{len(report.skipped)} skipped, {len(report.failed)} failed, {report.elapsed_s}s")
    return report


def refresh(config: LibraryConfig, *, client) -> BuildReport:
    """Re-process only books that changed, were added, or left the selection.

    Per R10: a changed/removed book's drawers are deleted first
    (``client.delete_room``), then only the changed books' files are mined
    (``--files-from``). Nothing is ever mined over stale drawers, and a book is
    marked ``indexed`` (with its new size/mtime) only after its mine succeeded.
    """
    from pipelines.library.state import require_built, require_embedder_match

    t0 = time.time()
    _log_config("refresh", config)
    require_library_palace(config.palace)
    stamp = require_built(config)
    require_embedder_match(config, stamp)
    check_source_root(config)
    work = Path(config.work_dir)
    rendered = work / RENDERED

    selected, sel_skipped = select_books_report(config)
    books = [b.to_dict() for b in selected]
    log(f"selection: {len(books)} books selected, {len(sel_skipped)} skipped")
    write_manifest(books, work / MANIFEST)
    prior: dict[str, dict] = read_json(work / LEDGER, {})
    selected_ids = {str(b["book_id"]) for b in books}
    log(f"fetching {len(books)} sidecars")
    fetched = {r["book_id"]: r for r in fetch_all(books, config.cache_dir)}

    removed = sorted(int(i) for i in prior if i not in selected_ids)
    changed_books = []
    for b in books:
        e = prior.get(str(b["book_id"]))
        f = fetched[b["book_id"]]
        if (
            e is None
            or e.get("status") != "indexed"
            or e.get("src_size") != f.get("bytes")
            or e.get("src_mtime") != f.get("src_mtime")
        ):
            changed_books.append(b)

    prior_ids = set(prior)
    n_added = sum(1 for b in changed_books if str(b["book_id"]) not in prior_ids)
    log(f"plan: {len(changed_books)} to process ({n_added} added, "
        f"{len(changed_books) - n_added} changed), {len(removed)} removed")
    sections: dict[str, dict] = read_json(rendered / SECTIONS, {})
    dropping = set(removed) | {b["book_id"] for b in changed_books}
    # Delete drawers first, then forget their files.
    delete_failed: dict[int, str] = {}
    for bid in sorted(dropping):
        if prior.get(str(bid), {}).get("status") in ("indexed", "failed"):
            _try_delete(client, bid, delete_failed)
        shutil.rmtree(rendered / f"b{bid}", ignore_errors=True)
    sections = {k: v for k, v in sections.items() if v["book_id"] not in dropping}

    report = BuildReport(selected=len(books) + len(sel_skipped), skipped=list(sel_skipped))
    for bid in removed:
        if bid in delete_failed:  # keep it in the ledger so the next refresh retries
            prior[str(bid)] = _failed_entry(prior.get(str(bid)), delete_failed[bid])
            report.failed.append({"book_id": bid, "reason": delete_failed[bid]})
        else:
            prior.pop(str(bid), None)
            report.removed.append(bid)

    new_entries: dict[str, dict] = {}
    new_files: list[str] = []
    new_sections: dict[str, dict] = {}
    for i, b in enumerate(changed_books, 1):
        bid = b["book_id"]
        log(f"rendering {i}/{len(changed_books)} {b.get('title')}")
        if bid in delete_failed:
            prior[str(bid)] = _failed_entry(prior.get(str(bid)), delete_failed[bid])
            report.failed.append({"book_id": bid, "reason": delete_failed[bid]})
            continue
        entry, recs = process_book(b, fetched[bid], rendered)
        if entry["status"] == "indexed":
            for r in recs:
                new_sections[r["file"]] = r
            new_files += entry["files"]
            new_entries[str(bid)] = entry
            report.changed.append(bid)
        else:
            prior[str(bid)] = entry
            bucket = report.skipped if entry["status"] == "skipped" else report.failed
            bucket.append({"book_id": bid, "reason": entry["reason"]})

    def _laid_out(entries):
        return [
            b for b in books
            if (entries.get(str(b["book_id"])) or prior.get(str(b["book_id"]), {})).get("status")
            == "indexed"
        ]

    all_sections = {**sections, **new_sections}
    write_palace_layout(rendered, list(all_sections.values()), _laid_out(new_entries))
    if new_files:
        try:
            _mine(client, rendered, new_files)
            mark_library_palace(config.palace)
        except Exception as e:
            for k, entry in new_entries.items():
                prior[k] = _failed_entry(entry, f"mine failed: {e}")
            write_palace_layout(rendered, list(sections.values()), _laid_out({}))
            write_json(work / LEDGER, prior)
            raise
    prior.update(new_entries)
    write_json(work / LEDGER, prior)
    laid_out = _laid_out({})
    report.indexed = len(laid_out)
    report.passages = len(all_sections)
    report.index_bytes = dir_bytes(config.palace)
    report.elapsed_s = round(time.time() - t0, 3)
    log(f"done: {report.indexed} books, {report.passages} passages, changed {len(report.changed)}, "
        f"removed {len(report.removed)}, {len(report.skipped)} skipped, "
        f"{len(report.failed)} failed, {report.elapsed_s}s")
    return report
