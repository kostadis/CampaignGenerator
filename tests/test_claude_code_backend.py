"""Tests for the claude-code (Pro/Max subscription) backend façade.

Covers two fixes:
  - issue #108 — `max_tokens` must reach the `claude -p` subprocess as the
    CLAUDE_CODE_MAX_OUTPUT_TOKENS env var instead of being silently dropped,
    so the subscription path honors the same output ceiling as the Anthropic
    API and DGX backends.
  - the truncation/auto-continue fix — `--output-format json`'s single
    `result` field only reflects the LAST assistant turn when the CLI
    auto-continues past its output ceiling, silently dropping the head of
    the response. The backend now uses `--output-format stream-json
    --verbose` and concatenates the text of every assistant turn.
"""
import json
import subprocess
import types

import pytest

import campaignlib.api.backends as backends


def _assistant_event(text: str) -> str:
    return json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    })


def _thinking_event() -> str:
    """A thinking-only assistant event.

    Thinking-capable models (claude-fable-5 always, claude-opus-5 by default)
    emit the `thinking` block as its OWN assistant event, ahead of the event
    carrying the answer text. Verified against `claude -p --output-format
    stream-json` on claude-fable-5: an untruncated call returns exactly two
    assistant events, `['thinking']` then `['text']`, with is_error=False.
    """
    return json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "thinking", "thinking": ""}]},
    })


def _result_event(*, result="ok", is_error=False, num_turns=1) -> str:
    return json.dumps({
        "type": "result", "result": result, "is_error": is_error,
        "num_turns": num_turns,
    })


def _fake_run_factory(captured, *, result="ok", is_error=False, returncode=0,
                      stderr="", assistant_texts=None, num_turns=None,
                      raw_stdout=None):
    """Return a subprocess.run stand-in that records the env it was called with.

    Emits `claude -p --output-format stream-json` NDJSON: one line per
    assistant turn (default: a single turn built from `result`, unless
    `assistant_texts` overrides it) followed by the terminal `type=result`
    envelope line — so the backend's envelope-first error handling sees a
    well-formed payload. Pass returncode=1 to simulate the CLI exiting
    non-zero while still emitting the envelope (the overflow case).

    `raw_stdout`, if given, replaces the generated NDJSON entirely — for
    tests that need to simulate a non-JSON / garbled response.
    """
    if assistant_texts is None:
        assistant_texts = [] if is_error else [result]
    if num_turns is None:
        num_turns = len(assistant_texts) or 1

    def _fake_run(cmd, *, input, capture_output, text, env):
        captured["cmd"] = cmd
        captured["env"] = env
        captured["input"] = input
        if raw_stdout is not None:
            stdout = raw_stdout
        else:
            lines = [_assistant_event(t) for t in assistant_texts]
            lines.append(_result_event(result=result, is_error=is_error, num_turns=num_turns))
            stdout = "\n".join(lines)
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
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


def test_overflow_error_surfaces_when_exit_nonzero(monkeypatch):
    # The real bug: `claude -p` exits 1 AND emits the is_error envelope on
    # overflow. The envelope must be inspected before the returncode, so the
    # friendly message wins over the raw "exited 1" dump.
    captured = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(
        captured, is_error=True, returncode=1,
        result="API Error: Claude's response exceeded the 200 output token maximum."))
    with pytest.raises(RuntimeError, match="200-token output ceiling") as excinfo:
        backends._claude_code_generate(
            system="s", user="u", model="m", max_tokens=200)
    assert "exited 1" not in str(excinfo.value)


def test_nonzero_exit_without_json_raises_raw(monkeypatch):
    # A genuine process failure (CLI not found, auth error, crash) emits no JSON
    # envelope — it must still surface as the raw "exited N" error, not be
    # swallowed by the envelope-first path.
    def _fake_run(cmd, *, input, capture_output, text, env):
        return types.SimpleNamespace(
            returncode=1, stdout="", stderr="claude: command not found")
    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(RuntimeError, match="exited 1") as excinfo:
        backends._claude_code_generate(system="s", user="u", model="m", max_tokens=100)
    assert "command not found" in str(excinfo.value)


