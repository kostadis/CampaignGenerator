"""Tests for ``query_rpg_lib.py`` (GH mneme#9 — HTTP-only rework).

query_rpg_lib.py used to open rpg-lib's SQLite DB directly; it now talks to
rpg-lib's HTTP API instead, tested here against an in-process stdlib
HTTPServer fixture — mirroring the ``rpglib_http`` fixture in
``tests/test_rpg_retriever.py``.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import yaml

import query_rpg_lib as qrl


class _CannedRpgLibraryHandler(BaseHTTPRequestHandler):
    """In-process rpg-library API stand-in for ``/search`` and ``/book/{id}``."""

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
                self._respond({"detail": "Book not found"}, 404)
                return
            self._respond(book)
            return
        if self.path.startswith("/api/library/search"):
            results = responses.get("search", [])
            self._respond({
                "results": results, "total": len(results),
                "page": 1, "per_page": 50, "total_pages": 1,
            })
            return
        self._respond({"detail": "unhandled"}, 404)


@pytest.fixture
def rpglib_http():
    """Spin up a local HTTPServer on an ephemeral port. Yields
    ``(base_url, responses_dict)``; mutate the dict in-test to control
    the canned payloads.
    """
    server = HTTPServer(("127.0.0.1", 0), _CannedRpgLibraryHandler)
    server.responses = {"search": [], "books": {}}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base_url, server.responses
    finally:
        server.shutdown()
        thread.join(timeout=2)


# ── search ─────────────────────────────────────────────────────────────


def test_search_happy_path(rpglib_http, capsys):
    base_url, responses = rpglib_http
    responses["search"] = [
        {"id": 7421, "display_title": "Tales of the Yawning Portal",
         "filename": "tales.pdf", "publisher": "WotC",
         "product_type": "adventure", "relative_path": "wotc/tales.pdf"},
    ]
    rc = qrl.main(["yawning portal", "--rpg-library-url", base_url])
    assert rc == 0
    out = capsys.readouterr().out
    assert "id=7421" in out
    assert "Tales of the Yawning Portal" in out


# ── --book-id emit ───────────────────────────────────────────────────────


def test_book_id_emit_happy_path(rpglib_http, capsys):
    base_url, responses = rpglib_http
    responses["books"][7421] = {
        "id": 7421, "display_title": "Tales of the Yawning Portal",
        "filename": "tales.pdf", "publisher": "WotC",
        "relative_path": "wotc/tales.pdf",
    }
    rc = qrl.main(["--book-id", "7421", "--rpg-library-url", base_url])
    assert rc == 0
    out = capsys.readouterr().out
    entry = yaml.safe_load(out)[0]
    assert entry["rpglib"] == "wotc/tales.pdf"
    assert entry["book_id"] == 7421


def test_book_id_not_found(rpglib_http):
    base_url, _responses = rpglib_http
    with pytest.raises(SystemExit) as exc_info:
        qrl.main(["--book-id", "99999", "--rpg-library-url", base_url])
    assert "Book not found" in str(exc_info.value)


# ── unreachable server ────────────────────────────────────────────────────


def test_unreachable_server_raises_systemexit():
    with pytest.raises(SystemExit) as exc_info:
        qrl.main(["anything", "--rpg-library-url", "http://127.0.0.1:1"])
    assert "library_server" in str(exc_info.value)
