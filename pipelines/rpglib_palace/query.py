"""Query the pilot palace: expand hits to whole sections, cap per book.

``mempalace.searcher.query.search_memories`` returns a dict::

    {"query", "filters", "total_before_filter", "primary", "results" (alias of
     primary), "themes", ["error" on failure]}

and each hit in ``results`` is::

    {"drawer_id", "text" (chunk), "wing", "room",
     "source_file" (BASENAME only), "source_path" (full stored path),
     "similarity", "distance", ...date fields}

Basenames are only unique within a book (``001-intro.md`` exists in every
book), so hits are mapped through ``source_path`` (fallback: room + basename).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from pipelines.rpglib_palace.guard import ENV_VAR, WING, require_pilot_palace

_COMMENT = re.compile(r"^<!-- book_id=.*-->\n?", re.M)


def _default_search(text, palace, fetch):
    from mempalace.searcher.query import search_memories

    return search_memories(text, palace_path=str(palace), wing=WING, n_results=fetch)


def _lookup(hit: dict, root: Path, sections: dict):
    sp = hit.get("source_path") or ""
    if sp:
        try:
            rel = Path(sp).resolve().relative_to(root).as_posix()
            if rel in sections:
                return rel
        except ValueError:
            pass
    room, base = hit.get("room"), hit.get("source_file")
    if room and base:
        rel = f"{room}/{base}"
        if rel in sections:
            return rel
    return None


def run_query(
    text,
    palace: Path,
    render_root: Path,
    search_fn=None,
    fetch=50,
    per_book=2,
    top=10,
    home: Path | None = None,
) -> dict:
    palace = require_pilot_palace({ENV_VAR: str(palace)}, home)
    root = Path(render_root).resolve()
    sections = json.loads((root / "sections.json").read_text(encoding="utf-8"))
    search_fn = search_fn or (lambda t, p, n: _default_search(t, p, n))
    t0 = time.time()
    raw = search_fn(text, palace, fetch)
    if raw.get("error"):
        raise RuntimeError(raw["error"])
    hits = raw.get("results") or raw.get("primary") or []

    order: list[str] = []
    best: dict[str, float] = {}
    unmapped: list[str] = []
    for h in hits:
        rel = _lookup(h, root, sections)
        if rel is None:
            unmapped.append(h.get("source_path") or h.get("source_file") or "?")
            continue
        score = float(h.get("similarity", 0.0))
        if rel not in best:
            order.append(rel)
            best[rel] = score
        else:
            best[rel] = max(best[rel], score)

    results: list[dict] = []
    per: dict[int, int] = {}
    cap_fired = 0
    for rel in order:
        rec = sections[rel]
        bid = rec["book_id"]
        if per.get(bid, 0) >= per_book:
            cap_fired += 1
            continue
        per[bid] = per.get(bid, 0) + 1
        body = _COMMENT.sub("", (root / rel).read_text(encoding="utf-8"), count=1)
        results.append(
            {
                "book_id": bid,
                "title": rec["title"],
                "publisher": rec.get("publisher"),
                "section_path": rec["section_path"],
                "page": rec.get("page"),
                "score": best[rel],
                "file": rel,
                "text": body,
            }
        )
    results = results[:top]
    return {
        "results": results,
        "distinct_books": len({r["book_id"] for r in results}),
        "cap_fired": cap_fired,
        "unmapped": unmapped,
        "latency_s": round(time.time() - t0, 3),
    }


def format_human(out: dict) -> str:
    lines: list[str] = []
    for n, r in enumerate(out["results"], 1):
        page = f"p.{r['page']}" if r["page"] is not None else "p.?"
        lines.append(
            f"[{n}] {r['title']} (book {r['book_id']}) — {' > '.join(r['section_path'])}, {page}"
        )
        lines.append(r["text"][:600])
        lines.append("")
    lines.append(
        f"--- distinct books: {out['distinct_books']}, cap fired: {out['cap_fired']}, "
        f"unmapped: {len(out['unmapped'])}, latency: {out['latency_s']}s"
    )
    return "\n".join(lines)
