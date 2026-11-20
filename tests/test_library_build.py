import json
import sqlite3
from pathlib import Path

import pytest

from pipelines.library import SourceUnavailable
from pipelines.library.build import BuildReport, build
from pipelines.library.config import LibraryConfig, Selection


class FakeClient:
    def __init__(self):
        self.calls = []

    def mine(self, render_root, *, wing, files=None):
        self.calls.append(("mine", Path(render_root), wing, files))
        return "ok"

    def delete_room(self, wing, room):
        self.calls.append(("delete_room", wing, room))
        return 1

    def search(self, query, *, wing=None, limit=50):
        self.calls.append(("search", query))
        return {"results": []}


def sidecar(path: Path, sections=("Intro",)):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"data": [
        {"type": "section", "name": n, "page": 1, "entries": [f"body of {n}"]} for n in sections
    ]}))


def world(tmp_path, books):
    """books: {id: sections tuple | 'bad' | None(no sidecar)}"""
    root = tmp_path / "src"
    root.mkdir()
    db = tmp_path / "lib.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, filepath TEXT, display_title TEXT,"
                " pdf_title TEXT, publisher TEXT, product_type TEXT, is_old_version INT,"
                " is_duplicate INT, is_printer_friendly INT)")
    for i, secs in books.items():
        pdf = root / f"{i}.pdf"
        pdf.write_text("")
        if secs == "bad":
            pdf.with_suffix(".json").write_text("{not json")
        elif secs is not None:
            sidecar(pdf.with_suffix(".json"), secs)
        con.execute("INSERT INTO books VALUES (?,?,?,?,?,?,0,0,0)",
                    (i, str(pdf), f"Book {i}", None, "Pub", "adventure"))
    con.commit()
    con.close()
    env = {"MEMPALACE_BACKEND": "turbovec", "MEMPALACE_EMBEDDING_PROVIDER": "ollama",
           "MEMPALACE_EMBEDDING_MODEL": "qwen3-embedding:0.6b",
           "MEMPALACE_EMBEDDING_ENDPOINT": "http://h:1"}
    return LibraryConfig(
        palace=tmp_path / "pal", source_root=root, work_dir=tmp_path / "work",
        cache_dir=tmp_path / "work" / "cache", selection=Selection(all_converted=True),
        rpg_library_db=db, env=env)


def test_build_writes_state_and_mines(tmp_path):
    cfg = world(tmp_path, {1: ("A", "B"), 2: ("C",)})
    client = FakeClient()
    rep = build(cfg, client=client)
    w = cfg.work_dir
    for f in ("manifest.json", "library_ledger.json", "rendered/sections.json", "embedder.json"):
        assert (w / f).is_file(), f
    assert (w / "rendered" / "b1").is_dir()
    assert isinstance(rep, BuildReport)
    assert (rep.selected, rep.indexed, rep.passages) == (2, 2, 3)
    assert rep.skipped == [] and rep.failed == []
    assert sorted(rep.changed) == [1, 2]
    mines = [c for c in client.calls if c[0] == "mine"]
    assert len(mines) == 1 and mines[0][1] == w / "rendered" and mines[0][2] == "wing_dmsguild"
    ledger = json.loads((w / "library_ledger.json").read_text())
    e = ledger["1"]
    assert e["status"] == "indexed" and len(e["files"]) == 2 and e["render_hash"]
    assert e["src_size"] > 0 and e["src_mtime"] > 0
    stamp = json.loads((w / "embedder.json").read_text())
    assert stamp["backend"] == "turbovec" and stamp["model"] == "qwen3-embedding:0.6b"
    assert stamp["provider"] == "ollama" and stamp["endpoint"] == "http://h:1"
    assert "built_at" in stamp
    assert set(json.loads((w / "rendered" / "sections.json").read_text())) == {
        "b1/001-a.md", "b1/002-b.md", "b2/001-c.md"}


def test_unreadable_and_missing_sidecars_skipped_others_build(tmp_path):
    cfg = world(tmp_path, {1: ("A",), 2: "bad", 3: ("C",)})
    # book 4: row exists, sidecar vanishes after selection -> simulate via fetch miss below
    rep = build(cfg, client=FakeClient())
    assert rep.indexed == 2
    assert [s["book_id"] for s in rep.skipped] == [2]
    assert "unreadable" in rep.skipped[0]["reason"]
    ledger = json.loads((cfg.work_dir / "library_ledger.json").read_text())
    assert ledger["2"]["status"] == "skipped" and ledger["2"]["reason"]
    assert "b2" not in {p.split("/")[0] for p in json.loads(
        (cfg.work_dir / "rendered" / "sections.json").read_text())}


def test_book_with_no_sections_skipped(tmp_path):
    cfg = world(tmp_path, {1: ("A",)})
    (Path(cfg.source_root) / "1.json").write_text(json.dumps({"data": []}))
    rep = build(cfg, client=FakeClient())
    assert rep.indexed == 0 and rep.skipped[0]["book_id"] == 1


def test_unreadable_source_root_raises_and_writes_nothing(tmp_path):
    cfg = world(tmp_path, {1: ("A",)})
    cfg.source_root = tmp_path / "gone"
    client = FakeClient()
    with pytest.raises(SourceUnavailable):
        build(cfg, client=client)
    assert not (cfg.work_dir / "rendered").exists()
    assert not (cfg.work_dir / "library_ledger.json").exists()
    assert client.calls == []


def test_mine_error_propagates_and_no_stamp(tmp_path):
    cfg = world(tmp_path, {1: ("A",)})

    class Boom(FakeClient):
        def mine(self, *a, **k):
            raise RuntimeError("mine failed")

    with pytest.raises(RuntimeError):
        build(cfg, client=Boom())
    assert not (cfg.work_dir / "embedder.json").exists()


def test_rebuild_clears_stale_rendered(tmp_path):
    cfg = world(tmp_path, {1: ("A", "B")})
    build(cfg, client=FakeClient())
    sidecar(Path(cfg.source_root) / "1.json", ("A",))
    build(cfg, client=FakeClient())
    assert not (cfg.work_dir / "rendered" / "b1" / "002-b.md").exists()


def test_rebuild_deletes_prior_rooms_before_mining(tmp_path):
    cfg = world(tmp_path, {1: ("A",), 2: ("C",)})
    build(cfg, client=FakeClient())
    client = FakeClient()
    build(cfg, client=client)
    kinds = [c[0] for c in client.calls]
    assert kinds == ["delete_room", "delete_room", "mine"]
    assert {c[2] for c in client.calls if c[0] == "delete_room"} == {"b1", "b2"}
