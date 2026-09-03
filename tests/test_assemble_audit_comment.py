"""Tests for assemble.py stripping Pass 5's table-speech audit comment
(issue #245, Work Order A).

Pass 5 (narrate) may append a single HTML comment after the narration when
it reclassifies a mislabelled quoted span as GM table speech:

    <!-- table-speech reclassified: "..." | "..." -->

That comment is the GM's review queue and belongs in the per-scene
``.md`` file — it must never leak into the assembled session document, and
the per-scene source file must be left untouched by assembly (assemble.py
only reads scene files, it never writes them). An unrelated hand-written
HTML comment must survive assembly unchanged.

Reuses the subprocess harness pattern from ``test_chapter_identity.py``
(``_scene`` helper + ``subprocess.run`` against ``session_doc/assemble.py``).
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _scene(dir_path: Path, n: int, body: str) -> None:
    (dir_path / f"session_doc_scene_{n:02d}_x.md").write_text(
        f"---\nscene: {n}\nscene_name: Scene {n}\nnarrator: Vukradin\n---\n{body}\n",
        encoding="utf-8")


def _run_assemble(narr: Path, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "session_doc/assemble.py"), str(narr),
         "--output", str(out)],
        capture_output=True, text=True, cwd=REPO)


def test_audit_comment_stripped_and_source_unmodified(tmp_path):
    """A trailing single-line audit comment is stripped from the assembled
    document, the narration prose is otherwise byte-identical (modulo
    trailing whitespace) to the same scene without the comment, and the
    per-scene source file on disk is left untouched."""
    prose = "The room fell quiet as she considered what to say next."
    comment = ('<!-- table-speech reclassified: "you immediately remember" '
               '| "So he says:" -->')

    narr_with = tmp_path / "with" / "summaries" / "20260706" / "narration"
    narr_with.mkdir(parents=True)
    _scene(narr_with, 1, prose + "\n\n" + comment)
    scene_path = narr_with / "session_doc_scene_01_x.md"
    source_before = scene_path.read_text(encoding="utf-8")

    out_with = tmp_path / "with" / "session_doc.md"
    proc_with = _run_assemble(narr_with, out_with)
    assert proc_with.returncode == 0, proc_with.stderr

    narr_without = tmp_path / "without" / "summaries" / "20260706" / "narration"
    narr_without.mkdir(parents=True)
    _scene(narr_without, 1, prose)
    out_without = tmp_path / "without" / "session_doc.md"
    proc_without = _run_assemble(narr_without, out_without)
    assert proc_without.returncode == 0, proc_without.stderr

    assembled_with = out_with.read_text(encoding="utf-8")
    assembled_without = out_without.read_text(encoding="utf-8")

    assert "table-speech reclassified" not in assembled_with
    assert assembled_with.rstrip() == assembled_without.rstrip()

    # Assembly never writes the source scene file.
    assert scene_path.read_text(encoding="utf-8") == source_before
    assert "table-speech reclassified" in source_before


def test_multiline_audit_comment_stripped(tmp_path):
    """A <!-- ... --> audit comment spanning three lines is also stripped."""
    narr = tmp_path / "summaries" / "20260706" / "narration"
    narr.mkdir(parents=True)
    prose = "She let the silence answer for her."
    multiline_comment = (
        "<!-- table-speech reclassified:\n"
        '    "you immediately remember"\n'
        '    | "So he says:" -->'
    )
    _scene(narr, 1, prose + "\n\n" + multiline_comment)

    out = tmp_path / "session_doc.md"
    proc = _run_assemble(narr, out)
    assert proc.returncode == 0, proc.stderr

    assembled = out.read_text(encoding="utf-8")
    assert "table-speech reclassified" not in assembled
    assert "<!--" not in assembled
    assert prose in assembled


def test_unrelated_html_comment_survives(tmp_path):
    """A GM's own hand-written HTML comment is not touched by assembly."""
    narr = tmp_path / "summaries" / "20260706" / "narration"
    narr.mkdir(parents=True)
    prose = "He crossed the threshold without looking back."
    unrelated_comment = "<!-- GM: check this against the VTT -->"
    _scene(narr, 1, prose + "\n\n" + unrelated_comment)

    out = tmp_path / "session_doc.md"
    proc = _run_assemble(narr, out)
    assert proc.returncode == 0, proc.stderr

    assembled = out.read_text(encoding="utf-8")
    assert unrelated_comment in assembled


# --- provenance apparatus beyond Pass 5's own comment -----------------------
# voice-smooth and the manual post-narration repair pass both write their
# rulings into the per-scene file as HTML comments. Those are apparatus, not
# narration: the assembled doc feeds the release append and the chapter split,
# so anything left in it travels into the bible.

import pytest


@pytest.mark.parametrize("marker,comment", [
    ("hand-fixed", "<!-- hand-fixed after narration, 2026-09-02 (GM instruction):\n"
                   "     - Cut the second greeting; the dwarves greeted the party twice. -->"),
    ("Editorial note:", "<!-- Editorial note: unrecovered in both passes. Keep as\n"
                        "     captured. Do not narrate it as meaningful. -->"),
    ("Scene boundary note:", "<!-- Scene boundary note: the closing beat lives in scene 01\n"
                             "     per the GM's de-duplication ruling. -->"),
])
def test_provenance_comment_stripped(tmp_path, marker, comment):
    """Apparatus written by voice-smooth or a manual repair pass is stripped."""
    narr = tmp_path / "summaries" / "20260706" / "narration"
    narr.mkdir(parents=True)
    prose = "She let the silence answer for her."
    _scene(narr, 1, prose + "\n\n" + comment)

    out = tmp_path / "session_doc.md"
    proc = _run_assemble(narr, out)
    assert proc.returncode == 0, proc.stderr

    assembled = out.read_text(encoding="utf-8")
    assert marker not in assembled
    assert "<!--" not in assembled
    assert prose in assembled


def test_apparatus_stripped_but_gm_note_in_same_scene_survives(tmp_path):
    """The two kinds coexist in one scene and are treated differently."""
    narr = tmp_path / "summaries" / "20260706" / "narration"
    narr.mkdir(parents=True)
    prose = "He crossed the threshold without looking back."
    gm_note = "<!-- GM: check this against the VTT -->"
    apparatus = "<!-- Editorial note: keep as captured. -->"
    _scene(narr, 1, prose + "\n\n" + apparatus + "\n\n" + gm_note)

    out = tmp_path / "session_doc.md"
    proc = _run_assemble(narr, out)
    assert proc.returncode == 0, proc.stderr

    assembled = out.read_text(encoding="utf-8")
    assert "Editorial note:" not in assembled
    assert gm_note in assembled
    assert prose in assembled
