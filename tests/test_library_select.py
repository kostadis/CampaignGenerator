import sqlite3
from pathlib import Path

import pipelines.library as pkg
from pipelines.library.select import read_manifest, select_books, write_manifest

WORKTREE = Path(__file__).resolve().parent.parent


def test_package_imported_from_worktree():
    assert Path(pkg.__file__).resolve().is_relative_to(WORKTREE)


def _db(tmp_path, rows):
    p = tmp_path / "lib.db"
    con = sqlite3.connect(p)
    con.execute(
        "CREATE TABLE books (id INTEGER PRIMARY KEY, filepath TEXT, display_title TEXT,"
        " pdf_title TEXT, publisher TEXT, product_type TEXT, is_old_version INT, is_duplicate INT)"
    )
    con.executemany("INSERT INTO books VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return p


def _touch(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    return p


def row(i, root, name, ptype="adventure", old=0, dup=0, dt="T", pt=None, pub="P"):
    return (i, str(root / name), dt, pt, pub, ptype, old, dup)


def test_selects_only_finished_sidecars(tmp_path):
    root = tmp_path / "src"
    _touch(root / "A/A.pdf"); _touch(root / "A/A.json")
    _touch(root / "B/B.pdf"); _touch(root / "B/B-extract.json")
    db = _db(tmp_path, [row(1, root, "A/A.pdf"), row(2, root, "B/B.pdf")])
    assert [b["book_id"] for b in select_books(db, root)] == [1]


def test_excludes_old_and_duplicate(tmp_path):
    root = tmp_path / "src"
    rows = []
    for i, (name, kw) in enumerate(
        [("a.pdf", {}), ("b.pdf", {"old": 1}), ("c.pdf", {"dup": 1}), ("d.old-001.pdf", {})], 1
    ):
        _touch(root / name); _touch((root / name).with_suffix(".json"))
        rows.append(row(i, root, name, **kw))
    db = _db(tmp_path, rows)
    assert [b["book_id"] for b in select_books(db, root)] == [1]


def test_type_filter_and_limit(tmp_path):
    root = tmp_path / "src"
    rows = []
    for i, t in [(5, "adventure"), (3, "setting"), (4, "novel"), (9, "gm_aid"), (1, "adventure")]:
        n = f"{i}.pdf"
        _touch(root / n); _touch(root / f"{i}.json")
        rows.append(row(i, root, n, ptype=t))
    db = _db(tmp_path, rows)
    assert [b["book_id"] for b in select_books(db, root)] == [1, 3, 5, 9]
    assert [b["book_id"] for b in select_books(db, root, limit=2)] == [1, 3]


def test_title_fallback(tmp_path):
    root = tmp_path / "src"
    rows = []
    for i, (dt, pt) in enumerate([("D", "P"), (None, "P"), (None, None)], 1):
        n = f"stem{i}.pdf"
        _touch(root / n); _touch(root / f"stem{i}.json")
        rows.append(row(i, root, n, dt=dt, pt=pt))
    db = _db(tmp_path, rows)
    assert [b["title"] for b in select_books(db, root)] == ["D", "P", "stem3"]


def test_rejects_filepath_outside_root(tmp_path):
    root = tmp_path / "src"
    other = tmp_path / "other"
    _touch(root / "a.pdf"); _touch(root / "a.json")
    _touch(other / "b.pdf"); _touch(other / "b.json")
    db = _db(tmp_path, [row(1, root, "a.pdf"), row(2, other, "b.pdf")])
    assert [b["book_id"] for b in select_books(db, root)] == [1]


def test_manifest_roundtrip(tmp_path):
    books = [{"book_id": 1}]
    write_manifest(books, tmp_path / "m.json")
    assert read_manifest(tmp_path / "m.json") == {"books": books}
