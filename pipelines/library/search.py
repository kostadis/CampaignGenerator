"""Search the library: expand hits to whole sections, cap per book (FR-007..010).

All palace access is through the injected ``client`` (a
``mempalace_client.LibraryPalaceClient``); this module imports no mempalace.

The client's ``search`` returns the MCP ``mempalace_search`` dict::

    {"query", "filters", "total_before_filter", "primary", "results" (alias),
     "themes", ["error" on failure]}

each hit: ``drawer_id``, ``text`` (chunk), ``wing``, ``room``, ``source_file``
(BASENAME only), ``source_path`` (full stored path), ``similarity``. Basenames
are only unique within a book, so hits map through ``source_path`` (fallback:
room + basename).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from pipelines.library.config import LibraryConfig
from pipelines.library.guard import WING, require_library_palace
from pipelines.library.state import rendered_root, require_built, require_embedder_match

_COMMENT = re.compile(r"^<!-- book_id=.*-->\n?", re.M)


@dataclass
class SearchResultSet:
    query: str
    results: list = field(default_factory=list)
    distinct_books: int = 0
    cap_fired: int = 0
    unmapped: list = field(default_factory=list)
    latency_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "results": self.results,
            "distinct_books": self.distinct_books,
            "cap_fired": self.cap_fired,
            "unmapped": self.unmapped,
            "latency_s": self.latency_s,
        }


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


def search_library(
    config: LibraryConfig, query: str, *, limit: int = 10, per_book: int = 2, client
) -> SearchResultSet:
    require_library_palace(config.palace)
    stamp = require_built(config)
    require_embedder_match(config, stamp)
    root = rendered_root(config).resolve()
    sections = json.loads((root / "sections.json").read_text(encoding="utf-8"))

    t0 = time.time()
    raw = client.search(query, wing=WING, limit=min(100, max(50, limit * 5)))
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
    results = results[:limit]
    return SearchResultSet(
        query=query,
        results=results,
        distinct_books=len({r["book_id"] for r in results}),
        cap_fired=cap_fired,
        unmapped=unmapped,
        latency_s=round(time.time() - t0, 3),
    )


def format_human(out: SearchResultSet) -> str:
    lines: list[str] = []
    for n, r in enumerate(out.results, 1):
        page = f"p.{r['page']}" if r["page"] is not None else "p.?"
        lines.append(
            f"[{n}] {r['title']} (book {r['book_id']}) — {' > '.join(r['section_path'])}, {page}"
        )
        lines.append(r["text"][:600])
        lines.append("")
    lines.append(
        f"--- distinct books: {out.distinct_books}, cap fired: {out.cap_fired}, "
        f"unmapped: {len(out.unmapped)}, latency: {out.latency_s}s"
    )
    return "\n".join(lines)