def test_exit_zero_without_result_event_raises_with_stdout_snippet(monkeypatch):
    # Exited 0 but stdout has no parseable `type=result` event at all — a
    # genuine "unusable output" case, distinct from the exited-nonzero path.
    captured = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(
        captured, returncode=0, raw_stdout="not json at all, just noise"))
    with pytest.raises(RuntimeError, match="non-JSON output") as excinfo:
        backends._claude_code_generate(system="s", user="u", model="m", max_tokens=100)
    assert "not json at all" in str(excinfo.value)


# ── Multi-turn auto-continue concatenation (stream-json) ────────────────────

def test_two_assistant_turns_are_concatenated_in_order(monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(
        captured, assistant_texts=["First half. ", "Second half."],
        result="Second half.", num_turns=2))
    out = backends._claude_code_generate(
        system="s", user="u", model="m", max_tokens=100)
    assert out == "First half. Second half."
    err = capsys.readouterr().err
    assert "AUTO-CONTINUED" in err
    assert "2" in err


def test_single_assistant_turn_has_no_warning(monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(
        captured, assistant_texts=["Only turn."], result="Only turn.", num_turns=1))
    out = backends._claude_code_generate(
        system="s", user="u", model="m", max_tokens=100)
    assert out == "Only turn."
    err = capsys.readouterr().err
    assert "AUTO-CONTINUED" not in err


def test_thinking_event_alone_does_not_trigger_warning(monkeypatch, capsys):
    # Regression: the warning used to count EVERY assistant event, so a
    # thinking-capable model's separate `thinking` event made a perfectly
    # untruncated call report an auto-continuation. Reproduced live on
    # claude-fable-5 at a 31000-token ceiling with a 6.7KB (untruncated)
    # response. Only text-bearing turns count.
    captured = {}
    stdout = "\n".join([
        _thinking_event(),
        _assistant_event("The whole answer."),
        _result_event(result="The whole answer.", num_turns=1),
    ])
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(
        captured, raw_stdout=stdout))
    out = backends._claude_code_generate(
        system="s", user="u", model="claude-fable-5", max_tokens=31000)
    assert out == "The whole answer."
    assert "AUTO-CONTINUED" not in capsys.readouterr().err


def test_thinking_events_do_not_mask_a_real_continuation(monkeypatch, capsys):
    # The other half: interleaved thinking events must not suppress the
    # warning when the CLI genuinely auto-continued across two text turns.
    captured = {}
    stdout = "\n".join([
        _thinking_event(),
        _assistant_event("First half. "),
        _thinking_event(),
        _assistant_event("Second half."),
        _result_event(result="Second half.", num_turns=2),
    ])
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(
        captured, raw_stdout=stdout))
    out = backends._claude_code_generate(
        system="s", user="u", model="claude-fable-5", max_tokens=100)
    assert out == "First half. Second half."
    err = capsys.readouterr().err
    assert "AUTO-CONTINUED" in err
    # Reports 2 text turns, not the 4 raw assistant events.
    assert "across 2 assistant turns" in err


def test_no_assistant_events_falls_back_to_result_field(monkeypatch):
    # Defensive fallback: a well-formed, non-error result envelope but no
    # assistant events were parsed (shouldn't happen in practice, but the
    # backend must not crash and must still return something usable).
    captured = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(
        captured, assistant_texts=[], result="fallback text", num_turns=0))
    out = backends._claude_code_generate(system="s", user="u", model="m")
    assert out == "fallback text"


def test_command_uses_stream_json_and_verbose(monkeypatch):
    captured = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(captured))
    backends._claude_code_generate(system="s", user="u", model="m")
    cmd = captured["cmd"]
    assert "stream-json" in cmd
    assert "--verbose" in cmd
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
