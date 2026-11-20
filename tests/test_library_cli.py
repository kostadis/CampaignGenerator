import json

import pytest

from pipelines.library import NotConfigured, PalaceRefused
from pipelines.library import cli
from pipelines.library.search import SearchResultSet
from tests.test_library_search import _setup


class C:
    def search(self, *a, **k):
        return {"results": []}


def _patch(monkeypatch, cfg):
    monkeypatch.setattr(cli, "load_library_config", lambda: cfg)
    monkeypatch.setattr(cli, "_client", lambda c: C())


def _results():
    return SearchResultSet(query="q", results=[{
        "book_id": 1, "title": "Book1", "publisher": "P", "section_path": ["S"],
        "page": 4, "score": 0.9, "file": "b1/001.md", "text": "body"}], distinct_books=1)


def test_search_human_and_json(monkeypatch, tmp_path, capsys):
    cfg, _ = _setup(tmp_path, {"b1/001.md": (1, "x")})
    _patch(monkeypatch, cfg)
    monkeypatch.setattr("pipelines.library.search.search_library", lambda *a, **k: _results())
    assert cli.main(["search", "q"]) == 0
    assert "Book1 (book 1)" in capsys.readouterr().out
    assert cli.main(["search", "q", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["distinct_books"] == 1


def test_not_configured_exit_3(monkeypatch, capsys):
    def boom():
        raise NotConfigured("no library: block; add one")
    monkeypatch.setattr(cli, "load_library_config", boom)
    assert cli.main(["search", "q"]) == 3
    assert "library: block" in capsys.readouterr().err


def test_not_built_exit_4_names_hypostasis(monkeypatch, tmp_path, capsys):
    cfg, _ = _setup(tmp_path, {}, stamp=False)
    _patch(monkeypatch, cfg)
    assert cli.main(["search", "q"]) == 4
    assert "hypostasis" in capsys.readouterr().err


def test_embedder_mismatch_exit_5(monkeypatch, tmp_path, capsys):
    cfg, _ = _setup(tmp_path, {"b1/001.md": (1, "x")})
    cfg.env["MEMPALACE_EMBEDDING_MODEL"] = "other"
    _patch(monkeypatch, cfg)
    assert cli.main(["search", "q"]) == 5
    err = capsys.readouterr().err
    assert "other" in err and "qwen3-embedding:0.6b" in err


def test_refused_exit_6(monkeypatch, tmp_path):
    def boom():
        raise PalaceRefused("refusing")
    monkeypatch.setattr(cli, "load_library_config", boom)
    assert cli.main(["status"]) == 6


def test_status_json_fields(monkeypatch, tmp_path, capsys):
    cfg, _ = _setup(tmp_path, {"b1/001.md": (1, "x")})
    _patch(monkeypatch, cfg)
    assert cli.main(["status", "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    for k in ("configured", "built", "books", "stale", "embedder_match", "palace", "index_bytes"):
        assert k in s
    assert s["configured"] and s["built"] and s["embedder_match"] is True


def test_status_not_built_exit_4(monkeypatch, tmp_path, capsys):
    cfg, _ = _setup(tmp_path, {}, stamp=False)
    _patch(monkeypatch, cfg)
    assert cli.main(["status", "--json"]) == 4
    assert json.loads(capsys.readouterr().out)["built"] is False


def test_status_reports_stale(monkeypatch, tmp_path, capsys):
    cfg, _ = _setup(tmp_path, {"b1/001.md": (1, "x")})
    src = tmp_path / "s.json"
    src.write_text("{}")
    st = src.stat()
    (cfg.work_dir / "manifest.json").write_text(json.dumps({"books": [
        {"book_id": 1, "sidecar_path": str(src)}, {"book_id": 2, "sidecar_path": str(src)}]}))
    (cfg.work_dir / "library_ledger.json").write_text(json.dumps({
        "1": {"src_size": st.st_size, "src_mtime": st.st_mtime, "status": "indexed"},
        "2": {"src_size": st.st_size + 1, "src_mtime": st.st_mtime, "status": "indexed"}}))
    _patch(monkeypatch, cfg)
    cli.main(["status", "--json"])
    assert json.loads(capsys.readouterr().out)["stale"] == [2]


def test_verify_citation_cli(monkeypatch, tmp_path, capsys):
    cfg, root = _setup(tmp_path, {"b1/001.md": (1, "brave new world")})
    _patch(monkeypatch, cfg)
    assert cli.main(["verify-citation", "b1/001.md", "brave  new", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["found"] is True
    assert cli.main(["verify-citation", "b1/001.md", "nope"]) == 1
