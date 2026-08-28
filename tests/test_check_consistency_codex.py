"""End-to-end CLI seam tests for the Codex consistency backend."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from campaignlib.api.codex_cli import CodexCliError
from session_doc import check_consistency


def _campaign(tmp_path: Path):
    campaign = tmp_path / "campaign"
    docs = campaign / "docs"
    docs.mkdir(parents=True)
    (docs / "entity_registry.yaml").write_text(
        "version: 1\ncampaign: fixture\nentities:\n  - name: Exact Canon\n    type: npc\n",
        encoding="utf-8",
    )
    config = campaign / "config.yaml"
    config.write_text("documents: []\n", encoding="utf-8")
    document = campaign / "session.md"
    document.write_text("Document α bytes.\n", encoding="utf-8")
    ctx_a = tmp_path / "a.md"
    ctx_b = tmp_path / "b.md"
    ctx_a.write_text("Context A exact.\n", encoding="utf-8")
    ctx_b.write_text("Context B exact.\n", encoding="utf-8")
    return document, config, ctx_a, ctx_b


def _argv(document, config, ctx_a, ctx_b, output, *extra):
    return [
        "check_consistency",
        str(document),
        "--config",
        str(config),
        "--context",
        str(ctx_a),
        "--context",
        str(ctx_b),
        "--backend",
        "codex-cli",
        "--output",
        str(output),
        *extra,
    ]


def test_codex_cli_preserves_prompt_and_report_workflow(tmp_path, monkeypatch, capsys):
    document, config, ctx_a, ctx_b = _campaign(tmp_path)
    output = tmp_path / "report.md"
    calls = []

    monkeypatch.setattr(check_consistency, "client_from_args", lambda args: "codex-client")

    def fake_stream(client, system, user, model, **kwargs):
        calls.append((client, system, user, model, kwargs))
        return "## Consistency Report\n\n- **Issue**: Wrong name\n  **Location**: line 1"

    monkeypatch.setattr(check_consistency, "stream_api", fake_stream)
    monkeypatch.setattr(sys, "argv", _argv(document, config, ctx_a, ctx_b, output))

    check_consistency.main()

    assert len(calls) == 1
    _, system, user, model, kwargs = calls[0]
    assert "consistency" in system.lower()
    assert user.index("Document α bytes.") < user.index("Exact Canon")
    assert user.index("Context A exact.") < user.index("Context B exact.")
    assert model is None
    assert kwargs["silent"] is True
    assert output.read_text(encoding="utf-8") == "## Consistency Report\n\n- **Issue**: Wrong name\n  **Location**: line 1"
    stdout = capsys.readouterr().out
    assert "Found 1 potential issue" in stdout
    assert "Codex subscription default" in stdout


@pytest.mark.parametrize(
    ("explicit", "environment", "expected"),
    [
        ("explicit-model", "env-model", "explicit-model"),
        (None, "env-model", None),
        (None, None, None),
    ],
)
def test_cli_model_is_forwarded_only_when_explicit(tmp_path, monkeypatch, explicit, environment, expected):
    document, config, ctx_a, ctx_b = _campaign(tmp_path)
    output = tmp_path / "report.md"
    if environment is None:
        monkeypatch.delenv("CG_CODEX_MODEL", raising=False)
    else:
        monkeypatch.setenv("CG_CODEX_MODEL", environment)
    seen = {}

    def fake_client(args):
        seen["client_model"] = args.model
        return object()

    def fake_stream(client, system, user, model, **kwargs):
        seen["call_model"] = model
        return "No issues found."

    monkeypatch.setattr(check_consistency, "client_from_args", fake_client)
    monkeypatch.setattr(check_consistency, "stream_api", fake_stream)
    extra = ("--model", explicit) if explicit else ()
    monkeypatch.setattr(sys, "argv", _argv(document, config, ctx_a, ctx_b, output, *extra))
    check_consistency.main()
    assert seen == {"client_model": expected, "call_model": expected}


def test_existing_backend_keeps_default_model(tmp_path, monkeypatch):
    document, config, ctx_a, ctx_b = _campaign(tmp_path)
    output = tmp_path / "report.md"
    seen = {}
    monkeypatch.setattr(
        check_consistency,
        "client_from_args",
        lambda args: seen.update(client_model=args.model) or object(),
    )
    monkeypatch.setattr(
        check_consistency,
        "stream_api",
        lambda client, system, user, model, **kwargs: seen.update(call_model=model) or "ok",
    )
    argv = _argv(document, config, ctx_a, ctx_b, output)
    argv[argv.index("codex-cli")] = "anthropic"
    monkeypatch.setattr(sys, "argv", argv)
    check_consistency.main()
    assert seen == {
        "client_model": check_consistency.DEFAULT_MODEL,
        "call_model": check_consistency.DEFAULT_MODEL,
    }


@pytest.mark.parametrize(
    "message",
    [
        "codex executable not found; install Codex CLI",
        "authentication failed; run codex login",
        "codex-cli exited 2: incompatible configuration",
    ],
)
def test_codex_error_is_concise_and_writes_no_report(
    tmp_path, monkeypatch, capsys, message
):
    document, config, ctx_a, ctx_b = _campaign(tmp_path)
    output = tmp_path / "report.md"
    monkeypatch.setattr(check_consistency, "client_from_args", lambda args: object())
    monkeypatch.setattr(
        check_consistency,
        "stream_api",
        lambda *a, **k: (_ for _ in ()).throw(CodexCliError(message)),
    )
    monkeypatch.setattr(sys, "argv", _argv(document, config, ctx_a, ctx_b, output))
    with pytest.raises(SystemExit) as excinfo:
        check_consistency.main()
    assert excinfo.value.code == 1
    assert message in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize("source", ["explicit", "environment"])
def test_incompatible_claude_model_refuses_before_child(
    tmp_path, monkeypatch, capsys, source
):
    document, config, ctx_a, ctx_b = _campaign(tmp_path)
    output = tmp_path / "report.md"
    if source == "environment":
        monkeypatch.setenv("CG_CODEX_MODEL", "claude-opus-4")
    monkeypatch.setattr(
        check_consistency,
        "stream_api",
        check_consistency.stream_api,
    )
    extra = ("--model", "claude-sonnet-4") if source == "explicit" else ()
    monkeypatch.setattr(
        sys, "argv", _argv(document, config, ctx_a, ctx_b, output, *extra)
    )
    with pytest.raises(SystemExit) as excinfo:
        check_consistency.main()
    assert excinfo.value.code == 1
    assert "incompatible" in capsys.readouterr().err.lower()
    assert not output.exists()
