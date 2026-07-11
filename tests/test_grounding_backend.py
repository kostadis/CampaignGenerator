"""The grounding routes (campaign_state / distill / party / planning /
build-dossiers) must forward the campaign's global backend choice to the
subprocess, exactly like scene_editor and ensemble do.

Regression guard for the bug where a "subscription" (claude-code) selection in
the sidebar was silently dropped by server/routers/grounding.py, so every
grounding run billed the metered Anthropic API. Forwarding is env-only
(CG_BACKEND / DGX_*), never a --backend flag: distill.py calls make_client()
with no args and reads the env var, so the env is the only channel that works
uniformly across all five scripts.
"""

import types

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def _capture_cmd(monkeypatch):
    captured = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        captured["cmd"] = cmd
        captured["env_extra"] = env_extra
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("server.routers.grounding.stream_subprocess", fake_stream_subprocess)
    return captured


def _set_backend(monkeypatch, session_doc: dict | None):
    """Point app.state.config_service at a fake whose resolved() carries the
    given ui.session_doc block. Pass None to simulate no config service."""
    if session_doc is None:
        monkeypatch.setattr(app.state, "config_service", None, raising=False)
        return
    fake = types.SimpleNamespace(
        resolved=lambda: {"ui": {"session_doc": session_doc}},
    )
    monkeypatch.setattr(app.state, "config_service", fake, raising=False)


# ── claude-code (subscription) is forwarded on every grounding route ─────────

def test_campaign_state_forwards_subscription_env(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    _set_backend(monkeypatch, {"backend": "claude-code"})
    r = client.get("/api/grounding/run/campaign-state", params={
        "input": "docs/x.md", "output": "docs/cs.md", "model": "claude-sonnet-4-6",
    })
    assert r.status_code == 200
    _ = r.text  # drain the SSE generator so fake_stream_subprocess runs
    assert captured["env_extra"] == {"CG_BACKEND": "claude-code"}
    # env-only — the flag would crash distill.py's parser, so no route emits it.
    assert "--backend" not in captured["cmd"]


def test_distill_forwards_subscription_env(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    _set_backend(monkeypatch, {"backend": "claude-code"})
    r = client.get("/api/grounding/run/distill", params={
        "input": "docs/x.md", "output": "docs/ws.md",
    })
    assert r.status_code == 200
    _ = r.text
    assert captured["env_extra"] == {"CG_BACKEND": "claude-code"}
    assert "--backend" not in captured["cmd"]


def test_party_forwards_subscription_env(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    _set_backend(monkeypatch, {"backend": "claude-code"})
    r = client.get("/api/grounding/run/party", params={"output": "docs/party.md"})
    assert r.status_code == 200
    _ = r.text
    assert captured["env_extra"] == {"CG_BACKEND": "claude-code"}


def test_planning_forwards_subscription_env(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    _set_backend(monkeypatch, {"backend": "claude-code"})
    r = client.get("/api/grounding/run/planning", params={"output": "docs/planning.md"})
    assert r.status_code == 200
    _ = r.text
    assert captured["env_extra"] == {"CG_BACKEND": "claude-code"}


def test_build_dossiers_forwards_subscription_env(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    _set_backend(monkeypatch, {"backend": "claude-code"})
    r = client.get("/api/grounding/run/build-dossiers", params={"summaries": "docs/s"})
    assert r.status_code == 200
    _ = r.text
    assert captured["env_extra"] == {"CG_BACKEND": "claude-code"}


# ── dgx is forwarded as endpoint/model env ───────────────────────────────────

def test_campaign_state_forwards_dgx_env(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    _set_backend(monkeypatch, {
        "backend": "dgx", "dgx_endpoint": "http://box:8001", "dgx_model": "Qwen-X",
    })
    r = client.get("/api/grounding/run/campaign-state", params={"input": "docs/x.md"})
    assert r.status_code == 200
    _ = r.text
    assert captured["env_extra"] == {
        "DGX_ENDPOINT": "http://box:8001", "DGX_MODEL": "Qwen-X",
    }


# ── anthropic / no config service → no overrides (default API path) ──────────

def test_anthropic_backend_yields_no_overrides(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    _set_backend(monkeypatch, {"backend": "anthropic"})
    r = client.get("/api/grounding/run/campaign-state", params={"input": "docs/x.md"})
    assert r.status_code == 200
    _ = r.text
    assert captured["env_extra"] == {}


def test_missing_config_service_yields_no_overrides(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    _set_backend(monkeypatch, None)
    r = client.get("/api/grounding/run/campaign-state", params={"input": "docs/x.md"})
    assert r.status_code == 200
    _ = r.text
    assert captured["env_extra"] == {}
