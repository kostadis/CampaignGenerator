"""
fivetools_ingest.py — push a 5etools JSON file into MemPalace.

The 5etools schema covers two distinct document shapes:

* **Adventure / book** — ``{data: [{type:"section", entries:[...]}]}``
  (chapters, scenes, prose, inline statblocks). pdf-translators
  outputs this shape. The homebrew variant uses ``adventure`` +
  ``adventureData`` wrapper keys; the sourcebook variant uses
  ``book`` + ``bookData``. Both are handled identically.
* **Catalog** — ``{monster:[...], spell:[...], item:[...], class:[...],
  ...}`` keyed by entity wrapper key. Canonical 5etools repository
  files (``bestiary-mm.json``, ``spells-phb.json``, …) use this shape.

Each top-level entity becomes one drawer:

    * monster / vehicle / object → wing_bestiary
    * spell / psionic            → wing_spells
    * item / itemGroup / baseitem / magicvariant / reward → wing_items
    * class / subclass / classFeature / subclassFeature   → wing_classes
    * race / subrace / background / feat / deity → wing_lore
    * variantrule / condition / disease / status / action → wing_rules
    * adventure prose (sections / scenes / etc.)          → wing_rpglib
    * statblocks inside adventure prose                   → wing_bestiary
    * *Fluff entries                                      → wing_lore

Book-level metadata (book_id, display_title, publisher, game_system,
product_type, tags, series) is snapshot-copied from ``rpg_library.db``
at ingest time so retrieval-time filtering stays a Chroma metadata
query (no cross-DB join). The source_filepath stays verbatim so callers
can jump back to the PDF at any point.

Idempotence: the (json_path, size, mtime) tuple is recorded in a
sidecar state file so re-running on an unchanged JSON is a no-op. Pass
``--force`` to override, or ``--replace`` to also wipe drawers from a
previous ingest of this book before re-adding.

Usage (--palace is always required — alias or absolute path):
    python fivetools_ingest.py path/to/adventure.json --palace abyss
    python fivetools_ingest.py path/to/bestiary-mm.json --palace chat
    python fivetools_ingest.py path/to/bestiary-mm.json --palace chat --filter "name=Drow Priestess of Lolth"
    python fivetools_ingest.py path/to/bestiary-mm.json --palace chat --filter "name=Drow,source=MM"
    python fivetools_ingest.py path/to/adventure.json --palace /abs/path/to/palace
    python fivetools_ingest.py path/to/adventure.json --palace abyss --book-id 7421
    python fivetools_ingest.py path/to/adventure.json --palace abyss --force
    python fivetools_ingest.py path/to/adventure.json --palace abyss --replace
    python fivetools_ingest.py path/to/adventure.json --palace abyss --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterator

from mempalace_client import MempalaceClient

import fivetools_copy
import fivetools_render

logger = logging.getLogger(__name__)


# ── Defaults ─────────────────────────────────────────────────────────────

_DEFAULT_RPGLIB_DB = Path.home() / "src" / "mytools" / "rpg-lib" / "rpg_library.db"
_DEFAULT_PDF_TRANSLATORS = Path.home() / "src" / "mytools" / "pdf-translators"
_DEFAULT_FIVETOOLS_DATA_ROOT = Path.home() / "src" / "5etools-kostadis" / "data"
_STATE_DIRNAME = ".fivetools_ingest"
_STATE_VERSION = 1

# Entry types we ingest from adventure-shape docs. Unknown types are
# skipped with a debug log.
_STATBLOCK_TYPES = {"statblock", "statblockInline"}
_PROSE_CONTAINER_TYPES = {
    "section",
    "entries",
    "inset",
    "insetReadaloud",
    "quote",
    "variantInner",
    "variantBlock",
}
_PROSE_LEAF_TYPES = {"p", "paragraph", "quote"}
_TABLE_TYPES = {"table", "tableGroup"}


# Catalog wrapper-key → MemPalace wing routing. Anything not listed and
# not ending in "Fluff" falls through to ``wing_lore`` (with a warning).
_WRAPPER_KEY_WINGS = {
    "monster": "wing_bestiary",
    "vehicle": "wing_bestiary",
    "object": "wing_bestiary",
    "spell": "wing_spells",
    "psionic": "wing_spells",
    "item": "wing_items",
    "itemGroup": "wing_items",
    "baseitem": "wing_items",
    "magicvariant": "wing_items",
    "reward": "wing_items",
    "class": "wing_classes",
    "subclass": "wing_classes",
    "classFeature": "wing_classes",
    "subclassFeature": "wing_classes",
    "optionalfeature": "wing_classes",
    "race": "wing_lore",
    "subrace": "wing_lore",
    "background": "wing_lore",
    "feat": "wing_lore",
    "deity": "wing_lore",
    "charoption": "wing_lore",
    "variantrule": "wing_rules",
    "condition": "wing_rules",
    "disease": "wing_rules",
    "status": "wing_rules",
    "action": "wing_rules",
    "sense": "wing_rules",
    "skill": "wing_rules",
    "trap": "wing_rules",
    "hazard": "wing_rules",
    "language": "wing_rules",
}

# Top-level keys that are not entities (filter from catalog dispatch).
_NON_ENTITY_TOP_KEYS = {
    "_meta",
    "adventure",
    "book",
    "monsterTemplate",
    "monsterTemplateGroup",
    "_xtraData",
    "_test",
}

# Wrapper keys that ship inside larger items.json / items-base.json
# files but aren't independent entities for ingest purposes.
_SKIPPED_CATALOG_KEYS = {
    "itemProperty",
    "itemType",
    "itemTypeAdditionalEntries",
    "itemEntry",
    "itemMastery",
    "linkedLootTables",
}


# ── Validation hook into pdf-translators ─────────────────────────────────


def _load_adventure_model(module_root: Path, *, strict: bool = False):
    """Import adventure_model lazily so the script still runs for
    ``--dry-run`` or ``--help`` without pdf-translators on the machine.

    Returns ``None`` if the module can't be imported. Callers treat that
    as "validator unavailable" and skip the schema check — validation
    is best-effort metadata, not load-bearing. In ``strict`` mode we
    raise instead, because the user has asked for hard enforcement.
    """
    if str(module_root) not in sys.path:
        sys.path.insert(0, str(module_root))
    try:
        import adventure_model  # noqa: WPS433 — intentional late import

        return adventure_model
    except ImportError as exc:
        msg = (
            f"fivetools_ingest: cannot import adventure_model from {module_root!r}: {exc}. "
            "Pass --pdf-translators with the correct path to enable schema validation."
        )
        if strict:
            raise SystemExit(msg)
        logger.warning("%s Proceeding without validation.", msg)
        return None


def validate_adventure_json(raw: dict, module_root: Path, strict: bool = False) -> list[str]:
    """Run pdf-translators' structural validator. Returns a list of issues
    (empty when the JSON is well-formed or the validator is unavailable).
    Raises on malformed JSON only when ``strict=True``.
    """
    mod = _load_adventure_model(module_root, strict=strict)
    if mod is None:
        return []
    try:
        mode_enum = mod.ValidationMode
    except AttributeError:
        # API drift: older builds exposed mod.ErrorMode under that name.
        mode_enum = getattr(mod, "ErrorMode", None)
        if mode_enum is None:
            msg = (
                "fivetools_ingest: adventure_model exposes neither "
                "ValidationMode nor ErrorMode — pdf-translators API has drifted."
            )
            if strict:
                raise SystemExit(msg)
            logger.warning("%s Skipping validation.", msg)
            return []
    ctx = mod.BuildContext(mode=mode_enum.STRICT if strict else mode_enum.WARN)
    mod.parse_document(raw, ctx=ctx)
    errs = getattr(ctx.result, "errors", None) or []
    return [str(e) for e in errs]


def validate_doc(raw: Any, kind: str, module_root: Path, strict: bool = False) -> list[str]:
    """Kind-aware validation dispatch.

    ``adventure`` shapes go through pdf-translators' adventure_model.
    ``catalog`` shapes have no Python-side validator yet — the JSON
    Schemas live in ``5etools-kostadis/node_modules/5etools-utils/lib/
    schema/`` but porting them is deferred (Batch B in the audit).
    """
    if kind == "adventure":
        return validate_adventure_json(raw, module_root, strict=strict)
    return []


# ── rpglib lookup (direct SQLite — read-only) ────────────────────────────


_BOOK_COLUMNS = (
    "id",
    "filename",
    "filepath",
    "publisher",
    "game_system",
    "product_type",
    "series",
    "tags",
    "page_count",
    "pdf_title",
    "pdf_author",
    "min_level",
    "max_level",
)


def lookup_book(
    db_path: Path,
    *,
    book_id: int | None = None,
    filepath: str | None = None,
) -> dict | None:
    """Return the rpglib row for ``book_id`` or a ``filepath`` match, or None.

    Direct SQLite read — rpglib has no Python API. Switching to MCP later
    is a one-function rewrite; callers only see the dict return shape.
    """
    if not db_path.is_file():
        logger.warning("rpglib db not found at %s — ingesting without book metadata", db_path)
        return None
    cols = ", ".join(_BOOK_COLUMNS)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        logger.warning("rpglib db open failed (%s) — skipping metadata lookup", exc)
        return None

    try:
        conn.row_factory = sqlite3.Row
        if book_id is not None:
            row = conn.execute(
                f"SELECT {cols} FROM books WHERE id = ?", (book_id,)
            ).fetchone()
        elif filepath is not None:
            row = conn.execute(
                f"SELECT {cols} FROM books WHERE filepath = ?", (filepath,)
            ).fetchone()
            if row is None:
                # Fuzzy fallback: match by basename when the caller didn't
                # pin the full path (common for JSONs copied out of the
                # source tree).
                row = conn.execute(
                    f"SELECT {cols} FROM books WHERE filename = ? LIMIT 1",
                    (Path(filepath).name,),
                ).fetchone()
        else:
            return None
    finally:
        conn.close()

    if row is None:
        return None
    data = dict(row)
    tags_raw = data.get("tags")
    if isinstance(tags_raw, str):
        try:
            data["tags"] = json.loads(tags_raw)
        except json.JSONDecodeError:
            data["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]
    return data


# ── Document shape detection ─────────────────────────────────────────────

_ADVENTURE_SECTION_TYPES = {
    "section", "entries", "inset", "insetReadaloud", "p", "paragraph", "quote",
    "variantInner", "variantBlock",
}


def detect_doc_kind(raw: Any) -> str:
    """Return ``"adventure"``, ``"catalog"``, or ``"unknown"``.

    A doc is **adventure** when it carries ``adventureData[]`` (homebrew
    adventure) or ``bookData[]`` (sourcebook) OR ``data[]`` whose
    elements look like sections/prose. A doc is **catalog** when its
    top-level keys include any of the known wrapper keys (``monster``,
    ``spell``, ``item``, …). Some files contain both shapes (rare);
    precedence: adventure > catalog.
    """
    if isinstance(raw, list):
        return "adventure"
    if not isinstance(raw, dict):
        return "unknown"

    if isinstance(raw.get("adventureData"), list) or isinstance(raw.get("bookData"), list):
        return "adventure"

    data = raw.get("data")
    if isinstance(data, list) and data:
        if any(
            isinstance(d, dict) and (d.get("type") in _ADVENTURE_SECTION_TYPES or "entries" in d)
            for d in data
        ):
            return "adventure"

    if (
        isinstance(raw.get("entries"), list)
        and "data" not in raw
        and "adventureData" not in raw
        and "bookData" not in raw
    ):
        return "adventure"

    for k in raw.keys():
        if k in _WRAPPER_KEY_WINGS or k.endswith("Fluff"):
            return "catalog"

    return "unknown"


def iter_catalog_entities(raw: dict) -> Iterator[tuple[str, dict]]:
    """Yield ``(wrapper_key, entity)`` for every top-level catalog entity.

    Skips ``_meta`` and other non-entity tops, and skips wrapper keys
    that aren't independently ingestable (item properties, type tags).
    """
    if not isinstance(raw, dict):
        return
    for k, v in raw.items():
        if k in _NON_ENTITY_TOP_KEYS or k in _SKIPPED_CATALOG_KEYS:
            continue
        if not isinstance(v, list):
            continue
        if k not in _WRAPPER_KEY_WINGS and not k.endswith("Fluff"):
            # Skip unknown top-level lists silently — there are several
            # configuration arrays at the root of items.json etc.
            continue
        for ent in v:
            if isinstance(ent, dict):
                yield (k, ent)


def wing_for_wrapper_key(prop: str) -> str:
    if prop in _WRAPPER_KEY_WINGS:
        return _WRAPPER_KEY_WINGS[prop]
    if prop.endswith("Fluff"):
        return "wing_lore"
    return "wing_lore"


# ── Adventure entry walk (existing, preserved) ───────────────────────────


def _iter_top_level_entries(doc: Any) -> Iterator[dict]:
    """Yield every top-level adventure entry regardless of doc shape.

    The observed shapes:
        * Homebrew adventure: ``{"adventure": [...index...], "adventureData": [{"data": [...]}]}``
        * Sourcebook:         ``{"book": [...index...], "bookData": [{"data": [...]}]}``
        * Official adventure: ``{"data": [...]}``
    Plus a couple of one-off outputs where the top level is simply a list.
    """
    if isinstance(doc, list):
        yield from (e for e in doc if isinstance(e, dict))
        return
    if not isinstance(doc, dict):
        return

    for wrapper_key in ("adventureData", "bookData"):
        wrapped = doc.get(wrapper_key)
        if isinstance(wrapped, list):
            for ad in wrapped:
                if isinstance(ad, dict) and isinstance(ad.get("data"), list):
                    yield from (e for e in ad["data"] if isinstance(e, dict))
    if isinstance(doc.get("data"), list):
        yield from (e for e in doc["data"] if isinstance(e, dict))
    if (
        isinstance(doc.get("entries"), list)
        and "adventureData" not in doc
        and "bookData" not in doc
        and "data" not in doc
    ):
        yield from (e for e in doc["entries"] if isinstance(e, dict))


def _walk_entries(
    node: Any,
    path: tuple[str, ...] = (),
) -> Iterator[tuple[dict, tuple[str, ...]]]:
    """Depth-first walk yielding every dict node with its section path.

    The path is the chain of ``name`` fields from root down to the
    immediate parent — useful in metadata so hits can show "book →
    chapter → scene" without re-deriving at query time.
    """
    if isinstance(node, dict):
        yield (node, path)
        child_path = path + (node["name"],) if isinstance(node.get("name"), str) else path
        entries = node.get("entries")
        if isinstance(entries, list):
            for child in entries:
                yield from _walk_entries(child, child_path)
    elif isinstance(node, list):
        for child in node:
            yield from _walk_entries(child, path)


# ── Drawer shaping ──────────────────────────────────────────────────────


_NAME_SAFE_RE = re.compile(r"[^A-Za-z0-9]+")


def sanitize_room_slug(text: str, *, fallback: str = "unknown") -> str:
    """Turn a book title into a room-safe slug (ascii-lower, ``-`` joined)."""
    if not isinstance(text, str) or not text.strip():
        return fallback
    slug = _NAME_SAFE_RE.sub("-", text.strip().lower()).strip("-")
    return slug or fallback


def build_drawer(
    entry: dict,
    section_path: tuple[str, ...],
    *,
    book: dict | None,
    book_room_slug: str,
    source_filepath: str,
) -> dict | None:
    """Convert one entry into a drawer-ready dict, or ``None`` to skip.

    Returned dict keys:
        wing, room, content, metadata (dict of scalars).
    """
    entry_type = entry.get("type") if isinstance(entry.get("type"), str) else None
    name = entry.get("name") if isinstance(entry.get("name"), str) else None
    page = entry.get("page") if isinstance(entry.get("page"), int) else None

    content = _render_entry_content(entry, entry_type, name, page)
    if not content:
        return None

    is_statblock = entry_type in _STATBLOCK_TYPES
    wing = "wing_bestiary" if is_statblock else "wing_rpglib"
    room = f"room_{book_room_slug}"
    section_str = " / ".join(section_path) if section_path else ""

    metadata: dict[str, Any] = {
        "entry_type": entry_type or "unknown",
        "section_name": name or "",
        "section_path": section_str,
        "page": int(page) if page is not None else -1,
        "source_filepath": source_filepath,
    }
    if book:
        metadata.update(_book_metadata(book))
    if is_statblock:
        metadata["statblock_name"] = name or ""
        metadata["statblock_source"] = entry.get("source") or ""
        metadata["statblock_tag"] = entry.get("tag") or ""

    return {"wing": wing, "room": room, "content": content, "metadata": metadata}


def _book_metadata(book: dict) -> dict[str, Any]:
    return {
        "book_id": int(book["id"]),
        "display_title": book.get("pdf_title") or book.get("filename") or "",
        "publisher": book.get("publisher") or "",
        "game_system": book.get("game_system") or "",
        "product_type": book.get("product_type") or "",
        "series": book.get("series") or "",
        "tags": ";".join(book["tags"]) if isinstance(book.get("tags"), list) else "",
    }


def build_drawer_catalog(
    prop: str,
    entity: dict,
    *,
    book: dict | None,
    room_slug: str,
    source_filepath: str,
) -> dict | None:
    """Convert one catalog entity (monster / spell / item / …) into a
    drawer-ready dict, or ``None`` to skip.

    The drawer's ``wing`` is determined by the wrapper key; ``content``
    is rendered via :mod:`fivetools_render`; ``metadata`` carries
    everything a hierarchical AAAK descent (and downstream filtering)
    needs to do its job — entity name, source, page, CR / level / etc.
    """
    if not isinstance(entity, dict):
        return None
    name = entity.get("name") if isinstance(entity.get("name"), str) else None
    if not name:
        return None
    content = fivetools_render.render_entity(prop, entity)
    if not content:
        return None

    wing = wing_for_wrapper_key(prop)
    room = f"room_{room_slug}"
    page = entity.get("page") if isinstance(entity.get("page"), int) else None
    source = entity.get("source") or ""

    metadata: dict[str, Any] = {
        "entry_type": prop,
        "wrapper_key": prop,
        "section_name": name,
        "section_path": "",
        "page": int(page) if page is not None else -1,
        "source_filepath": source_filepath,
        "entity_name": name,
        "entity_source": source,
    }
    if book:
        metadata.update(_book_metadata(book))

    # Per-type facets — small, scalar-only metadata that hierarchical
    # AAAK can route on. Anything richer is in the rendered content.
    metadata.update(_catalog_facets(prop, entity))

    return {"wing": wing, "room": room, "content": content, "metadata": metadata}


def _catalog_facets(prop: str, e: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if prop == "monster":
        out["statblock_name"] = e.get("name") or ""
        out["statblock_source"] = e.get("source") or ""
        out["statblock_tag"] = "creature"
        cr = e.get("cr")
        if isinstance(cr, (str, int, float)):
            out["cr"] = str(cr)
        elif isinstance(cr, dict) and "cr" in cr:
            out["cr"] = str(cr["cr"])
        t = e.get("type")
        if isinstance(t, str):
            out["creature_type"] = t
        elif isinstance(t, dict) and isinstance(t.get("type"), str):
            out["creature_type"] = t["type"]
        sizes = e.get("size")
        if isinstance(sizes, list) and sizes:
            out["size"] = sizes[0]
    elif prop == "spell":
        if isinstance(e.get("level"), int):
            out["spell_level"] = e["level"]
        if isinstance(e.get("school"), str):
            out["spell_school"] = e["school"]
    elif prop in ("class", "subclass", "classFeature", "subclassFeature"):
        if isinstance(e.get("className"), str):
            out["class_name"] = e["className"]
        if isinstance(e.get("level"), int):
            out["class_level"] = e["level"]
    elif prop in ("item", "baseitem", "itemGroup", "magicvariant"):
        if isinstance(e.get("rarity"), str):
            out["item_rarity"] = e["rarity"]
        if isinstance(e.get("type"), str):
            out["item_type"] = e["type"]
    return out


# ── Catalog filtering ────────────────────────────────────────────────────


def parse_filter_spec(spec: str | None) -> dict[str, str]:
    """Parse ``"name=Drow,source=MM"`` into ``{"name": "Drow", "source": "MM"}``.

    Comma-separated key=value pairs. Whitespace around tokens is
    stripped. Empty spec → empty dict (matches everything).
    """
    if not spec:
        return {}
    out: dict[str, str] = {}
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"--filter token {token!r} missing '='")
        k, v = token.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def matches_filter(entity: dict, filters: dict[str, str]) -> bool:
    """All-keys-must-match (AND) string-equality filter."""
    if not filters:
        return True
    for k, expected in filters.items():
        actual = entity.get(k)
        if not isinstance(actual, str):
            actual = "" if actual is None else str(actual)
        if actual.strip().lower() != expected.strip().lower():
            return False
    return True


def _render_entry_content(entry: dict, entry_type: str | None, name: str | None, page) -> str:
    """Render an entry to a verbatim-ish text drawer.

    Prose containers (section, entries, inset, …) store the header +
    their own flat prose tokens so hierarchical pruning has something to
    match on. Leaf nodes (``p``, ``quote``) store their ``entry`` text.
    Statblocks store a compact header line; the full stat block lives in
    the source JSON and is fetched by callers via source_filepath + name.
    """
    if entry_type in _STATBLOCK_TYPES:
        tag = entry.get("tag", "")
        source = entry.get("source", "")
        lines = [f"# {name or 'Unnamed statblock'}"]
        if tag:
            lines.append(f"tag: {tag}")
        if source:
            lines.append(f"source: {source}")
        if page is not None:
            lines.append(f"page: {page}")
        return "\n".join(lines)

    # Leaf prose.
    leaf_text = entry.get("entry") if isinstance(entry.get("entry"), str) else None
    if leaf_text:
        header = f"# {name}\n\n" if name else ""
        return f"{header}{leaf_text.strip()}"

    # Container — emit its header + flat text of its direct children so a
    # container-level hit still has some prose to show.
    entries = entry.get("entries") if isinstance(entry.get("entries"), list) else []
    inline_tokens = []
    for child in entries:
        if isinstance(child, dict):
            t = child.get("entry")
            if isinstance(t, str) and t.strip():
                inline_tokens.append(t.strip())
        elif isinstance(child, str) and child.strip():
            inline_tokens.append(child.strip())
    if name or inline_tokens:
        header = f"# {name}\n\n" if name else ""
        return header + "\n\n".join(inline_tokens)

    # Tables — render the header labels so text search can hit a table
    # by the terms in its column headings.
    if entry_type in _TABLE_TYPES:
        labels = entry.get("colLabels") or []
        caption = entry.get("caption") or name or "Table"
        if labels:
            return f"# {caption}\n\n| " + " | ".join(str(x) for x in labels) + " |"
    return ""


# ── Idempotence state ────────────────────────────────────────────────────


def _state_path(json_path: Path) -> Path:
    state_dir = json_path.parent / _STATE_DIRNAME
    digest = hashlib.sha256(str(json_path.resolve()).encode("utf-8")).hexdigest()[:16]
    return state_dir / f"{digest}.json"


def read_state(json_path: Path) -> dict | None:
    p = _state_path(json_path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_state(json_path: Path, payload: dict) -> None:
    p = _state_path(json_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def file_signature(json_path: Path) -> dict:
    st = json_path.stat()
    return {
        "size": int(st.st_size),
        "mtime": float(round(st.st_mtime, 6)),
        "path": str(json_path.resolve()),
    }


# ── Main ingest ──────────────────────────────────────────────────────────


def build_drawers_from_json(
    raw: Any,
    *,
    book: dict | None,
    book_room_slug: str,
    source_filepath: str,
    kind: str | None = None,
    filters: dict[str, str] | None = None,
    data_root: Path | None = None,
    json_path: Path | None = None,
) -> list[dict]:
    """Walk a 5etools JSON document and return every drawer-ready dict.

    Dispatches on ``kind`` — adventure-shaped docs go through the
    section/scene walker; catalog-shaped docs iterate every wrapper-key
    list, optionally apply ``filters``, resolve ``_copy`` references,
    and route each entity through :func:`build_drawer_catalog`.
    """
    if kind is None:
        kind = detect_doc_kind(raw)

    if kind == "adventure":
        return _build_drawers_adventure(
            raw,
            book=book,
            book_room_slug=book_room_slug,
            source_filepath=source_filepath,
            filters=filters or {},
        )

    if kind == "catalog":
        return _build_drawers_catalog(
            raw,
            book=book,
            room_slug=book_room_slug,
            source_filepath=source_filepath,
            filters=filters or {},
            data_root=data_root,
            json_path=json_path,
        )

    logger.warning(
        "fivetools_ingest: unknown document shape (no adventure or catalog "
        "wrapper keys at top level); no drawers built"
    )
    return []


def _build_drawers_adventure(
    raw: Any,
    *,
    book: dict | None,
    book_room_slug: str,
    source_filepath: str,
    filters: dict[str, str] | None = None,
) -> list[dict]:
    chapter_ordinal: int | None = None
    unsupported: list[str] = []
    for k, v in (filters or {}).items():
        if k == "chapter":
            try:
                chapter_ordinal = int(str(v).strip())
            except (TypeError, ValueError):
                raise ValueError(
                    f"--filter chapter={v!r} is not an integer ordinal "
                    "(use the chapter_ordinal fivetools_catalog records)"
                )
        else:
            unsupported.append(k)
    if unsupported:
        logger.warning(
            "fivetools_ingest: filter key(s) %s ignored for adventure-shape docs "
            "(use chapter=<ordinal>); supported keys: chapter",
            ", ".join(repr(k) for k in unsupported),
        )

    drawers: list[dict] = []
    for ordinal, top in enumerate(_iter_top_level_entries(raw)):
        if chapter_ordinal is not None and ordinal != chapter_ordinal:
            continue
        for node, path in _walk_entries(top):
            d = build_drawer(
                node,
                path,
                book=book,
                book_room_slug=book_room_slug,
                source_filepath=source_filepath,
            )
            if d is not None:
                drawers.append(d)
    return drawers


def _build_drawers_catalog(
    raw: dict,
    *,
    book: dict | None,
    room_slug: str,
    source_filepath: str,
    filters: dict[str, str],
    data_root: Path | None,
    json_path: Path | None,
) -> list[dict]:
    """Build drawers for every catalog entity in the doc.

    Pipeline per wrapper key:

    1. Collect every entity for that key.
    2. Optionally apply ``filters`` (drops non-matching entities early).
    3. Resolve ``_copy`` references — same-file pool first, then
       cross-file dependencies via ``_meta.dependencies`` if a data
       root is available.
    4. Route each entity through :func:`build_drawer_catalog`.
    """
    if not isinstance(raw, dict):
        return []

    by_prop: dict[str, list[dict]] = {}
    for prop, entity in iter_catalog_entities(raw):
        by_prop.setdefault(prop, []).append(entity)

    drawers: list[dict] = []
    auto_data_root = data_root or _autodetect_data_root(json_path)

    for prop, entities in by_prop.items():
        # Filtering happens BEFORE _copy resolution so we don't load
        # dependency files for entities we're about to drop.
        if filters:
            kept = [e for e in entities if matches_filter(e, filters)]
        else:
            kept = list(entities)

        if not kept:
            continue

        # _copy resolution. We pass the *full* same-file list as the
        # primary parent pool so a kept entity that copies from a
        # filtered-out sibling still resolves.
        needs_copy = any("_copy" in e for e in kept)
        if needs_copy:
            extra_pool: list[dict] = []
            if auto_data_root is not None:
                try:
                    extra_pool = fivetools_copy.load_dependency_pool(
                        raw, prop=prop, data_root=auto_data_root
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("dependency load failed for prop %r: %s", prop, exc)
            try:
                fivetools_copy.resolve_copies(
                    # Resolve over the *kept* list, but seed the pool
                    # with every same-file entity (kept or not) so
                    # internal copies don't break.
                    kept,
                    prop=prop,
                    extra_pool=list(entities) + extra_pool,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("_copy resolution failed for prop %r: %s", prop, exc)

        for entity in kept:
            d = build_drawer_catalog(
                prop,
                entity,
                book=book,
                room_slug=room_slug,
                source_filepath=source_filepath,
            )
            if d is not None:
                drawers.append(d)

    return drawers


def _autodetect_data_root(json_path: Path | None) -> Path | None:
    """Walk up from ``json_path`` to find a directory whose basename is
    ``data`` (the canonical 5etools data root). Falls back to the
    package default when nothing is found.
    """
    if json_path is None:
        return _DEFAULT_FIVETOOLS_DATA_ROOT if _DEFAULT_FIVETOOLS_DATA_ROOT.is_dir() else None
    p = json_path.resolve().parent
    for _ in range(8):  # bounded walk
        if p.name == "data" and p.is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    return _DEFAULT_FIVETOOLS_DATA_ROOT if _DEFAULT_FIVETOOLS_DATA_ROOT.is_dir() else None


def ingest_file(
    json_path: Path,
    *,
    palace: str | None,
    book_id: int | None,
    rpglib_db: Path,
    pdf_translators: Path,
    mp_client: MempalaceClient | None = None,
    force: bool = False,
    replace: bool = False,
    dry_run: bool = False,
    strict: bool = False,
    filters: dict[str, str] | None = None,
    data_root: Path | None = None,
) -> dict:
    """Ingest one 5etools JSON. Returns a report dict."""
    if not json_path.is_file():
        raise SystemExit(f"fivetools_ingest: {json_path} is not a file")

    sig = file_signature(json_path)
    prior = read_state(json_path)
    # Filters change the drawer set, so cache hit must include them.
    cur_filter_key = json.dumps(filters or {}, sort_keys=True)
    prior_filter_key = (prior or {}).get("filter_key", "{}") if prior else "{}"
    if prior and not force:
        if (
            prior.get("size") == sig["size"]
            and abs(prior.get("mtime", -1) - sig["mtime"]) < 0.001
            and prior_filter_key == cur_filter_key
        ):
            logger.info("fivetools_ingest: %s unchanged since last ingest (skip)", json_path)
            return {
                "status": "unchanged",
                "json_path": str(json_path),
                "prior": prior,
                "drawers_emitted": 0,
            }

    raw = json.loads(json_path.read_text(encoding="utf-8"))
    kind = detect_doc_kind(raw)
    errors = validate_doc(raw, kind, pdf_translators, strict=strict)
    if errors:
        logger.warning(
            "fivetools_ingest: %d validation issue(s) in %s (ingesting anyway)",
            len(errors),
            json_path,
        )

    # Locate the source PDF + rpglib metadata. Catalog files (the 5e
    # repo's own JSONs) usually have no associated PDF — the
    # source_filepath then falls back to the JSON itself, and the
    # rpglib lookup gracefully returns None.
    source_filepath = raw.get("_meta", {}).get("sourceFilepath") if isinstance(raw, dict) else None
    if not source_filepath:
        candidate = json_path.with_suffix(".pdf")
        source_filepath = str(candidate) if candidate.exists() else str(json_path)

    book = lookup_book(rpglib_db, book_id=book_id, filepath=source_filepath)
    display_title = (
        (book or {}).get("pdf_title")
        or (book or {}).get("filename")
        or (raw.get("_meta", {}).get("title") if isinstance(raw, dict) else None)
        or json_path.stem
    )
    book_room_slug = sanitize_room_slug(display_title)

    drawers = build_drawers_from_json(
        raw,
        book=book,
        book_room_slug=book_room_slug,
        source_filepath=source_filepath,
        kind=kind,
        filters=filters,
        data_root=data_root,
        json_path=json_path,
    )

    if dry_run:
        return {
            "status": "dry-run",
            "json_path": str(json_path),
            "kind": kind,
            "book_room_slug": book_room_slug,
            "book": book,
            "validation_errors": errors,
            "drawer_count": len(drawers),
            "drawers_preview": drawers[:3],
        }

    owns_client = mp_client is None
    if owns_client:
        mp_client = MempalaceClient(palace=palace)
        mp_client.start()
    try:
        if replace:
            logger.info("fivetools_ingest: --replace not yet implemented at MCP layer")
            # Tool surface doesn't expose a "delete drawers by metadata"
            # call yet. Deferred until that lands; for now --replace is a
            # no-op with a warning so callers notice.
        results = []
        for drawer in drawers:
            ack = mp_client.add_drawer(
                wing=drawer["wing"],
                room=drawer["room"],
                content=drawer["content"],
                metadata=drawer["metadata"],
            )
            results.append(ack)
    finally:
        if owns_client:
            mp_client.close()

    state_payload = {
        "version": _STATE_VERSION,
        "size": sig["size"],
        "mtime": sig["mtime"],
        "json_path": sig["path"],
        "source_filepath": source_filepath,
        "book_room_slug": book_room_slug,
        "book_id": (book or {}).get("id"),
        "drawer_count": len(drawers),
        "ingested_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": kind,
        "filter_key": cur_filter_key,
    }
    write_state(json_path, state_payload)

    return {
        "status": "ingested",
        "json_path": str(json_path),
        "kind": kind,
        "book_room_slug": book_room_slug,
        "book_id": (book or {}).get("id"),
        "drawer_count": len(drawers),
        "validation_errors": errors,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else None)
    parser.add_argument("json_path", type=Path, help="Path to the 5etools JSON file.")
    parser.add_argument(
        "--palace",
        required=True,
        help="Palace alias or absolute path (forwarded to mempalace-mcp). "
        "Required: silent default-palace resolution at the mempalace-mcp "
        "layer was footgun-prone (drawers landing in the wrong campaign).",
    )
    parser.add_argument(
        "--book-id",
        type=int,
        default=None,
        help="rpg_library.db book id. If omitted, the script looks up the "
        "book by filepath (the JSON's _meta.sourceFilepath or a sibling PDF).",
    )
    parser.add_argument(
        "--rpglib-db",
        type=Path,
        default=_DEFAULT_RPGLIB_DB,
        help=f"Path to rpg_library.db (default {_DEFAULT_RPGLIB_DB}).",
    )
    parser.add_argument(
        "--pdf-translators",
        type=Path,
        default=_DEFAULT_PDF_TRANSLATORS,
        help=f"Path to the pdf-translators checkout (default {_DEFAULT_PDF_TRANSLATORS}).",
    )
    parser.add_argument(
        "--fivetools-data-root",
        type=Path,
        default=None,
        help=(
            "Path to the 5etools data tree (used for cross-file _copy "
            "dependency resolution). Auto-detected from json_path when "
            f"omitted; default {_DEFAULT_FIVETOOLS_DATA_ROOT}."
        ),
    )
    parser.add_argument(
        "--filter",
        default=None,
        help=(
            "Comma-separated key=value pairs to select a subset of "
            "catalog entities (e.g. \"name=Drow,source=MM\"). Ignored "
            "for adventure-shape docs."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest even if the JSON is unchanged since last run.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="(Reserved) Wipe this book's drawers before re-ingesting.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Abort on the first structural validation error.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the ingest plan (counts + preview) without writing drawers.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        filters = parse_filter_spec(args.filter)
    except ValueError as exc:
        raise SystemExit(f"fivetools_ingest: {exc}")
    report = ingest_file(
        args.json_path,
        palace=args.palace,
        book_id=args.book_id,
        rpglib_db=args.rpglib_db,
        pdf_translators=args.pdf_translators,
        force=args.force,
        replace=args.replace,
        dry_run=args.dry_run,
        strict=args.strict,
        filters=filters,
        data_root=args.fivetools_data_root,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
