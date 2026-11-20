"""Render a converted 5etools book into one markdown file per section."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from pipelines.content_ingest.fivetools_render import render_entries_block, strip_tags

MAX_FILE_BYTES = 300_000
WING = "wing_dmsguild"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s or "section")[:50]


def _size(s: str) -> int:
    return len(s.encode("utf-8"))


def _head(title: str, path: list[str], book_id: int, page) -> str:
    crumb = " > ".join([strip_tags(title)] + [strip_tags(p) for p in path])
    return f"# {crumb}\n<!-- book_id={book_id} page={page if page is not None else 'null'} -->\n\n"


def _split_paragraphs(head: str, body: str, limit: int) -> list[str]:
    """Pack paragraphs into bodies so head+body fits limit; never truncates."""
    budget = max(limit - _size(head), 1)
    parts: list[str] = []
    cur: list[str] = []
    cur_size = 0
    for para in body.split("\n\n"):
        ps = _size(para) + 2
        if cur and cur_size + ps > budget:
            parts.append("\n\n".join(cur))
            cur, cur_size = [], 0
        cur.append(para)
        cur_size += ps
    if cur:
        parts.append("\n\n".join(cur))
    return parts


def _node_parts(node: dict) -> list[tuple[str | None, object, list]]:
    """Group a node's children at named entries: (name, page, entries)."""
    parts: list[tuple[str | None, object, list]] = []
    for child in node.get("entries") or []:
        if isinstance(child, dict) and child.get("name"):
            parts.append((str(child["name"]), child.get("page", node.get("page")), [child]))
        elif parts:
            parts[-1][2].append(child)
        else:
            parts.append((None, node.get("page"), [child]))
    return parts


def book_sections(book_json) -> list:
    """Section list from a 5etools book: top-level `data`, else homebrew
    `adventureData`/`bookData` entries' `data` lists concatenated in order."""
    if not isinstance(book_json, dict):
        return []
    if isinstance(book_json.get("data"), list):
        return book_json["data"]
    out: list = []
    for key in ("adventureData", "bookData"):
        for item in book_json.get(key) or []:
            if isinstance(item, dict) and isinstance(item.get("data"), list):
                out.extend(item["data"])
    return out


_PRICE_RE = re.compile(r"^\d+(\.\d+)?\s*[a-z]{2}\b", re.I)


def looks_like_fragment(title: str) -> bool:
    """True when a section title looks like a promoted table cell / wrapped line."""
    t = strip_tags(title or "").strip()
    if not t:
        return True
    if t[0].isdigit() or t[0] in "/+-":
        return True
    if t[0].islower():
        return True
    if t[-1] in ".,):":
        return True
    return bool(_PRICE_RE.match(t))


def render_book(
    book: dict,
    book_json: dict,
    out_root: Path,
    merge_fragments: bool = False,
    min_chars: int = 300,
) -> list[dict]:
    out_root = Path(out_root)
    book_id = book["book_id"]
    title = book["title"]
    bdir = out_root / f"b{book_id}"
    bdir.mkdir(parents=True, exist_ok=True)
    data = book_sections(book_json)
    if not data:
        return []
    records: list[dict] = []
    counter = 0

    def emit(path: list[str], page, body: str, suffix: str = "", merged: list[str] | None = None) -> None:
        nonlocal counter
        counter += 1
        name = f"{counter:03d}-{_slug(path[-1] if path else 'section')}{suffix}.md"
        text = _head(title, path, book_id, page) + body + "\n"
        (bdir / name).write_text(text, encoding="utf-8")
        records.append(
            {
                "file": f"b{book_id}/{name}",
                "book_id": book_id,
                "title": title,
                "publisher": book.get("publisher"),
                "section_path": [strip_tags(p) for p in path],
                "page": page if isinstance(page, int) else None,
                "merged_titles": list(merged or []),
            }
        )

    def emit_sized(path: list[str], page, body: str, merged: list[str] | None = None) -> None:
        head = _head(title, path, book_id, page)
        if _size(head) + _size(body) + 1 <= MAX_FILE_BYTES:
            emit(path, page, body, merged=merged)
            return
        chunks = _split_paragraphs(head, body, MAX_FILE_BYTES)
        if len(chunks) == 1:
            emit(path, page, chunks[0], merged=merged)
            return
        for k, chunk in enumerate(chunks, 1):
            emit(path, page, chunk, suffix=f"-part{k}", merged=merged)

    units: list[dict] = []
    for i, node in enumerate(data, 1):
        if isinstance(node, dict):
            name = node.get("name") or f"Untitled {i}"
            page = node.get("page")
            entries = node.get("entries") or []
        else:
            name, page, entries = f"Untitled {i}", None, [node]
        u = {
            "node": node,
            "name": str(name),
            "page": page,
            "body": render_entries_block(entries),
            "raw_name": node.get("name") if isinstance(node, dict) else None,
            "merged": [],
        }
        if merge_fragments and units and (
            len(u["body"]) < min_chars or looks_like_fragment(u["raw_name"] or "")
        ):
            prev = units[-1]
            prev["body"] = f"{prev['body']}\n\n### {strip_tags(u['name'])}\n\n{u['body']}".rstrip()
            prev["merged"].append(strip_tags(u["name"]))
            continue
        units.append(u)

    for u in units:
        node, name, page, body = u["node"], u["name"], u["page"], u["body"]
        path = [name]
        if u["merged"]:
            emit_sized(path, page, body, merged=u["merged"])
            continue
        if _size(_head(title, path, book_id, page)) + _size(body) + 1 <= MAX_FILE_BYTES:
            emit(path, page, body)
            continue
        if not isinstance(node, dict):
            emit_sized(path, page, body)
            continue
        for cname, cpage, centries in _node_parts(node):
            cpath = path + ([cname] if cname else [])
            cbody = render_entries_block(centries)
            if not cbody:
                continue
            emit_sized(cpath, cpage if cpage is not None else page, cbody)
    return records


def write_palace_layout(
    out_root: Path, records: list[dict], books: list[dict], render_meta: dict | None = None
) -> None:
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    cfg = {
        "wing": WING,
        # sections.json is our own manifest; keep it out of the palace.
        "exclude_patterns": ["sections.json", "render_meta.json"],
        "rooms": [
            {"name": f"b{b['book_id']}", "description": b["title"], "keywords": [f"b{b['book_id']}"]}
            for b in books
        ],
    }
    (out_root / "mempalace.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    (out_root / "sections.json").write_text(
        json.dumps({r["file"]: r for r in records}, indent=2), encoding="utf-8"
    )
    (out_root / "render_meta.json").write_text(
        json.dumps(render_meta or {"merge_fragments": False, "min_chars": 300}, indent=2),
        encoding="utf-8",
    )
