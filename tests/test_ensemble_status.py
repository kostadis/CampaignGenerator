"""Integration tests for /api/ensemble/status — disk-derived stage state (FR-002)."""

import json

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def test_status_extract_current_then_complete(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs/chapters").mkdir(parents=True)
    (tmp_path / "docs/chapters/chapter_01.md").write_text("# ch1")

    # No run yet → extract is the current stage.
    r = client.get("/api/ensemble/status")
    assert r.status_code == 200
    body = r.json()
    assert body["current_stage"] == "extract"
    assert {s["id"] for s in body["stages"]} == {"extract", "bundle", "synthesize", "review"}
    assert next(s for s in body["stages"] if s["id"] == "extract")["status"] == "not_started"

    # Extraction artifacts appear on disk → status flips to complete with no caching.
    pc = tmp_path / "docs/ensemble/per_chapter/chapter_01"
    pc.mkdir(parents=True)
    (pc / "merged.json").write_text(json.dumps({"facts": []}))

    body2 = client.get("/api/ensemble/status").json()
    extract = next(s for s in body2["stages"] if s["id"] == "extract")
    assert extract["status"] == "complete"
    assert extract["artifacts"] == 1
    assert body2["current_stage"] == "bundle"
