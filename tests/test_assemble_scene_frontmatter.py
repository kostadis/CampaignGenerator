"""Tests for session_doc/assemble.py's scene-number frontmatter handling
(issue #261).

assemble.py used to parse per-scene YAML frontmatter with its own
hand-rolled `k: v` line splitter (`parse_frontmatter`), which always
returned string values. It now imports `campaignlib.textproc.
split_frontmatter`, a real YAML parser, and that changes the TYPE of the
`scene` field: `scene: 04` becomes the int 4, but `scene: 08` and
`scene: 09` become the strings '08'/'09' (PyYAML's octal resolver rejects
08/09 as invalid octal and falls back to str). assemble.py must coerce both
shapes to the same scene number without crashing on a bare `.strip()` (which
an int does not have) and without regressing the existing skip-on-missing /
skip-on-non-numeric behaviour.

Reuses the subprocess harness pattern from test_assemble_audit_comment.py.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _write_scene(dir_path: Path, filename: str, frontmatter_lines: list[str],
                  body: str) -> Path:
    fm = "\n".join(frontmatter_lines)
    path = dir_path / filename
    path.write_text(f"---\n{fm}\n---\n{body}\n", encoding="utf-8")
    return path


def _run_assemble(narr: Path, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "session_doc/assemble.py"), str(narr),
         "--output", str(out)],
        capture_output=True, text=True, cwd=REPO)


def test_int_scene_under_yaml(tmp_path):
    """`scene: 04` parses as the YAML int 4 — must not crash on `.strip()`."""
    narr = tmp_path / "summaries" / "20260706" / "narration"
    narr.mkdir(parents=True)
    _write_scene(narr, "session_doc_scene_04_x.md",
                 ["scene: 04", "scene_name: Four"], "Scene four prose.")

    out = tmp_path / "session_doc.md"
    proc = _run_assemble(narr, out)

    assert proc.returncode == 0, proc.stderr
    assert "Scene four prose." in out.read_text(encoding="utf-8")


def test_str_scene_under_yaml_invalid_octal(tmp_path):
    """`scene: 08` is invalid octal, so PyYAML yields the STR '08', not an
    int — the coercion must accept this shape too."""
    narr = tmp_path / "summaries" / "20260706" / "narration"
    narr.mkdir(parents=True)
    _write_scene(narr, "session_doc_scene_08_x.md",
                 ["scene: 08", "scene_name: Eight"], "Scene eight prose.")

    out = tmp_path / "session_doc.md"
    proc = _run_assemble(narr, out)

    assert proc.returncode == 0, proc.stderr
    assert "Scene eight prose." in out.read_text(encoding="utf-8")


def test_missing_scene_key_is_skipped(tmp_path):
    """A file with no `scene` field is skipped with the existing message —
    it must not appear in the assembled document."""
    narr = tmp_path / "summaries" / "20260706" / "narration"
    narr.mkdir(parents=True)
    _write_scene(narr, "session_doc_scene_01_x.md",
                 ["scene_name: NoScene"], "Should not appear.")
    # A second, valid scene so assemble doesn't hard-error on "no usable
    # scene files" (which would mask the skip behaviour under test).
    _write_scene(narr, "session_doc_scene_02_x.md",
                 ["scene: 2", "scene_name: Two"], "Scene two prose.")

    out = tmp_path / "session_doc.md"
    proc = _run_assemble(narr, out)

    assert proc.returncode == 0, proc.stderr
    assert "missing or non-numeric 'scene'" in proc.stderr
    assembled = out.read_text(encoding="utf-8")
    assert "Should not appear." not in assembled
    assert "Scene two prose." in assembled


def test_non_numeric_scene_is_skipped(tmp_path):
    """A `scene:` value that isn't numeric at all is skipped the same way."""
    narr = tmp_path / "summaries" / "20260706" / "narration"
    narr.mkdir(parents=True)
    _write_scene(narr, "session_doc_scene_01_x.md",
                 ["scene: not-a-number", "scene_name: Bad"],
                 "Should not appear.")
    _write_scene(narr, "session_doc_scene_02_x.md",
                 ["scene: 2", "scene_name: Two"], "Scene two prose.")

    out = tmp_path / "session_doc.md"
    proc = _run_assemble(narr, out)

    assert proc.returncode == 0, proc.stderr
    assert "missing or non-numeric 'scene'" in proc.stderr
    assembled = out.read_text(encoding="utf-8")
    assert "Should not appear." not in assembled
    assert "Scene two prose." in assembled
