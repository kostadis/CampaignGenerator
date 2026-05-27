"""Tests for ``rpg_retriever.py`` (Step 3 contract).

Step 3 reshapes the retriever:
  * `search_rpglib` is HTTP-only (was direct SQLite). Tested against an
    in-process stdlib HTTPServer fixture.
  * `reconcile` is a pure function — tested with in-memory fixtures and
    asserts the new tiered (`drawer`/`statblock`/`candidate(cost: ...)`)
    output shape.
  * `retrieve` is the top-level orchestrator — tested end-to-end with a
    `FakeMempalaceClient`, the HTTP fixture, and a synthetic
    fivetools_catalog stand-in.
"""

import json
import threading
import unittest.mock
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import rpg_retriever as rpgr
from mempalace_client import FakeMempalaceClient


# ── HTTP fixture for rpg-library API ─────────────────────────────────────


class _CannedRpgLibraryHandler(BaseHTTPRequestHandler):
    """In-process rpg-library API stand-in. Reads canned responses from
    ``self.server.responses`` keyed by (method, path-or-prefix).
    """

    def log_message(self, *_args, **_kwargs):
        return

    def _respond(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        responses = self.server.responses
        if self.path.startswith("/api/library/book/"):
            book_id = int(self.path.rsplit("/", 1)[-1])
            book = responses.get("books", {}).get(book_id)
            if not book:
                self._respond({"detail": "not found"}, 404)
                return
            self._respond(book)
            return
        if self.path.startswith("/api/library/search"):
            self._respond({"results": responses.get("search", []), "total": 0,
                           "page": 1, "per_page": 50, "total_pages": 0})
            return
        self._respond({"detail": "unhandled"}, 404)

    def do_POST(self):  # noqa: N802
        responses = self.server.responses
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if self.path == "/api/library/nlq":
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {}
            results = responses.get("nlq", [])
            self._respond({
                "query_parsed": {"keywords": payload.get("query", "")},
                "results": results,
                "total": len(results),
            })
            return
        self._respond({"detail": "unhandled"}, 404)


@pytest.fixture
def rpglib_http(monkeypatch):
    """Spin up a local HTTPServer on an ephemeral port. Yields
    ``(base_url, responses_dict)``; mutate the dict in-test to control
    the canned payloads.
    """
    server = HTTPServer(("127.0.0.1", 0), _CannedRpgLibraryHandler)
    server.responses = {
        "nlq": [],
        "search": [],
        "books": {},
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base_url, server.responses
    finally:
        server.shutdown()
        thread.join(timeout=2)


# ── search_rpglib ────────────────────────────────────────────────────────


def test_search_rpglib_uses_nlq_for_free_text(rpglib_http):
    base_url, responses = rpglib_http
    responses["nlq"] = [
        {"id": 1, "filepath": "/m/A.pdf", "pdf_title": "Adventure A",
         "publisher": "WotC", "game_system": "D&D 5e", "product_type": "adventure",
         "tags": ["horror"], "page_count": 100},
    ]
    out = rpgr.search_rpglib("horror adventure", base_url=base_url)
    assert len(out) == 1
    assert out[0]["pdf_title"] == "Adventure A"


def test_search_rpglib_filters_game_system(rpglib_http):
    base_url, responses = rpglib_http
    responses["nlq"] = [
        {"id": 1, "filepath": "/m/A.pdf", "pdf_title": "A", "game_system": "D&D 5e",
         "product_type": "adventure", "tags": [], "page_count": 80},
        {"id": 2, "filepath": "/m/B.pdf", "pdf_title": "B", "game_system": "Pathfinder 2e",
         "product_type": "adventure", "tags": [], "page_count": 80},
    ]
    out = rpgr.search_rpglib("any", base_url=base_url, game_system="D&D 5e")
    assert {b["pdf_title"] for b in out} == {"A"}


def test_search_rpglib_book_id_pin(rpglib_http):
    base_url, responses = rpglib_http
    responses["books"][42] = {
        "id": 42, "filepath": "/x/y.pdf", "pdf_title": "Pinned",
        "publisher": "WotC", "game_system": "D&D 5e", "product_type": "adventure",
        "tags": [], "page_count": 200,
    }
    out = rpgr.search_rpglib("", base_url=base_url, book_id=42)
    assert len(out) == 1
    assert out[0]["id"] == 42


def test_search_rpglib_unreachable_server_soft_fails():
    out = rpgr.search_rpglib("anything", base_url="http://127.0.0.1:1")  # nothing listening
    assert out == []


def test_search_rpglib_empty_query_uses_search_endpoint(rpglib_http):
    base_url, responses = rpglib_http
    responses["search"] = [
        {"id": 1, "filepath": "/m/A.pdf", "pdf_title": "A",
         "game_system": "D&D 5e", "product_type": "adventure",
         "tags": [], "page_count": 80},
    ]
    out = rpgr.search_rpglib("", base_url=base_url, game_system="D&D 5e")
    assert len(out) == 1


# ── reconcile ────────────────────────────────────────────────────────────


def _fake_mp_result(
    hits: list[dict] | None = None,
    *,
    fallback: bool = False,
    path: dict | None = None,
) -> dict:
    return {
        "query": "x",
        "max_depth": 2,
        "path": path or {"wings": [], "rooms": []},
        "results": hits or [],
        "total_before_filter": len(hits or []),
        "fallback": fallback,
    }


class TestReconcile:
    def test_drawer_hit_joined_with_book_metadata(self):
        mp = _fake_mp_result([
            {"drawer_id": "d1", "wing": "wing_rpglib", "room": "room_obojima",
             "text": "An encounter with a kappa.", "similarity": 0.82,
             "book_id": 2, "page": 45},
        ])
        books = [
            {"id": 2, "pdf_title": "Obojima", "publisher": "Atlas",
             "game_system": "D&D 5e", "product_type": "adventure",
             "filepath": "/mnt/g/Obojima.pdf", "tags": ["asian"],
             "page_count": 260},
        ]
        got = rpgr.reconcile("kappa", rpglib_books=books, mempalace_result=mp,
                             k_expensive=0)
        assert got.drawer_hits == 1
        assert got.statblock_hits == 0
        shaped = got.hits[0]
        assert shaped["kind"] == "drawer"
        assert shaped["book_id"] == 2
        assert shaped["title"] == "Obojima"
        assert shaped["game_system"] == "D&D 5e"

    def test_bestiary_hit_becomes_statblock(self):
        mp = _fake_mp_result([
            {"drawer_id": "sb1", "wing": "wing_bestiary", "text": "# Kappa",
             "book_id": 2},
        ])
        got = rpgr.reconcile(
            "kappa", rpglib_books=[
                {"id": 2, "pdf_title": "Obojima", "filepath": "/o.pdf",
                 "tags": [], "page_count": 100}
            ],
            mempalace_result=mp, k_expensive=0,
        )
        assert got.statblock_hits == 1
        assert got.hits[0]["kind"] == "statblock"

    def test_uncovered_book_becomes_expensive_candidate(self):
        mp = _fake_mp_result([])
        books = [
            {"id": 7, "pdf_title": "Some Adventure", "filepath": "/m/u.pdf",
             "filename": "u.pdf", "publisher": "Indie", "game_system": "D&D 5e",
             "product_type": "adventure", "page_count": 80, "tags": ["urban"]},
        ]
        got = rpgr.reconcile("urban", rpglib_books=books, mempalace_result=mp)
        assert got.candidates_expensive_emitted == 1
        hit = got.hits[0]
        assert hit["kind"] == "candidate"
        assert hit["cost"] == "expensive"
        assert hit["book_id"] == 7
        assert hit["convert_command"][1].endswith("pdf_to_5etools_v2.py")
        assert hit["ingest_command"][1].endswith("fivetools_ingest.py")

    def test_drawer_suppresses_expensive_for_same_book(self):
        mp = _fake_mp_result([
            {"drawer_id": "d1", "wing": "wing_rpglib", "text": "prose", "book_id": 2},
        ])
        books = [
            {"id": 2, "pdf_title": "A", "filepath": "/o.pdf", "filename": "o.pdf",
             "page_count": 100, "tags": []},
            {"id": 3, "pdf_title": "B", "filepath": "/b.pdf", "filename": "b.pdf",
             "page_count": 200, "tags": []},
        ]
        got = rpgr.reconcile("q", rpglib_books=books, mempalace_result=mp)
        kinds = [(h["kind"], h.get("cost")) for h in got.hits]
        assert kinds[0] == ("drawer", None)
        # Only book 3 (no drawer) becomes an expensive candidate.
        cand_book_ids = [h.get("book_id") for h in got.hits
                         if h["kind"] == "candidate"]
        assert cand_book_ids == [3]

    def test_k_expensive_caps_emission(self):
        mp = _fake_mp_result([])
        books = [
            {"id": i, "pdf_title": f"B{i}", "filepath": f"/b{i}.pdf",
             "filename": f"b{i}.pdf", "page_count": 50, "tags": []}
            for i in range(1, 11)
        ]
        got = rpgr.reconcile("q", rpglib_books=books, mempalace_result=mp,
                             k_expensive=3)
        assert got.candidates_expensive_emitted == 3

    def test_include_expensive_false_suppresses_all(self):
        mp = _fake_mp_result([])
        books = [{"id": 1, "pdf_title": "X", "filepath": "/p.pdf",
                  "filename": "p.pdf", "page_count": 10, "tags": []}]
        got = rpgr.reconcile("q", rpglib_books=books, mempalace_result=mp,
                             include_expensive=False)
        assert got.candidates_expensive_emitted == 0
        assert got.hits == []

    def test_cheap_candidates_emitted_in_order(self):
        from fivetools_catalog import Candidate as FC
        cheap = [
            FC(entity_type="monster", name="Drow Priestess of Lolth",
               source="MM", file_path="/d/bestiary-mm.json",
               wrapper_key="monster", score=82, page=129),
            FC(entity_type="chapter", name="Velkynvelve", source="OotA",
               file_path="/d/adventure-oota.json", wrapper_key="data",
               score=100, chapter_ordinal=0),
        ]
        mp = _fake_mp_result([])
        got = rpgr.reconcile(
            "drow", rpglib_books=[], fivetools_candidates=cheap,
            mempalace_result=mp, palace="abyss",
        )
        assert got.candidates_cheap_emitted == 2
        first, second = got.hits[:2]
        assert first["kind"] == "candidate" and first["cost"] == "cheap"
        # Catalog order is preserved (the catalog itself sorts by score).
        assert first["name"] == "Drow Priestess of Lolth"
        assert "--filter" in first["ingest_command"]
        assert "name=Drow Priestess of Lolth,source=MM" in first["ingest_command"]
        assert "--palace" in first["ingest_command"]
        assert first["ingest_command"][-1] == "abyss"
        # Adventure cheap candidate uses chapter filter.
        assert second["entity_type"] == "chapter"
        assert "chapter=0" in second["ingest_command"]

    def test_include_cheap_false_suppresses_cheap_tier(self):
        from fivetools_catalog import Candidate as FC
        cheap = [FC(entity_type="monster", name="X", source="MM",
                    file_path="/d/m.json", wrapper_key="monster", score=80)]
        mp = _fake_mp_result([])
        got = rpgr.reconcile("q", rpglib_books=[], fivetools_candidates=cheap,
                             mempalace_result=mp, include_cheap=False)
        assert got.candidates_cheap_emitted == 0


# ── retrieve (top-level) ─────────────────────────────────────────────────


def test_retrieve_end_to_end_with_fakes(rpglib_http, monkeypatch):
    base_url, responses = rpglib_http
    responses["nlq"] = [
        {"id": 7, "pdf_title": "Some Book", "filepath": "/m/s.pdf",
         "publisher": "Indie", "game_system": "D&D 5e", "product_type": "adventure",
         "tags": ["urban"], "page_count": 80},
    ]
    fake_mp = FakeMempalaceClient(responses={
        "mempalace_search_hierarchical": lambda **kw: {
            "query": kw["query"], "max_depth": kw.get("max_depth", 2),
            "path": {"wings": [], "rooms": []}, "results": [],
            "total_before_filter": 0, "fallback": False,
        },
    })
    out = rpgr.retrieve(
        "urban", rpg_library_url=base_url, mp_client=fake_mp,
        limit=5, k_cheap=0, k_expensive=2, palace="abyss",
    )
    # No drawers, no cheap (k_cheap=0), one expensive candidate from rpglib.
    assert out["drawer_hits"] == 0
    assert out["candidates_cheap_emitted"] == 0
    assert out["candidates_expensive_emitted"] == 1
    hit = out["hits"][0]
    assert hit["kind"] == "candidate"
    assert hit["cost"] == "expensive"
    # Palace is plumbed into the ingest command.
    assert "--palace" in hit["ingest_command"]
    assert hit["ingest_command"][hit["ingest_command"].index("--palace") + 1] == "abyss"


def test_retrieve_mode_c_cheap_pin():
    # Mode C: no query, file_path + pin_filter → single cheap candidate.
    out = rpgr.retrieve(
        query="",
        file_path="/d/bestiary-mm.json",
        pin_filter="name=Drow Priestess of Lolth",
        palace="abyss",
    )
    assert out["candidates_cheap_emitted"] == 1
    assert out["candidates_expensive_emitted"] == 0
    hit = out["hits"][0]
    assert hit["kind"] == "candidate"
    assert hit["cost"] == "cheap"
    assert hit["score"] == 100
    cmd = hit["ingest_command"]
    assert cmd[2].endswith("bestiary-mm.json")
    assert "--filter" in cmd
    assert cmd[cmd.index("--filter") + 1] == "name=Drow Priestess of Lolth"
    assert "--palace" in cmd
    assert cmd[cmd.index("--palace") + 1] == "abyss"


def test_retrieve_validation_requires_some_driver():
    with pytest.raises(ValueError):
        rpgr.retrieve(query="")


def test_retrieve_book_id_only_targets_expensive(rpglib_http):
    base_url, responses = rpglib_http
    responses["books"][42] = {
        "id": 42, "filepath": "/x/y.pdf", "pdf_title": "Pinned",
        "publisher": "WotC", "game_system": "D&D 5e",
        "product_type": "adventure", "tags": [], "page_count": 200,
    }
    fake_mp = FakeMempalaceClient(responses={
        "mempalace_search_hierarchical": lambda **kw: {
            "query": "", "max_depth": 2, "path": {"wings": [], "rooms": []},
            "results": [], "total_before_filter": 0, "fallback": False,
        },
    })
    out = rpgr.retrieve(query="", book_id=42, rpg_library_url=base_url,
                        mp_client=fake_mp)
    assert out["candidates_expensive_emitted"] == 1
    assert out["candidates_cheap_emitted"] == 0
    assert out["hits"][0]["book_id"] == 42
