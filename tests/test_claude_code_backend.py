"""Tests for the claude-code (Pro/Max subscription) backend façade.

Focus: the fix for issue #108 — `max_tokens` must reach the `claude -p`
subprocess as the CLAUDE_CODE_MAX_OUTPUT_TOKENS env var instead of being
silently dropped, so the subscription path honors the same output ceiling as
the Anthropic API and DGX backends.
"""
import json
import subprocess
import types

import pytest

import campaignlib.api.backends as backends


def _fake_run_factory(captured, *, result="ok", is_error=False):
    """Return a subprocess.run stand-in that records the env it was called with."""
    def _fake_run(cmd, *, input, capture_output, text, env):
        captured["cmd"] = cmd
        captured["env"] = env
        captured["input"] = input
        payload = {"result": result, "is_error": is_error}
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
    return _fake_run


def test_max_tokens_forwarded_as_env(monkeypatch):
    captured = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(captured))
    out = backends._claude_code_generate(
        system="sys", user="hello", model="claude-opus-4-8", max_tokens=4096)
    assert out == "ok"
    assert captured["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "4096"


def test_no_max_tokens_leaves_env_unset(monkeypatch):
    captured = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(captured))
    backends._claude_code_generate(system="sys", user="hi", model="m")
    assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" not in captured["env"]


def test_api_key_still_stripped(monkeypatch):
    captured = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(captured))
    backends._claude_code_generate(system="s", user="u", model="m", max_tokens=100)
    assert "ANTHROPIC_API_KEY" not in captured["env"]


def test_messages_facade_threads_max_tokens(monkeypatch):
    captured = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(captured))
    client = backends._ClaudeCodeClient()
    # stream() path (used by stream_api)
    with client.messages.stream(
        model="m", max_tokens=8000, system="s",
        messages=[{"role": "user", "content": "hi"}],
    ):
        pass
    assert captured["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "8000"


def test_overflow_error_mentions_token_ceiling(monkeypatch):
    captured = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(
        captured, is_error=True,
        result="API Error: Claude's response exceeded the 200 output token maximum."))
    with pytest.raises(RuntimeError, match="200-token output ceiling"):
        backends._claude_code_generate(
            system="s", user="u", model="m", max_tokens=200)
