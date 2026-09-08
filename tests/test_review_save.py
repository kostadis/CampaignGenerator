"""Saving a review to disk — the endpoint and the CLI behind it (#455).

The reviewer used to end at the clipboard. That was a ruling taken for a stated
reason — not designing the paste-back format before the page had been used — and
using it discharged the reason twice over:

- what gets copied is exactly this record, so there was nothing left to learn
- copying it through a phone's clipboard corrupted every em dash in it, because
  the channel is not under our control

**One function writes the file, and both surfaces call it.** `sd_review apply`
is the engine and the endpoint is a face on it, so a route cannot drift into
being a second implementation of the record format.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from session_doc.authored import AuthoredError, load_record  # noqa: E402
from session_doc.review.export import digest  # noqa: E402
from session_doc.review.records import (  # noqa: E402
    SaveRefused,
    review_to_record,
    save_record,
    summarise,
)

NARRATION = "prose one\n\n[GM NARRATION — TO BE WRITTEN: the GM said a thing]\n\nprose two\n"


def scene(tmp_path: Path) -> Path:
    p = tmp_path / "session_doc_scene_01_x.md"
    p.write_text(NARRATION, encoding="utf-8")
    return p


def review(narration: Path, blocks: list[dict]) -> dict:
    return {"version": 1, "narration": narration.name,
            "generated_sha256": digest(narration.read_text(encoding="utf-8")),
            "blocks": blocks}


# ── the record it writes ────────────────────────────────────────────────────

def test_a_review_becomes_a_record_on_disk(tmp_path):
    n = scene(tmp_path)
    rec = review_to_record(review(n, [{"id": "gap-1", "disposition": "authored",
                                       "text": "The door shuts."}]))
    path, lost = save_record(n, rec)
    assert path.name == "session_doc_scene_01_x.authored.yaml"
    assert lost == []
    assert load_record(path).by_id()["gap-1"].text == "The door shuts."


def test_the_file_says_it_is_hand_authored_state(tmp_path):
    """The narration and the .composed.md beside it are generated and get
    rewritten; this one does not. Somebody opening the directory should be able
    to tell which is which without reading the docs."""
    n = scene(tmp_path)
    path, _ = save_record(n, review_to_record(review(n, [])))
    assert "HAND-AUTHORED" in path.read_text(encoding="utf-8")


def test_the_page_is_not_trusted_with_the_date(tmp_path):
    """A phone's clock is a phone's clock. `recorded` is stamped here."""
    n = scene(tmp_path)
    rec = review_to_record(review(n, [{"id": "gap-1", "disposition": "mine"}]))
    assert rec.blocks[0].recorded is not None


def test_an_invalid_review_is_refused_with_its_reason(tmp_path):
    n = scene(tmp_path)
    with pytest.raises(AuthoredError, match="not a valid record"):
        review_to_record(review(n, [{"id": "gap-1", "disposition": "invented"}]))


# ── the guard that protects an evening's writing ────────────────────────────

def test_a_stale_tab_cannot_drop_prose_already_on_disk(tmp_path):
    """The reviewer autosaves. A tab left open on a phone this morning, saving
    after an evening at the desk, would otherwise replace an hour of writing
    with a record that never had it — silently, because autosave is silent."""
    n = scene(tmp_path)
    save_record(n, review_to_record(review(n, [
        {"id": "gap-1", "disposition": "authored", "text": "An evening's work."}])))
    stale = review_to_record(review(n, [{"id": "gap-1", "disposition": "mine"}]))
    with pytest.raises(SaveRefused, match="stale tab"):
        save_record(n, stale)
    # …and nothing was written.
    assert "An evening's work." in load_record(
        n.with_name(n.stem + ".authored.yaml")).by_id()["gap-1"].text


def test_force_saves_anyway_and_says_what_it_dropped(tmp_path):
    n = scene(tmp_path)
    save_record(n, review_to_record(review(n, [
        {"id": "gap-1", "disposition": "authored", "text": "old"}])))
    _path, lost = save_record(
        n, review_to_record(review(n, [{"id": "gap-1", "disposition": "mine"}])),
        force=True)
    assert lost == ["gap-1"]


def test_shortening_a_passage_is_an_edit_not_a_loss(tmp_path):
    """The guard is about prose that is ABSENT from what is arriving, not about
    any difference. Refusing a deliberate trim would make the tool unusable."""
    n = scene(tmp_path)
    save_record(n, review_to_record(review(n, [
        {"id": "gap-1", "disposition": "authored", "text": "A long passage indeed."}])))
    _p, lost = save_record(n, review_to_record(review(n, [
        {"id": "gap-1", "disposition": "authored", "text": "Short."}])))
    assert lost == []


def test_an_unreadable_existing_record_does_not_block_a_save(tmp_path):
    """There is nothing to lose from a file nobody can read, and refusing would
    strand the GM with no way to replace it from the page."""
    n = scene(tmp_path)
    n.with_name(n.stem + ".authored.yaml").write_text("not: [valid\n", encoding="utf-8")
    path, lost = save_record(n, review_to_record(review(n, [])))
    assert path.is_file() and lost == []


# ── the CLI, which the endpoint is a face on ────────────────────────────────

def test_the_cli_writes_the_same_record_from_stdin(tmp_path):
    """Principle VI. A clipboard still works — `pbpaste | sd_review apply` — and
    more importantly the endpoint has an engine underneath it rather than being
    the only way to do this."""
    n = scene(tmp_path)
    payload = json.dumps(review(n, [{"id": "gap-1", "disposition": "cut"}]))
    rc = subprocess.run(
        [sys.executable, "-m", "session_doc.sd_review", "apply", "--scene", str(n), "--from", "-"],
        input=payload, capture_output=True, text=True, cwd=ROOT)
    assert rc.returncode == 0, rc.stderr
    assert load_record(n.with_name(n.stem + ".authored.yaml")).by_id()["gap-1"].disposition == "cut"


def test_the_cli_refuses_a_stale_save_and_exits_nonzero(tmp_path):
    n = scene(tmp_path)
    save_record(n, review_to_record(review(n, [
        {"id": "gap-1", "disposition": "authored", "text": "kept"}])))
    payload = json.dumps(review(n, [{"id": "gap-1", "disposition": "mine"}]))
    rc = subprocess.run(
        [sys.executable, "-m", "session_doc.sd_review", "apply", "--scene", str(n), "--from", "-"],
        input=payload, capture_output=True, text=True, cwd=ROOT)
    assert rc.returncode == 1
    assert "stale tab" in rc.stderr


def test_summarise_reports_the_two_completions(tmp_path):
    n = scene(tmp_path)
    rec = review_to_record(review(n, [
        {"id": "gap-1", "disposition": "authored", "text": "x"},
        {"id": "gap-2", "disposition": "mine"}]))
    assert summarise(rec) == "2 ruled, 1 written"
