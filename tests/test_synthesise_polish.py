"""Tests for synthesise_polish.py's --batch wiring (feature 004-claude-api-batch).

Single-call CLI: the render call already takes an explicit --max-tokens
(default 16000); --batch must route through run_single_batch with that same
max_tokens, and the default (no --batch) path must stay byte-identical.
"""
import asyncio
import inspect
import json
import sys
from pathlib import Path

import pytest
from fastapi import Request
from starlette.responses import PlainTextResponse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipelines.ensemble import synthesise_polish  # noqa: E402
from server.ensemble_config_service import EnsembleConfigService  # noqa: E402
from server.routers import ensemble as ensemble_router  # noqa: E402


class FakeStreamAPI:
    def __init__(self):
        self.calls = []

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model, "kwargs": kwargs})
        return "## NPCs\n\n**Daz**\n- Current state: active\n"


class FakeRunSingleBatch:
    def __init__(self):
        self.calls = []

    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens})
        return "## NPCs\n\n**Daz**\n- Current state: active (batched)\n"


class FailingRunSingleBatch:
    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        raise RuntimeError("batch item 'single' did not succeed: status=errored error=boom")


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(synthesise_polish, "stream_api", fake)
    monkeypatch.setattr(synthesise_polish, "client_from_args", lambda *a, **kw: None)
    return fake


@pytest.fixture
def fake_run_single_batch(monkeypatch):
    fake = FakeRunSingleBatch()
    monkeypatch.setattr(synthesise_polish, "run_single_batch", fake)
    monkeypatch.setattr(synthesise_polish, "client_from_args", lambda *a, **kw: None)
    return fake


def _write_merged(tmp_path: Path) -> Path:
    p = tmp_path / "merged.json"
    p.write_text(json.dumps([
        {"type": "npc", "subject": "Daz", "fact": "Daz acts.", "source_quote": ""},
    ]), encoding="utf-8")
    return p


def test_default_path_uses_stream_api_unchanged(monkeypatch, fake_stream_api, tmp_path):
    merged = _write_merged(tmp_path)
    output = tmp_path / "polished.md"
    monkeypatch.setattr(sys, "argv", [
        "synthesise_polish.py", str(merged), "--output", str(output),
    ])
    synthesise_polish.main()

    assert len(fake_stream_api.calls) == 1
    assert fake_stream_api.calls[0]["kwargs"].get("max_tokens") == 16000
    assert output.exists()


def test_batch_flag_routes_through_run_single_batch(monkeypatch, fake_run_single_batch, tmp_path):
    merged = _write_merged(tmp_path)
    output = tmp_path / "polished.md"
    monkeypatch.setattr(sys, "argv", [
        "synthesise_polish.py", str(merged), "--output", str(output), "--batch",
    ])
    synthesise_polish.main()

    assert len(fake_run_single_batch.calls) == 1
    assert fake_run_single_batch.calls[0]["max_tokens"] == 16000
    assert "(batched)" in output.read_text(encoding="utf-8")


def test_batch_flag_honors_custom_max_tokens(monkeypatch, fake_run_single_batch, tmp_path):
    merged = _write_merged(tmp_path)
    output = tmp_path / "polished.md"
    monkeypatch.setattr(sys, "argv", [
        "synthesise_polish.py", str(merged), "--output", str(output),
        "--batch", "--max-tokens", "24000",
    ])
    synthesise_polish.main()

    assert fake_run_single_batch.calls[0]["max_tokens"] == 24000


def test_batch_failure_exits_nonzero(monkeypatch, tmp_path, capsys):
    merged = _write_merged(tmp_path)
    output = tmp_path / "polished.md"
    monkeypatch.setattr(synthesise_polish, "run_single_batch", FailingRunSingleBatch())
    monkeypatch.setattr(synthesise_polish, "client_from_args", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", [
        "synthesise_polish.py", str(merged), "--output", str(output), "--batch",
    ])

    with pytest.raises(SystemExit) as exc_info:
        synthesise_polish.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Error: batch item failed:" in err
    assert not output.exists()


def test_codex_polish_keeps_merged_checkpoint_as_input_only(
    monkeypatch, fake_stream_api, tmp_path
):
    """Codex synthesis writes a review artifact without mutating merged.json."""
    merged = _write_merged(tmp_path)
    original = merged.read_bytes()
    output = tmp_path / "polished.md"
    monkeypatch.setattr(sys, "argv", [
        "synthesise_polish.py", str(merged), "--output", str(output),
        "--backend", "codex-cli", "--model", "gpt-5-codex",
    ])
    synthesise_polish.main()

    assert merged.read_bytes() == original
    assert output.exists()
    assert "# NPCs" in output.read_text(encoding="utf-8")
    assert fake_stream_api.calls[0]["model"] == "gpt-5-codex"


def _request(path: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [],
    })


def _call_endpoint(endpoint, *args, **kwargs):
    result = endpoint(*args, **kwargs)
    return asyncio.run(result) if inspect.isawaitable(result) else result


def test_synthesise_polish_route_preserves_reviewed_input_output_and_codex_model(
    monkeypatch, tmp_path
):
    """The explicit route renders a selected merged checkpoint only.

    The model omission is intentional for Codex: the subscription CLI owns
    its default.  A typed model is forwarded verbatim, and neither invocation
    gets an approval/next-stage flag that could cross the human checkpoint.
    """
    monkeypatch.chdir(tmp_path)
    merged = tmp_path / "merged.json"
    merged.write_text("[]", encoding="utf-8")
    captured = {}

    def capture(stage, cmd, *args, **kwargs):
        captured["stage"] = stage
        captured["cmd"] = cmd
        return PlainTextResponse("captured")

    def backend_args(backend, model, request, **kwargs):
        args = ["--backend", backend]
        if model:
            args += ["--model", model]
        return args

    monkeypatch.setattr(ensemble_router, "_run_locked", capture)
    monkeypatch.setattr(ensemble_router, "_backend_args", backend_args)
    endpoint = next(
        route.endpoint
        for route in ensemble_router.router.routes
        if getattr(route, "path", "") == "/run/synthesise-polish"
    )
    service = EnsembleConfigService(tmp_path / "config")

    output = tmp_path / "review" / "polished.md"
    response = _call_endpoint(
        endpoint,
        _request("/run/synthesise-polish"),
        merged=str(merged),
        output=str(output),
        backend="codex-cli",
        model=None,
        service=service,
    )
    assert response.status_code == 200
    cmd = captured["cmd"]
    assert "synthesise_polish" in cmd[0]
    assert str(merged) in cmd
    assert cmd[cmd.index("--output") + 1] == str(output)
    assert cmd[cmd.index("--backend") + 1] == "codex-cli"
    assert "--model" not in cmd
    assert "--approve" not in cmd

    explicit_output = tmp_path / "review" / "polished-explicit.md"
    _call_endpoint(
        endpoint,
        _request("/run/synthesise-polish"),
        merged=str(merged),
        output=str(explicit_output),
        backend="codex-cli",
        model="gpt-5-codex",
        service=service,
    )
    explicit_cmd = captured["cmd"]
    assert explicit_cmd[explicit_cmd.index("--model") + 1] == "gpt-5-codex"
