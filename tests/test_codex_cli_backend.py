"""Contract tests for the Codex CLI subscription backend (issue #348)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import pytest

from campaignlib.api import client as client_mod
from campaignlib.api.codex_cli import CodexCliError, _CodexCliClient
from tests.helpers.fake_codex_cli import FakeCodexCli


SYSTEM = "Audit faithfully.\nKeep roles separate."
USER = "## Document\n\nExact bytes: αβγ\n"
REPORT = "## Consistency Report\n\n- **Issue**: Example\n  **Location**: Line 1"

DISABLED_FEATURES = {
    "apps",
    "hooks",
    "multi_agent",
    "plugins",
    "remote_plugin",
    "shell_tool",
    "skill_search",
    "skill_mcp_dependency_install",
    "workspace_dependencies",
    "tool_suggest",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "image_generation",
    "view_image",
    "code_mode_host",
}


def _message(content=USER):
    return [{"role": "user", "content": content}]


def _successful_run(captured: list[dict], result: str = REPORT):
    def fake_run(cmd, **kwargs):
        result_path = Path(cmd[cmd.index("--output-last-message") + 1])
        captured.append({"cmd": cmd, "result_path": result_path, **kwargs})
        assert Path(kwargs["cwd"]).is_dir()
        result_path.write_text(result, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout=result, stderr="progress")

    return fake_run


def _create(client=None, **overrides):
    client = client or _CodexCliClient()
    kwargs = {
        "model": None,
        "max_tokens": 32000,
        "system": SYSTEM,
        "messages": _message(),
    }
    kwargs.update(overrides)
    return client.messages.create(**kwargs)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"system": [{"type": "image", "source": {}}]}, "text-only"),
        ({"messages": []}, "exactly one"),
        ({"messages": _message() + _message("second")}, "exactly one"),
        ({"messages": [{"role": "assistant", "content": "old"}]}, "user"),
        ({"messages": _message([{"type": "image", "source": {}}])}, "text-only"),
        ({"messages": _message([{"type": "tool_result", "content": "x"}])}, "text-only"),
        ({"messages": _message(123)}, "text-only"),
        ({"tools": [{"name": "search"}]}, "tool"),
    ],
)
def test_rejects_unsupported_request_shapes(monkeypatch, overrides, match):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("child started"))
    with pytest.raises(CodexCliError, match=match):
        _create(**overrides)


def test_text_blocks_are_preserved_in_order(monkeypatch):
    captured = []
    monkeypatch.setattr(subprocess, "run", _successful_run(captured))
    response = _create(messages=_message([
        {"type": "text", "text": "first\n"},
        {"type": "text", "text": "second"},
    ]))
    assert response.content[0].text == REPORT
    assert captured[0]["input"] == "first\nsecond"


def test_system_text_blocks_preserve_order_and_ignore_cache_metadata(monkeypatch):
    """Anthropic cache hints are metadata, not content for Codex transport."""
    captured = []
    monkeypatch.setattr(subprocess, "run", _successful_run(captured))
    system = [
        {"type": "text", "text": "first instruction\n", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "second instruction", "cache_control": {"type": "ephemeral"}},
    ]

    response = _create(system=system)

    assert response.content[0].text == REPORT
    developer_arg = next(
        value for value in captured[0]["cmd"]
        if value.startswith("developer_instructions=")
    )
    assert json.loads(developer_arg.split("=", 1)[1]) == (
        "first instruction\nsecond instruction"
    )
    assert "cache_control" not in developer_arg
def test_create_uses_exact_role_transport_and_isolated_child(monkeypatch):
    captured = []
    monkeypatch.setenv("OPENAI_API_KEY", "metered-openai")
    monkeypatch.setenv("CODEX_API_KEY", "metered-codex")
    monkeypatch.setattr(subprocess, "run", _successful_run(captured))

    response = _create()

    assert response.content[0].text == REPORT
    assert len(captured) == 1
    call = captured[0]
    cmd = call["cmd"]
    assert call["input"] == USER
    assert SYSTEM not in USER
    assert f"developer_instructions={__import__('json').dumps(SYSTEM, ensure_ascii=False)}" in cmd
    assert cmd[-1] == "-"
    assert call["capture_output"] is True
    assert call["text"] is True
    assert call["timeout"] == 1800.0
    assert "OPENAI_API_KEY" not in call["env"]
    assert "CODEX_API_KEY" not in call["env"]
    assert os.environ["OPENAI_API_KEY"] == "metered-openai"
    assert os.environ["CODEX_API_KEY"] == "metered-codex"
    assert Path(call["cwd"]) == Path(cmd[cmd.index("--cd") + 1])
    assert not Path(call["cwd"]).exists()
    assert not call["result_path"].exists()


def test_command_contains_complete_fail_closed_policy(monkeypatch):
    captured = []
    monkeypatch.setattr(subprocess, "run", _successful_run(captured))
    _create()
    cmd = captured[0]["cmd"]

    assert cmd[:2] == ["codex", "exec"]
    for flag in (
        "--ephemeral", "--ignore-user-config", "--ignore-rules",
        "--strict-config", "--skip-git-repo-check",
    ):
        assert cmd.count(flag) == 1
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert cmd[cmd.index("--color") + 1] == "never"
    config_values = [cmd[i + 1] for i, arg in enumerate(cmd[:-1]) if arg == "-c"]
    for value in (
        'approval_policy="never"',
        'forced_login_method="chatgpt"',
        'web_search="disabled"',
        "tools.web_search=false",
        "apps._default.enabled=false",
        "agents.enabled=false",
        "project_doc_max_bytes=0",
    ):
        assert config_values.count(value) == 1
    disabled = {cmd[i + 1] for i, arg in enumerate(cmd[:-1]) if arg == "--disable"}
    assert disabled == DISABLED_FEATURES


def test_stream_yields_one_complete_chunk_and_runs_once(monkeypatch):
    captured = []
    monkeypatch.setattr(subprocess, "run", _successful_run(captured))
    client = _CodexCliClient()
    with client.messages.stream(
        model=None, max_tokens=10, system=SYSTEM, messages=_message()
    ) as stream:
        assert list(stream.text_stream) == [REPORT]
    assert len(captured) == 1


def test_process_backed_child_keeps_saved_login_context_and_strips_metered_keys(
    monkeypatch, tmp_path
):
    """The fake executable verifies the actual child environment, not a mock."""
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.direct(REPORT))
    fake.install(monkeypatch)
    monkeypatch.setenv("HOME", "/home/subscriber")
    monkeypatch.setenv("CODEX_HOME", "/home/subscriber/.codex")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "metered-anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "metered-openai")
    monkeypatch.setenv("CODEX_API_KEY", "metered-codex")

    response = _create()

    assert response.content[0].text == REPORT
    call = fake.last_call
    assert call is not None
    assert call.env["HOME"] == "/home/subscriber"
    assert call.env["CODEX_HOME"] == "/home/subscriber/.codex"
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY"):
        assert key not in call.env
    assert call.structured is False
    assert not call.cwd.exists()
    assert call.output_last_message is not None
    assert not call.output_last_message.exists()


def test_brokered_call_uses_structured_capability_and_returns_tool_use_facade(
    monkeypatch, tmp_path
):
    fake = FakeCodexCli(
        tmp_path,
        response=FakeCodexCli.structured(
            "I will inspect the draft first.",
            tool_calls=[{"name": "list_sections", "arguments_json": "{}"}],
        ),
    )
    fake.install(monkeypatch)

    response = client_mod.call_api_with_tools(
        _CodexCliClient(),
        system=SYSTEM,
        messages=[{"role": "user", "content": "Inspect the draft."}],
        tools=[{"name": "list_sections", "input_schema": {"type": "object"}}],
        model=None,
    )

    assert response.stop_reason == "tool_use"
    assert [block.type for block in response.content] == ["text", "tool_use"]
    assert response.content[0].text == "I will inspect the draft first."
    assert response.content[1].name == "list_sections"
    assert response.content[1].input == {}
    assert response.content[1].id
    assert response.usage.input_tokens is None
    assert response.usage.output_tokens is None
    assert len(fake.calls) == 1
    assert fake.last_call.structured is True


def _broker_request(client, messages):
    return client_mod.call_api_with_tools(
        client,
        system=SYSTEM,
        messages=messages,
        tools=[{"name": "read_doc_section", "input_schema": {"type": "object"}}],
        model=None,
    )


def test_broker_transcript_preserves_user_and_assistant_text_order(
    monkeypatch, tmp_path
):
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.structured("done"))
    fake.install(monkeypatch)

    _broker_request(
        _CodexCliClient(),
        [
            {"role": "user", "content": "user text"},
            {"role": "assistant", "content": "assistant text"},
        ],
    )

    invocation = fake.last_call
    assert invocation is not None
    transcript = json.loads(invocation.stdin)
    assert transcript["version"] == "codex-brokered-v1"
    assert transcript["messages"] == [
        {"role": "user", "blocks": [{"type": "text", "text": "user text"}]},
        {"role": "assistant", "blocks": [{"type": "text", "text": "assistant text"}]},
    ]


def test_broker_transcript_preserves_tool_order_and_replays_opaque_ids(
    monkeypatch, tmp_path
):
    """A later turn must carry host-assigned IDs back as typed results."""
    fake = FakeCodexCli(
        tmp_path,
        responses=[
            FakeCodexCli.structured(
                "I will inspect both sections.",
                tool_calls=[
                    {"name": "read_doc_section", "arguments_json": '{"section":"A"}'},
                    {"name": "read_doc_section", "arguments_json": '{"section":"B"}'},
                ],
            ),
            FakeCodexCli.structured("finished"),
        ],
    )
    fake.install(monkeypatch)
    client = _CodexCliClient()

    first = _broker_request(
        client, [{"role": "user", "content": "Inspect A and B."}]
    )
    action_blocks = [block for block in first.content if block.type == "tool_use"]
    ids = [block.id for block in action_blocks]
    assert len(action_blocks) == 2
    assert all(isinstance(tool_id, str) and tool_id for tool_id in ids)
    assert len(set(ids)) == 2
    assert all(tool_id not in {block.name for block in action_blocks} for tool_id in ids)
    assert first.stop_reason == "tool_use"
    assert first.usage.input_tokens is None
    assert first.usage.output_tokens is None

    second = _broker_request(
        client,
        [
            {"role": "user", "content": "Inspect A and B."},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I will inspect both sections."},
                    {
                        "type": "tool_use",
                        "id": ids[0],
                        "name": action_blocks[0].name,
                        "input": action_blocks[0].input,
                    },
                    {
                        "type": "tool_use",
                        "id": ids[1],
                        "name": action_blocks[1].name,
                        "input": action_blocks[1].input,
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": ids[0], "content": "A text", "is_error": False},
                    {"type": "tool_result", "tool_use_id": ids[1], "content": "B text", "is_error": False},
                ],
            },
        ],
    )

    assert second.stop_reason == "end_turn"
    assert second.usage.input_tokens is None
    assert second.usage.output_tokens is None
    assert len(fake.calls) == 2
    transcript = json.loads(fake.calls[1].stdin)
    assert [message["role"] for message in transcript["messages"]] == [
        "user", "assistant", "user"
    ]
    assert [block["type"] for block in transcript["messages"][1]["blocks"]] == [
        "text", "tool_use", "tool_use"
    ]
    assert [block["id"] for block in transcript["messages"][1]["blocks"][1:]] == ids
    assert [
        block["input"] for block in transcript["messages"][1]["blocks"][1:]
    ] == [action_blocks[0].input, action_blocks[1].input]
    assert [
        block["tool_use_id"] for block in transcript["messages"][2]["blocks"]
    ] == ids
    assert [
        block["is_error"] for block in transcript["messages"][2]["blocks"]
    ] == [False, False]


def test_broker_text_only_result_has_end_turn_and_null_usage(monkeypatch, tmp_path):
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.structured("finished"))
    fake.install(monkeypatch)

    response = _broker_request(
        _CodexCliClient(), [{"role": "user", "content": "Finish."}]
    )

    assert response.stop_reason == "end_turn"
    assert response.content[0].text == "finished"
    assert response.usage.input_tokens is None
    assert response.usage.output_tokens is None


@pytest.mark.parametrize(
    "messages",
    [
        [
            {"role": "user", "content": "request"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "dup", "name": "a", "input": {}},
                {"type": "tool_use", "id": "dup", "name": "b", "input": {}},
            ]},
        ],
        [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "missing", "content": "x", "is_error": False},
            ]},
        ],
        [
            {"role": "user", "content": "request"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "one", "name": "a", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "one", "content": "x", "is_error": False},
                {"type": "tool_result", "tool_use_id": "one", "content": "again", "is_error": False},
            ]},
        ],
    ],
    ids=["duplicate-id", "unresolved-id", "duplicate-result"],
)
def test_broker_rejects_duplicate_or_unresolved_action_ids(
    monkeypatch, tmp_path, messages
):
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.structured("unused"))
    fake.install(monkeypatch)

    with pytest.raises(CodexCliError):
        _broker_request(_CodexCliClient(), messages)

    assert fake.calls == []


@pytest.mark.parametrize(
    "messages",
    [
        [
            {"role": "user", "content": "request"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "bad", "name": "action", "input": []},
            ]},
        ],
        [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "missing", "content": "x", "is_error": "false"},
            ]},
        ],
    ],
    ids=["non-object-action-input", "invalid-result-error-flag"],
)
def test_broker_rejects_malformed_typed_action_blocks(
    monkeypatch, tmp_path, messages
):
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.structured("unused"))
    fake.install(monkeypatch)

    with pytest.raises(CodexCliError):
        _broker_request(_CodexCliClient(), messages)

    assert fake.calls == []


@pytest.mark.parametrize(
    "raw_result",
    [
        "not json",
        "[]",
        "{}",
        '{"text":"ok"}',
        '{"text":"ok","tool_calls":{},"extra":true}',
        '{"text":"","tool_calls":[]}',
    ],
    ids=["invalid-json", "array", "missing-fields", "missing-tool-calls", "unknown-field", "empty"],
)
def test_broker_rejects_malformed_result_envelopes(monkeypatch, tmp_path, raw_result):
    fake = FakeCodexCli(
        tmp_path,
        response=FakeCodexCli.direct("unused", raw_result=raw_result),
    )
    fake.install(monkeypatch)

    with pytest.raises(CodexCliError):
        _broker_request(_CodexCliClient(), [{"role": "user", "content": "request"}])

    assert len(fake.calls) == 1
    assert fake.last_call is not None and fake.last_call.structured is True
    assert not fake.last_call.cwd.exists()


@pytest.mark.parametrize(
    "arguments_json",
    ["not-json", "[]", "null", "1", '"text"', ""],
    ids=["invalid-json", "array", "null", "number", "string", "empty"],
)
def test_broker_rejects_non_object_tool_arguments(monkeypatch, tmp_path, arguments_json):
    result = json.dumps({
        "text": "I need an action.",
        "tool_calls": [{"name": "read_doc_section", "arguments_json": arguments_json}],
    })
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.direct("unused", raw_result=result))
    fake.install(monkeypatch)

    with pytest.raises(CodexCliError):
        _broker_request(_CodexCliClient(), [{"role": "user", "content": "request"}])


@pytest.mark.parametrize(
    "overrides",
    [
        {"system": [{"type": "image", "source": {}}]},
        {"messages": _message() + _message("second")},
        {"messages": [{"role": "assistant", "content": "old"}]},
        {"messages": _message([{"type": "tool_use", "id": "x", "name": "x", "input": {}}])},
        {"messages": _message([{"type": "tool_result", "tool_use_id": "x", "content": "x"}])},
        {"tools": [{"name": "read_doc_section"}]},
    ],
    ids=["system-image", "multi-turn", "assistant-history", "user-tool", "user-tool-result", "tools"],
)
def test_direct_shape_refusal_happens_before_fake_child(
    monkeypatch, tmp_path, overrides
):
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.direct(REPORT))
    fake.install(monkeypatch)

    with pytest.raises(CodexCliError):
        _create(client=_CodexCliClient(), **overrides)

    assert fake.calls == []


def test_failed_child_makes_no_provider_fallback_and_cleans_up(monkeypatch, tmp_path):
    fake = FakeCodexCli(
        tmp_path,
        response=FakeCodexCli.direct(
            "partial output must not win",
            returncode=23,
            stderr="subscription child failed",
        ),
    )
    fake.install(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)

    with pytest.raises(CodexCliError, match="exited 23"):
        _create()

    assert len(fake.calls) == 1
    call = fake.last_call
    assert call is not None
    assert not call.cwd.exists()
    assert call.output_last_message is not None
    assert not call.output_last_message.exists()


@pytest.mark.parametrize(
    ("explicit", "environment", "expected"),
    [
        ("explicit-model", "env-model", "explicit-model"),
        (None, "env-model", "env-model"),
        (None, "  ", None),
        (None, None, None),
    ],
)
def test_model_precedence(monkeypatch, explicit, environment, expected):
    captured = []
    if environment is None:
        monkeypatch.delenv("CG_CODEX_MODEL", raising=False)
    else:
        monkeypatch.setenv("CG_CODEX_MODEL", environment)
    monkeypatch.setattr(subprocess, "run", _successful_run(captured))
    _create(client=_CodexCliClient(model_override=explicit))
    cmd = captured[0]["cmd"]
    if expected is None:
        assert "--model" not in cmd
    else:
        assert cmd[cmd.index("--model") + 1] == expected


@pytest.mark.parametrize("source", ["explicit", "environment"])
def test_claude_model_is_rejected_before_child(monkeypatch, source):
    monkeypatch.delenv("CG_CODEX_MODEL", raising=False)
    client = _CodexCliClient(
        model_override="claude-sonnet-4" if source == "explicit" else None
    )
    if source == "environment":
        monkeypatch.setenv("CG_CODEX_MODEL", "claude-opus-4")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("child started"))
    with pytest.raises(CodexCliError, match="incompatible.*claude"):
        _create(client=client)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "not-a-number"])
def test_invalid_timeout_refuses_before_child(monkeypatch, value):
    monkeypatch.setenv("CG_CODEX_TIMEOUT", value)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("child started"))
    with pytest.raises(CodexCliError, match="CG_CODEX_TIMEOUT"):
        _create()


def test_configured_timeout_is_forwarded(monkeypatch):
    captured = []
    monkeypatch.setenv("CG_CODEX_TIMEOUT", "12.5")
    monkeypatch.setattr(subprocess, "run", _successful_run(captured))
    _create()
    assert captured[0]["timeout"] == 12.5


def test_timeout_is_actionable_and_temp_dir_is_cleaned(monkeypatch):
    seen = {}

    def timeout(cmd, **kwargs):
        seen["cwd"] = kwargs["cwd"]
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"], stderr="still running")

    monkeypatch.setenv("CG_CODEX_TIMEOUT", "3")
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(CodexCliError, match="timed out after 3"):
        _create()
    assert not Path(seen["cwd"]).exists()


def test_missing_executable_is_actionable(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(CodexCliError, match="not installed|not found"):
        _create()


def test_authentication_failure_is_distinct(monkeypatch):
    def fail(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Not logged in; run codex login")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(CodexCliError, match="authentication|login"):
        _create()


def test_nonzero_exit_ignores_partial_result_and_bounds_diagnostic(monkeypatch):
    def fail(cmd, **kwargs):
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(
            "partial result must not win", encoding="utf-8"
        )
        return subprocess.CompletedProcess(cmd, 7, stdout="partial", stderr="x" * 5000)

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(CodexCliError, match="exited 7") as excinfo:
        _create()
    assert "partial result must not win" not in str(excinfo.value)
    assert len(str(excinfo.value)) < 1500


@pytest.mark.parametrize("result", [None, "", "  \n\t"])
def test_success_without_nonempty_final_result_fails(monkeypatch, result):
    def fake_run(cmd, **kwargs):
        if result is not None:
            Path(cmd[cmd.index("--output-last-message") + 1]).write_text(result, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(CodexCliError, match="empty|missing"):
        _create()


def test_codex_errors_are_not_retryable():
    assert client_mod._is_retryable(CodexCliError("boom")) is False


def test_client_from_args_codex_forwards_model(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        client_mod,
        "make_client",
        lambda backend=None, endpoint=None, model_override=None: seen.update(
            backend=backend, endpoint=endpoint, model_override=model_override
        ) or "client",
    )
    ns = argparse.Namespace(
        backend="codex-cli", endpoint=None, model="codex-model", batch=False
    )
    assert client_mod.client_from_args(ns) == "client"
    assert seen == {
        "backend": "codex-cli",
        "endpoint": None,
        "model_override": "codex-model",
    }
