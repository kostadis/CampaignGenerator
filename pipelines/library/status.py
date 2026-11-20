"""Library health check (``library status``). No LLM, no palace access."""

from __future__ import annotations

import json
from pathlib import Path

from pipelines.library.build import LEDGER, MANIFEST, dir_bytes, read_json
from pipelines.library.config import LibraryConfig
from pipelines.library.select import select_books_report
from pipelines.library.state import embedder_matches, read_stamp, rendered_root


def stale_book_ids(config: LibraryConfig) -> list[int]:
    """Books whose source sidecar no longer matches the ledger (size/mtime)."""
    work = Path(config.work_dir)
    manifest = read_json(work / MANIFEST, {"books": []})
    ledger = read_json(work / LEDGER, {})
    stale: list[int] = []
    for b in manifest.get("books", []):
        e = ledger.get(str(b["book_id"]))
        if e is None:
            continue
        try:
            st = Path(b["sidecar_path"]).stat()
        except OSError:
            stale.append(b["book_id"])
            continue
        if st.st_size != e.get("src_size") or st.st_mtime != e.get("src_mtime"):
            stale.append(b["book_id"])
    return sorted(stale)


def selection_drift(config: LibraryConfig) -> tuple[list[int], list[int]]:
    """(added, removed) book ids, by the same rules ``refresh`` uses.

    added: selected now but absent from the ledger. removed: in the ledger but
    no longer selected. (A selected book whose ledger entry is skipped/failed is
    neither: ``refresh`` retries it, but it is not a selection change.)
    """
    ledger = read_json(Path(config.work_dir) / LEDGER, {})
    selected = {b.book_id for b in select_books_report(config)[0]}
    in_ledger = {int(i) for i in ledger}
    return sorted(selected - in_ledger), sorted(in_ledger - selected)


def status(config: LibraryConfig) -> dict:
    stamp = read_stamp(config)
    built = stamp is not None and (rendered_root(config) / "sections.json").is_file()
    ledger = read_json(Path(config.work_dir) / LEDGER, {})
    added, removed = selection_drift(config) if built else ([], [])
    stale = sorted(set(stale_book_ids(config)) | set(added) | set(removed)) if built else []
    return {
        "configured": True,
        "built": built,
        "books": sum(1 for e in ledger.values() if e.get("status") == "indexed"),
        "stale": stale,
        "added": added,
        "removed": removed,
        "embedder_match": embedder_matches(config, stamp) if stamp else None,
        "palace": str(config.palace),
        "index_bytes": dir_bytes(config.palace),
    }
