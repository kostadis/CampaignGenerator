import json

import pytest

from pipelines.rpglib_palace.guard import PalaceGuardError
from pipelines.rpglib_palace.query import format_human, run_query


def _setup(tmp_path, files):
    """files: {rel: (book_id, body)}"""
    root = tmp_path / "rendered"
    sections = {}
    for rel, (bid, body) in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# T > S\n<!-- book_id={bid} page=4 -->\n\n{body}\n")
        sections[rel] = {
            "file": rel, "book_id": bid, "title": f"Book{bid}", "publisher": "P",
            "section_path": ["S"], "page": 4,
        }
    (root / "sections.json").write_text(json.dumps(sections))
    return root


def _hit(root, rel, sim, chunk="chunk"):
    # Shape pinned from mempalace.searcher.query.search_within: source_file is the
    # BASENAME, source_path the full stored path.
    return {
        "drawer_id": "d", "text": chunk, "wing": "wing_dmsguild", "room": rel.split("/")[0],
        "source_file": rel.split("/")[-1], "source_path": str(root / rel),
        "similarity": sim, "distance": round(1 - sim, 4),
    }


def _fake(hits):
    return lambda text, palace, n: {
        "query": text, "filters": {}, "total_before_filter": len(hits),
        "primary": hits, "results": hits, "themes": [],
    }


PAL = "rpglib-palace/palace"


def run(tmp_path, root, hits, **kw):
    return run_query("q", tmp_path / PAL, root, search_fn=_fake(hits), home=tmp_path, **kw)


def test_expands_to_whole_section(tmp_path):
    root = _setup(tmp_path, {"b1/001-a.md": (1, "WHOLE BODY")})
    out = run(tmp_path, root, [_hit(root, "b1/001-a.md", 0.9, "just a chunk")])
    r = out["results"][0]
    assert "WHOLE BODY" in r["text"] and "just a chunk" not in r["text"]
    assert "book_id=" not in r["text"]
    assert (r["title"], r["book_id"], r["page"], r["section_path"]) == ("Book1", 1, 4, ["S"])


def test_dedupes_chunks_of_same_file(tmp_path):
    root = _setup(tmp_path, {"b1/001-a.md": (1, "x"), "b2/001-a.md": (2, "y")})
    hits = [_hit(root, "b1/001-a.md", 0.5), _hit(root, "b2/001-a.md", 0.7), _hit(root, "b1/001-a.md", 0.9)]
    out = run(tmp_path, root, hits)
    assert [r["file"] for r in out["results"]] == ["b1/001-a.md", "b2/001-a.md"]
    assert out["results"][0]["score"] == 0.9


def test_same_basename_different_books_not_merged(tmp_path):
    root = _setup(tmp_path, {"b1/001-a.md": (1, "x"), "b2/001-a.md": (2, "y")})
    out = run(tmp_path, root, [_hit(root, "b1/001-a.md", 0.9), _hit(root, "b2/001-a.md", 0.8)])
    assert out["distinct_books"] == 2


def test_cap_two_per_book(tmp_path):
    files = {f"b1/00{i}-a.md": (1, "x") for i in range(5)}
    files["b2/001-z.md"] = (2, "z")
    root = _setup(tmp_path, files)
    hits = [_hit(root, k, 0.9) for k in files]
    out = run(tmp_path, root, hits)
    assert len(out["results"]) == 3 and out["cap_fired"] == 3 and out["distinct_books"] == 2


def test_unmapped_reported(tmp_path):
    root = _setup(tmp_path, {"b1/001-a.md": (1, "x")})
    ghost = _hit(root, "b9/009-gone.md", 0.8)
    out = run(tmp_path, root, [ghost, _hit(root, "b1/001-a.md", 0.7)])
    assert len(out["unmapped"]) == 1 and "009-gone" in out["unmapped"][0]
    assert len(out["results"]) == 1


def test_query_refuses_live_palace(tmp_path):
    root = _setup(tmp_path, {"b1/001-a.md": (1, "x")})
    with pytest.raises(PalaceGuardError):
        run_query("q", tmp_path / ".mempalace/palace", root,
                  search_fn=_fake([]), home=tmp_path)


def test_search_error_raises(tmp_path):
    root = _setup(tmp_path, {"b1/001-a.md": (1, "x")})
    with pytest.raises(RuntimeError):
        run_query("q", tmp_path / PAL, root, home=tmp_path,
                  search_fn=lambda *a: {"error": "boom", "results": []})


def test_format_human(tmp_path):
    root = _setup(tmp_path, {"b1/001-a.md": (1, "x")})
    s = format_human(run(tmp_path, root, [_hit(root, "b1/001-a.md", 0.9)]))
    assert "[1] Book1 (book 1)" in s and "p.4" in s and "distinct books: 1" in s
