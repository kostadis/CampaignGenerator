"""The genre rulebook is a file, not a pasted string — #276 fix 2.

Covers the seam end to end, in the order a render travels it:

* ``NarrateKnobs`` no longer declares ``genre``. A campaign whose
  ``session_doc.yaml`` still carries the old key must **load**, not crash —
  but the value must be announced, because it is a whole document that has
  stopped reaching Pass 5.
* ``paths.genre_file`` is a campaign-scoped path field, so it relativizes on
  write and resolves absolute on read like ``voice_dir`` does.
* The injected ``ResolvedGenre`` summary distinguishes unset / missing /
  resolved, and never carries the document's full text.
* ``sd_narrate`` reads the file, and warns loudly when it cannot — with the
  rulebook no longer mirrored into YAML, a bad path means Pass 5 silently runs
  with no register rules at all.
* The subprocess command passes the resolved **path**, and the per-scene knobs
  snapshot records identity (path + digest), not a 16K copy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.session_editor_config_service import (  # noqa: E402
    _describe_genre_file,
    SessionEditorConfigService,
)
from server.session_editor_config_shared import (  # noqa: E402
    NarrateKnobs,
    SessionEditorConfig,
)
from session_doc.sd_narrate import _load_genre_file  # noqa: E402

RULEBOOK = "GENRE & REGISTER\n\nFirst-person noir.\nWry, never cruel.\n"


# ── The retired key ──────────────────────────────────────────────────────

def test_narrate_knobs_no_longer_declares_genre():
    knobs = NarrateKnobs()
    assert not hasattr(knobs, "genre")
    assert "genre" not in knobs.model_dump()


def test_stale_genre_key_loads_but_is_announced(capsys):
    """A stale key must not take the editor down on boot — nor vanish quietly."""
    knobs = NarrateKnobs.model_validate({"tokens": 9000, "genre": "x" * 16303})
    assert knobs.tokens == 9000
    assert not hasattr(knobs, "genre")

    err = capsys.readouterr().err
    assert "relocated" in err
    assert "16303 chars" in err          # names the size, so a document is visible
    assert "paths.genre_file" in err     # says where it went
    assert "migrate_narrate_genre" in err  # says how to move it
    assert "NOT reaching Pass 5" in err  # says what it costs meanwhile


def test_retired_batch_key_still_announced_separately(capsys):
    """The two notices are distinct: one is obsolete, one has a new home."""
    NarrateKnobs.model_validate({"batch": True, "genre": "noir"})
    err = capsys.readouterr().err
    assert "retired" in err and "batch" in err
    assert "relocated" in err and "paths.genre_file" in err


# ── The path field ───────────────────────────────────────────────────────

def _service(tmp_path) -> SessionEditorConfigService:
    from server.platform_config_service import PlatformConfigService

    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "config.yaml").write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )
    return SessionEditorConfigService(PlatformConfigService(str(tmp_path)))


def test_genre_file_is_a_campaign_scoped_path(tmp_path):
    """Absolute in, relative on disk, absolute out — the path contract."""
    (tmp_path / "voice").mkdir()
    (tmp_path / "voice" / "_genre.md").write_text(RULEBOOK, encoding="utf-8")
    svc = _service(tmp_path)

    svc.update_config({"paths": {"genre_file": str(tmp_path / "voice" / "_genre.md")}})

    on_disk = (tmp_path / "config" / "session_doc.yaml").read_text(encoding="utf-8")
    assert "genre_file: voice/_genre.md" in on_disk, on_disk

    resolved = svc.resolved_editor_config()
    assert resolved.paths.genre_file == str(tmp_path / "voice" / "_genre.md")


def test_resolved_config_summarises_the_rulebook(tmp_path):
    (tmp_path / "voice").mkdir()
    (tmp_path / "voice" / "_genre.md").write_text(RULEBOOK, encoding="utf-8")
    svc = _service(tmp_path)
    svc.update_config({"paths": {"genre_file": "voice/_genre.md"}})

    genre = svc.resolved_editor_config().genre
    assert genre is not None
    assert genre.exists is True
    assert genre.lines == 4
    assert genre.chars == len(RULEBOOK.strip())
    assert genre.preview.startswith("GENRE & REGISTER")
    assert len(genre.sha256) == 12
    assert genre.error is None


# ── The summary's three states ───────────────────────────────────────────

def test_describe_unset():
    got = _describe_genre_file(None)
    assert (got.path, got.exists, got.error) == (None, False, None)


def test_describe_missing_says_what_it_costs(tmp_path):
    got = _describe_genre_file(str(tmp_path / "nope.md"))
    assert got.exists is False
    assert "not found" in got.error
    assert "no genre directive" in got.error


def test_describe_caps_the_preview(tmp_path):
    big = tmp_path / "big.md"
    big.write_text("x" * 5000, encoding="utf-8")
    got = _describe_genre_file(str(big))
    assert got.chars == 5000
    assert len(got.preview) == 600  # _GENRE_PREVIEW_CHARS — a preview, not the text


def test_describe_digest_tracks_content_not_path(tmp_path):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text(RULEBOOK, encoding="utf-8")
    b.write_text(RULEBOOK, encoding="utf-8")
    assert _describe_genre_file(str(a)).sha256 == _describe_genre_file(str(b)).sha256

    b.write_text(RULEBOOK + "One more rule.\n", encoding="utf-8")
    assert _describe_genre_file(str(a)).sha256 != _describe_genre_file(str(b)).sha256


# ── The CLI reader ───────────────────────────────────────────────────────

def test_load_genre_file_reads_it(tmp_path):
    p = tmp_path / "_genre.md"
    p.write_text(RULEBOOK, encoding="utf-8")
    assert _load_genre_file(str(p)) == RULEBOOK.strip()


def test_load_genre_file_none_when_unset():
    assert _load_genre_file(None) is None


def test_load_genre_file_warns_when_missing(tmp_path, capsys):
    assert _load_genre_file(str(tmp_path / "nope.md")) is None
    err = capsys.readouterr().err
    assert "does not exist" in err
    assert "NO genre directive" in err
    assert "banned-tic list" in err  # names what is lost, not just that it failed


def test_load_genre_file_warns_when_empty(tmp_path, capsys):
    p = tmp_path / "_genre.md"
    p.write_text("   \n\n", encoding="utf-8")
    assert _load_genre_file(str(p)) is None
    assert "is empty" in capsys.readouterr().err


# ── The subprocess command and the run record ────────────────────────────

def _cfg_stub(genre_file, genre=None):
    """Minimal stand-in for ResolvedEditorConfig's narrate-command surface."""
    from types import SimpleNamespace

    return SimpleNamespace(
        paths=SimpleNamespace(genre_file=genre_file),
        narrate=SimpleNamespace(tokens=0, prose_mode=False, reflections=False,
                                context=[]),
        backends=SimpleNamespace(active="anthropic"),
        genre=genre,
    )


