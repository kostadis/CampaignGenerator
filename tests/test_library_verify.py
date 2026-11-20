import pytest

from pipelines.library import LibraryError
from pipelines.library.verify import verify_citation


@pytest.fixture
def work(tmp_path):
    r = tmp_path / "rendered" / "b1"
    r.mkdir(parents=True)
    (r / "001-a.md").write_text("# T\n<!-- book_id=1 page=null -->\n\nThe  tavern keeper\nis a gruff dwarf.\n")
    (tmp_path / "secret.md").write_text("outside")
    return tmp_path


def test_exact_found_with_offset(work):
    r = verify_citation(work, "b1/001-a.md", "gruff dwarf")
    assert r["found"] is True and r["file"] == "b1/001-a.md"
    text = (work / "rendered/b1/001-a.md").read_text()
    assert text[r["offset"]:].startswith("gruff dwarf")


def test_whitespace_only_difference_found(work):
    r = verify_citation(work, "b1/001-a.md", "The tavern   keeper is a gruff dwarf.")
    assert r["found"] is True


def test_changed_word_not_found(work):
    assert verify_citation(work, "b1/001-a.md", "The tavern keeper is a gruff elf.")["found"] is False


def test_empty_quote_not_found(work):
    assert verify_citation(work, "b1/001-a.md", "   ")["found"] is False


@pytest.mark.parametrize("f", ["../secret.md", "/etc/passwd", "b1/../../secret.md"])
def test_outside_rendered_refused(work, f):
    with pytest.raises(LibraryError):
        verify_citation(work, f, "outside")
