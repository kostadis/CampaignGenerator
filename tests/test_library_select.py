import sqlite3
from pathlib import Path

import pipelines.library as pkg
from pipelines.library.config import LibraryConfig, Selection
from pipelines.library.select import read_manifest, select_books, write_manifest

WORKTREE = Path(__file__).resolve().parent.parent


def test_package_imported_from_worktree():
    assert Path(pkg.__file__).resolve().is_relative_to(WORKTREE)


def _db(tmp_path, rows):
    p = tmp_path / "lib.db"
    con = sqlite3.connect(p)
    con.execute(
        "CREATE TABLE books (id INTEGER PRIMARY KEY, filepath TEXT, display_title TEXT,"
        " pdf_title TEXT, publisher TEXT, product_type TEXT, is_old_version INT, is_duplicate INT,"
        " is_printer_friendly INT)"
    )
    con.executemany("INSERT INTO books VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return p


def _touch(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    return p


def row(i, root, name, ptype="adventure", old=0, dup=0, dt="T", pt=None, pub="P", pf=0):
    return (i, str(root / name), dt, pt, pub, ptype, old, dup, pf)


def cfg(tmp_path, db, root, **sel):
    exclude = sel.pop("exclude_book_ids", [])
    sel = sel or {"all_converted": True}
    return LibraryConfig(
        palace=tmp_path / "pal", source_root=root, work_dir=tmp_path / "w",
        cache_dir=tmp_path / "c", selection=Selection(**sel), rpg_library_db=db,
        exclude_book_ids=exclude,
    )


def mk(tmp_path, specs):
    """specs: list of (id, name, kwargs). Creates pdf+sidecar. Returns (db, root)."""
    root = tmp_path / "src"
    rows = []
    for i, name, kw in specs:
        _touch(root / name)
        _touch((root / name).with_suffix(".json"))
        rows.append(row(i, root, name, **{"dt": f"T{i}", **kw}))
    return _db(tmp_path, rows), root


def ids(books):
    return [b.book_id for b in books]


def test_selects_only_finished_sidecars(tmp_path):
    root = tmp_path / "src"
    _touch(root / "A/A.pdf"); _touch(root / "A/A.json")
    _touch(root / "B/B.pdf"); _touch(root / "B/B-extract.json")
    db = _db(tmp_path, [row(1, root, "A/A.pdf"), row(2, root, "B/B.pdf")])
    assert ids(select_books(cfg(tmp_path, db, root))) == [1]


def test_excludes_old_and_duplicate(tmp_path):
    db, root = mk(tmp_path, [(1, "a.pdf", {}), (2, "b.pdf", {"old": 1}),
                             (3, "c.pdf", {"dup": 1}), (4, "d.old-001.pdf", {})])
    assert ids(select_books(cfg(tmp_path, db, root))) == [1]


def test_product_types(tmp_path):
    db, root = mk(tmp_path, [(5, "5.pdf", {"ptype": "adventure"}), (3, "3.pdf", {"ptype": "setting"}),
                             (4, "4.pdf", {"ptype": "novel"}), (9, "9.pdf", {"ptype": "gm_aid"})])
    got = select_books(cfg(tmp_path, db, root, product_types=["adventure", "setting"]))
    assert ids(got) == [3, 5]


def test_book_ids(tmp_path):
    db, root = mk(tmp_path, [(1, "1.pdf", {}), (2, "2.pdf", {}), (3, "3.pdf", {})])
    assert ids(select_books(cfg(tmp_path, db, root, book_ids=[3, 1]))) == [1, 3]


def test_all_converted_includes_every_type(tmp_path):
    db, root = mk(tmp_path, [(1, "1.pdf", {"ptype": "novel"}), (2, "2.pdf", {"ptype": None})])
    assert ids(select_books(cfg(tmp_path, db, root))) == [1, 2]


def test_exclude_book_ids(tmp_path):
    db, root = mk(tmp_path, [(1, "1.pdf", {}), (2, "2.pdf", {})])
    assert ids(select_books(cfg(tmp_path, db, root, exclude_book_ids=[1]))) == [2]
    assert ids(select_books(cfg(tmp_path, db, root, book_ids=[1, 2], exclude_book_ids=[2]))) == [1]


def test_print_friendly_twin_deduped(tmp_path):
    db, root = mk(tmp_path, [
        (1, "a-pf.pdf", {"dt": "Dungeon of Doom (Print Friendly)"}),
        (2, "a.pdf", {"dt": "Dungeon of Doom"}),
        (3, "b.pdf", {"dt": "Other"}),
    ])
    assert ids(select_books(cfg(tmp_path, db, root))) == [2, 3]


def test_printer_friendly_variant_and_case(tmp_path):
    db, root = mk(tmp_path, [
        (1, "a.pdf", {"dt": "Dungeon  of Doom [Printer Friendly]"}),
        (2, "b.pdf", {"dt": "dungeon of doom"}),
    ])
    assert ids(select_books(cfg(tmp_path, db, root))) == [2]


def test_flag_tiebreaker_when_titles_identical(tmp_path):
    db, root = mk(tmp_path, [(1, "a.pdf", {"dt": "Same", "pf": 1}), (2, "b.pdf", {"dt": "Same", "pf": 0})])
    assert ids(select_books(cfg(tmp_path, db, root))) == [2]


def test_only_print_friendly_copy_is_kept(tmp_path):
    db, root = mk(tmp_path, [(1, "a-pf.pdf", {"dt": "Solo (Print Friendly)"})])
    assert ids(select_books(cfg(tmp_path, db, root))) == [1]


def test_explicit_book_ids_bypass_dedupe(tmp_path):
    db, root = mk(tmp_path, [
        (1, "a-pf.pdf", {"dt": "Dungeon (Print Friendly)"}),
        (2, "a.pdf", {"dt": "Dungeon"}),
    ])
    assert ids(select_books(cfg(tmp_path, db, root, book_ids=[1, 2]))) == [1, 2]


def test_title_fallback(tmp_path):
    root = tmp_path / "src"
    rows = []
    for i, (dt, pt) in enumerate([("D", "P"), (None, "P"), (None, None)], 1):
        n = f"stem{i}.pdf"
        _touch(root / n); _touch(root / f"stem{i}.json")
        rows.append(row(i, root, n, dt=dt, pt=pt))
    db = _db(tmp_path, rows)
    assert [b.title for b in select_books(cfg(tmp_path, db, root))] == ["D", "P", "stem3"]


def test_rejects_filepath_outside_root(tmp_path):
    root = tmp_path / "src"
    other = tmp_path / "other"
    _touch(root / "a.pdf"); _touch(root / "a.json")
    _touch(other / "b.pdf"); _touch(other / "b.json")
    db = _db(tmp_path, [row(1, root, "a.pdf"), row(2, other, "b.pdf")])
    assert ids(select_books(cfg(tmp_path, db, root))) == [1]


def test_manifest_roundtrip(tmp_path):
    books = [{"book_id": 1}]
    write_manifest(books, tmp_path / "m.json")
    assert read_manifest(tmp_path / "m.json") == {"books": books}
