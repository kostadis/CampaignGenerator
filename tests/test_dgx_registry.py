"""CG-side wiring of the shared dgxlib per-model registry into the DGX backend.

Covers that _OpenAICompatClient resolves per-call request behavior from the
registry, and that the DGX-only `thinking` knob is threaded to the DGX backend
but never leaks to the Anthropic / Claude Code clients.
"""

import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from campaignlib.api.backends import _OpenAICompatClient
from campaignlib.api import client as api_client


QWEN3 = "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"   # can_think: true in the bundled registry
QWEN25 = "Qwen/Qwen2.5-14B-Instruct-AWQ"          # can_think: false


@pytest.fixture
def dgx_client(monkeypatch):
    monkeypatch.setenv("DGX_MODEL", QWEN3)
    monkeypatch.delenv("DGX_NO_THINKING", raising=False)
    monkeypatch.delenv("DGX_READ_TIMEOUT", raising=False)
    # No connection happens at construction; only when a request is issued.
    return _OpenAICompatClient("http://127.0.0.1:1")


# ── per-call registry resolution ─────────────────────────────────────────────

def test_thinking_default_off_for_reasoning_model(dgx_client):
    assert dgx_client.extra_body_for(QWEN3, None) == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_thinking_per_call_override_on(dgx_client):
    assert dgx_client.extra_body_for(QWEN3, True) == {
        "chat_template_kwargs": {"enable_thinking": True}
    }


def test_non_reasoning_model_forced_off(monkeypatch):
    monkeypatch.setenv("DGX_MODEL", QWEN25)
    c = _OpenAICompatClient("http://127.0.0.1:1")
    assert c.extra_body_for(QWEN25, True) == {}


def test_read_timeout_from_registry(dgx_client):
    # Qwen3-Next sets read_timeout: 600 in the bundled registry.
    assert dgx_client.oai.timeout.read == 600.0


def test_client_retains_resolved_registry_config(dgx_client):
    # Older installed dgxlib versions remain supported until the companion
    # registry branch is delivered.
    assert getattr(dgx_client.model_config, "max_concurrency", None) is None


def test_client_exposes_registry_declared_max_concurrency(monkeypatch):
    cfg = SimpleNamespace(
        read_timeout=60,
        max_concurrency=8,
        extra_body={},
    )
    fake_dgxlib = SimpleNamespace(resolve_model_config=lambda *_args, **_kwargs: cfg)
    monkeypatch.setitem(sys.modules, "dgxlib", fake_dgxlib)
    monkeypatch.setenv("DGX_MODEL", "qwen3.8-flash-next")
    client = _OpenAICompatClient("http://127.0.0.1:1")
    assert client.model_config.max_concurrency == 8


def test_dgx_read_timeout_env_overrides_registry(monkeypatch):
    monkeypatch.setenv("DGX_MODEL", QWEN3)
    monkeypatch.setenv("DGX_READ_TIMEOUT", "42")
    c = _OpenAICompatClient("http://127.0.0.1:1")
    assert c.oai.timeout.read == 42.0


def test_dgx_no_thinking_env_back_compat(dgx_client, monkeypatch):
    monkeypatch.setenv("DGX_NO_THINKING", "1")
    # caller didn't ask → env forces off
    assert dgx_client.extra_body_for(QWEN3, None) == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


# ── thinking is threaded to DGX, never to other backends ─────────────────────

class _RecordingMessages:
    def __init__(self):
        self.create_kwargs = None

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        class _Resp:
            content = [type("B", (), {"text": "ok"})()]
        return _Resp()


class _FakeAnthropic:
    """A non-DGX client: must never receive a `thinking` kwarg."""

    def __init__(self):
        self.messages = _RecordingMessages()


def test_thinking_not_leaked_to_non_dgx_client():
    fake = _FakeAnthropic()
    api_client.call_api(fake, "sys", "hi", "claude-sonnet-4-6", thinking=True)
    assert "thinking" not in fake.messages.create_kwargs


def test_thinking_forwarded_to_dgx_client(dgx_client, monkeypatch):
    captured = {}

    class _FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            class _R:
                choices = [type("C", (), {"message": type("M", (), {"content": "ok"})()})()]
            return _R()

    dgx_client.oai.chat.completions = _FakeCompletions()
    api_client.call_api(dgx_client, "sys", "hi", QWEN3, thinking=True)
    assert captured["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}
