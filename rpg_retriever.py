"""
rpg_retriever.py — Step 3 orchestrator: tiered RPG retrieval over three piles.

Returns a single ranked-then-tiered hit list with discriminated records:

    * ``kind="drawer"``      — already-ingested MemPalace prose / table /
                                inset. Sorted by MemPalace AAAK score.
    * ``kind="statblock"``   — already-ingested MemPalace bestiary entry.
    * ``kind="candidate"``   — source the GM *could* ingest. Discriminated
                                further by ``cost``:
        * ``cost="cheap"``    — 5etools-canonical JSON on disk; surfaced
                                via :mod:`fivetools_catalog`. Carries a
                                ``ingest_command`` argv that runs
                                ``fivetools_ingest.py``.
        * ``cost="expensive"`` — rpg-library PDF needing pdf-translators
                                conversion. Carries a ``convert_command``
                                + ``ingest_command`` argv pair.

Tiering (no score normalization across sources):

    1. drawer / statblock                 (MemPalace native order)
    2. candidate (cost: cheap)            (fivetools_catalog score)
    3. candidate (cost: expensive)        (rpg-library /search or /nlq order)

Per-tier truncation via ``k_cheap`` and ``k_expensive``.

Three call modes (per Step 3 design D5):

    * Mode A (search):  ``retrieve(query="drow priestess")`` → ranked tiers.
    * Mode B (scoped):  ``retrieve(query="drow", source="MM")`` → cheap
      pool only (filtered to the named 5etools source); or
      ``retrieve(query="undead", book_id=42)`` → expensive pool only.
    * Mode C (pin):     ``retrieve(file_path=".../bestiary-mm.json",
      filter="name=Drow Priestess of Lolth")`` → one cheap candidate;
      or ``retrieve(book_id=42)`` → one expensive candidate.

rpg-library access is **HTTP-only** (per design D6) — `library_server`
must be running, or expensive-tier candidates are soft-skipped with a
logged warning. The 5etools-canonical catalog is local; cheap-tier
candidates do not depend on any server.
"""

from __future__ import annotations

import argparse
import json
import logging
import shlex
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from mempalace_client import MempalaceClient
from suggest_conversion import build_suggestion

logger = logging.getLogger(__name__)


_DEFAULT_RPGLIB_URL = "http://localhost:8000"
_DEFAULT_HTTP_TIMEOUT = 5.0


# ── rpg-library HTTP client ──────────────────────────────────────────────


def _http_get_json(
    url: str, *, timeout: float = _DEFAULT_HTTP_TIMEOUT
) -> Any | None:
    """GET ``url`` and return parsed JSON. None on connection / parse error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        logger.warning("rpg-library GET %s failed: %s", url, e)
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("rpg-library GET %s returned non-JSON: %s", url, e)
        return None


def _http_post_json(
    url: str, payload: dict, *, timeout: float = _DEFAULT_HTTP_TIMEOUT
) -> Any | None:
    """POST JSON to ``url`` and return parsed JSON response."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        logger.warning("rpg-library POST %s failed: %s", url, e)
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("rpg-library POST %s returned non-JSON: %s", url, e)
        return None


def search_rpglib(
    query: str,
    *,
    base_url: str = _DEFAULT_RPGLIB_URL,
    limit: int = 20,
    game_system: str | None = None,
    product_type: str | None = None,
    book_id: int | None = None,
) -> list[dict]:
    """Search rpg-library for candidate books via its HTTP API.

    Soft-fails to ``[]`` with a logged warning when the server is
    unreachable — drawers and cheap candidates still flow.

    When ``book_id`` is set, fetches ``/book/{id}`` directly and returns
    a one-element list (or empty if not found). Otherwise uses
    ``POST /nlq`` for free-text queries; falls back to
    ``GET /search?q=...`` when ``query`` is empty (used by Mode B
    scoped-search calls that pass only ``game_system`` or
    ``product_type``).
    """
    base_url = base_url.rstrip("/")

    # Mode C pin by book_id: single fetch.
    if book_id is not None:
        detail = _http_get_json(f"{base_url}/api/library/book/{book_id}")
        if isinstance(detail, dict) and detail.get("id") is not None:
            return [detail]
        return []

    if query:
        result = _http_post_json(
            f"{base_url}/api/library/nlq", {"query": query}
        )
        books = result.get("results", []) if isinstance(result, dict) else []
    else:
        params: dict[str, str] = {"per_page": str(int(limit))}
        if game_system:
            params["game_system"] = game_system
        if product_type:
            params["product_type"] = product_type
        qs = urllib.parse.urlencode(params)
        result = _http_get_json(f"{base_url}/api/library/search?{qs}")
        books = result.get("results", []) if isinstance(result, dict) else []

    if not isinstance(books, list):
        return []

    # Apply post-filter for game_system / product_type when NLQ didn't.
    filtered: list[dict] = []
    for b in books:
        if not isinstance(b, dict):
            continue
        if game_system and b.get("game_system") != game_system:
            continue
        if product_type and b.get("product_type") != product_type:
            continue
        filtered.append(b)

    return [b for b in filtered[:limit] if b.get("filepath")]


