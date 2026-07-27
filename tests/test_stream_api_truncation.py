"""Tests for stream_api's truncation warning (campaignlib/api/client.py).

`stream_api` inherits a default max_tokens (8096) far smaller than large
synthesis docs need. On the real Anthropic SDK, hitting that ceiling shows up
as `stop_reason=max_tokens` on the final message — silently, unless something
checks it. These tests cover the defensive check: warn loudly to stderr when
truncated, stay silent otherwise, and never crash against the DGX/openrouter/
claude-code façades in campaignlib/api/backends.py, none of which implement
`get_final_message()`.
"""
import types

from campaignlib.api.client import stream_api


class _FakeAnthropicStream:
    """Mimics the real anthropic SDK's streaming context manager, including
    `get_final_message()` — which only the real SDK stream exposes."""

    def __init__(self, chunks, stop_reason):
        self._chunks = chunks
        self._stop_reason = stop_reason

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @property
    def text_stream(self):
        return iter(self._chunks)

    def get_final_message(self):
        return types.SimpleNamespace(stop_reason=self._stop_reason)


class _FacadeStreamNoFinalMessage:
    """Mimics the DGX/openrouter (_OpenAICompatStream) and claude-code
    (_ClaudeCodeStream) façades in campaignlib/api/backends.py: no
    get_final_message() at all."""

    def __init__(self, chunks):
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @property
    def text_stream(self):
        return iter(self._chunks)


class _FakeMessages:
    def __init__(self, stream_obj):
        self._stream_obj = stream_obj

    def stream(self, **kwargs):
        return self._stream_obj


class _FakeClient:
    def __init__(self, stream_obj):
        self.messages = _FakeMessages(stream_obj)


def test_max_tokens_stop_reason_warns_loudly(capsys):
    stream_obj = _FakeAnthropicStream(["hello ", "world"], stop_reason="max_tokens")
    client = _FakeClient(stream_obj)

    result = stream_api(client, "sys", "user prompt", "model-x", max_tokens=123, silent=True)

    assert result == "hello world"
    err = capsys.readouterr().err
    assert "TRUNCATED" in err
    assert "123" in err


def test_end_turn_stop_reason_has_no_warning(capsys):
    stream_obj = _FakeAnthropicStream(["hello"], stop_reason="end_turn")
    client = _FakeClient(stream_obj)

    result = stream_api(client, "sys", "user prompt", "model-x", silent=True)

    assert result == "hello"
    err = capsys.readouterr().err
    assert "TRUNCATED" not in err


def test_stream_without_get_final_message_does_not_crash(capsys):
    stream_obj = _FacadeStreamNoFinalMessage(["hi there"])
    client = _FakeClient(stream_obj)

    result = stream_api(client, "sys", "user prompt", "model-x", silent=True)

    assert result == "hi there"
    err = capsys.readouterr().err
    assert "TRUNCATED" not in err
