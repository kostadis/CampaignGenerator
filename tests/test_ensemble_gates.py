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


# ── Stale backend-profile leakage (a switched-back-to-anthropic run must not
# ── inherit a previous non-anthropic model/endpoint) ─────────────────────────

def _capture_cmd(monkeypatch):
    captured = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        captured["cmd"] = cmd
        captured["env_extra"] = env_extra
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("server.routers.ensemble.stream_subprocess", fake_stream_subprocess)
    return captured


def test_synthesize_ignores_stale_model_for_anthropic(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/ensemble/run/synthesize", params={
        "doc": "world_state",
        "backend": "anthropic",
        "model": "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8",
        "endpoint": "http://192.168.1.147:8001/v1",
    })
    assert r.status_code == 200
    _ = r.text  # drain the SSE generator so fake_stream_subprocess actually runs
    assert "--model" not in captured["cmd"]
    assert "--backend" not in captured["cmd"]
    assert "--endpoint" not in captured["cmd"]
    assert not captured["env_extra"]


def test_bundle_ignores_stale_model_for_anthropic(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/ensemble/run/bundle", params={
        "backend": "anthropic",
        "model": "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8",
        "endpoints": ["http://192.168.1.147:8001/v1"],
    })
    assert r.status_code == 200
    _ = r.text
    assert "--model" not in captured["cmd"]
    assert "--endpoints" not in captured["cmd"]
    assert not captured["env_extra"]


# ── entity_registry.yaml supersedes stale UI-persisted --aliases/--known-names
# ── (a campaign that's migrated to the registry must not keep tripping
# ── facts_to_state.py's deprecation guard, which also disables its own
# ── auto-discovery when legacy flags are present) ──────────────────────────

def test_bundle_prefers_registry_over_stale_aliases(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    registry = tmp_path / "docs" / "entity_registry.yaml"
    registry.write_text("version: 1\nentities: []\n")

    r = client.get("/api/ensemble/run/bundle", params={
        "aliases": "docs/ensemble/alias.json",
        "known_names": ["docs/entity_inventory.md"],
    })
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--registry" in cmd
    assert cmd[cmd.index("--registry") + 1] == str(registry)
    assert "--aliases" not in cmd
    assert "--known-names" not in cmd


def test_bundle_falls_back_to_legacy_aliases_without_registry(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)

    r = client.get("/api/ensemble/run/bundle", params={
        "aliases": "docs/ensemble/alias.json",
        "known_names": ["docs/entity_inventory.md"],
    })
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--registry" not in cmd
    assert cmd[cmd.index("--aliases") + 1] == "docs/ensemble/alias.json"
    assert cmd[cmd.index("--known-names") + 1] == "docs/entity_inventory.md"


def test_threads_prefers_registry_over_stale_aliases(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    registry = tmp_path / "docs" / "entity_registry.yaml"
    registry.write_text("version: 1\nentities: []\n")

    r = client.get("/api/ensemble/run/threads",
                   params={"aliases": "docs/ensemble/alias.json"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--registry" in cmd
    assert cmd[cmd.index("--registry") + 1] == str(registry)
    assert "--aliases" not in cmd


# ── Subscription (claude-code) backend selection ────────────────────────────

def test_synthesize_forwards_claude_code_backend_and_model(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/ensemble/run/synthesize", params={
        "doc": "world_state",
        "backend": "claude-code",
        "model": "claude-opus-4-8",
    })
    assert r.status_code == 200
    _ = r.text
    assert "--backend" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--backend") + 1] == "claude-code"
    assert "--model" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == "claude-opus-4-8"
    assert captured["env_extra"] == {
        "CG_BACKEND": "claude-code",
        "CG_CLAUDE_CODE_MODEL": "claude-opus-4-8",
    }


def test_bundle_sets_claude_code_env(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/ensemble/run/bundle", params={
        "backend": "claude-code",
        "model": "claude-opus-4-8",
    })
    assert r.status_code == 200
    _ = r.text
    assert captured["env_extra"] == {
        "CG_BACKEND": "claude-code",
        "CG_CLAUDE_CODE_MODEL": "claude-opus-4-8",
    }


# ── party synthesis: party.yaml preferred over staged extracts ─────────────

def test_synthesize_party_auto_detects_conventional_config(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    party_yaml = tmp_path / "config" / "party.yaml"
    party_yaml.write_text("characters: []\n")

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "party"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--party-config" in cmd
    assert cmd[cmd.index("--party-config") + 1] == str(party_yaml)
    assert "--synthesize-only" not in cmd
    assert "--extract-dir" not in cmd
    # em-dash is JSON-escaped in the SSE payload — check around it instead.
    assert "Auto-detected" in r.text
    assert "party config:" in r.text


def test_synthesize_party_explicit_path_overrides_default(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "party.yaml").write_text("characters: []\n")
    custom = tmp_path / "custom_party.yaml"
    custom.write_text("characters: []\n")

    r = client.get("/api/ensemble/run/synthesize",
                   params={"doc": "party", "party": "custom_party.yaml"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert cmd[cmd.index("--party-config") + 1] == str(custom)
    # Caller supplied the path explicitly, and no world_state/campaign_state
    # docs exist in this tmp_path to auto-detect as context either.
    assert "Auto-detected" not in r.text


def test_synthesize_party_falls_back_without_any_party_config(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "party"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--party-config" not in cmd
    assert "--synthesize-only" in cmd


def test_synthesize_party_auto_includes_world_state_and_campaign_state_context(tmp_path, monkeypatch):
    """Characters-only party synthesis has no session extracts of its own —
    without world_state/campaign_state as --context it can only report
    current location/quests/reputation as absent (the bug this closes)."""
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "party.yaml").write_text("characters: []\n")
    (tmp_path / "docs").mkdir()
    # world_state: only a draft exists — draft should be preferred.
    ws_draft = tmp_path / "docs" / "world_state_draft.md"
    ws_draft.write_text("world state")
    # campaign_state: only the live doc exists — should be used as a fallback.
    cs_live = tmp_path / "docs" / "campaign_state.md"
    cs_live.write_text("campaign state")

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "party"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    context_flags = [cmd[i + 1] for i, v in enumerate(cmd) if v == "--context"]
    assert str(ws_draft) in context_flags
    assert str(cs_live) in context_flags
    # em-dash is JSON-escaped in the SSE payload — check around it instead.
    assert "Auto-detected" in r.text
    assert "party config:" in r.text
    assert "context:" in r.text


def test_synthesize_party_explicit_context_overrides_auto_detect(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "party.yaml").write_text("characters: []\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "world_state_draft.md").write_text("world state")
    custom_context = tmp_path / "notes.md"
    custom_context.write_text("notes")

    r = client.get("/api/ensemble/run/synthesize",
                   params={"doc": "party", "context": ["notes.md"]})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    context_flags = [cmd[i + 1] for i, v in enumerate(cmd) if v == "--context"]
    assert context_flags == ["notes.md"]
    # Caller-supplied context — no auto-detect note for it.
    assert "context:" not in r.text
