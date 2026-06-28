"""Gate guards: drafts-only synthesis, no live-doc writes, promote is the sole
live-doc writer (FR-013, SC-005, spec US3)."""

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def test_synthesize_rejects_live_doc_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/ensemble/run/synthesize",
                   params={"doc": "world_state", "output": "docs/world_state.md"})
    assert r.status_code == 400
    assert "draft" in r.json()["detail"]


def test_put_file_rejects_live_doc(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    r = client.put("/api/ensemble/file", params={"path": "docs/world_state.md"},
                   json={"content": "clobbered"})
    assert r.status_code == 403


def test_put_file_allows_aliases(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.put("/api/ensemble/file",
                   params={"path": "docs/ensemble/aliases.json"},
                   json={"content": "{}"})
    assert r.status_code == 200
    assert (tmp_path / "docs/ensemble/aliases.json").read_text() == "{}"


def test_promote_is_sole_live_writer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    draft = tmp_path / "docs/world_state_draft.md"
    draft.write_text("promoted body")
    live = tmp_path / "docs/world_state.md"
    assert not live.exists()

    r = client.post("/api/ensemble/promote",
                    json={"draft": "docs/world_state_draft.md", "live": "docs/world_state.md"})
    assert r.status_code == 200
    assert live.read_text() == "promoted body"


def test_promote_rejects_non_grounding_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/world_state_draft.md").write_text("x")
    r = client.post("/api/ensemble/promote",
                    json={"draft": "docs/world_state_draft.md", "live": "docs/notes.md"})
    assert r.status_code == 400


def test_path_traversal_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/ensemble/file", params={"path": "../../etc/passwd"})
    assert r.status_code == 400
