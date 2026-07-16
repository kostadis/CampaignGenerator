"""The grounding routes (campaign_state / distill / party / planning /
build-dossiers) must forward the campaign's global backend choice to the
subprocess, exactly like scene_editor and ensemble do.

Regression guard for the bug where a "subscription" (claude-code) or
"openrouter" selection in the sidebar was silently dropped by
server/routers/grounding.py, so every grounding run billed the metered
Anthropic API. The underlying failure mode these tests guard against hasn't
changed — only the forwarding mechanism has: backend selection is now
translated into explicit CLI flags on the subprocess `cmd` list
(--backend/--endpoint/--model) via the shared
`server.backend_forwarding.backend_cli_args` helper, rather than env vars.
This is possible because every script these routes invoke
(campaign_state.py, distill.py, party.py, planning.py) now accepts
--backend/--endpoint/--model directly through
campaignlib.api.client.add_backend_args — see server/routers/grounding.py's
`_backend_flags` for the per-route translation.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from server.backend_forwarding import backend_cli_args
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


def _run(monkeypatch, path: str, session_doc: dict | None, params: dict) -> dict:
    """Call a grounding route with a fake backend + fake subprocess, and
    return the captured {"cmd", "env_extra"} (draining the SSE body so the
    fake subprocess actually runs)."""
    captured = _capture_cmd(monkeypatch)
    _set_backend(monkeypatch, session_doc)
    r = client.get(path, params=params)
    assert r.status_code == 200
    _ = r.text  # drain the SSE generator so fake_stream_subprocess runs
    return captured


def _flag_value(cmd: list[str], flag: str) -> str | None:
    """Return the argument following the LAST occurrence of `flag` in cmd.

    Every route appends the rendering --model (e.g. "claude-sonnet-4-6")
    before the backend flags, so a backend override's own --model (dgx/
    openrouter) is always the later of the two occurrences.
    """
    if flag not in cmd:
        return None
    idx = len(cmd) - 1 - cmd[::-1].index(flag)
    return cmd[idx + 1] if idx + 1 < len(cmd) else None


# ── claude-code (subscription) is forwarded as --backend on every route ─────

def test_campaign_state_forwards_subscription_flag(monkeypatch):
    captured = _run(
        monkeypatch, "/api/grounding/run/campaign-state",
        {"backend": "claude-code"},
        {"input": "docs/x.md", "output": "docs/cs.md", "model": "claude-sonnet-4-6"},
    )
    assert _flag_value(captured["cmd"], "--backend") == "claude-code"
    assert captured["cmd"][-2:] == backend_cli_args("claude-code")
    # no more env-var channel — the router never populates env_extra now.
    assert captured["env_extra"] is None


def test_distill_forwards_subscription_flag(monkeypatch):
    captured = _run(
        monkeypatch, "/api/grounding/run/distill",
        {"backend": "claude-code"},
        {"input": "docs/x.md", "output": "docs/ws.md"},
    )
    assert _flag_value(captured["cmd"], "--backend") == "claude-code"
    assert captured["cmd"][-2:] == backend_cli_args("claude-code")


def test_party_forwards_subscription_flag(monkeypatch):
    captured = _run(
        monkeypatch, "/api/grounding/run/party",
        {"backend": "claude-code"},
        {"output": "docs/party.md"},
    )
    assert _flag_value(captured["cmd"], "--backend") == "claude-code"


def test_planning_forwards_subscription_flag(monkeypatch):
    captured = _run(
        monkeypatch, "/api/grounding/run/planning",
        {"backend": "claude-code"},
        {"output": "docs/planning.md"},
    )
    assert _flag_value(captured["cmd"], "--backend") == "claude-code"


def test_build_dossiers_forwards_subscription_flag(monkeypatch):
    captured = _run(
        monkeypatch, "/api/grounding/run/build-dossiers",
        {"backend": "claude-code"},
        {"summaries": "docs/s"},
    )
    assert _flag_value(captured["cmd"], "--backend") == "claude-code"


# ── openrouter is forwarded as --backend + --model. This was the actual bug:
# the old env-only translator silently dropped "openrouter" entirely, so a
# GM's openrouter pick quietly ran against the metered Anthropic API. ───────

def test_campaign_state_forwards_openrouter_flag(monkeypatch):
    captured = _run(
        monkeypatch, "/api/grounding/run/campaign-state",
        {"backend": "openrouter", "openrouter_model": "anthropic/claude-sonnet-4"},
        {"input": "docs/x.md"},
    )
    expected = backend_cli_args("openrouter", model="anthropic/claude-sonnet-4")
    assert captured["cmd"][-len(expected):] == expected
    assert _flag_value(captured["cmd"], "--backend") == "openrouter"
    assert _flag_value(captured["cmd"], "--model") == "anthropic/claude-sonnet-4"


def test_party_forwards_openrouter_flag(monkeypatch):
    captured = _run(
        monkeypatch, "/api/grounding/run/party",
        {"backend": "openrouter", "openrouter_model": "anthropic/claude-sonnet-4"},
        {"output": "docs/party.md"},
    )
    expected = backend_cli_args("openrouter", model="anthropic/claude-sonnet-4")
    assert captured["cmd"][-len(expected):] == expected


# ── dgx is forwarded as --backend/--endpoint/--model ─────────────────────────

def test_campaign_state_forwards_dgx_flags_from_session_doc(monkeypatch):
    captured = _run(
        monkeypatch, "/api/grounding/run/campaign-state",
        {"backend": "dgx", "dgx_endpoint": "http://box:8001", "dgx_model": "Qwen-X"},
        {"input": "docs/x.md"},
    )
    expected = backend_cli_args("dgx", model="Qwen-X", endpoint="http://box:8001")
    assert captured["cmd"][-len(expected):] == expected
    assert _flag_value(captured["cmd"], "--endpoint") == "http://box:8001"
    assert _flag_value(captured["cmd"], "--model") == "Qwen-X"


def test_campaign_state_dgx_falls_back_to_wiring(monkeypatch):
    """When the session_doc doesn't pin dgx_endpoint/dgx_model (global
    default, nothing overridden in the sidebar), the router falls back to
    campaignlib.wiring_get — NOT a hardcoded model literal. This replaces
    the old hardcoded "Qwen/Qwen2.5-14B-Instruct-AWQ" default, which is now
    gone from the router entirely.
    """
    monkeypatch.setattr(
        "server.routers.grounding.wiring_get",
        lambda key, default=None: {
            "dgx_endpoint": "http://wired-box:9000",
            "dgx_model": "Wired/Model-Name",
        }.get(key, default),
    )
    captured = _run(
        monkeypatch, "/api/grounding/run/campaign-state",
        {"backend": "dgx"},
        {"input": "docs/x.md"},
    )
    expected = backend_cli_args("dgx", model="Wired/Model-Name", endpoint="http://wired-box:9000")
    assert captured["cmd"][-len(expected):] == expected
    assert "Qwen/Qwen2.5-14B-Instruct-AWQ" not in captured["cmd"]


# ── anthropic / no config service → no --backend flag (default API path) ────

def test_anthropic_backend_yields_no_flag(monkeypatch):
    captured = _run(
        monkeypatch, "/api/grounding/run/campaign-state",
        {"backend": "anthropic"},
        {"input": "docs/x.md"},
    )
    assert "--backend" not in captured["cmd"]
    # unchanged from the pre-backend-flags baseline: just the rendering --model.
    assert captured["cmd"][-2:] == ["--model", "claude-sonnet-4-6"]


def test_missing_config_service_yields_no_flag(monkeypatch):
    captured = _run(
        monkeypatch, "/api/grounding/run/campaign-state",
        None,
        {"input": "docs/x.md"},
    )
    assert "--backend" not in captured["cmd"]
    assert captured["cmd"][-2:] == ["--model", "claude-sonnet-4-6"]
