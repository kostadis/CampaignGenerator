"""Select converted books from the rpg-lib SQLite file (research R4, FR-002/003)."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path

from pipelines.library.config import LibraryConfig

_PF = re.compile(r"[\(\[]\s*print(?:er)?[\s-]*friendly\s*[\)\]]", re.I)


@dataclass
class LibraryBook:
    book_id: int
    title: str
    publisher: str | None
    product_type: str | None
    pdf_path: str
    sidecar_path: str

    def to_dict(self) -> dict:
        return asdict(self)


def _norm(title: str) -> str:
    return " ".join(_PF.sub(" ", title).split()).casefold()


def select_books(config: LibraryConfig) -> list[LibraryBook]:
    return select_books_report(config)[0]


def select_books_report(config: LibraryConfig) -> tuple[list[LibraryBook], list[dict]]:
    """Return (selected books, skipped entries ``{book_id, reason}``).

    An explicitly listed ``book_ids`` entry is the GM's word, so one that cannot
    be selected is reported. ``exclude_book_ids`` hits are reported too. For
    ``product_types`` / ``all_converted``, a book without a finished sidecar is
    simply not selected (FR-003) and is not reported.
    """
    root = str(config.source_root).rstrip("/") + "/"
    sel = config.selection
    explicit = bool(sel.book_ids)
    where, params = ["1=1"], []
    if sel.product_types:
        where.append(f"product_type IN ({','.join('?' for _ in sel.product_types)})")
        params += list(sel.product_types)
    if sel.book_ids:
        where.append(f"id IN ({','.join('?' for _ in sel.book_ids)})")
        params += [int(i) for i in sel.book_ids]
    else:
        # an explicit book_ids entry is the GM's word; everything else drops old/dup rows
        where.append("COALESCE(is_old_version, 0) = 0 AND COALESCE(is_duplicate, 0) = 0")
    con = sqlite3.connect(f"file:{config.rpg_library_db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT id, filepath, display_title, pdf_title, publisher, product_type,"
            " COALESCE(is_printer_friendly, 0) FROM books WHERE "
            + " AND ".join(where)
            + " ORDER BY id",
            params,
        ).fetchall()
    finally:
        con.close()

    excluded = set(config.exclude_book_ids)
    skipped: list[dict] = []

    def skip(bid: int, reason: str, always: bool = False) -> None:
        if explicit or always:
            skipped.append({"book_id": bid, "reason": reason})

    if explicit:
        found = {int(r[0]) for r in rows}
        for bid in sorted({int(i) for i in sel.book_ids} - found):
            skip(bid, "book id not in the rpg-lib database")

    cands: list[tuple[LibraryBook, int]] = []
    for bid, filepath, dt, pt, pub, ptype, pf in rows:
        bid = int(bid)
        if bid in excluded:
            skip(bid, "excluded by library.exclude_book_ids", always=True)
            continue
        if not filepath:
            skip(bid, "no filepath in the database")
            continue
        if not str(filepath).startswith(root):
            skip(bid, "filepath is outside library.source_root")
            continue
        pdf = Path(filepath)
        if ".old-" in pdf.name:
            skip(bid, "old-version file (.old-)")
            continue
        sidecar = pdf.with_suffix(".json")
        if not sidecar.is_file():
            skip(bid, "no finished sidecar (.json) next to the PDF")
            continue
        cands.append(
            (LibraryBook(bid, dt or pt or pdf.stem, pub, ptype, str(pdf), str(sidecar)), int(pf))
        )

    skipped.sort(key=lambda s: s["book_id"])
    if explicit:  # explicit ids bypass twin dedupe
        return [b for b, _ in cands], skipped

    best: dict[tuple, tuple[tuple, LibraryBook]] = {}
    for b, pf in cands:
        rank = (bool(_PF.search(b.title)), pf, b.book_id)
        k = (_norm(b.title), (b.publisher or "").strip().casefold())
        if k not in best or rank < best[k][0]:
            best[k] = (rank, b)
    return sorted((b for _, b in best.values()), key=lambda b: b.book_id), skipped


def write_manifest(books, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    books = [b.to_dict() if isinstance(b, LibraryBook) else b for b in books]
    path.write_text(json.dumps({"books": books}, indent=2), encoding="utf-8")


def read_manifest(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
