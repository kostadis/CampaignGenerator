"""query_rpg_lib.py — search rpg-lib's catalog and emit refs.yaml entries.

This is an *authoring-time* helper for ``refs.yaml``. It goes through rpg-lib's
own ``library_api.db`` module so it inherits whatever search semantics
rpg-lib supports (currently LIKE-based across multiple columns with
product-type / tags / level filters; future upgrades like FTS or NLQ would
land here automatically). No HTTP service, no daemon — direct SQLite.

Two modes:

* **Search:** ``query_rpg_lib.py "tales yawning portal"`` lists matching books
  with their id, title, and relative path.
* **Emit:** ``query_rpg_lib.py --book-id 7421`` prints a paste-ready
  ``refs.yaml`` block for that book.

The script imports rpg-lib's ``library_api.db`` from the rpg-lib checkout. If
it lives somewhere other than ``~/src/mytools/rpg-lib/``, point at it with
``--rpglib-dir`` or set the ``RPGLIB_DIR`` env var.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import yaml


DEFAULT_RPGLIB_DIR = Path("~/src/mytools/rpg-lib").expanduser()
DEFAULT_DB_BASENAME = "rpg_library.db"

# Schema columns rpg-lib's search_books / get_book SELECT but which only exist
# after the enrichment pass has run. If any of these is missing, both
# functions will raise with a sqlite OperationalError or an IndexError out of
# _row_to_summary. We surface a friendlier hint instead.
_ENRICHMENT_COLUMNS = (
    "display_title", "tags", "series", "min_level", "max_level",
)


def _add_rpglib_to_path(rpglib_dir: Path) -> None:
    if not rpglib_dir.is_dir():
        raise SystemExit(
            f"query_rpg_lib: rpg-lib directory not found at {rpglib_dir}. "
            f"Set --rpglib-dir or RPGLIB_DIR."
        )
    if str(rpglib_dir) not in sys.path:
        sys.path.insert(0, str(rpglib_dir))


def _detect_schema_gap(db_path: Path) -> list[str]:
    """Return enrichment columns missing from this DB, if any."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        present = {r[1] for r in conn.execute("PRAGMA table_info(books)")}
    finally:
        conn.close()
    return [c for c in _ENRICHMENT_COLUMNS if c not in present]


def _schema_hint(db_path: Path, missing: list[str]) -> str:
    return (
        f"query_rpg_lib: rpg-lib database at {db_path} is missing enrichment "
        f"column(s): {', '.join(missing)}. Run the enrichment pass:\n"
        f"  cd ~/src/mytools/rpg-lib && python pdf_enricher.py\n"
        f"(or whichever script populates display_title / tags / series in your "
        f"rpg-lib version)."
    )


def _open_db(db_path: Path):
    """Open the rpg-lib DB read-only via ``library_api.db.get_db``.

    Attaches a sibling ``user_data.db`` because rpg-lib's ``search_books`` and
    ``get_book`` JOIN against ``user_data.favorites``. ``init_user_db`` is
    idempotent (CREATE TABLE IF NOT EXISTS).
    """
    if not db_path.is_file():
        raise SystemExit(f"query_rpg_lib: database not found at {db_path}")
    missing = _detect_schema_gap(db_path)
    if missing:
        raise SystemExit(_schema_hint(db_path, missing))
    from library_api import db as rpglib_db  # noqa: E402  (sys.path mutated by caller)
    user_db_path = str(db_path.parent / "user_data.db")
    rpglib_db.init_user_db(user_db_path)
    return rpglib_db.get_db(str(db_path), user_db_path), rpglib_db


def _call_rpglib(fn, *args, db_path: Path, **kwargs):
    """Wrap a rpg-lib call so schema-gap errors produce a useful hint."""
    try:
        return fn(*args, **kwargs)
    except (sqlite3.OperationalError, IndexError, KeyError) as exc:
        # Re-check the schema in case the DB changed between _open_db and now,
        # or in case the failure was from some other column we didn't enumerate.
        missing = _detect_schema_gap(db_path)
        if missing:
            raise SystemExit(_schema_hint(db_path, missing)) from exc
        raise SystemExit(
            f"query_rpg_lib: rpg-lib call {fn.__name__} failed: {exc}. "
            f"This usually means rpg-lib expects a schema column that isn't in "
            f"your DB. Try re-running rpg-lib's indexer + enricher."
        ) from exc


