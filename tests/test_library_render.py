import json

import yaml

from pipelines.library import render
from pipelines.library.render import render_book, write_palace_layout

BOOK = {"book_id": 7, "title": "Book", "publisher": "Pub"}


def _sec(name, entries, page=None):
    d = {"type": "section", "name": name, "entries": entries}
    if page is not None:
        d["page"] = page
    return d


def test_one_file_per_top_section_with_breadcrumb(tmp_path):
    bj = {"data": [_sec("Ch1", ["alpha text"], 3), _sec("Ch2", ["beta text"], 9)]}
    recs = render_book(BOOK, bj, tmp_path)
    assert len(recs) == 2
    for r in recs:
        text = (tmp_path / r["file"]).read_text()
        assert text.startswith("# Book > ")
    assert recs[0]["page"] == 3 and recs[0]["section_path"] == ["Ch1"]
    assert recs[0]["file"].startswith("b7/001-")


def test_lists_and_tables_survive(tmp_path):
    bj = {
        "data": [
            _sec(
                "Ch",
                [
                    {"type": "list", "items": ["rumour about a hermit"]},
                    {"type": "table", "colLabels": ["d6", "Patron"], "rows": [["1", "Old Grimble"]]},
                ],
            )
        ]
    }
    recs = render_book(BOOK, bj, tmp_path)
    text = (tmp_path / recs[0]["file"]).read_text()
    assert "rumour about a hermit" in text and "Old Grimble" in text


def test_oversize_split_no_loss(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "MAX_FILE_BYTES", 300)
    kids = [_sec(f"Kid{i}", [f"unique-marker-{i} " + "word " * 20], i) for i in range(4)]
    recs = render_book(BOOK, {"data": [_sec("Big", kids, 1)]}, tmp_path)
    assert len(recs) >= 4
    texts = [(tmp_path / r["file"]).read_text() for r in recs]
    for i in range(4):
        assert sum(f"unique-marker-{i}" in t for t in texts) == 1
    assert any(r["section_path"] == ["Big", "Kid2"] and r["page"] == 2 for r in recs)


def test_oversize_paragraph_split_no_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "MAX_FILE_BYTES", 250)
    paras = [f"para-{i} " + "x" * 80 for i in range(6)]
    kid = _sec("Kid", paras)
    recs = render_book(BOOK, {"data": [_sec("Big", [kid])]}, tmp_path)
    texts = [(tmp_path / r["file"]).read_text() for r in recs]
    assert len(recs) > 1
    for i in range(6):
        assert sum(f"para-{i} " in t for t in texts) == 1
    assert any("-part" in r["file"] for r in recs)


def test_render_missing_pages(tmp_path):
    recs = render_book(BOOK, {"data": [_sec("Ch", ["x"])]}, tmp_path)
    assert recs[0]["page"] is None
    assert "page=null" in (tmp_path / recs[0]["file"]).read_text()


def test_no_data_list(tmp_path):
    assert render_book(BOOK, {}, tmp_path) == []
    assert render_book(BOOK, {"data": "nope"}, tmp_path) == []


def test_untitled_section(tmp_path):
    recs = render_book(BOOK, {"data": [{"type": "section", "entries": ["hi"]}]}, tmp_path)
    assert recs[0]["section_path"] == ["Untitled 1"]


def test_layout_files(tmp_path):
    recs = render_book(BOOK, {"data": [_sec("A", ["a"]), _sec("B", ["b"])]}, tmp_path)
    write_palace_layout(tmp_path, recs, [BOOK])
    cfg = yaml.safe_load((tmp_path / "mempalace.yaml").read_text())
    assert cfg["wing"] == "wing_dmsguild"
    assert [r["name"] for r in cfg["rooms"]] == ["b7"]
    assert "sections.json" in cfg["exclude_patterns"]
    sections = json.loads((tmp_path / "sections.json").read_text())
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.glob("b7/*.md")}
    assert set(sections) == written


