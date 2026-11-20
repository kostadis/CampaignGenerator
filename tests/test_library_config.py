from pathlib import Path

import pytest

from pipelines.library import ExitCode, NotConfigured, PalaceRefused
from pipelines.library.config import load_library_config

BASE = """env:
  MEMPALACE_BACKEND: turbovec
  MEMPALACE_EMBEDDING_MODEL: qwen3-embedding:0.6b
  OTHER: ignored
data_roots:
  rpg_library_db: ~/lib/rpg_library.db
library:
  palace: {palace}
  work_dir: {work}
  source_root: {src}
  selection:
{selection}
"""


def _write(tmp_path, selection="    all_converted: true\n", extra="", text=None):
    p = tmp_path / "h.yaml"
    p.write_text(
        text
        if text is not None
        else BASE.format(
            palace=tmp_path / "lib/palace",
            work=tmp_path / "lib",
            src=tmp_path / "src",
            selection=selection,
        )
        + extra
    )
    return p


def load(tmp_path, environ=None, **kw):
    return load_library_config(
        _write(tmp_path, **kw), environ if environ is not None else {}, home=tmp_path
    )


def test_reads_block(tmp_path):
    c = load(tmp_path, selection="    product_types: [adventure, setting]\n",
             extra="  exclude_book_ids: [7]\n")
    assert c.palace == (tmp_path / "lib/palace").resolve()
    assert c.work_dir == tmp_path / "lib"
    assert c.source_root == tmp_path / "src"
    assert c.cache_dir == tmp_path / "lib" / "cache"  # default <work_dir>/cache
    assert c.selection.product_types == ["adventure", "setting"]
    assert c.exclude_book_ids == [7]


def test_cache_dir_explicit(tmp_path):
    c = load(tmp_path, extra=f"  cache_dir: {tmp_path / 'cc'}\n")
    assert c.cache_dir == tmp_path / "cc"


def test_env_merge_never_overrides(tmp_path):
    c = load(tmp_path, {"MEMPALACE_BACKEND": "chroma", "A": "1"})
    assert c.env["MEMPALACE_BACKEND"] == "chroma"
    assert c.env["MEMPALACE_EMBEDDING_MODEL"] == "qwen3-embedding:0.6b"
    assert c.env["A"] == "1" and "OTHER" not in c.env


def test_missing_file(tmp_path):
    with pytest.raises(NotConfigured, match="hypostasis"):
        load_library_config(tmp_path / "nope.yaml", {}, home=tmp_path)


def test_missing_block(tmp_path):
    with pytest.raises(NotConfigured, match="library:"):
        load(tmp_path, text="env:\n  MEMPALACE_BACKEND: turbovec\ndata_roots:\n  rpg_library_db: x\n")


@pytest.mark.parametrize("sel", ["", "    product_types: []\n", "    all_converted: false\n"])
def test_missing_or_empty_selection(tmp_path, sel):
    with pytest.raises(NotConfigured, match="selection"):
        load(tmp_path, selection=sel)


def test_two_forms_refused_naming_forms(tmp_path):
    with pytest.raises(NotConfigured) as ei:
        load(tmp_path, selection="    all_converted: true\n    book_ids: [1]\n")
    assert "all_converted" in str(ei.value) and "book_ids" in str(ei.value)


def test_no_backend_refused(tmp_path):
    with pytest.raises(NotConfigured, match="MEMPALACE_BACKEND"):
        load(tmp_path, text=BASE.format(
            palace=tmp_path / "p", work=tmp_path / "w", src=tmp_path / "s",
            selection="    all_converted: true\n").replace("MEMPALACE_BACKEND: turbovec", "X: 1"))


def test_tilde_expanded_and_db_top_level(tmp_path):
    c = load(tmp_path)
    assert c.rpg_library_db == Path("~/lib/rpg_library.db").expanduser()
    assert "~" not in str(c.rpg_library_db)


def test_live_palace_refused(tmp_path):
    p = _write(tmp_path)
    p.write_text(p.read_text().replace(str(tmp_path / "lib/palace"),
                                       str(tmp_path / ".mempalace/palaces/x")))
    with pytest.raises(PalaceRefused):
        load_library_config(p, {}, home=tmp_path)


def test_exit_codes():
    assert [e.value for e in ExitCode] == [0, 1, 2, 3, 4, 5, 6]
    assert NotConfigured.exit_code == ExitCode.NOT_CONFIGURED == 3


def test_top_level_rpg_library_db_not_accepted(tmp_path):
    text = BASE.format(
        palace=tmp_path / "lib/palace", work=tmp_path / "lib", src=tmp_path / "src",
        selection="    all_converted: true\n",
    ).replace("data_roots:\n  rpg_library_db:", "rpg_library_db:")
    with pytest.raises(NotConfigured, match=r"data_roots\.rpg_library_db"):
        load(tmp_path, text=text)
