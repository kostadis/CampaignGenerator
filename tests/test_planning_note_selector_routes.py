"""Planning's authority-note selectors are owned by the planning API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.main import app  # noqa: E402
from server.platform_config_service import TRACKED_CONFIG_NAME, PlatformConfigService  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / TRACKED_CONFIG_NAME).write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(app.state, "platform", PlatformConfigService(tmp_path), raising=False)
    return TestClient(app), cfg / "planning.yaml"


def test_note_selector_crud_preserves_authored_path_and_unsets_empty_list(client):
    http, path = client
    body = {"id": "gm-notes", "path": "notes/gm/*.md", "record_ids": ["note-a"]}
    created = http.post("/api/planning/notes", json=body)
    assert created.status_code == 201
    assert created.json() == body
    assert http.get("/api/planning/notes").json() == [body]

    changed = {**body, "path": "notes/gm/current.md"}
    assert http.put("/api/planning/notes/gm-notes", json=changed).json() == changed
    assert http.delete("/api/planning/notes/gm-notes").status_code == 204
    assert http.get("/api/planning/notes").json() == []
    assert "notes:" not in path.read_text(encoding="utf-8")
