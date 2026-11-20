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


def render_book(book: dict, book_json: dict, out_root: Path) -> list[dict]:
    out_root = Path(out_root)
    book_id = book["book_id"]
    title = book["title"]
    bdir = out_root / f"b{book_id}"
    bdir.mkdir(parents=True, exist_ok=True)
    data = book_json.get("data") if isinstance(book_json, dict) else None
    if not isinstance(data, list):
        return []
    records: list[dict] = []
    counter = 0

    def emit(path: list[str], page, body: str, suffix: str = "") -> None:
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
            }
        )

    def emit_sized(path: list[str], page, body: str) -> None:
        head = _head(title, path, book_id, page)
        if _size(head) + _size(body) + 1 <= MAX_FILE_BYTES:
            emit(path, page, body)
            return
        chunks = _split_paragraphs(head, body, MAX_FILE_BYTES)
        if len(chunks) == 1:
            emit(path, page, chunks[0])
            return
        for k, chunk in enumerate(chunks, 1):
            emit(path, page, chunk, suffix=f"-part{k}")

    for i, node in enumerate(data, 1):
        if isinstance(node, dict):
            name = node.get("name") or f"Untitled {i}"
            page = node.get("page")
            entries = node.get("entries") or []
        else:
            name, page, entries = f"Untitled {i}", None, [node]
        path = [str(name)]
        body = render_entries_block(entries)
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


def write_palace_layout(out_root: Path, records: list[dict], books: list[dict]) -> None:
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    cfg = {
        "wing": WING,
        "rooms": [
            {"name": f"b{b['book_id']}", "description": b["title"], "keywords": [f"b{b['book_id']}"]}
            for b in books
        ],
    }
    (out_root / "mempalace.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    (out_root / "sections.json").write_text(
        json.dumps({r["file"]: r for r in records}, indent=2), encoding="utf-8"
    )