# ── 5etools-canonical search (local, no network) ─────────────────────────


def _filter_candidates_by_source(
    candidates: list, source: str | None
) -> list:
    if not source:
        return candidates
    src = source.strip().lower()
    return [c for c in candidates if c.source.lower() == src]


def search_fivetools_catalog(
    query: str,
    *,
    catalog,
    limit: int = 20,
    source: str | None = None,
) -> list:
    """Run a name-token search against the 5etools-canonical catalog.

    Returns a list of :class:`fivetools_catalog.Candidate`. Empty when
    the catalog is None or the query is empty *and* no scoping arg is
    set.
    """
    if catalog is None:
        return []
    if not query and not source:
        return []
    import fivetools_catalog as fc

    if not query and source:
        # Source-only scope — return everything from that source up to
        # `limit`. Helps Mode B (rpg_search source="MM") with no query.
        out = [
            r for r in catalog.records
            if r.source.lower() == source.strip().lower()
        ]
        out = out[: limit * 2]
    else:
        out = fc.search(catalog, query, limit=limit * 2)
    return _filter_candidates_by_source(out, source)[:limit]


# ── Result shaping ───────────────────────────────────────────────────────


@dataclass
class RetrievalResult:
    query: str
    hits: list[dict] = field(default_factory=list)
    path: dict = field(default_factory=dict)
    total_before_filter: int = 0
    rpglib_candidates_seen: int = 0
    fivetools_candidates_seen: int = 0
    candidates_cheap_emitted: int = 0
    candidates_expensive_emitted: int = 0
    drawer_hits: int = 0
    statblock_hits: int = 0
    fallback: bool = False
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "query": self.query,
            "hits": self.hits,
            "path": self.path,
            "total_before_filter": self.total_before_filter,
            "rpglib_candidates_seen": self.rpglib_candidates_seen,
            "fivetools_candidates_seen": self.fivetools_candidates_seen,
            "candidates_cheap_emitted": self.candidates_cheap_emitted,
            "candidates_expensive_emitted": self.candidates_expensive_emitted,
            "drawer_hits": self.drawer_hits,
            "statblock_hits": self.statblock_hits,
            "fallback": self.fallback,
        }
        if self.fallback_reason:
            out["fallback_reason"] = self.fallback_reason
        return out


def _classify_drawer_hit(hit: dict) -> str:
    wing = hit.get("wing", "")
    if wing == "wing_bestiary":
        return "statblock"
    return "drawer"


def _shape_drawer_hit(hit: dict, *, book: dict | None) -> dict:
    """Convert a MemPalace hit into the retriever's external hit dict."""
    kind = _classify_drawer_hit(hit)
    entry_type = None
    for candidate in ("entry_type", "matched_via"):
        if hit.get(candidate):
            entry_type = hit[candidate]
            break

    shaped: dict[str, Any] = {
        "kind": kind,
        "source": f"{hit.get('wing', '?')}/{hit.get('room', '?')}",
        "wing": hit.get("wing"),
        "room": hit.get("room"),
        "drawer_id": hit.get("drawer_id"),
        "drawer_text": hit.get("text"),
        "similarity": hit.get("similarity"),
        "distance": hit.get("distance"),
        "entry_type": entry_type,
        "page": hit.get("page"),
        "source_file": hit.get("source_file"),
    }
    if book:
        shaped["book_id"] = book.get("id")
        shaped["title"] = (
            book.get("pdf_title")
            or book.get("display_title")
            or book.get("filename")
        )
        shaped["publisher"] = book.get("publisher")
        shaped["game_system"] = book.get("game_system")
        shaped["product_type"] = book.get("product_type")
        shaped["tags"] = list(book.get("tags") or [])
    return shaped


