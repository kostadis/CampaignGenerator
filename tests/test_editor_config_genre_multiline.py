"""Executed round-trip check for CG#249 (WO-3): the KnobDrawer genre field
became a <textarea> so a pasted multi-line genre document (real embedded
``\\n``) is captured intact instead of the browser flattening it on paste
into a single-line <input> — the campaigns#149 incident this guards against.

This is the backend half of the round trip named in the work order
("save -> reload -> .knobs.json"): given a multi-line string actually
reaches the wire (which is what the textarea widget itself makes possible —
that DOM-level behavior has no test harness in this repo and is verified by
code inspection, not here), these tests execute:

  1. PUT /api/editor/config with a multi-line narrate.genre -> a fresh
     service instance (simulated restart) -> GET returns the exact string,
     newlines intact -- mirrors
     TestPutPersistsViaService.test_put_editor_config_persists_through_service.
  2. The on-disk session_doc.yaml itself carries real linebreaks (not one
     flattened line, not escaped "\\n" text) -- the literal defect campaigns#149
     fixed and this WO exists to keep fixed.
  3. The `.knobs.json` sidecar (_write_knobs_sidecar / _read_knobs_sidecar in
     server/routers/scene_editor.py) round-trips a multi-line genre value
     via plain json.dumps/json.loads.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.platform_config_service import PlatformConfigService, TRACKED_CONFIG_NAME
from server.routers import scene_editor
from server.routers.scene_editor import _read_knobs_sidecar, _write_knobs_sidecar

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


def test_multiline_genre_survives_put_reload_and_disk(fresh_campaign):
    assert "\n" in MULTILINE_GENRE
    assert MULTILINE_GENRE.count("\n") >= 6  # shaped like a document, not a line

    # PUT through the same grouped door the frontend's buildEditorConfigPayload
    # uses (SessionDocEditor.vue: narrate.genre).
    client_a = TestClient(_make_app(fresh_campaign))
    resp = client_a.put("/api/editor/config", json={"narrate": {"genre": MULTILINE_GENRE}})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}

    # Simulated restart: fresh app/service instance, same campaign dir.
    client_b = TestClient(_make_app(fresh_campaign))
    editor_cfg = client_b.get("/api/editor/config").json()
    assert editor_cfg["narrate"]["genre"] == MULTILINE_GENRE

    # The on-disk YAML itself must carry real linebreaks -- the campaigns#149
    # defect was exactly this value collapsed to one 7,063-char line.
    raw = (fresh_campaign / CONFIG_SUBDIR / "session_doc.yaml").read_text(encoding="utf-8")
    assert "GENRE & REGISTER" in raw
    assert raw.count("\n") >= MULTILINE_GENRE.count("\n")
    # No escaped-newline text sneaked in in place of a real linebreak.
    assert "\\n" not in raw


def test_knobs_sidecar_round_trips_multiline_genre(tmp_path):
    narration_path = tmp_path / "session_doc_scene_02_the-market.md"
    narration_path.write_text("placeholder narration\n", encoding="utf-8")

    _write_knobs_sidecar(narration_path, {"narration_genre": MULTILINE_GENRE})

    sidecar = narration_path.with_name(narration_path.stem + ".knobs.json")
    assert sidecar.exists()
    on_disk = sidecar.read_text(encoding="utf-8")
    assert "GENRE & REGISTER" in on_disk  # JSON-escaped, but human-legible

    restored = _read_knobs_sidecar(narration_path)
    assert restored == {"narration_genre": MULTILINE_GENRE}
    assert restored["narration_genre"].count("\n") == MULTILINE_GENRE.count("\n")
