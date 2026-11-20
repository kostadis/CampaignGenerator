import os
import shutil

from pipelines.library.fetch import fetch_all


def _book(tmp_path, i, content=b"{}", create=True):
    p = tmp_path / "src" / f"{i}.json"
    p.parent.mkdir(exist_ok=True)
    if create:
        p.write_bytes(content)
    return {"book_id": i, "sidecar_path": str(p)}


def test_copies_new(tmp_path):
    b = _book(tmp_path, 1, b'{"a":1}')
    r = fetch_all([b], tmp_path / "cache")[0]
    assert r["status"] == "copied"
    assert (tmp_path / "cache/1.json").read_bytes() == b'{"a":1}'
    assert r["bytes"] == 7 and r["cache_path"].endswith("1.json")


def test_skips_unchanged(tmp_path, monkeypatch):
    b = _book(tmp_path, 1)
    fetch_all([b], tmp_path / "cache")

    def boom(*a, **k):
        raise AssertionError("copied")

    monkeypatch.setattr(shutil, "copy2", boom)
    assert fetch_all([b], tmp_path / "cache")[0]["status"] == "cached"


def test_recopies_on_change(tmp_path):
    b = _book(tmp_path, 1, b"{}")
    fetch_all([b], tmp_path / "cache")
    (tmp_path / "src/1.json").write_bytes(b'{"x": 1}')
    assert fetch_all([b], tmp_path / "cache")[0]["status"] == "copied"
    # mtime-only change
    p = tmp_path / "src/1.json"
    os.utime(p, (1, 1))
    assert fetch_all([b], tmp_path / "cache")[0]["status"] == "copied"


def test_missing_source_continues(tmp_path):
    bs = [_book(tmp_path, 1, create=False), _book(tmp_path, 2)]
    assert [r["status"] for r in fetch_all(bs, tmp_path / "cache")] == ["missing", "copied"]
