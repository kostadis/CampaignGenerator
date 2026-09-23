"""Structured user-content coverage for the live Anthropic-shaped API path."""

from campaignlib.api import client as client_mod


class _OneChunkStream:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @property
    def text_stream(self):
        return iter(("complete response",))


class _RecordingMessages:
    def __init__(self):
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return _OneChunkStream()


class _AnthropicShapedClient:
    def __init__(self):
        self.messages = _RecordingMessages()


def test_stream_api_forwards_user_content_blocks_to_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = _AnthropicShapedClient()
    blocks = [
        {
            "type": "text",
            "text": "stable context\n\n---\n\n",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "changing targets"},
    ]

    result = client_mod.stream_api(client, "system", blocks, "model", silent=True)

    assert result == "complete response"
    assert client.messages.calls[0]["messages"] == [
        {"role": "user", "content": blocks}
    ]


def test_stream_api_keeps_string_user_content_unchanged(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = _AnthropicShapedClient()

    client_mod.stream_api(client, "system", "plain request", "model", silent=True)

    assert client.messages.calls[0]["messages"] == [
        {"role": "user", "content": "plain request"}
    ]
