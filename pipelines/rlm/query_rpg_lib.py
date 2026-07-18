"""query_rpg_lib.py — search rpg-lib's catalog and emit refs.yaml entries.

This is an *authoring-time* helper for ``refs.yaml``. It talks to rpg-lib's
HTTP API (``library_server``, default port 8000) — the only supported way to
reach rpg-lib's catalog. rpg-lib is an external index service that anonymizes
a physical PDF library behind that endpoint (constitution Principle II);
nothing in this repo should open its SQLite DB directly (GH mneme#9).

Two modes:

* **Search:** ``query_rpg_lib "tales yawning portal"`` lists matching books
  with their id, title, and relative path.
* **Emit:** ``query_rpg_lib --book-id 7421`` prints a paste-ready
  ``refs.yaml`` block for that book.

The rpg-lib base URL comes from mneme wiring (``rpg_library_url``); override
with ``--rpg-library-url``. Requires ``library_server`` to be running.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

from campaignlib import wiring_get

_DEFAULT_RPGLIB_URL = wiring_get("rpg_library_url")
_DEFAULT_HTTP_TIMEOUT = 10.0


def _http_get_json(url: str, *, timeout: float = _DEFAULT_HTTP_TIMEOUT) -> dict:
    """GET ``url`` and return parsed JSON, or raise a friendly ``SystemExit``."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("detail", body)
        except (json.JSONDecodeError, AttributeError):
            detail = body
        raise SystemExit(
            f"query_rpg_lib: rpg-lib returned HTTP {e.code} for {url}: {detail}"
        ) from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SystemExit(
            f"query_rpg_lib: could not reach rpg-lib at {url}: {e}\n"
            f"Is library_server running? "
            f"(cd ~/src/mytools/rpg-lib && python library_server.py)"
        ) from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SystemExit(
            f"query_rpg_lib: rpg-lib returned non-JSON from {url}: {e}"
        ) from e


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
        "--rpg-library-url",
        default=_DEFAULT_RPGLIB_URL,
        help="rpg-lib base URL (default: mneme wiring rpg_library_url).",
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
    if not args.rpg_library_url:
        raise SystemExit(
            "query_rpg_lib: no rpg-lib URL — pass --rpg-library-url or render "
            "mneme wiring (rpg_library_url)."
        )
    base_url = args.rpg_library_url.rstrip("/")

    if args.book_id is not None:
        book = _http_get_json(f"{base_url}/api/library/book/{args.book_id}")
        sys.stdout.write(format_refs_entry(book))
        return 0

    if not args.query:
        raise SystemExit("query_rpg_lib: provide a query or --book-id")

    params = {"q": args.query, "per_page": str(args.limit)}
    if args.product_type:
        params["product_type"] = args.product_type
    qs = urllib.parse.urlencode(params)
    result = _http_get_json(f"{base_url}/api/library/search?{qs}")
    results = result.get("results", []) if isinstance(result, dict) else []
    total = result.get("total", len(results)) if isinstance(result, dict) else len(results)
    print(f"# {len(results)} of {total} match(es) for {args.query!r}")
    print(format_search_results(results))
    if results:
        print()
        print("# To emit a refs.yaml entry for one of these:")
        print("#   query_rpg_lib --book-id <id>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
