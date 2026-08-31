"""Shared Codex reasoning-effort resolver and adapter contract tests."""

from __future__ import annotations

import argparse
import json

import pytest

from campaignlib.api import client as client_mod
from campaignlib.api.codex_cli import CodexCliError, _CodexCliClient
from campaignlib.selection import CODEX_REASONING_EFFORTS
from tests.helpers.fake_codex_cli import FakeCodexCli


def _args(*, backend="codex-cli", effort=None, model="gpt-5.6-sol"):
    return argparse.Namespace(
        backend=backend,
        endpoint=None,
        batch=False,
        model=model,
        codex_reasoning_effort=effort,
    )


def _request(client):
    return client.messages.create(
        model="gpt-5.6-sol",
        max_tokens=64,
        system="Return a short test response.",
        messages=[{"role": "user", "content": "test"}],
    )


@pytest.mark.parametrize("effort", CODEX_REASONING_EFFORTS)
def test_all_explicit_efforts_reach_one_fake_child(monkeypatch, tmp_path, effort):
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.direct("ok"))
    fake.install(monkeypatch)
    monkeypatch.setenv("CG_CODEX_REASONING_EFFORT", "low")

    response = _request(client_mod.client_from_args(_args(effort=effort)))

    assert response.content[0].text == "ok"
    assert fake.call_count == 1
    assert fake.last_call is not None
    assert fake.last_call.reasoning_effort == json.dumps(effort)


def test_effort_omission_sends_no_override(monkeypatch, tmp_path):
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.direct("ok"))
    fake.install(monkeypatch)
    monkeypatch.delenv("CG_CODEX_REASONING_EFFORT", raising=False)

    _request(client_mod.client_from_args(_args()))

    assert fake.last_call is not None
    assert fake.last_call.reasoning_effort is None


def test_environment_effort_is_trimmed_and_forwarded(monkeypatch, tmp_path):
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.direct("ok"))
    fake.install(monkeypatch)
    monkeypatch.setenv("CG_CODEX_REASONING_EFFORT", "  high  ")

    _request(client_mod.client_from_args(_args()))

    assert fake.last_call is not None
    assert fake.last_call.reasoning_effort == '"high"'


@pytest.mark.parametrize("environment", ["", "  \t\n"])
def test_blank_environment_is_omission(monkeypatch, tmp_path, environment):
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.direct("ok"))
    fake.install(monkeypatch)
    monkeypatch.setenv("CG_CODEX_REASONING_EFFORT", environment)

    _request(client_mod.client_from_args(_args()))

    assert fake.last_call is not None
    assert fake.last_call.reasoning_effort is None


def test_explicit_effort_with_non_codex_backend_fails_before_client(monkeypatch):
    monkeypatch.setattr(
        client_mod,
        "make_client",
        lambda **_kwargs: pytest.fail("client constructed"),
    )
    with pytest.raises((ValueError, SystemExit), match="codex-cli|Codex"):
        client_mod.client_from_args(_args(backend="anthropic", effort="max"))


def test_invalid_environment_fails_before_child(monkeypatch, tmp_path):
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.direct("unused"))
    fake.install(monkeypatch)
    monkeypatch.setenv("CG_CODEX_REASONING_EFFORT", "turbo")

    with pytest.raises((ValueError, CodexCliError), match="CG_CODEX_REASONING_EFFORT"):
        client_mod.client_from_args(_args())

    assert fake.call_count == 0


def test_direct_streaming_and_brokered_clients_share_effort(monkeypatch, tmp_path):
    fake = FakeCodexCli(
        tmp_path,
        responses=[
            FakeCodexCli.direct("direct"),
            FakeCodexCli.direct("stream"),
            FakeCodexCli.structured("brokered"),
        ],
    )
    fake.install(monkeypatch)
    client = _CodexCliClient(
        reasoning_effort="max", reasoning_effort_source="explicit"
    )

    _request(client)
    with client.messages.stream(
        model="gpt-5.6-sol",
        max_tokens=64,
        system="stream",
        messages=[{"role": "user", "content": "stream"}],
    ) as stream:
        assert list(stream.text_stream) == ["stream"]
    client_mod.call_api_with_tools(
        client,
        system="broker",
        messages=[{"role": "user", "content": "broker"}],
        tools=[],
        model="gpt-5.6-sol",
        max_tokens=64,
    )

    assert fake.call_count == 3
    assert [call.reasoning_effort for call in fake.calls] == ['"max"'] * 3


def test_model_effort_rejection_names_both_and_never_falls_back(
    monkeypatch, tmp_path
):
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.rejected("unsupported"))
    fake.install(monkeypatch)

    with pytest.raises(CodexCliError, match=r"gpt-5\.6-sol.*max"):
        _request(client_mod.client_from_args(_args(effort="max")))

    assert fake.call_count == 1


@pytest.mark.parametrize(
    ("explicit", "environment", "expected", "source", "override"),
    [
        ("max", "low", "max", "explicit", True),
        (None, "high", "high", "environment", True),
        (None, None, "Codex default", "omitted", False),
    ],
)
def test_last_run_identity_and_status_line_report_actual_resolution(
    monkeypatch, tmp_path, capsys, explicit, environment, expected, source, override
):
    fake = FakeCodexCli(tmp_path, response=FakeCodexCli.direct("ok"))
    fake.install(monkeypatch)
    if environment is None:
        monkeypatch.delenv("CG_CODEX_REASONING_EFFORT", raising=False)
    else:
        monkeypatch.setenv("CG_CODEX_REASONING_EFFORT", environment)

    codex = client_mod.client_from_args(_args(effort=explicit))
    _request(codex)

    identity = codex.last_run_identity
    assert identity is not None
    assert identity.codex_reasoning_effort == expected
    assert identity.codex_reasoning_effort_source == source
    assert identity.codex_reasoning_override is override
    line = capsys.readouterr().out
    assert "Codex run:" in line
    assert f"reasoning_effort={expected} ({source})" in line
