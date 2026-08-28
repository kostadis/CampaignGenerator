"""Tests for check_consistency.py's --batch routing (spec 004).

check_consistency.py is a single-call CLI (contract's "Single-call CLIs"
group): with --batch, its one consistency-check stream_api call must route
through run_single_batch instead — same system/user/model/max_tokens (it
already computes an explicit max_tokens from CG_CONSISTENCY_MAX_TOKENS, so
that same value must be threaded through unchanged). A RuntimeError from
run_single_batch (item did not succeed) must exit non-zero. The default
(no --batch) path is unaffected (FR-011).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from session_doc import check_consistency  # noqa: E402


def _make_config(tmp_path: Path) -> Path:
    """Config with no documents — forces reliance on --context only, so the
    test doesn't depend on the real repo's docs/ tree existing."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("documents: []\n", encoding="utf-8")
    return config_path


def _make_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    doc_path = tmp_path / "session-doc.md"
    doc_path.write_text("Some session narration.", encoding="utf-8")
    context_path = tmp_path / "party.md"
    context_path.write_text("Party roster.", encoding="utf-8")
    config_path = _make_config(tmp_path)
    return doc_path, context_path, config_path


def test_check_consistency_batch_routes_through_run_single_batch(tmp_path, monkeypatch):
    doc_path, context_path, config_path = _make_inputs(tmp_path)
    monkeypatch.delenv("CG_CONSISTENCY_MAX_TOKENS", raising=False)

    calls = []

    def fake_run_single_batch(client, *, system, user, model, max_tokens=8192,
                              cache_system=False):
        calls.append({"system": system, "user": user, "model": model,
                      "max_tokens": max_tokens, "cache_system": cache_system})
        return "## Consistency Report\n\nNo issues found."

    def fail_if_called(*a, **kw):
        raise AssertionError("stream_api must not be called when --batch is set")

    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(check_consistency, "run_single_batch", fake_run_single_batch)
    monkeypatch.setattr(check_consistency, "stream_api", fail_if_called)

    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path),
        "--config", str(config_path),
        "--context", str(context_path),
        "--batch",
    ])
    check_consistency.main()

    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 32000  # CG_CONSISTENCY_MAX_TOKENS default
    assert calls[0]["cache_system"] is False


def test_check_consistency_batch_item_failure_exits_nonzero(tmp_path, monkeypatch, capsys):
    doc_path, context_path, config_path = _make_inputs(tmp_path)
    monkeypatch.delenv("CG_CONSISTENCY_MAX_TOKENS", raising=False)

    def fake_run_single_batch(client, **kw):
        raise RuntimeError(
            "batch item 'single' did not succeed: status=errored error=boom"
        )

    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(check_consistency, "run_single_batch", fake_run_single_batch)

    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path),
        "--config", str(config_path),
        "--context", str(context_path),
        "--batch",
    ])
    with pytest.raises(SystemExit) as exc_info:
        check_consistency.main()
    assert exc_info.value.code != 0
    assert "Error: batch item failed" in capsys.readouterr().err


def test_check_consistency_rejects_codex_batch_before_client(tmp_path, monkeypatch):
    doc_path, context_path, config_path = _make_inputs(tmp_path)
    monkeypatch.setattr(
        check_consistency,
        "make_client",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("client constructed")),
        raising=False,
    )
    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path),
        "--config", str(config_path),
        "--context", str(context_path),
        "--backend", "codex-cli",
        "--batch",
    ])
    with pytest.raises(SystemExit) as excinfo:
        check_consistency.main()
    assert "backend 'codex-cli' has no batch support" in str(excinfo.value)


def test_check_consistency_default_path_uses_stream_api(tmp_path, monkeypatch):
    """FR-011 regression guard: default (no --batch) path must be unaffected
    by the batch wiring."""
    doc_path, context_path, config_path = _make_inputs(tmp_path)
    monkeypatch.delenv("CG_CONSISTENCY_MAX_TOKENS", raising=False)

    calls = []

    def fake_stream_api(client, system, user, model, **kwargs):
        calls.append({"system": system, "user": user, "model": model, **kwargs})
        return "## Consistency Report\n\nNo issues found."

    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(check_consistency, "stream_api", fake_stream_api)

    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path),
        "--config", str(config_path),
        "--context", str(context_path),
    ])
    check_consistency.main()

    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 32000
    assert calls[0].get("silent") is True


def test_codex_consistency_keeps_report_path_and_issue_count(tmp_path, monkeypatch, capsys):
    """Subscription output uses the normal report artifact and presentation."""
    doc_path, context_path, config_path = _make_inputs(tmp_path)
    report_path = tmp_path / "checks" / "codex-consistency.md"
    report_path.parent.mkdir()
    calls = []

    def fake_stream_api(client, system, user, model, **kwargs):
        calls.append((model, system, user))
        return (
            "## Consistency Report\n\n"
            "**Location**: scene 1\n- **Issue**: mismatch\n\n"
            "**Location**: scene 2\n- **Issue**: missing event\n"
        )

    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(check_consistency, "stream_api", fake_stream_api)
    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path), "--config", str(config_path),
        "--context", str(context_path), "--backend", "codex-cli",
        "--model", "gpt-5-codex", "--out", str(report_path),
    ])

    check_consistency.main()

    assert calls and calls[0][0] == "gpt-5-codex"
    assert report_path.read_text(encoding="utf-8").count("**Location**") == 2
    assert "Found 2 potential issue(s):" in capsys.readouterr().out
