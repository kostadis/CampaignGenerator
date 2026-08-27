"""Contract tests for the Codex CLI subscription backend (issue #348)."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

import pytest

from campaignlib.api import client as client_mod
from campaignlib.api.codex_cli import CodexCliError, _CodexCliClient


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
        ({"system": [{"type": "text", "text": "system"}]}, "system"),
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
    assert call["timeout"] == 600.0
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
