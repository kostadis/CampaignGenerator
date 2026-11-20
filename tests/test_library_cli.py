import json
from pathlib import Path

import pytest

from pipelines.library import NotConfigured, PalaceRefused
from pipelines.library import cli
from pipelines.library.search import SearchResultSet
from tests.test_library_search import _setup


class C:
    def search(self, *a, **k):
        return {"results": []}


def _patch(monkeypatch, cfg):
    monkeypatch.setattr(cli, "load_library_config", lambda *a, **k: cfg)
    monkeypatch.setattr(cli, "_client", lambda c: C())


def _select(monkeypatch, ids):
    from pipelines.library.select import LibraryBook
    monkeypatch.setattr("pipelines.library.status.select_books_report",
                        lambda c: ([LibraryBook(i, "t", None, None, "p", "s") for i in ids], []))


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
    def boom(*a, **k):
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
    def boom(*a, **k):
        raise PalaceRefused("refusing")
    monkeypatch.setattr(cli, "load_library_config", boom)
    assert cli.main(["status"]) == 6


def test_status_json_fields(monkeypatch, tmp_path, capsys):
    cfg, _ = _setup(tmp_path, {"b1/001.md": (1, "x")})
    _patch(monkeypatch, cfg)
    _select(monkeypatch, [])
    assert cli.main(["status", "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    for k in ("configured", "built", "books", "stale", "added", "removed", "embedder_match", "palace", "index_bytes"):
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
    _select(monkeypatch, [1, 2])
    cli.main(["status", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["stale"] == [2] and out["added"] == [] and out["removed"] == []


def test_verify_citation_cli(monkeypatch, tmp_path, capsys):
    cfg, root = _setup(tmp_path, {"b1/001.md": (1, "brave new world")})
    _patch(monkeypatch, cfg)
    assert cli.main(["verify-citation", "b1/001.md", "brave  new", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["found"] is True
    assert cli.main(["verify-citation", "b1/001.md", "nope"]) == 1


def test_refresh_cli(monkeypatch, tmp_path, capsys):
    cfg, _ = _setup(tmp_path, {})
    _patch(monkeypatch, cfg)
    from pipelines.library.build import BuildReport
    monkeypatch.setattr("pipelines.library.build.refresh",
                        lambda c, client: BuildReport(selected=1, indexed=1, changed=[7]))
    assert cli.main(["refresh", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["changed"] == [7]


def test_refresh_not_built_exit_4(monkeypatch, tmp_path):
    cfg, _ = _setup(tmp_path, {}, stamp=False)
    _patch(monkeypatch, cfg)
    assert cli.main(["refresh"]) == 4


def test_status_reports_added_and_removed(tmp_path, capsys):
    """Real selection + ledger from a built library; refresh must agree."""
    from pipelines.library.build import build, refresh
    from tests.test_library_refresh import PalaceClient
    from tests.test_library_build import world, sidecar

    cfg = world(tmp_path, {1: ("A",), 2: ("B",)})
    cfg.selection.all_converted = False
    cfg.selection.book_ids = [1, 2]
    build(cfg, client=PalaceClient())
    # widen to add 3 (new on disk and selected), narrow away 2
    import sqlite3
    con = sqlite3.connect(cfg.rpg_library_db)
    pdf = cfg.source_root / "3.pdf"
    pdf.write_text("")
    sidecar(pdf.with_suffix(".json"), ("C",))
    con.execute("INSERT INTO books VALUES (3,?,?,?,?,?,0,0,0)",
                (str(pdf), "Book 3", None, "Pub", "adventure"))
    con.commit()
    con.close()
    cfg.selection.book_ids = [1, 3]

    from pipelines.library.status import status
    s = status(cfg)
    assert s["added"] == [3] and s["removed"] == [2]
    assert s["stale"] == [2, 3]
    rep = refresh(cfg, client=PalaceClient())
    assert rep.removed == s["removed"] and s["added"][0] in rep.changed
    s2 = status(cfg)
    assert s2["added"] == [] and s2["removed"] == [] and s2["stale"] == []


def test_status_human_mentions_added_removed(monkeypatch, tmp_path, capsys):
    cfg, _ = _setup(tmp_path, {"b1/001.md": (1, "x")})
    (cfg.work_dir / "library_ledger.json").write_text(json.dumps(
        {"2": {"status": "indexed", "src_size": 0, "src_mtime": 0}}))
    _patch(monkeypatch, cfg)
    _select(monkeypatch, [1])
    assert cli.main(["status"]) == 0
    assert "(added 1, removed 1)" in capsys.readouterr().out


def test_config_flag_status_honoured(monkeypatch, tmp_path):
    cfg, _ = _setup(tmp_path, {"b1/001.md": (1, "x")})
    _select(monkeypatch, [])
    seen = []
    monkeypatch.setattr(cli, "load_library_config", lambda p: seen.append(p) or cfg)
    assert cli.main(["status", "--json", "--config", "~/alt/h.yaml"]) == 0
    assert seen == [Path("~/alt/h.yaml").expanduser()]
    assert cli.main(["status", "-c", "/x/y.yaml"]) == 0
    assert seen[-1] == Path("/x/y.yaml")


def test_config_flag_build_honoured(monkeypatch, tmp_path):
    cfg, _ = _setup(tmp_path, {})
    seen = []
    monkeypatch.setattr(cli, "load_library_config", lambda p: seen.append(p) or cfg)
    monkeypatch.setattr(cli, "_client", lambda c: C())
    from pipelines.library.build import BuildReport
    monkeypatch.setattr("pipelines.library.build.build", lambda c, client: BuildReport())
    assert cli.main(["build", "--json", "--config", "/x/h.yaml"]) == 0
    assert seen == [Path("/x/h.yaml")]


@pytest.mark.parametrize("argv", [["status", "--json"], ["build"], ["refresh"], ["search", "q"],
                                  ["verify-citation", "f", "q"]])
def test_config_flag_missing_file_exit_3(tmp_path, capsys, argv):
    missing = tmp_path / "nope.yaml"
    assert cli.main(argv + ["--config", str(missing)]) == 3
    assert str(missing) in capsys.readouterr().err


def test_default_config_path_unchanged(monkeypatch, tmp_path):
    cfg, _ = _setup(tmp_path, {})
    _select(monkeypatch, [])
    seen = []
    monkeypatch.setattr(cli, "load_library_config", lambda p: seen.append(p) or cfg)
    cli.main(["status", "--json"])
    assert seen == [Path("~/.config/hypostasis/hypostasis.yaml").expanduser()]