def test_homebrew_adventuredata_shape(tmp_path):
    bj = {
        "_meta": {},
        "adventure": [{"name": "A", "id": "A", "source": "S", "contents": []}],
        "adventureData": [
            {"id": "A", "source": "S", "data": [_sec("Ch1", ["alpha"]), _sec("Ch2", ["beta"])]},
            {"id": "B", "source": "S", "data": [_sec("Ch3", ["gamma"])]},
        ],
    }
    recs = render_book(BOOK, bj, tmp_path)
    assert [r["section_path"] for r in recs] == [["Ch1"], ["Ch2"], ["Ch3"]]


def test_homebrew_bookdata_shape(tmp_path):
    bj = {"book": [{"name": "B"}], "bookData": [{"id": "B", "data": [_sec("Ch1", ["alpha"])]}]}
    recs = render_book(BOOK, bj, tmp_path)
    assert [r["section_path"] for r in recs] == [["Ch1"]]


def _messy():
    return {
        "data": [
            _sec("Real Chapter", ["real body " + "text " * 80], 4),
            _sec("5 gp", ["cell-one"], 5),
            _sec("Another Real", ["another body " + "word " * 80], 6),
            _sec("hit points.", ["frag-two"], 7),
        ]
    }


def test_merge_default_off(tmp_path):
    recs = render_book(BOOK, _messy(), tmp_path)
    assert len(recs) == 4
    assert all(r["merged_titles"] == [] for r in recs)


def test_merge_on_folds_fragments(tmp_path):
    recs = render_book(BOOK, _messy(), tmp_path, merge_fragments=True)
    assert [r["section_path"] for r in recs] == [["Real Chapter"], ["Another Real"]]
    assert recs[0]["merged_titles"] == ["5 gp"] and recs[0]["page"] == 4
    assert recs[1]["merged_titles"] == ["hit points."]


def test_merge_preserves_titles_and_text(tmp_path):
    recs = render_book(BOOK, _messy(), tmp_path, merge_fragments=True)
    texts = [(tmp_path / r["file"]).read_text() for r in recs]
    assert "### 5 gp" in texts[0] and "### hit points." in texts[1]
    for s in ("cell-one", "frag-two", "real body", "another body"):
        assert sum(s in t for t in texts) == 1


def test_merge_fragment_first(tmp_path):
    bj = {"data": [_sec("1/2", ["lead-frag"]), _sec("Real", ["real " * 100])]}
    recs = render_book(BOOK, bj, tmp_path, merge_fragments=True)
    assert [r["section_path"] for r in recs] == [["1/2"], ["Real"]]


def test_merge_short_body_min_chars(tmp_path):
    bj = {"data": [_sec("Real", ["real " * 100]), _sec("Tiny Title", ["short"])]}
    assert len(render_book(BOOK, bj, tmp_path / "a", merge_fragments=True)) == 1
    assert len(render_book(BOOK, bj, tmp_path / "b", merge_fragments=True, min_chars=3)) == 2


def test_merge_respects_max_file_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "MAX_FILE_BYTES", 400)
    bj = {"data": [_sec("Real", ["a " * 100]), _sec("5 gp", ["b " * 20] * 12)]}
    recs = render_book(BOOK, bj, tmp_path, merge_fragments=True)
    assert len(recs) >= 2
    for r in recs:
        assert (tmp_path / r["file"]).stat().st_size <= 400


def test_render_meta_written_and_excluded(tmp_path):
    recs = render_book(BOOK, _messy(), tmp_path, merge_fragments=True)
    write_palace_layout(
        tmp_path, recs, [BOOK], render_meta={"merge_fragments": True, "min_chars": 300}
    )
    meta = json.loads((tmp_path / "render_meta.json").read_text())
    assert meta == {"merge_fragments": True, "min_chars": 300}
    cfg = yaml.safe_load((tmp_path / "mempalace.yaml").read_text())
    assert "render_meta.json" in cfg["exclude_patterns"]
    assert set(json.loads((tmp_path / "sections.json").read_text())) == {r["file"] for r in recs}