def _shape_cheap_candidate(
    cand,
    *,
    palace: str | None,
    python: str = "",
    ingest_script: str = "fivetools_ingest.py",
) -> dict:
    """Convert a fivetools_catalog.Candidate into an external hit dict."""
    import sys as _sys
    py = python or _sys.executable

    if cand.entity_type in ("chapter", "section"):
        # Adventure prose — filter by chapter ordinal.
        ordinal = cand.chapter_ordinal if cand.chapter_ordinal is not None else 0
        filter_arg = f"chapter={ordinal}"
    else:
        # Catalog entity — filter by name (and source for disambiguation).
        filter_arg = f"name={cand.name}"
        if cand.source:
            filter_arg += f",source={cand.source}"

    argv = [py, ingest_script, cand.file_path, "--filter", filter_arg]
    if palace:
        argv += ["--palace", palace]

    return {
        "kind": "candidate",
        "cost": "cheap",
        "score": int(cand.score),
        "entity_type": cand.entity_type,
        "name": cand.name,
        "source": cand.source,
        "file_path": cand.file_path,
        "wrapper_key": cand.wrapper_key,
        "chapter_ordinal": cand.chapter_ordinal,
        "page": cand.page,
        "palace": palace,
        "ingest_command": argv,
        "command": shlex.join(argv),
    }


def _shape_expensive_candidate(book: dict, *, palace: str | None) -> dict:
    """Convert an rpg-library book row into an expensive candidate hit."""
    suggestion = build_suggestion(book, palace=palace)
    payload = suggestion.to_dict()
    payload["kind"] = "candidate"
    payload["cost"] = "expensive"
    # rpg-library has no relevance score; constant 0 keeps tier-2 sorting
    # by source-native order (the input list ordering from /nlq or /search).
    payload["score"] = 0
    payload["command"] = shlex.join(suggestion.convert_command)
    return payload


# ── Reconciliation (pure function) ───────────────────────────────────────


def reconcile(
    query: str,
    *,
    rpglib_books: Iterable[dict],
    fivetools_candidates: Iterable = (),
    mempalace_result: dict,
    include_expensive: bool = True,
    include_cheap: bool = True,
    k_cheap: int = 10,
    k_expensive: int = 10,
    palace: str | None = None,
) -> RetrievalResult:
    """Merge MemPalace hits + cheap + expensive candidates into the tiered
    retrieval result. Pure function — no I/O.
    """
    rpglib_index = {
        int(b["id"]): b
        for b in rpglib_books
        if isinstance(b, dict) and b.get("id") is not None
    }
    drawer_hits = mempalace_result.get("results") or []

    fivetools_list = list(fivetools_candidates)
    result = RetrievalResult(
        query=query,
        path=mempalace_result.get("path") or {},
        total_before_filter=int(mempalace_result.get("total_before_filter", 0) or 0),
        rpglib_candidates_seen=len(rpglib_index),
        fivetools_candidates_seen=len(fivetools_list),
        fallback=bool(mempalace_result.get("fallback")),
        fallback_reason=mempalace_result.get("fallback_reason"),
    )

    # ── Tier 1: drawers / statblocks ─────────────────────────────────────
    covered_book_ids: set[int] = set()
    for raw in drawer_hits:
        book_id = _coerce_int(raw.get("book_id"))
        if book_id is None:
            md = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else None
            if md:
                book_id = _coerce_int(md.get("book_id"))
        book = rpglib_index.get(book_id) if book_id is not None else None
        shaped = _shape_drawer_hit(raw, book=book)
        if shaped["kind"] == "statblock":
            result.statblock_hits += 1
        else:
            result.drawer_hits += 1
        result.hits.append(shaped)
        if book_id is not None:
            covered_book_ids.add(book_id)

    # ── Tier 2: cheap candidates (5etools-canonical) ─────────────────────
    if include_cheap:
        for cand in fivetools_list[:k_cheap]:
            result.hits.append(_shape_cheap_candidate(cand, palace=palace))
            result.candidates_cheap_emitted += 1

    # ── Tier 3: expensive candidates (rpg-library PDFs) ──────────────────
    if include_expensive and k_expensive > 0:
        emitted = 0
        for bid, book in rpglib_index.items():
            if bid in covered_book_ids:
                continue
            if not book.get("filepath"):
                continue
            result.hits.append(_shape_expensive_candidate(book, palace=palace))
            result.candidates_expensive_emitted += 1
            emitted += 1
            if emitted >= k_expensive:
                break

    return result


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        try:
            return int(value)
        except ValueError:
            return None
    return None


# ── Top-level orchestrator ───────────────────────────────────────────────


def _resolve_active_palace(palace: str | None) -> str | None:
    """Return the campaign palace name to use in cheap/expensive
    one-liners. Defaults to the explicit arg; otherwise None (the caller
    can paste-and-edit before running).
    """
    if palace:
        return palace
    return None


