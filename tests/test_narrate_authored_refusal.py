"""Re-narrating never silently destroys authored work — contract N (#455).

The prose in an `.authored.yaml` is the only thing in this pipeline a human
wrote from scratch. Re-narrating replaces the draft it was authored against, so
the record's digest stops matching, `sd_compose` refuses it, and the work is
reachable only by restoring the old narration by hand.

Refusal rather than a merge, in v1. Anchor matching is what would let a record
survive a re-narrate, and an anchor landing an authored block on the wrong prose
is the same attribution error this whole feature exists to prevent — committed
by us instead of by a model. Refusing is never wrong, only inconvenient.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from session_doc.sd_narrate import _refuse_over_authored_work  # noqa: E402


def scene(d: Path, n: int, *, disposition: str | None, text: str | None = None) -> Path:
    narration = d / f"session_doc_scene_{n:02d}_x.md"
    narration.write_text("prose\n", encoding="utf-8")
    if disposition is not None:
        block = {"id": "gap-1", "disposition": disposition}
        if text is not None:
            block["text"] = text
        (d / f"session_doc_scene_{n:02d}_x.authored.yaml").write_text(
            yaml.safe_dump({"version": 1, "narration": narration.name,
                            "generated_sha256": "sha256:0", "blocks": [block]},
                           sort_keys=False), encoding="utf-8")
    return narration


def test_a_record_with_authored_prose_blocks_the_run(tmp_path, capsys):
    """N1, and it exits before any model call — spending tokens and *then*
    refusing to write is the worst ordering available."""
    scene(tmp_path, 1, disposition="authored", text="The door shuts.")
    with pytest.raises(SystemExit) as exc:
        _refuse_over_authored_work(tmp_path, reroll=False)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "session_doc_scene_01_x.authored.yaml" in err
    assert "--reroll" in err


def test_rulings_without_prose_do_not_block(tmp_path):
    """N3. A triage pass done on a phone is cheap to redo; prose is not. A
    record of `mine` and `cut` is exactly the normal end state of a mobile
    session and must not make the GM fight the tool to re-render."""
    scene(tmp_path, 1, disposition="mine")
    scene(tmp_path, 2, disposition="cut")
    _refuse_over_authored_work(tmp_path, reroll=False)      # must not raise


def test_no_record_at_all_does_not_block(tmp_path):
    scene(tmp_path, 1, disposition=None)
    _refuse_over_authored_work(tmp_path, reroll=False)


def test_reroll_lifts_the_refusal_and_says_what_happens_first(tmp_path, capsys):
    """N2. "It states what becomes of the record BEFORE doing it" — a lift that
    printed nothing would leave the GM to discover at compose time that every
    record now refuses."""
    scene(tmp_path, 1, disposition="authored", text="The door shuts.")
    _refuse_over_authored_work(tmp_path, reroll=True)       # must not raise
    err = capsys.readouterr().err
    assert "left exactly as they are" in err
    assert "sd_compose` will refuse" in err
    assert "Nothing you wrote is deleted" in err


def test_a_broken_record_does_not_block_the_run(tmp_path):
    """An unreadable record is `sd_compose`'s problem to report, with its own
    message. Blocking narration on it would make one bad file stop a session
    with an error pointing at the wrong tool."""
    narration = tmp_path / "session_doc_scene_01_x.md"
    narration.write_text("prose\n", encoding="utf-8")
    (tmp_path / "session_doc_scene_01_x.authored.yaml").write_text(
        "not: [a, valid, record\n", encoding="utf-8")
    _refuse_over_authored_work(tmp_path, reroll=False)


def test_a_missing_directory_is_not_an_error(tmp_path):
    """First run of a session: nothing has been narrated yet."""
    _refuse_over_authored_work(tmp_path / "not-there", reroll=False)


def test_generated_variants_are_not_mistaken_for_narrations(tmp_path):
    """`.composed.md` and `.scrubbed.md` are output; only the narration a record
    is authored against matters here."""
    (tmp_path / "session_doc_scene_01_x.composed.md").write_text("x", encoding="utf-8")
    (tmp_path / "session_doc_scene_01_x.scrubbed.md").write_text("x", encoding="utf-8")
    _refuse_over_authored_work(tmp_path, reroll=False)
