"""
suggest_conversion.py — build a "here's what to run" payload for pointer hits.

When ``rpg_retriever.py`` finds a candidate book in rpglib that has no
drawers in MemPalace yet (a "pointer" result in the plan's three-state
taxonomy), it needs to surface a concrete suggestion to the user:

    * the PDF filepath on disk
    * the exact ``convert_book.py`` invocation to run
    * the exact ``fivetools_ingest.py`` invocation to run afterwards
    * a rough token estimate so the user knows the cost envelope

This module is import-friendly (``build_suggestion``) and also runs as
a CLI for ad-hoc inspection. Conversion is **never** auto-triggered —
the LLM surfaces this payload, the user approves, the user runs the
commands.

Usage (library):

    from suggest_conversion import build_suggestion
    payload = build_suggestion(book_row, campaign_workspace="~/camp/icespire")

Usage (CLI):

    python suggest_conversion.py --book-id 7421
    python suggest_conversion.py --filepath /mnt/g/some.pdf
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from campaignlib import wiring_get

logger = logging.getLogger(__name__)


_DEFAULT_RPGLIB_URL = wiring_get("rpg_library_url")
_DEFAULT_PDF_TRANSLATORS = Path.home() / "src" / "mytools" / "pdf-translators"
_DEFAULT_CONVERT_SCRIPT_NAME = "pdf_to_5etools_v2.py"
_DEFAULT_INGEST_SCRIPT = "fivetools_ingest.py"

# product_type values that map to v2 --type book (vs the default --type adventure).
_BOOK_PRODUCT_TYPES = frozenset(
    {
        "sourcebook",
        "setting",
        "gm_aid",
        "anthology",
        "character_options",
        "magic_items",
        "map_pack",
        "non_rpg",
    }
)

# Average tokens per PDF page once pdf-translators renders prose through
# Claude. Measured empirically at ~500 tokens/page for adventure prose;
# scaled up for reference books that are denser. Conservative default.
_TOKENS_PER_PAGE = 650


@dataclass
class ConversionSuggestion:
    book_id: int | None
    title: str
    filepath: str
    publisher: str
    game_system: str
    product_type: str
    page_count: int
    tags: list[str]
    output_json_path: str
    convert_command: list[str]
    ingest_command: list[str]
    estimated_cost_tokens: int
    estimated_cost_usd_min: float  # at $0.80 / 1M input (Haiku) rough
    estimated_cost_usd_max: float  # at $3.00 / 1M input (Sonnet)
    notes: list[str]
    relative_path: str | None = None
    product_id: str | None = None
    palace: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _map_product_type_to_v2_flags(product_type: str | None) -> list[str]:
    """Translate rpg-library product_type → v2 CLI flags."""
    pt = (product_type or "").strip().lower()
    if pt == "adventure":
        return []  # default
    if pt == "bestiary":
        return ["--type", "book", "--monsters-only"]
    if pt in _BOOK_PRODUCT_TYPES:
        return ["--type", "book"]
    if not pt:
        return []
    return ["--type", "book"]


def _http_get_json(url: str, *, timeout: float = 10.0) -> dict | None:
    """GET ``url`` and return parsed JSON, or None on any failure. Soft-fail
    is deliberate — this is a CLI/library helper where "book not found" is
    a normal, tolerated outcome, not a hard error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            logger.warning("rpg-lib GET %s failed: HTTP %s", url, e.code)
        return None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        logger.warning("rpg-lib GET %s failed: %s", url, e)
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("rpg-lib GET %s returned non-JSON: %s", url, e)
        return None


def _find_book_id_by_filepath(base_url: str, filepath: str) -> int | None:
    """Resolve a book id from an absolute filepath via rpg-lib's search
    endpoint. There's no exact-filepath endpoint, so this mirrors the
    two-tier match (exact filepath, then filename basename) the old
    direct-SQLite query performed: ungrouped (so a variant group's
    representative doesn't hide the specific file), tolerant of
    old/duplicate/draft editions (the old raw-SQL query was too).
    """
    name = Path(filepath).name
    params = {
        "q_name": name, "grouped": "false", "per_page": "50",
        "include_old": "true", "include_drafts": "true", "include_duplicates": "true",
    }
    qs = urllib.parse.urlencode(params)
    result = _http_get_json(f"{base_url}/api/library/search?{qs}")
    books = result.get("results", []) if isinstance(result, dict) else []
    if not isinstance(books, list):
        return None
    for b in books:
        if isinstance(b, dict) and b.get("filepath") == filepath:
            return b.get("id")
    for b in books:
        if isinstance(b, dict) and b.get("filename") == name:
            return b.get("id")
    return None


def _lookup_book(
    rpg_library_url: str | None, *, book_id: int | None = None, filepath: str | None = None
) -> dict | None:
    """HTTP lookup via rpg-lib's ``library_server`` (was direct SQLite —
    GH mneme#9). CLI helper only — runtime retrieval goes via
    rpg-library HTTP per Step 3 design D6, same as this now does.
    """
    if not rpg_library_url:
        return None
    base_url = rpg_library_url.rstrip("/")
    if book_id is None and filepath is not None:
        book_id = _find_book_id_by_filepath(base_url, filepath)
    if book_id is None:
        return None
    return _http_get_json(f"{base_url}/api/library/book/{book_id}")