# ── Output formatters ────────────────────────────────────────────────────


def _book_title(book: dict) -> str:
    return (
        book.get("display_title")
        or book.get("pdf_title")
        or book.get("filename")
        or "(untitled)"
    )


def format_search_results(results: list[dict]) -> str:
    """Render search results."""
    if not results:
        return "(no matches)"
    lines = []
    for r in results:
        title = _book_title(r)
        publisher = r.get("publisher") or ""
        product_type = r.get("product_type") or ""
        lines.append(f"  id={r['id']:<7} {title}")
        meta_bits = [b for b in (publisher, product_type) if b]
        if meta_bits:
            lines.append(f"             {' · '.join(meta_bits)}")
        if r.get("filename"):
            lines.append(f"             file:     {r['filename']}")
    return "\n".join(lines)


def format_refs_entry(book: dict) -> str:
    """Emit a paste-ready refs.yaml block for one book."""
    title = _book_title(book)
    rel = book.get("relative_path")
    if not rel:
        raise SystemExit(
            f"query_rpg_lib: book {book.get('id')} has no relative_path. "
            f"Is the rpg-lib database freshly re-indexed?"
        )
    entry = {
        "rpglib": rel,
        "book_id": book["id"],
    }
    note_bits = [title]
    if book.get("publisher"):
        note_bits.append(book["publisher"])
    entry["note"] = " · ".join(note_bits)
    # yaml.safe_dump with a single-item list keeps the indentation correct
    # for pasting into the existing `refs:` array.
    return yaml.safe_dump(
        [entry], sort_keys=False, default_flow_style=False, allow_unicode=True
    )


# ── CLI ──────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None,
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Free-text search across title/description/tags. "
        "Required unless --book-id is given.",
    )
    parser.add_argument(
        "--book-id",
        type=int,
        default=None,
        help="Skip search; emit a refs.yaml block for this specific book id.",
    )
    parser.add_argument(
        "--rpglib-dir",
        type=Path,
        default=Path(os.environ.get("RPGLIB_DIR") or DEFAULT_RPGLIB_DIR),
        help=f"Path to the rpg-lib checkout. Default: {DEFAULT_RPGLIB_DIR}",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help=f"Path to rpg_library.db. Default: <rpglib-dir>/{DEFAULT_DB_BASENAME}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max search results to show. Default: 20.",
    )
    parser.add_argument(
        "--product-type",
        default=None,
        help="Filter by product_type (adventure, sourcebook, bestiary, …).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    rpglib_dir = args.rpglib_dir.expanduser().resolve()
    _add_rpglib_to_path(rpglib_dir)
    db_path = (args.db or (rpglib_dir / DEFAULT_DB_BASENAME)).expanduser().resolve()
    conn, db_mod = _open_db(db_path)

    if args.book_id is not None:
        book = _call_rpglib(db_mod.get_book, conn, args.book_id, db_path=db_path)
        if not book:
            raise SystemExit(f"query_rpg_lib: no book with id {args.book_id}")
        sys.stdout.write(format_refs_entry(book))
        return 0

    if not args.query:
        raise SystemExit("query_rpg_lib: provide a query or --book-id")

    result = _call_rpglib(
        db_mod.search_books,
        conn,
        q=args.query,
        product_type=args.product_type,
        per_page=args.limit,
        db_path=db_path,
    )
    results = result.get("results", []) if isinstance(result, dict) else []
    total = result.get("total", len(results)) if isinstance(result, dict) else len(results)
    print(f"# {len(results)} of {total} match(es) for {args.query!r}")
    print(format_search_results(results))
    if results:
        print()
        print("# To emit a refs.yaml entry for one of these:")
        print("#   python query_rpg_lib.py --book-id <id>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
