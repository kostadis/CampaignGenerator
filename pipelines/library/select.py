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
    root = str(config.source_root).rstrip("/") + "/"
    sel = config.selection
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
    cands: list[tuple[LibraryBook, int]] = []
    for bid, filepath, dt, pt, pub, ptype, pf in rows:
        if int(bid) in excluded or not filepath or not str(filepath).startswith(root):
            continue
        pdf = Path(filepath)
        if ".old-" in pdf.name:
            continue
        sidecar = pdf.with_suffix(".json")
        if not sidecar.is_file():
            continue
        cands.append(
            (LibraryBook(int(bid), dt or pt or pdf.stem, pub, ptype, str(pdf), str(sidecar)), int(pf))
        )

    if sel.book_ids:  # explicit ids bypass twin dedupe
        return [b for b, _ in cands]

    best: dict[str, tuple[tuple, LibraryBook]] = {}
    for b, pf in cands:
        rank = (bool(_PF.search(b.title)), pf, b.book_id)
        k = _norm(b.title)
        if k not in best or rank < best[k][0]:
            best[k] = (rank, b)
    return sorted((b for _, b in best.values()), key=lambda b: b.book_id)


def write_manifest(books, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    books = [b.to_dict() if isinstance(b, LibraryBook) else b for b in books]
    path.write_text(json.dumps({"books": books}, indent=2), encoding="utf-8")


def read_manifest(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
