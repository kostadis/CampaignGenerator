"""
fivetools_catalog.py — name index over the canonical 5etools data tree.

Step 2 of the three-pile RLM plan. The retriever uses this to surface
"cheap" candidates: entities sitting on disk in 5etools JSON form, ready
for ``fivetools_ingest.py`` to consume. The catalog is purely an
awareness layer — it knows where things are, not what they say.

Shape::

    >>> cat = build_catalog(Path("~/src/5e-tools-kostadis/data").expanduser())
    >>> hits = search(cat, "drow priestess")
    >>> hits[0]
    Candidate(entity_type='monster', name='Drow Priestess of Lolth',
              source='MM', file_path='.../bestiary-mm.json',
              wrapper_key='monster', score=80, chapter_ordinal=None, page=129)

The catalog itself is small (a few MB of records for the full ~106 MB
data tree) but builds in ~10 s on a fresh read. ``load_or_build`` caches
to ``<data_root>/.fivetools_catalog.pkl`` and validates against the
deepest mtime under the data root, so subsequent loads are sub-100 ms.

This module does not call MemPalace, the Anthropic API, or rpg-library.
It walks the filesystem and emits dataclass records. The retriever
(``rpg_retriever.py``, Step 3) is what merges these candidates with
rpg-library candidates and constructs the ingest one-liner.
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# fivetools_ingest moved to pipelines/content_ingest/ in the source-tree
# restructure (docs/design/SourceTreeRestructure.md); this file itself is
# part of the still-unmigrated `rlm` cluster, so import the new location
# directly rather than a bare `import fivetools_ingest`.
from pipelines.content_ingest import fivetools_ingest
import resolve_refs

logger = logging.getLogger(__name__)


_CACHE_FILENAME = ".fivetools_catalog.pkl"
_CACHE_VERSION = 1
# 5etools root is EXTERNAL config (mneme-owned). Precedence:
# FIVETOOLS_DATA_ROOT → mneme wiring → None. See
# resolve_refs.default_fivetools_data_root. None here (no env, no wiring) keeps
# import safe; load_or_build raises a clear error if the root is still unset.
_DEFAULT_DATA_ROOT = resolve_refs.default_fivetools_data_root()


# ── Records ────────────────────────────────────────────────────────────────


@dataclass
class Candidate:
    """One cheap-candidate record. Carries enough data for the retriever
    (Step 3) to construct a ``fivetools_ingest.py --filter ...`` one-liner.

    Fields:
        entity_type   — the wrapper key (``monster``, ``spell``, ...) or
                        ``"chapter"`` / ``"section"`` for adventure prose.
        name          — entity name as it appears in JSON.
        source        — 5etools source code (``MM``, ``OotA``, ...).
        file_path     — absolute path to the JSON file containing the entity.
        wrapper_key   — the catalog wrapper key, or ``"data"`` for adventure.
        score         — search-time only; 0 in stored catalog records.
        chapter_ordinal — for adventure chapters/sections: zero-based
                          index of the chapter under ``data[]``. ``None``
                          for catalog entities.
        page          — page number when present in the source JSON.
    """
    entity_type: str
    name: str
    source: str
    file_path: str
    wrapper_key: str
    score: int = 0
    chapter_ordinal: int | None = None
    page: int | None = None


@dataclass
class CatalogIndex:
    """In-memory index. Pickled to disk via ``load_or_build``."""
    entities: list[Candidate] = field(default_factory=list)
    data_root: str = ""
    deepest_mtime: float = 0.0
    built_at: float = 0.0
    version: int = _CACHE_VERSION


# ── Build ──────────────────────────────────────────────────────────────────


def build_catalog(
    data_root: Path,
    *,
    on_warning=None,
) -> CatalogIndex:
    """Walk ``data_root`` and emit a CatalogIndex over every entity found.

    Catalog files (``bestiary-*.json``, ``spells-*.json``, ``items*.json``,
    ``class/*.json``, ``races.json``, ``backgrounds.json``, ``feats.json``,
    ``actions.json``, ``variantrules.json``, …) are walked via
    :func:`fivetools_ingest.iter_catalog_entities`.

    Adventure / book files (``adventure/*.json``, ``book/*.json``) are
    walked top-down: each top-level ``section`` becomes a ``chapter``
    record with ``chapter_ordinal`` set; each named child one level deep
    becomes a ``section`` record (so place names like ``Velkynvelve``
    inside ``Prisoners of the Drow`` are findable).
    """
    on_warn = on_warning or (lambda m: logger.warning("catalog: %s", m))
    data_root = Path(data_root).expanduser().resolve()
    if not data_root.is_dir():
        raise FileNotFoundError(f"data root {data_root} does not exist")

    entities: list[Candidate] = []
    deepest_mtime = 0.0
    started = time.time()
    file_count = 0

    for json_path in _iter_json_files(data_root):
        try:
            mtime = json_path.stat().st_mtime
            if mtime > deepest_mtime:
                deepest_mtime = mtime
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            on_warn(f"skip {json_path}: {exc}")
            continue
        file_count += 1
        kind = fivetools_ingest.detect_doc_kind(raw)
        if kind == "catalog":
            entities.extend(_index_catalog_file(json_path, raw))
        elif kind == "adventure":
            entities.extend(_index_adventure_file(json_path, raw))
        # 'unknown' is silently skipped — gendata-*, index files, etc.

    elapsed = time.time() - started
    logger.info(
        "catalog: %d entities from %d files in %s (%.2fs)",
        len(entities), file_count, data_root, elapsed,
    )
    return CatalogIndex(
        entities=entities,
        data_root=str(data_root),
        deepest_mtime=deepest_mtime,
        built_at=time.time(),
    )


def _iter_json_files(root: Path) -> Iterator[Path]:
    for p in root.rglob("*.json"):
        # Skip hidden + tooling artefacts.
        if p.name.startswith("."):
            continue
        # ``index.json`` is a per-shard-dir manifest, not entity data.
        if p.name == "index.json":
            continue
        # Shard meta / loader manifests.
        if p.name.startswith("foundry-"):
            continue
        if "node_modules" in p.parts:
            continue
        yield p


def _index_catalog_file(json_path: Path, raw: dict) -> Iterator[Candidate]:
    for prop, entity in fivetools_ingest.iter_catalog_entities(raw):
        name = entity.get("name")
        if not isinstance(name, str) or not name:
            continue
        source = entity.get("source")
        if not isinstance(source, str):
            source = ""
        page = entity.get("page") if isinstance(entity.get("page"), int) else None
        yield Candidate(
            entity_type=prop,
            name=name,
            source=source,
            file_path=str(json_path),
            wrapper_key=prop,
            page=page,
        )


def _index_adventure_file(json_path: Path, raw: dict) -> Iterator[Candidate]:
    src = _adventure_source_code(raw)
    chapter_ordinal = 0
    # Re-use the existing top-level walker (covers homebrew + official shapes).
    for top in fivetools_ingest._iter_top_level_entries(raw):
        if not isinstance(top, dict):
            continue
        name = top.get("name")
        if not isinstance(name, str) or not name:
            chapter_ordinal += 1
            continue
        # Top-level: a chapter (or named section).
        is_chapter = top.get("type") == "section"
        yield Candidate(
            entity_type="chapter" if is_chapter else "section",
            name=name,
            source=src,
            file_path=str(json_path),
            wrapper_key="data",
            chapter_ordinal=chapter_ordinal,
        )
        # One level deep — named sub-rooms (e.g. "Velkynvelve").
        for child in (top.get("entries") or []):
            if not isinstance(child, dict):
                continue
            cname = child.get("name")
            if isinstance(cname, str) and cname:
                yield Candidate(
                    entity_type="section",
                    name=cname,
                    source=src,
                    file_path=str(json_path),
                    wrapper_key="data",
                    chapter_ordinal=chapter_ordinal,
                )
        chapter_ordinal += 1


def _adventure_source_code(raw: dict) -> str:
    if not isinstance(raw, dict):
        return ""
    # Preferred: _meta.sources[0].json (the canonical 5etools source code).
    srcs = ((raw.get("_meta") or {}).get("sources") or [])
    if srcs and isinstance(srcs[0], dict):
        s = srcs[0].get("json") or srcs[0].get("abbreviation")
        if isinstance(s, str) and s:
            return s
    # Fallback: top-level adventure/book index entry.
    for key in ("adventure", "book"):
        v = raw.get(key)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            s = v[0].get("source") or v[0].get("id")
            if isinstance(s, str) and s:
                return s
    return ""


# ── Search ─────────────────────────────────────────────────────────────────


_TOKEN_RE = re.compile(r"\w+")

# Type-quality offsets applied as a tie-breaker on top of the name score.
# Primary catalog entities (the things a GM usually means when searching)
# outrank their *Fluff companions and ambient adventure prose at the same
# match strength.
_TYPE_QUALITY_BONUS = 2
_TYPE_QUALITY_PENALTY = -2


def search(catalog: CatalogIndex, query: str, *, limit: int = 20) -> list[Candidate]:
    """Rank-ordered case-insensitive search over the catalog.

    Scoring (highest wins):
      100 — exact name match
       80 — name starts with query
       60 — query is a substring of the name
       20-50 — token overlap between query and name (10 per shared token)

    A small type-quality offset is applied as a tie-breaker: primary
    entities (monster / spell / item / class / …) get +2, ``*Fluff``
    gets -2. This ensures e.g. the canonical "Fireball" spell outranks
    "FireballFluff" or an adventure chapter accidentally named "Fireball"
    at the same match strength.

    Final tie-breaks are alphabetical on name then file_path so results
    are deterministic across runs.
    """
    if not isinstance(query, str):
        return []
    q = query.lower().strip()
    if not q:
        return []
    q_tokens = set(_TOKEN_RE.findall(q))

    out: list[Candidate] = []
    for c in catalog.entities:
        score = _score(c.name, q, q_tokens)
        if score <= 0:
            continue
        score += _type_quality(c.entity_type)
        out.append(Candidate(
            entity_type=c.entity_type,
            name=c.name,
            source=c.source,
            file_path=c.file_path,
            wrapper_key=c.wrapper_key,
            score=score,
            chapter_ordinal=c.chapter_ordinal,
            page=c.page,
        ))
    out.sort(key=lambda c: (-c.score, c.name.lower(), c.file_path))
    return out[:limit]


def _score(name: str, q: str, q_tokens: set[str]) -> int:
    if not name:
        return 0
    name_lower = name.lower()
    if name_lower == q:
        return 100
    if name_lower.startswith(q):
        return 80
    if q in name_lower:
        return 60
    name_tokens = set(_TOKEN_RE.findall(name_lower))
    overlap = len(q_tokens & name_tokens)
    if overlap == 0:
        return 0
    return 20 + 10 * overlap


def _type_quality(entity_type: str) -> int:
    if entity_type.endswith("Fluff"):
        return _TYPE_QUALITY_PENALTY
    if entity_type in ("chapter", "section"):
        return 0
    return _TYPE_QUALITY_BONUS


# ── Cache ──────────────────────────────────────────────────────────────────


def cache_path(data_root: Path) -> Path:
    return Path(data_root).expanduser().resolve() / _CACHE_FILENAME


def load_or_build(
    data_root: Path,
    *,
    force_rebuild: bool = False,
) -> CatalogIndex:
    """Load a cached catalog if fresh, otherwise rebuild and write the cache.

    Cache freshness check: deepest mtime over all walked JSON files
    against ``CatalogIndex.deepest_mtime``. Any newer file → rebuild.

    Cache failures (corrupt pickle, version mismatch, write error) are
    logged but never raised — the catalog is always recoverable from
    the source tree.
    """
    if data_root is None:
        raise SystemExit(
            "fivetools_catalog: 5etools data root not configured. Pass it "
            "explicitly, or set FIVETOOLS_DATA_ROOT / render config/wiring.yaml "
            "(fivetools_data_root — mneme-owned external config)."
        )
    data_root = Path(data_root).expanduser().resolve()
    cache = cache_path(data_root)

    if not force_rebuild and cache.is_file():
        payload = _try_load_cache(cache)
        if payload is not None:
            current = _deepest_mtime(data_root)
            if current <= payload.deepest_mtime + 0.001:
                logger.info("catalog: cache hit (%d entities)", len(payload.entities))
                return payload
            logger.info("catalog: cache stale (mtime drift); rebuilding")

    catalog = build_catalog(data_root)
    try:
        cache.write_bytes(pickle.dumps(catalog))
    except OSError as exc:
        logger.warning("catalog cache write failed: %s", exc)
    return catalog


def _try_load_cache(cache: Path) -> CatalogIndex | None:
    try:
        payload = pickle.loads(cache.read_bytes())
    except (OSError, pickle.UnpicklingError, EOFError, ValueError, AttributeError) as exc:
        logger.warning("catalog cache load failed: %s; rebuilding", exc)
        return None
    if not isinstance(payload, CatalogIndex):
        return None
    if payload.version != _CACHE_VERSION:
        logger.info("catalog: cache version mismatch (%s); rebuilding", payload.version)
        return None
    return payload


def _deepest_mtime(root: Path) -> float:
    deepest = 0.0
    for p in _iter_json_files(root):
        try:
            m = p.stat().st_mtime
            if m > deepest:
                deepest = m
        except OSError:
            pass
    return deepest


# ── Stats ──────────────────────────────────────────────────────────────────


def count_by_type(catalog: CatalogIndex) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in catalog.entities:
        out[c.entity_type] = out.get(c.entity_type, 0) + 1
    return out


# ── CLI ────────────────────────────────────────────────────────────────────


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build/query the 5etools catalog.")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    build_p = sub.add_parser("build", help="Build the catalog and cache it.")
    build_p.add_argument(
        "data_root", type=Path, nargs="?", default=_DEFAULT_DATA_ROOT,
        help=f"5etools data tree (default {_DEFAULT_DATA_ROOT}).",
    )
    build_p.add_argument(
        "--force", action="store_true",
        help="Force rebuild even if the cache is fresh.",
    )

    search_p = sub.add_parser("search", help="Search the catalog.")
    search_p.add_argument("query", type=str)
    search_p.add_argument(
        "--data-root", type=Path, default=_DEFAULT_DATA_ROOT,
        help=f"5etools data tree (default {_DEFAULT_DATA_ROOT}).",
    )
    search_p.add_argument("--limit", type=int, default=20)

    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.cmd == "build":
        cat = load_or_build(args.data_root, force_rebuild=args.force)
        print(json.dumps({
            "data_root": cat.data_root,
            "entities": len(cat.entities),
            "by_type": count_by_type(cat),
            "cache": str(cache_path(args.data_root)),
        }, indent=2))
        return 0
    if args.cmd == "search":
        cat = load_or_build(args.data_root)
        hits = search(cat, args.query, limit=args.limit)
        for h in hits:
            payload: dict = {
                "score": h.score,
                "type": h.entity_type,
                "name": h.name,
                "source": h.source,
                "file": h.file_path,
                "wrapper_key": h.wrapper_key,
            }
            if h.chapter_ordinal is not None:
                payload["chapter_ordinal"] = h.chapter_ordinal
            if h.page is not None:
                payload["page"] = h.page
            print(json.dumps(payload))
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
