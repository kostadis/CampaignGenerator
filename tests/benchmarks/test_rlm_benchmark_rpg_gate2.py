"""Gate 2: RPG retrieval benchmark over a self-contained fixture.

Builds a temporary rpglib SQLite + MemPalace palace seeded from
``rlm_benchmark_rpg.json``, runs ``recursive_indexer.rebuild_all`` so
the hierarchical index layer exists, then exercises
``rpg_retriever.retrieve`` against ~15 RPG queries. Asserts that at
least 90% of queries surface the expected drawer (or pointer) in the
top-3 hits — the Gate 2 pass criterion from the RLM integration plan.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest


FIXTURE_PATH = Path(__file__).parent / "rlm_benchmark_rpg.json"


# The benchmark depends on mempalace being installed in the test venv.
pytest.importorskip("mempalace")
from mempalace import palace as palace_mod  # noqa: E402
from mempalace import recursive_indexer  # noqa: E402

import rpg_retriever  # noqa: E402
from mempalace_client import MempalaceClient  # noqa: E402


# ── Fixture materialization ──────────────────────────────────────────────


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rpglib_url(fixture) -> str:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    class _BenchmarkRpgLibraryHandler(BaseHTTPRequestHandler):
        def log_message(self, *args, **kwargs):
            return

        def _respond(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            books = self.server.books
            if self.path.startswith("/api/library/book/"):
                try:
                    book_id = int(self.path.rsplit("/", 1)[-1])
                    for b in books:
                        if b.get("id") == book_id:
                            self._respond(b)
                            return
                except ValueError:
                    pass
                self._respond({"detail": "not found"}, 404)
                return

            if self.path.startswith("/api/library/search"):
                self._respond({"results": books, "total": len(books)})
                return

            self._respond({"detail": "unhandled"}, 404)

        def do_POST(self):
            books = self.server.books
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            if self.path == "/api/library/nlq":
                try:
                    payload = json.loads(body)
                    query = payload.get("query", "").lower()
                except Exception:
                    query = ""

                if query:
                    filtered = []
                    for b in books:
                        text_fields = [
                            b.get("pdf_title", ""),
                            b.get("description", ""),
                            b.get("filename", ""),
                            " ".join(b.get("tags") or []),
                        ]
                        combined = " ".join(text_fields).lower()
                        words = query.split()
                        if any(w in combined for w in words):
                            filtered.append(b)
                    self._respond({"results": filtered, "total": len(filtered)})
                else:
                    self._respond({"results": books, "total": len(books)})
                return
            self._respond({"detail": "unhandled"}, 404)

    server = HTTPServer(("127.0.0.1", 0), _BenchmarkRpgLibraryHandler)
    server.books = fixture["fixture"]["books"]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield url
    finally:
        server.shutdown()
        thread.join(timeout=2)



@pytest.fixture(scope="module")
def benchmark_palace(tmp_path_factory, fixture) -> Path:
    palace_path = Path(tmp_path_factory.mktemp("palace_gate2"))
    drawers_col = palace_mod.get_collection(str(palace_path))
    closets_col = palace_mod.get_closets_collection(str(palace_path))

    book_by_id = {b["id"]: b for b in fixture["fixture"]["books"]}

    drawer_ids: list[str] = []
    drawer_docs: list[str] = []
    drawer_metas: list[dict] = []
    closet_ids: list[str] = []
    closet_docs: list[str] = []
    closet_metas: list[dict] = []

    for d in fixture["fixture"]["drawers"]:
        book = book_by_id[d["book_id"]]
        meta = {
            "wing": d["wing"],
            "room": d["room"],
            "source_file": book["filename"],
            "chunk_index": 0,
            "book_id": d["book_id"],
            "entry_type": d.get("entry_type", ""),
            "section_path": d.get("section_path", ""),
        }
        drawer_ids.append(d["id"])
        drawer_docs.append(d["text"])
        drawer_metas.append(meta)

        # Synthesize a closet line so recursive_indexer has something to
        # project. We reuse the first line of text as the topic.
        first_line = d["text"].splitlines()[0].lstrip("# ").strip()
        closet_line = f"{first_line or 'topic'}||→{d['id']}"
        closet_ids.append(f"closet_{d['id']}")
        closet_docs.append(closet_line)
        closet_metas.append(
            {
                "wing": d["wing"],
                "room": d["room"],
                "source_file": book["filename"],
                "top_entities": "",
            }
        )

    drawers_col.add(ids=drawer_ids, documents=drawer_docs, metadatas=drawer_metas)
    closets_col.add(ids=closet_ids, documents=closet_docs, metadatas=closet_metas)

    recursive_indexer.rebuild_all(str(palace_path))
    return palace_path


# ── Benchmark ────────────────────────────────────────────────────────────


def _top3_match(hit_list: list[dict], query_spec: dict) -> bool:
    """Gate 2 pass check for one query.

    For drawer/statblock expectations, the hit must land in the top-3 —
    these are primary retrieval answers that a user expects to see
    first. For pointer expectations (unconverted-book suggestions), it
    suffices that the pointer appears anywhere in the hit list, since
    pointers are secondary "you may want to convert X" nudges that
    intentionally rank below real drawer hits.
    """
    expected_kind = query_spec.get("expected_kind")
    expected_book_id = query_spec.get("expected_book_id")
    expected_drawer_id = query_spec.get("expected_drawer_id")

    scope = hit_list if expected_kind == "pointer" else hit_list[:3]
    for h in scope:
        kind = h.get("kind")
        cost = h.get("cost")
        if expected_kind == "pointer":
            if not (kind == "candidate" and cost == "expensive"):
                continue
        else:
            if expected_kind and kind != expected_kind:
                continue
        if expected_drawer_id and h.get("drawer_id") == expected_drawer_id:
            return True
        if expected_book_id and h.get("book_id") == expected_book_id and not expected_drawer_id:
            return True
    return False


@pytest.mark.benchmark
def test_gate2_rpg_retrieval(benchmark_palace, rpglib_url, fixture):
    queries = fixture["queries"]
    thresholds = fixture["gate_thresholds"]

    correct = 0
    pointer_payload_ok = True
    any_fallback = False
    per_query: list[dict] = []

    with MempalaceClient(
        palace=str(benchmark_palace),
        command=sys.executable,
        args=["-m", "mempalace.mcp_server", "--palace", str(benchmark_palace)],
        call_timeout=45.0,
        startup_timeout=45.0,
    ) as mp:
        for q in queries:
            result = rpg_retriever.retrieve(
                q["query"],
                rpg_library_url=rpglib_url,
                mp_client=mp,
                limit=5,
                k_expensive=5,
            )
            hits = result.get("hits", [])
            if result.get("fallback"):
                any_fallback = True
            hit = _top3_match(hits, q)

            # Pointer-payload integrity check: every pointer hit must
            # carry a well-formed suggest_conversion block.
            for h in hits:
                if h.get("kind") == "candidate" and h.get("cost") == "expensive":
                    if not (h.get("convert_command") and h.get("ingest_command")
                            and h.get("filepath")):
                        pointer_payload_ok = False

            correct += int(hit)
            per_query.append(
                {
                    "id": q["id"],
                    "query": q["query"],
                    "expected": {
                        "kind": q.get("expected_kind"),
                        "book_id": q.get("expected_book_id"),
                        "drawer_id": q.get("expected_drawer_id"),
                    },
                    "top3": [
                        {
                            "kind": h.get("kind"),
                            "book_id": h.get("book_id"),
                            "drawer_id": h.get("drawer_id"),
                            "similarity": h.get("similarity"),
                        }
                        for h in hits[:3]
                    ],
                    "match": hit,
                }
            )

    fraction = correct / len(queries) if queries else 0.0

    # Report
    print("\n── Gate 2 — RPG retrieval benchmark ──")
    print(f"  queries                : {len(queries)}")
    print(f"  top-3 correct          : {correct} ({fraction:.3f})")
    print(f"  threshold              : {thresholds['top3_correct_min_fraction']:.2f}")
    print(f"  pointer payloads valid : {pointer_payload_ok}")
    print(f"  any fallback?          : {any_fallback}")
    for row in per_query:
        mark = "✓" if row["match"] else "✗"
        print(
            f"  {mark} {row['id']:<3} {row['query'][:40]:<40} → "
            f"kinds={[h['kind'] for h in row['top3']]} "
            f"books={[h['book_id'] for h in row['top3']]}"
        )

    assert pointer_payload_ok, "pointer hits must always carry suggest_conversion"
    if not thresholds.get("fallback_allowed", True):
        assert not any_fallback, "indices expected to cover all queries — no fallback allowed"
    assert fraction >= thresholds["top3_correct_min_fraction"], (
        f"top-3 correctness {fraction:.3f} < required "
        f"{thresholds['top3_correct_min_fraction']:.2f}"
    )