def _load_catalog_silently(data_root: Path | None):
    """Best-effort load the 5etools catalog. Returns None on any failure
    so cheap-tier candidates degrade gracefully.
    """
    if data_root is None:
        logger.warning("no fivetools_data_root configured — cheap candidates disabled")
        return None
    try:
        import fivetools_catalog as fc
    except ImportError:
        logger.warning("fivetools_catalog import failed — cheap candidates disabled")
        return None
    try:
        return fc.load_or_build(data_root)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fivetools_catalog load failed: %s — cheap candidates disabled", exc)
        return None


def retrieve(
    query: str = "",
    *,
    palace: str | None = None,
    rpg_library_url: str = _DEFAULT_RPGLIB_URL,
    fivetools_data_root: Path | None = None,
    fivetools_catalog=None,
    limit: int = 10,
    k_cheap: int = 10,
    k_expensive: int = 10,
    include_cheap: bool = True,
    include_expensive: bool = True,
    game_system: str | None = None,
    product_type: str | None = None,
    source: str | None = None,
    book_id: int | None = None,
    file_path: str | None = None,
    pin_filter: str | None = None,
    mp_client: MempalaceClient | None = None,
    max_depth: int = 2,
) -> dict:
    """Run one tiered retrieval. Returns the result as a dict.

    Modes (per Step 3 design D5):
        * Mode A — pass ``query``. Searches all sources.
        * Mode B — pass ``query`` plus one of ``source`` / ``book_id``
          to scope the candidate pool.
        * Mode C — leave ``query`` empty; pass ``file_path`` (with
          optional ``pin_filter``) for a cheap pin, or ``book_id`` for
          an expensive pin.
    """
    active_palace = _resolve_active_palace(palace)

    # ── Mode C cheap pin: synthesize one cheap candidate, skip search ────
    if not query and file_path:
        return _retrieve_cheap_pin(
            file_path=file_path,
            pin_filter=pin_filter,
            palace=active_palace,
        )

    # ── Mode C expensive pin: single-book lookup ─────────────────────────
    # (handled by search_rpglib's book_id branch)

    # ── Validate: must have at least one driver ──────────────────────────
    if not query and book_id is None and source is None:
        raise ValueError(
            "rpg_retriever.retrieve: provide `query`, or one of "
            "`book_id` / `source` / `file_path` for a pin/scoped call"
        )

    # ── rpg-library (expensive candidates) ───────────────────────────────
    rpglib_books: list[dict] = []
    if include_expensive:
        rpglib_books = search_rpglib(
            query,
            base_url=rpg_library_url,
            limit=max(limit * 2, 10),
            game_system=game_system,
            product_type=product_type,
            book_id=book_id,
        )

    # ── 5etools catalog (cheap candidates) ───────────────────────────────
    cheap_candidates = []
    if include_cheap and book_id is None:  # book_id alone targets expensive only
        cat = fivetools_catalog or _load_catalog_silently(fivetools_data_root)
        cheap_candidates = search_fivetools_catalog(
            query, catalog=cat, limit=max(k_cheap * 2, 10), source=source
        )

    # ── MemPalace (already-ingested drawers) ─────────────────────────────
    owns_client = mp_client is None
    mempalace_result: dict
    if owns_client:
        mp_client = MempalaceClient(palace=active_palace)
        try:
            mp_client.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning("MemPalace start failed: %s — drawer tier empty", exc)
            mempalace_result = {"results": [], "path": {}, "fallback": True,
                                "fallback_reason": f"mempalace unavailable: {exc}"}
            mp_client = None
            owns_client = False
    if mp_client is not None:
        try:
            mempalace_result = mp_client.search_hierarchical(
                query, limit=limit, max_depth=max_depth
            ) if query else {"results": [], "path": {}, "fallback": False}
        except Exception as exc:  # noqa: BLE001
            logger.warning("MemPalace search failed: %s", exc)
            mempalace_result = {"results": [], "path": {}, "fallback": True,
                                "fallback_reason": f"mempalace search error: {exc}"}
        finally:
            if owns_client:
                mp_client.close()

    reconciled = reconcile(
        query,
        rpglib_books=rpglib_books,
        fivetools_candidates=cheap_candidates,
        mempalace_result=mempalace_result,
        include_expensive=include_expensive,
        include_cheap=include_cheap,
        k_cheap=k_cheap,
        k_expensive=k_expensive,
        palace=active_palace,
    )
    return reconciled.to_dict()


