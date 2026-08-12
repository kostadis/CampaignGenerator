"""Multi-line genre integrity, after the rulebook became a file (#276 fix 2).

CG#249 (WO-3) made the KnobDrawer genre field a ``<textarea>`` so a pasted
multi-line genre document survived instead of being flattened by a single-line
``<input>`` — the campaigns#149 incident. #276 fix 2 supersedes that guarantee
with a stronger one: **there is no genre text in ``session_doc.yaml`` at all.**
``paths.genre_file`` holds a path, the rulebook lives in ``voice/_genre.md``,
and the flattening path no longer exists because no browser field ever holds
the document.

So the property under test moves rather than disappearing. What must hold now:

  1. A multi-line rulebook file on disk reaches the Pass-5 prompt with every
     line intact, inside the delimited ``GENRE & REGISTER`` block.
  2. ``PUT``/``GET /api/editor/config`` round-trips the *path*, and the
     resolved config reports the file's real line and character counts.
  3. A configured-but-absent file is reported as an error, not silently
     treated as "no genre" — with the rulebook no longer mirrored into YAML,
     a typo'd path means Pass 5 runs with no register rules at all.
  4. The ``.knobs.json`` sidecar records which rulebook a scene used **by
     identity, not by copy** — and must NOT carry the document text, which is
     the regression this replaces (the old snapshot wrote all 16K of
     out-of-the-abyss' genre into every per-scene sidecar).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import session_doc  # noqa: E402
from server.platform_config_service import PlatformConfigService, TRACKED_CONFIG_NAME
from server.routers import scene_editor
from server.routers.scene_editor import _read_knobs_sidecar, _write_knobs_sidecar
from session_doc.sd_narrate import _load_genre_file

CONFIG_SUBDIR = "config"

# A stand-in for the real 61-line voice/_genre.md document: multiple
# paragraphs, blank lines, and a trailing line -- shaped like prose, not a
# single sentence, so a naive .strip()/collapse would be visible.
MULTILINE_GENRE = "\n".join(
    [
        "GENRE & REGISTER",
        "",
        "Present-tense, first-person comic-noir fantasy memoir.",
        "Each narrator speaks in their own voice; the register stays wry",
        "but never cruel.",
        "",
        "Line six of a much longer document -- stands in for the real",
        "61-line voice/_genre.md content.",
    ]
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def fresh_campaign(tmp_path):
    _write(
        tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME,
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
    )
    return tmp_path


def _make_app(campaign_dir: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(scene_editor.router, prefix="/api/editor")
    app.state.platform = PlatformConfigService(campaign_dir)
    return app


def test_multiline_rulebook_file_reaches_the_prompt_intact(tmp_path):
    """The end of the chain: file on disk -> Pass 5 prompt, line for line."""
    genre_path = tmp_path / "voice" / "_genre.md"
    _write(genre_path, MULTILINE_GENRE + "\n")

    loaded = _load_genre_file(str(genre_path))
    assert loaded == MULTILINE_GENRE
    assert loaded.count("\n") == MULTILINE_GENRE.count("\n")

    prompt = session_doc.build_narrate_system(examples_text=None, genre=loaded)
    assert "GENRE & REGISTER (campaign-specific) — BEGIN" in prompt
    for line in MULTILINE_GENRE.splitlines():
        if line.strip():
            assert line in prompt, f"line lost on the way to the prompt: {line!r}"


def test_config_round_trips_the_path_and_reports_the_file(fresh_campaign):
    genre_rel = "voice/_genre.md"
    _write(fresh_campaign / genre_rel, MULTILINE_GENRE + "\n")

    # PUT through the same grouped door the frontend's buildEditorConfigPayload
    # uses (SessionDocEditor.vue: paths.genre_file).
    client_a = TestClient(_make_app(fresh_campaign))
    resp = client_a.put("/api/editor/config", json={"paths": {"genre_file": genre_rel}})
    assert resp.status_code == 200, resp.text

    # Simulated restart: fresh app/service instance, same campaign dir.
    client_b = TestClient(_make_app(fresh_campaign))
    cfg = client_b.get("/api/editor/config").json()

    assert cfg["paths"]["genre_file"].endswith(genre_rel)
    genre = cfg["genre"]
    assert genre["exists"] is True
    assert genre["error"] is None
    assert genre["lines"] == len(MULTILINE_GENRE.strip().splitlines())
    assert genre["chars"] == len(MULTILINE_GENRE.strip())
    assert genre["preview"].startswith("GENRE & REGISTER")
    assert genre["sha256"]

    # No genre text is stored in the YAML — that is the whole point of fix 2.
    raw = (fresh_campaign / CONFIG_SUBDIR / "session_doc.yaml").read_text(encoding="utf-8")
    assert "comic-noir" not in raw
    assert "genre_file" in raw


def test_missing_rulebook_is_reported_not_silently_ignored(fresh_campaign):
    client = TestClient(_make_app(fresh_campaign))
    client.put("/api/editor/config", json={"paths": {"genre_file": "voice/_nope.md"}})

    genre = client.get("/api/editor/config").json()["genre"]
    assert genre["exists"] is False
    assert "not found" in (genre["error"] or "")
    assert genre["lines"] == 0

    # And the CLI half warns rather than proceeding quietly.
    assert _load_genre_file(str(fresh_campaign / "voice" / "_nope.md")) is None


def test_knobs_sidecar_records_identity_not_a_copy(tmp_path):
    narration_path = tmp_path / "session_doc_scene_02_the-market.md"
    narration_path.write_text("placeholder narration\n", encoding="utf-8")

    snapshot = {
        "narration_genre_file": "/campaign/voice/_genre.md",
        "narration_genre_sha": "abc123def456",
        "narration_genre_lines": 61,
    }
    _write_knobs_sidecar(narration_path, snapshot)

    sidecar = narration_path.with_name(narration_path.stem + ".knobs.json")
    assert sidecar.exists()
    on_disk = sidecar.read_text(encoding="utf-8")
    # The rulebook's prose must NOT be duplicated into the sidecar.
    assert "comic-noir" not in on_disk
    assert "_genre.md" in on_disk

    restored = _read_knobs_sidecar(narration_path)
    assert restored == snapshot
