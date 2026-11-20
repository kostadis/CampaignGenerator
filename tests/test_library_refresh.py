import json
import os
from pathlib import Path

import pytest

from pipelines.library import EmbedderMismatch, NotBuilt
from pipelines.library.build import build, refresh
from tests.test_library_build import sidecar, world


class PalaceClient:
    """Fake client that models drawers so stale ones are observable."""

    def __init__(self):
        self.calls = []
        self.drawers = {}  # source_path -> room

    def mine(self, render_root, *, wing, files=None):
        self.calls.append(("mine", sorted(files) if files is not None else None))
        root = Path(render_root)
        names = files if files is not None else [
            p.relative_to(root).as_posix() for p in root.rglob("*.md")]
        for f in names:
            self.drawers[str(root / f)] = f.split("/")[0]
        return "ok"

    def delete_room(self, wing, room):
        self.calls.append(("delete_room", room))
        gone = [k for k, v in self.drawers.items() if v == room]
        for k in gone:
            del self.drawers[k]
        return len(gone)

    def search(self, query, *, wing=None, limit=50):
        return {"results": []}


def _touch_change(cfg, book_id, sections):
    p = Path(cfg.source_root) / f"{book_id}.json"
    sidecar(p, sections)
    st = p.stat()
    os.utime(p, (st.st_atime, st.st_mtime + 100))


def _built(tmp_path, books):
    cfg = world(tmp_path, books)
    c = PalaceClient()
    build(cfg, client=c)
    c.calls.clear()
    return cfg, c


def _no_stale(cfg, c):
    sections = json.loads((cfg.work_dir / "rendered" / "sections.json").read_text())
    root = cfg.work_dir / "rendered"
    for sp in c.drawers:
        assert Path(sp).relative_to(root).as_posix() in sections, f"stale drawer {sp}"


def test_changed_book_deletes_room_then_mines_only_it(tmp_path):
    cfg, c = _built(tmp_path, {1: ("A", "B"), 2: ("C",)})
    _touch_change(cfg, 1, ("A",))  # B section disappears
    rep = refresh(cfg, client=c)
    assert c.calls[0] == ("delete_room", "b1")
    assert c.calls[1][0] == "mine" and all(f.startswith("b1/") for f in c.calls[1][1])
    assert len(c.calls) == 2  # book 2 untouched
    assert rep.changed == [1] and rep.removed == []
    _no_stale(cfg, c)
    sections = json.loads((cfg.work_dir / "rendered" / "sections.json").read_text())
    assert sum(1 for r in sections.values() if r["book_id"] == 1) == 1
    assert sum(1 for r in sections.values() if r["book_id"] == 2) == 1
    assert rep.passages == 2 and rep.indexed == 2


def test_removed_book(tmp_path):
    cfg, c = _built(tmp_path, {1: ("A",), 2: ("C",)})
    cfg.exclude_book_ids = [2]
    rep = refresh(cfg, client=c)
    assert ("delete_room", "b2") in c.calls
    assert not any(x[0] == "mine" for x in c.calls)
    assert rep.removed == [2] and rep.changed == []
    assert "2" not in json.loads((cfg.work_dir / "library_ledger.json").read_text())
    assert not (cfg.work_dir / "rendered" / "b2").exists()
    _no_stale(cfg, c)


def test_unchanged_no_client_calls(tmp_path):
    cfg, c = _built(tmp_path, {1: ("A",), 2: ("C",)})
    rep = refresh(cfg, client=c)
    assert c.calls == [] and rep.changed == [] and rep.removed == []


def test_ledger_updated(tmp_path):
    cfg, c = _built(tmp_path, {1: ("A",)})
    before = json.loads((cfg.work_dir / "library_ledger.json").read_text())["1"]
    _touch_change(cfg, 1, ("A", "B"))
    refresh(cfg, client=c)
    after = json.loads((cfg.work_dir / "library_ledger.json").read_text())["1"]
    assert after["src_mtime"] != before["src_mtime"] and len(after["files"]) == 2
    assert after["render_hash"] != before["render_hash"]


def test_added_book_is_mined(tmp_path):
    cfg, c = _built(tmp_path, {1: ("A",)})
    # a second book appears in the library db and on disk
    import sqlite3
    pdf = Path(cfg.source_root) / "9.pdf"
    pdf.write_text("")
    sidecar(pdf.with_suffix(".json"), ("Z",))
    con = sqlite3.connect(cfg.rpg_library_db)
    con.execute("INSERT INTO books VALUES (9,?,?,?,?,?,0,0,0)", (str(pdf), "Book 9", None, "Pub", "adventure"))
    con.commit()
    con.close()
    rep = refresh(cfg, client=c)
    assert rep.changed == [9]
    assert c.calls == [("mine", ["b9/" + p.name for p in (cfg.work_dir / "rendered" / "b9").glob("*.md")])]
    _no_stale(cfg, c)


def test_refresh_before_build_not_built(tmp_path):
    cfg = world(tmp_path, {1: ("A",)})
    with pytest.raises(NotBuilt):
        refresh(cfg, client=PalaceClient())


def test_refresh_refuses_embedder_mismatch(tmp_path):
    cfg, c = _built(tmp_path, {1: ("A",)})
    cfg.env["MEMPALACE_EMBEDDING_MODEL"] = "other"
    with pytest.raises(EmbedderMismatch):
        refresh(cfg, client=c)


class FailingMine(PalaceClient):
    fail = True

    def mine(self, render_root, *, wing, files=None):
        if self.fail:
            raise RuntimeError("mine exploded")
        return super().mine(render_root, wing=wing, files=files)


def test_refresh_failed_mine_marks_failed_then_retries(tmp_path):
    cfg, c = _built(tmp_path, {1: ("A",), 2: ("B",)})
    _touch_change(cfg, 1, ("A", "A2"))
    bad = FailingMine()
    bad.drawers = dict(c.drawers)
    with pytest.raises(RuntimeError, match="mine exploded"):
        refresh(cfg, client=bad)
    ledger = json.loads((cfg.work_dir / "library_ledger.json").read_text())
    assert ledger["1"]["status"] == "failed" and "mine exploded" in ledger["1"]["reason"]
    assert ledger["2"]["status"] == "indexed"
    bad.fail = False
    bad.calls.clear()
    rep = refresh(cfg, client=bad)
    assert 1 in rep.changed
    assert ("mine", ["b1/001-a.md", "b1/002-a2.md"]) in bad.calls
    ledger = json.loads((cfg.work_dir / "library_ledger.json").read_text())
    assert ledger["1"]["status"] == "indexed"


def test_refresh_failed_delete_marks_failed_and_does_not_mine_it(tmp_path):
    from pipelines.rlm.mempalace_client import MempalaceError

    cfg, c = _built(tmp_path, {1: ("A",), 2: ("B",)})
    _touch_change(cfg, 1, ("A", "A2"))

    class BadDelete(PalaceClient):
        def delete_room(self, wing, room):
            raise MempalaceError("delete failed")

    bd = BadDelete()
    bd.drawers = dict(c.drawers)
    rep = refresh(cfg, client=bd)
    assert [f["book_id"] for f in rep.failed] == [1]
    assert not any(call[0] == "mine" for call in bd.calls)
    ledger = json.loads((cfg.work_dir / "library_ledger.json").read_text())
    assert ledger["1"]["status"] == "failed"