def _retrieve_cheap_pin(
    *,
    file_path: str,
    pin_filter: str | None,
    palace: str | None,
) -> dict:
    """Mode C cheap pin — synthesize a single cheap-candidate hit
    pointing at ``file_path`` with the GM-supplied filter, no search.
    """
    import sys as _sys

    fp = str(Path(file_path).expanduser())
    name_guess = Path(fp).stem
    argv = [_sys.executable, "fivetools_ingest.py", fp]
    if pin_filter:
        argv += ["--filter", pin_filter]
    if palace:
        argv += ["--palace", palace]

    candidate = {
        "kind": "candidate",
        "cost": "cheap",
        "score": 100,  # pin → treat as exact
        "entity_type": "pin",
        "name": pin_filter or name_guess,
        "source": "",
        "file_path": fp,
        "wrapper_key": "",
        "chapter_ordinal": None,
        "page": None,
        "palace": palace,
        "ingest_command": argv,
        "command": shlex.join(argv),
    }
    return {
        "query": "",
        "hits": [candidate],
        "path": {},
        "total_before_filter": 1,
        "rpglib_candidates_seen": 0,
        "fivetools_candidates_seen": 1,
        "candidates_cheap_emitted": 1,
        "candidates_expensive_emitted": 0,
        "drawer_hits": 0,
        "statblock_hits": 0,
        "fallback": False,
    }


# ── CLI ──────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[1] if __doc__ else None,
    )
    parser.add_argument("query", nargs="?", default="", help="Free-text query (Mode A/B).")
    parser.add_argument("--palace", default=None)
    parser.add_argument("--rpg-library-url", default=_DEFAULT_RPGLIB_URL)
    parser.add_argument("--fivetools-data-root", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--k-cheap", type=int, default=10)
    parser.add_argument("--k-expensive", type=int, default=10)
    parser.add_argument(
        "--no-cheap", dest="include_cheap", action="store_false", default=True,
    )
    parser.add_argument(
        "--no-expensive", dest="include_expensive", action="store_false", default=True,
    )
    parser.add_argument("--game-system", default=None)
    parser.add_argument("--product-type", default=None)
    parser.add_argument("--source", default=None,
                        help="Scope cheap pool to a 5etools source code (MM, OotA, ...).")
    parser.add_argument("--book-id", type=int, default=None,
                        help="Scope expensive pool to one rpg-library book id.")
    parser.add_argument("--file-path", default=None,
                        help="Mode C cheap pin: pin to a specific 5etools JSON file.")
    parser.add_argument("--filter", dest="pin_filter", default=None,
                        help="Mode C cheap pin: filter spec for fivetools_ingest.")
    parser.add_argument("--max-depth", type=int, default=2, choices=[0, 1, 2])
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def _resolve_cli_defaults(args: argparse.Namespace) -> argparse.Namespace:
    """Backfill CLI args from config.yaml + env vars where unset, mirroring
    the MCP server's resolution. Lets ``python rpg_retriever.py "query"``
    from a campaign workspace pick up the configured palace and 5etools
    data root without forcing every flag on the command line.
    """
    import os
    from campaignlib import find_default_config, load_config

    try:
        config_path = find_default_config(__file__)
        config, _ = load_config(config_path)
    except Exception:  # noqa: BLE001
        config = {}

    if args.fivetools_data_root is None:
        env = os.environ.get("FIVETOOLS_DATA_ROOT")
        cfg = config.get("fivetools_data_root")
        if env:
            args.fivetools_data_root = Path(env).expanduser()
        elif isinstance(cfg, str) and cfg:
            args.fivetools_data_root = Path(cfg).expanduser()

    if args.rpg_library_url == _DEFAULT_RPGLIB_URL:
        env = os.environ.get("RPG_LIBRARY_URL")
        cfg = config.get("rpg_library_url")
        if env:
            args.rpg_library_url = env
        elif isinstance(cfg, str) and cfg:
            args.rpg_library_url = cfg

    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    args = _resolve_cli_defaults(args)
    out = retrieve(
        args.query,
        palace=args.palace,
        rpg_library_url=args.rpg_library_url,
        fivetools_data_root=args.fivetools_data_root,
        limit=args.limit,
        k_cheap=args.k_cheap,
        k_expensive=args.k_expensive,
        include_cheap=args.include_cheap,
        include_expensive=args.include_expensive,
        game_system=args.game_system,
        product_type=args.product_type,
        source=args.source,
        book_id=args.book_id,
        file_path=args.file_path,
        pin_filter=args.pin_filter,
        max_depth=args.max_depth,
    )
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
