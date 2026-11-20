import json

import pytest

from pipelines.library import (
    EmbedderMismatch, NotBuilt, NotConfigured, PalaceRefused,
)
from pipelines.library.search import SearchResultSet
from pipelines.rlm import mcp_server


def _ctx(monkeypatch, config=None, client=None, exc=None):
    def fake():
        if exc:
            raise exc
        return config, client
    monkeypatch.setattr(mcp_server, "_library_context", fake)


def test_returns_full_passage_json(monkeypatch):
    out = SearchResultSet(query="q", results=[{"book_id": 1, "text": "FULL " * 500}], distinct_books=1)
    seen = {}

    def fake_search(config, query, *, limit, per_book, client):
        seen.update(query=query, limit=limit, per_book=per_book)
        return out

    monkeypatch.setattr("pipelines.library.search.search_library", fake_search)
    _ctx(monkeypatch, config=object(), client=object())
    r = json.loads(mcp_server.library_search("tavern", limit=3, per_book=1))
    assert r["results"][0]["text"] == "FULL " * 500
    assert seen == {"query": "tavern", "limit": 3, "per_book": 1}


@pytest.mark.parametrize("exc,code", [
    (NotConfigured("nc"), "not_configured"),
    (NotBuilt("nb"), "not_built"),
    (EmbedderMismatch("em"), "embedder_mismatch"),
    (PalaceRefused("pr"), "refused"),
])
def test_errors_returned_not_raised(monkeypatch, exc, code):
    _ctx(monkeypatch, exc=exc)
    r = json.loads(mcp_server.library_search("x"))
    assert r == {"error": code, "message": str(exc)}


def test_error_from_search_itself(monkeypatch):
    def boom(*a, **k):
        raise NotBuilt("not built")
    monkeypatch.setattr("pipelines.library.search.search_library", boom)
    _ctx(monkeypatch, config=object(), client=object())
    assert json.loads(mcp_server.library_search("x"))["error"] == "not_built"


def test_docstring_guidance():
    d = mcp_server.library_search.__doc__.lower()
    assert "wording" in d                      # try several wordings
    assert "read" in d and "passage" in d      # read before recommending
    assert "book <id>" in d or "(book" in d    # citation format
    assert "nothing matches" in d              # say so plainly
    assert "library_verify_citation" in d


def test_verify_citation_tool(monkeypatch, tmp_path):
    (tmp_path / "rendered" / "b1").mkdir(parents=True)
    (tmp_path / "rendered" / "b1" / "a.md").write_text("hello brave world")

    class C:
        work_dir = tmp_path
    _ctx(monkeypatch, config=C(), client=None)
    r = json.loads(mcp_server.library_verify_citation("b1/a.md", "brave  world"))
    assert r["found"] is True
    r = json.loads(mcp_server.library_verify_citation("../x", "q"))
    assert r["error"] == "failed"
