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
from pipelines.library.guard import WING, require_library_palace
from pipelines.library.render import render_book, write_palace_layout
from pipelines.library.select import select_books, write_manifest

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


def build(config: LibraryConfig, *, client) -> BuildReport:
    t0 = time.time()
    require_library_palace(config.palace)
    check_source_root(config)
    work = Path(config.work_dir)
    rendered = work / RENDERED

    books = [b.to_dict() for b in select_books(config)]
    write_manifest(books, work / MANIFEST)

    prior = read_json(work / LEDGER, {})
    # A rebuild must not leave drawers of the previous build behind.
    for bid, e in prior.items():
        if e.get("status") == "indexed":
            client.delete_room(WING, f"b{bid}")

    if rendered.exists():
        shutil.rmtree(rendered)
    rendered.mkdir(parents=True)
    fetched = {r["book_id"]: r for r in fetch_all(books, config.cache_dir)}

    report = BuildReport(selected=len(books))
    ledger: dict[str, dict] = {}
    records: list[dict] = []
    laid_out: list[dict] = []
    for b in books:
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
    write_json(work / LEDGER, ledger)
    if laid_out:
        client.mine(rendered, wing=WING)
    write_json(work / STAMP, embedder_stamp(config))
    report.index_bytes = dir_bytes(config.palace)
    report.elapsed_s = round(time.time() - t0, 3)
    return report
