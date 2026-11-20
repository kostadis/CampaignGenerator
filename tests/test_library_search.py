import json
from pathlib import Path

import pytest

from pipelines.library import EmbedderMismatch, NotBuilt
from pipelines.library.config import LibraryConfig, Selection
from pipelines.library.search import format_human, search_library

ENV = {"MEMPALACE_BACKEND": "turbovec", "MEMPALACE_EMBEDDING_PROVIDER": "ollama",
       "MEMPALACE_EMBEDDING_MODEL": "qwen3-embedding:0.6b"}


def _cfg(tmp_path, env=None):
    return LibraryConfig(
        palace=tmp_path / "pal", source_root=tmp_path / "src", work_dir=tmp_path / "work",
        cache_dir=tmp_path / "work/cache", selection=Selection(all_converted=True),
        rpg_library_db=tmp_path / "db", env=dict(ENV if env is None else env))


def _setup(tmp_path, files, stamp=True):
    """files: {rel: (book_id, body)}; returns (config, render_root)."""
    cfg = _cfg(tmp_path)
    root = cfg.work_dir / "rendered"
    sections = {}
    for rel, (bid, body) in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# T > S\n<!-- book_id={bid} page=4 -->\n\n{body}\n")
        sections[rel] = {
            "file": rel, "book_id": bid, "title": f"Book{bid}", "publisher": "P",
            "section_path": ["S"], "page": 4,
        }
    root.mkdir(parents=True, exist_ok=True)
    (root / "sections.json").write_text(json.dumps(sections))
    if stamp:
        (cfg.work_dir / "embedder.json").write_text(json.dumps({
            "backend": "turbovec", "provider": "ollama", "model": "qwen3-embedding:0.6b",
            "endpoint": None, "built_at": "x"}))
    return cfg, root


def _hit(root, rel, sim, chunk="chunk"):
    # Shape pinned from the MCP mempalace_search: source_file is the BASENAME,
    # source_path the full stored path.
    return {
        "drawer_id": "d", "text": chunk, "wing": "wing_dmsguild", "room": rel.split("/")[0],
        "source_file": rel.split("/")[-1], "source_path": str(root / rel),
        "similarity": sim, "distance": round(1 - sim, 4),
    }


class FakeClient:
    def __init__(self, hits=None, raw=None):
        self.raw = raw if raw is not None else {
            "query": "q", "filters": {}, "primary": hits, "results": hits, "themes": []}
        self.calls = []

    def search(self, query, *, wing=None, limit=50):
        self.calls.append((query, wing, limit))
        return self.raw


def run(cfg, root, hits, **kw):
    return search_library(cfg, "q", client=FakeClient(hits), **kw)


def test_expands_to_whole_section(tmp_path):
    cfg, root = _setup(tmp_path, {"b1/001-a.md": (1, "WHOLE BODY")})
    out = run(cfg, root, [_hit(root, "b1/001-a.md", 0.9, "just a chunk")])
    r = out.results[0]
    assert "WHOLE BODY" in r["text"] and "just a chunk" not in r["text"]
    assert "book_id=" not in r["text"]
    assert (r["title"], r["book_id"], r["page"], r["section_path"]) == ("Book1", 1, 4, ["S"])


def test_dedupes_chunks_of_same_file(tmp_path):
    cfg, root = _setup(tmp_path, {"b1/001-a.md": (1, "x"), "b2/001-a.md": (2, "y")})
    hits = [_hit(root, "b1/001-a.md", 0.5), _hit(root, "b2/001-a.md", 0.7), _hit(root, "b1/001-a.md", 0.9)]
    out = run(cfg, root, hits)
    assert [r["file"] for r in out.results] == ["b1/001-a.md", "b2/001-a.md"]
    assert out.results[0]["score"] == 0.9


def test_same_basename_different_books_not_merged(tmp_path):
    cfg, root = _setup(tmp_path, {"b1/001-a.md": (1, "x"), "b2/001-a.md": (2, "y")})
    out = run(cfg, root, [_hit(root, "b1/001-a.md", 0.9), _hit(root, "b2/001-a.md", 0.8)])
    assert out.distinct_books == 2


def test_cap_per_book(tmp_path):
    files = {f"b1/00{i}-a.md": (1, "x") for i in range(5)}
    files["b2/001-z.md"] = (2, "z")
    cfg, root = _setup(tmp_path, files)
    out = run(cfg, root, [_hit(root, k, 0.9) for k in files])
    assert len(out.results) == 3 and out.cap_fired == 3 and out.distinct_books == 2


def test_unmapped_reported(tmp_path):
    cfg, root = _setup(tmp_path, {"b1/001-a.md": (1, "x")})
    out = run(cfg, root, [_hit(root, "b9/009-gone.md", 0.8), _hit(root, "b1/001-a.md", 0.7)])
    assert len(out.unmapped) == 1 and "009-gone" in out.unmapped[0]
    assert len(out.results) == 1


def test_limit_truncates(tmp_path):
    files = {f"b{i}/001-a.md": (i, "x") for i in range(1, 6)}
    cfg, root = _setup(tmp_path, files)
    assert len(run(cfg, root, [_hit(root, k, 0.9) for k in files], limit=3).results) == 3


def test_goes_through_client_with_wing(tmp_path):
    cfg, root = _setup(tmp_path, {"b1/001-a.md": (1, "x")})
    c = FakeClient([_hit(root, "b1/001-a.md", 0.9)])
    search_library(cfg, "tavern", client=c)
    assert c.calls[0][0] == "tavern" and c.calls[0][1] == "wing_dmsguild"


def test_not_built_without_stamp_or_sections(tmp_path):
    cfg, root = _setup(tmp_path, {"b1/001-a.md": (1, "x")}, stamp=False)
    with pytest.raises(NotBuilt, match="library build"):
        run(cfg, root, [])
    cfg2 = _cfg(tmp_path / "other")
    with pytest.raises(NotBuilt):
        search_library(cfg2, "q", client=FakeClient([]))


def test_embedder_mismatch_names_both_models(tmp_path):
    cfg, root = _setup(tmp_path, {"b1/001-a.md": (1, "x")})
    cfg.env["MEMPALACE_EMBEDDING_MODEL"] = "all-MiniLM-L6-v2"
    with pytest.raises(EmbedderMismatch) as ei:
        run(cfg, root, [])
    msg = str(ei.value)
    assert "qwen3-embedding:0.6b" in msg and "all-MiniLM-L6-v2" in msg


def test_mismatch_checked_before_searching(tmp_path):
    cfg, root = _setup(tmp_path, {"b1/001-a.md": (1, "x")})
    cfg.env["MEMPALACE_BACKEND"] = "chroma"
    c = FakeClient([])
    with pytest.raises(EmbedderMismatch):
        search_library(cfg, "q", client=c)
    assert c.calls == []


def test_search_error_raises(tmp_path):
    cfg, root = _setup(tmp_path, {"b1/001-a.md": (1, "x")})
    with pytest.raises(RuntimeError, match="boom"):
        search_library(cfg, "q", client=FakeClient(raw={"error": "boom", "results": []}))


def test_to_dict_and_format_human(tmp_path):
    cfg, root = _setup(tmp_path, {"b1/001-a.md": (1, "x")})
    out = run(cfg, root, [_hit(root, "b1/001-a.md", 0.9)])
    d = out.to_dict()
    assert set(d) == {"query", "results", "distinct_books", "cap_fired", "unmapped", "latency_s"}
    s = format_human(out)
    assert "[1] Book1 (book 1)" in s and "p.4" in s and "distinct books: 1" in s