def estimate_tokens(page_count: int | None, *, per_page: int = _TOKENS_PER_PAGE) -> int:
    """Rough upper-bound on Claude tokens needed to convert ``page_count`` pages."""
    if not isinstance(page_count, int) or page_count <= 0:
        return 0
    return int(math.ceil(page_count * per_page))


def _cost_bounds(tokens: int) -> tuple[float, float]:
    if tokens <= 0:
        return (0.0, 0.0)
    # Haiku input  ~$0.80 / 1M tokens; Sonnet input ~$3.00 / 1M tokens.
    # Output costs 4-5× input; keep it rough and on the cheap side for
    # suggestion UX — the user sees the order of magnitude, not a quote.
    low = tokens * 0.8 / 1_000_000
    high = tokens * 3.0 / 1_000_000
    return (round(low, 3), round(high, 3))


def build_suggestion(
    book: dict,
    *,
    convert_script: str | None = None,
    convert_script_dir: Path | str | None = None,
    ingest_script: str = _DEFAULT_INGEST_SCRIPT,
    python: str = sys.executable,
    palace: str | None = None,
) -> ConversionSuggestion:
    """Assemble the suggestion payload from an rpglib book row.

    ``book`` is a dict matching the rpg-library `BookSummary` / `BookDetail`
    shape — typically delivered by the HTTP retriever or, for ad-hoc CLI
    use, :func:`_lookup_book`.

    By default the convert command targets pdf-translators v2
    (`pdf_to_5etools_v2.py`). The `--type` flag is derived from
    `product_type` (adventure → default, bestiary → `--type book
    --monsters-only`, other → `--type book`).

    ``palace`` is plumbed into the ingest command as `--palace <palace>`
    when provided. The retriever passes the active campaign palace; the
    CLI helper leaves it None.
    """
    filepath = str(book.get("filepath") or "")
    if not filepath:
        raise ValueError("book row is missing 'filepath' — cannot suggest conversion")

    output_json = str(Path(filepath).with_suffix(".json"))
    title = (
        book.get("pdf_title")
        or book.get("filename")
        or Path(filepath).stem
        or "untitled"
    )
    page_count = int(book.get("page_count") or 0)
    tokens = estimate_tokens(page_count)
    cost_low, cost_high = _cost_bounds(tokens)
    product_type = str(book.get("product_type") or "")

    notes: list[str] = []
    if page_count <= 0:
        notes.append("page count missing from rpglib row — cost estimate not reliable")
    if "bestiary" in product_type.lower():
        notes.append(
            "product_type suggests a bestiary — statblocks will route to "
            "wing_bestiary/ at ingest time"
        )
    if page_count >= 100:
        notes.append(
            "page_count >= 100 — append `--batch` to the convert command "
            "for ~50% cost reduction at the price of async (minutes) "
            "completion"
        )

    # Resolve absolute path to the v2 converter so the GM can paste-and-run
    # from any working directory. If `convert_script` is an absolute path,
    # respect it as-is; otherwise join against `convert_script_dir`
    # (defaults to ~/src/mytools/pdf-translators).
    if convert_script is None:
        convert_script = _DEFAULT_CONVERT_SCRIPT_NAME
    script_path = Path(convert_script)
    if not script_path.is_absolute():
        base_dir = Path(convert_script_dir or _DEFAULT_PDF_TRANSLATORS).expanduser()
        script_path = base_dir / script_path
    convert_command = [python, str(script_path), filepath]
    convert_command.extend(_map_product_type_to_v2_flags(product_type))

    ingest_command = [python, ingest_script, output_json]
    if palace:
        ingest_command += ["--palace", palace]
    if book.get("id") is not None:
        ingest_command += ["--book-id", str(book["id"])]

    return ConversionSuggestion(
        book_id=(int(book["id"]) if book.get("id") is not None else None),
        title=str(title),
        filepath=filepath,
        publisher=str(book.get("publisher") or ""),
        game_system=str(book.get("game_system") or ""),
        product_type=product_type,
        page_count=page_count,
        tags=list(book.get("tags") or []),
        output_json_path=output_json,
        convert_command=convert_command,
        ingest_command=ingest_command,
        estimated_cost_tokens=tokens,
        estimated_cost_usd_min=cost_low,
        estimated_cost_usd_max=cost_high,
        notes=notes,
        relative_path=(str(book["relative_path"])
                       if book.get("relative_path") else None),
        product_id=(str(book["product_id"])
                    if book.get("product_id") else None),
        palace=palace,
    )


def suggest_from_rpglib(
    *,
    rpg_library_url: str | None = _DEFAULT_RPGLIB_URL,
    book_id: int | None = None,
    filepath: str | None = None,
    **kwargs: Any,
) -> ConversionSuggestion | None:
    """Look up a book via rpg-lib's HTTP API and build a
    :class:`ConversionSuggestion`."""
    row = _lookup_book(rpg_library_url, book_id=book_id, filepath=filepath)
    if row is None:
        return None
    return build_suggestion(row, **kwargs)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else None)
    parser.add_argument("--rpg-library-url", default=_DEFAULT_RPGLIB_URL)
    parser.add_argument("--book-id", type=int, default=None)
    parser.add_argument("--filepath", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.book_id is None and not args.filepath:
        raise SystemExit("suggest_conversion: pass --book-id or --filepath")
    suggestion = suggest_from_rpglib(
        rpg_library_url=args.rpg_library_url,
        book_id=args.book_id,
        filepath=args.filepath,
    )
    if suggestion is None:
        raise SystemExit("suggest_conversion: book not found in rpglib")
    print(json.dumps(suggestion.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
