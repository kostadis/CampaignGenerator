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


# ── planning synthesis: planning.yaml preferred over raw --npc/--arc-scores ─

def test_synthesize_planning_auto_detects_conventional_config(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    planning_yaml = tmp_path / "config" / "planning.yaml"
    planning_yaml.write_text("factions:\n  - name: Test\n")

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "planning"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--planning-config" in cmd
    assert cmd[cmd.index("--planning-config") + 1] == str(planning_yaml)
    assert "--arc-scores" not in cmd
    # em-dash is JSON-escaped in the SSE payload — check around it instead.
    assert "Auto-detected" in r.text
    assert "planning config:" in r.text


def test_synthesize_planning_explicit_path_overrides_default(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "planning.yaml").write_text("factions:\n  - name: Test\n")
    custom = tmp_path / "custom_planning.yaml"
    custom.write_text("factions:\n  - name: Test\n")

    r = client.get("/api/ensemble/run/synthesize",
                   params={"doc": "planning", "planning_config": "custom_planning.yaml"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert cmd[cmd.index("--planning-config") + 1] == str(custom)
    assert "Auto-detected" not in r.text


def test_synthesize_planning_falls_back_without_any_planning_config(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)

    r = client.get("/api/ensemble/run/synthesize", params={
        "doc": "planning",
        "npc": ["grundar.md"],
        "arc_scores": ["grundar_score.md"],
    })
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--planning-config" not in cmd
    assert cmd[cmd.index("--npc") + 1] == "grundar.md"
    assert cmd[cmd.index("--arc-scores") + 1] == "grundar_score.md"


# ── planning synthesis: --npc pass-through for NPCs not in planning.yaml ───
# planning.yaml's npcs: list is only the arc-scored minority (planning.py's
# own docstring calls --npc pass-through "the majority") — without this,
# every NPC not manually added to planning.yaml is silently absent from
# planning.md.

def test_synthesize_planning_auto_includes_passthrough_npc_dossiers(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    dossiers_dir = tmp_path / "docs" / "ensemble" / "merged_dossiers"
    dossiers_dir.mkdir(parents=True)
    tracked = dossiers_dir / "npc_grundar.md"
    tracked.write_text("# Grundar\n")
    untracked = dossiers_dir / "npc_xalvosh.md"
    untracked.write_text("# Xalvosh\n")

    planning_yaml = tmp_path / "config" / "planning.yaml"
    planning_yaml.write_text(f"npcs:\n  - name: Grundar\n    dossier: {tracked}\n")

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "planning"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    npc_flags = [cmd[i + 1] for i, v in enumerate(cmd) if v == "--npc"]
    # The config-bound dossier must NOT also appear as pass-through (planning.py's
    # own overlap guard rejects an NPC appearing in both places).
    assert str(untracked) in npc_flags
    assert str(tracked) not in npc_flags
    assert "Auto-detected" in r.text
    assert "pass-through NPC dossier" in r.text


def test_synthesize_planning_explicit_npc_overrides_passthrough(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    dossiers_dir = tmp_path / "docs" / "ensemble" / "merged_dossiers"
    dossiers_dir.mkdir(parents=True)
    (dossiers_dir / "npc_xalvosh.md").write_text("# Xalvosh\n")
    (tmp_path / "config" / "planning.yaml").write_text("factions:\n  - name: Test\n")

    r = client.get("/api/ensemble/run/synthesize",
                   params={"doc": "planning", "npc": ["custom.md"]})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    npc_flags = [cmd[i + 1] for i, v in enumerate(cmd) if v == "--npc"]
    assert npc_flags == ["custom.md"]
    assert "pass-through" not in r.text


def test_synthesize_planning_no_passthrough_without_merged_dossiers(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "planning.yaml").write_text("factions:\n  - name: Test\n")

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "planning"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--npc" not in cmd
    assert "pass-through" not in r.text


def test_synthesize_planning_bad_config_surfaces_sse_error_not_500(tmp_path, monkeypatch):
    """load_planning_config raises ValueError on a missing dossier reference —
    that must reach the client as a readable SSE error, not an unhandled 500
    (which the frontend's EventSource can't distinguish from a dropped
    connection and reports as "[connection lost — run stopped]")."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    bad = tmp_path / "config" / "planning.yaml"
    bad.write_text("npcs:\n  - name: Ghost\n    dossier: missing.md\n")
    dossiers_dir = tmp_path / "docs" / "ensemble" / "merged_dossiers"
    dossiers_dir.mkdir(parents=True)
    (dossiers_dir / "npc_xalvosh.md").write_text("# Xalvosh\n")

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "planning"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "planning config error" in r.text
    assert "event: done" in r.text
