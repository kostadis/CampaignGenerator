"""`sd_review status` — and the one distinction it must not blur (#455).

A scene with no gap markers means two entirely different things:

- it was rendered with ``--gap-marking`` and the model found no GM description
  to hand back — a genuinely finished scene; or
- it was never rendered with ``--gap-marking`` at all — a scene whose review has
  not started.

Reporting the second as the first tells a GM their work is done before it has
begun, which is the Optimistic Lie this repo keeps paying for elsewhere. The
per-scene ``.knobs.json`` records the mode (#454), so the answer is on disk;
narrations older than that feature record nothing, and *unknown* is its own
state rather than a convenient ``False``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from session_doc.review.status import scene_status  # noqa: E402

MARKED = "prose one\n\n[GM NARRATION — TO BE WRITTEN: the GM said a thing]\n\nprose two\n"
CLEAN = "prose one\n\nprose two\n"


def scene(directory: Path, n: int = 1, *, text: str = CLEAN,
          knobs: dict | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / f"session_doc_scene_{n:02d}_x.md"
    p.write_text(text, encoding="utf-8")
    if knobs is not None:
        p.with_name(p.stem + ".knobs.json").write_text(
            json.dumps(knobs), encoding="utf-8")
    return p


def status(directory: Path) -> str:
    rc = subprocess.run(
        [sys.executable, "-m", "session_doc.sd_review", "status", "--dir", str(directory)],
        capture_output=True, text=True, cwd=ROOT)
    assert rc.returncode == 0, rc.stderr
    return rc.stdout


# ── the tri-state itself ────────────────────────────────────────────────────

def test_a_marker_settles_it_without_a_sidecar(tmp_path):
    """A scene holding a marker was gap-marked, whatever any file says. This is
    the case for narrations rendered before the sidecar carried the flag."""
    assert scene_status(scene(tmp_path, text=MARKED))["gap_marked"] is True


def test_a_clean_scene_that_records_the_mode_is_known_finished(tmp_path):
    assert scene_status(
        scene(tmp_path, knobs={"gap_marking": True}))["gap_marked"] is True


def test_a_scene_rendered_without_the_mode_says_so(tmp_path):
    assert scene_status(
        scene(tmp_path, knobs={"gap_marking": False}))["gap_marked"] is False


def test_a_narration_older_than_the_feature_is_unknown_not_unmarked(tmp_path):
    """No sidecar at all: the mode cannot be known. Answering `False` would be a
    guess, and answering `True` would be the lie."""
    assert scene_status(scene(tmp_path))["gap_marked"] is None


def test_a_sidecar_without_the_key_is_unknown(tmp_path):
    assert scene_status(
        scene(tmp_path, knobs={"model": "x"}))["gap_marked"] is None


def test_an_unreadable_sidecar_is_unknown_rather_than_an_error(tmp_path):
    n = scene(tmp_path)
    n.with_name(n.stem + ".knobs.json").write_text("{not json", encoding="utf-8")
    assert scene_status(n)["gap_marked"] is None


# ── what the CLI says about it ──────────────────────────────────────────────

def test_a_session_that_was_never_gap_marked_is_not_called_finished(tmp_path):
    d = tmp_path / "narration"
    scene(d)
    out = status(d)
    assert "nothing to review yet" in out
    assert "sd_narrate --gap-marking" in out
    assert "will pass" not in out


def test_a_gap_marked_session_that_came_back_clean_is_finished(tmp_path):
    d = tmp_path / "narration"
    scene(d, 1, knobs={"gap_marking": True})
    scene(d, 2, knobs={"gap_marking": True})
    out = status(d)
    assert "came back with no GM description" in out
    assert "assemble --require-composed will pass" in out


def test_one_unmarked_scene_is_named_rather_than_absorbed(tmp_path):
    """Mixed is the dangerous shape: most of the session marked and clean, one
    scene rendered without the flag. Calling that whole session finished would
    lose exactly one scene's review."""
    d = tmp_path / "narration"
    scene(d, 1, knobs={"gap_marking": True})
    scene(d, 2, knobs={"gap_marking": False})
    named = " ".join(status(d).split()).split("do not record")[1]
    assert "session_doc_scene_02_x" in named
    assert "session_doc_scene_01_x" not in named   # it was marked; it is fine
    assert "1 of 2 do not record" in " ".join(status(d).split())
    assert "will pass" not in status(d)


def test_a_scene_with_an_unwritten_gap_still_reports_the_gate(tmp_path):
    """The pre-existing message is untouched for the ordinary case."""
    d = tmp_path / "narration"
    scene(d, 1, text=MARKED)
    assert "not ready to assemble" in status(d)
