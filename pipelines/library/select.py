"""Select converted books from the rpg-lib SQLite file into a manifest."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DEFAULT_TYPES = ("adventure", "setting", "gm_aid")


def select_books(
    db_path: Path,
    source_root: Path,
    limit: int = 50,
    types=DEFAULT_TYPES,
) -> list[dict]:
    root = str(source_root).rstrip("/") + "/"
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        ph = ",".join("?" for _ in types)
        rows = con.execute(
            "SELECT id, filepath, display_title, pdf_title, publisher, product_type "
            "FROM books "
            f"WHERE product_type IN ({ph}) "
            "AND COALESCE(is_old_version, 0) = 0 AND COALESCE(is_duplicate, 0) = 0 "
            "ORDER BY id",
            tuple(types),
        ).fetchall()
    finally:
        con.close()
    out: list[dict] = []
    for bid, filepath, dt, pt, pub, ptype in rows:
        if not filepath or not str(filepath).startswith(root):
            continue
        pdf = Path(filepath)
        if ".old-" in pdf.name:
            continue
        sidecar = pdf.with_suffix(".json")
        if not sidecar.is_file():
            continue
        out.append(
            {
                "book_id": int(bid),
                "title": dt or pt or pdf.stem,
                "publisher": pub,
                "product_type": ptype,
                "pdf_path": str(pdf),
                "sidecar_path": str(sidecar),
            }
        )
        if len(out) >= limit:
            break
    return out


def write_manifest(books, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"books": list(books)}, indent=2), encoding="utf-8")


def read_manifest(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