def test_knobs_snapshot_records_identity_not_text():
    from server.routers.scene_editor import _narrate_knobs_snapshot
    from server.session_editor_config_service import ResolvedGenre

    genre = ResolvedGenre(path="/c/voice/_genre.md", exists=True, lines=61,
                          chars=7351, preview="GENRE…", sha256="abc123abc123")
    snap = _narrate_knobs_snapshot(_cfg_stub("/c/voice/_genre.md", genre))

    assert snap["narration_genre_file"] == "/c/voice/_genre.md"
    assert snap["narration_genre_sha"] == "abc123abc123"
    assert snap["narration_genre_lines"] == 61
    # The old key carried the whole document into every per-scene sidecar.
    assert "narration_genre" not in snap


def test_knobs_snapshot_omits_digest_when_the_file_is_gone():
    from server.routers.scene_editor import _narrate_knobs_snapshot
    from server.session_editor_config_service import ResolvedGenre

    genre = ResolvedGenre(path="/c/voice/_gone.md", exists=False, error="not found")
    snap = _narrate_knobs_snapshot(_cfg_stub("/c/voice/_gone.md", genre))

    assert snap["narration_genre_file"] == "/c/voice/_gone.md"
    assert "narration_genre_sha" not in snap  # nothing was read, so claim nothing
