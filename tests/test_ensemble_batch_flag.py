"""T022 — ensemble.py forwards --batch to extract_facts; polish.py's notice.

ensemble.py is a subprocess orchestrator: the forwarding test monkeypatches
subprocess.run and uses --dry-run so main() returns after the generation
phase. polish.py accepts --batch for vocabulary uniformity but its agentic
tool-use loop (multi-turn messages + tools) has no Message Batches request
shape — the notice must be loud, once, and only under --batch.
"""
import sys
import pytest
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipelines.ensemble import ensemble  # noqa: E402
from pipelines.ensemble import ensemble_batch  # noqa: E402
from pipelines.ensemble import polish  # noqa: E402


def _run_ensemble(monkeypatch, tmp_path, extra_args):
    captured = []

    def fake_run(cmd, **kwargs):
        captured.append([str(c) for c in cmd])
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(ensemble.subprocess, "run", fake_run)
    doc = tmp_path / "session.md"
    doc.write_text("chapter text\n")
    argv = ["ensemble.py", str(doc), "--workdir", str(tmp_path), "--dry-run",
            *extra_args]
    monkeypatch.setattr(sys, "argv", argv)
    ensemble.main()
    return captured


def test_ensemble_forwards_batch_flag(monkeypatch, tmp_path):
    # Provider Message Batches remain valid for Anthropic; the dispatcher
    # rejects this flag for its default DGX backend (and for Codex below).
    captured = _run_ensemble(
        monkeypatch, tmp_path, ["--backend", "anthropic", "--batch"]
    )
    assert captured, "generation subprocess never launched"
    assert "--batch" in captured[0]


def test_ensemble_omits_batch_by_default(monkeypatch, tmp_path):
    captured = _run_ensemble(monkeypatch, tmp_path, [])
    assert captured
    assert "--batch" not in captured[0]


def test_ensemble_forwards_codex_backend_and_explicit_model(monkeypatch, tmp_path):
    captured = _run_ensemble(
        monkeypatch, tmp_path,
        ["--backend", "codex-cli", "--model", "gpt-5-codex"],
    )
    assert captured
    assert captured[0][captured[0].index("--backend") + 1] == "codex-cli"
    assert captured[0][captured[0].index("--model") + 1] == "gpt-5-codex"
    assert captured[0][0] == sys.executable


def test_ensemble_omits_inherited_codex_model(monkeypatch, tmp_path):
    captured = _run_ensemble(
        monkeypatch, tmp_path, ["--backend", "codex-cli"],
    )
    assert captured
    assert captured[0][captured[0].index("--backend") + 1] == "codex-cli"
    assert "--model" not in captured[0]


def test_ensemble_dispatcher_rejects_codex_batch_before_subprocess(monkeypatch, tmp_path):
    """The provider-message ``--batch`` flag must not reach the generation
    child when this dispatcher resolves to Codex."""
    launched = []

    def fake_run(cmd, **_kwargs):
        launched.append(cmd)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(ensemble.subprocess, "run", fake_run)
    doc = tmp_path / "session.md"
    doc.write_text("chapter text\n")
    monkeypatch.setattr(sys, "argv", [
        "ensemble.py", str(doc), "--workdir", str(tmp_path), "--dry-run",
        "--backend", "codex-cli", "--batch",
    ])
    with pytest.raises(SystemExit, match=r"--batch.*codex-cli"):
        ensemble.main()
    assert launched == []


def test_polish_main_rejects_codex_batch_before_agent_loop(monkeypatch, tmp_path):
    """Polish's real entrypoint rejects Codex batching before its agentic
    loop, client factory, or a child process can start."""
    doc = tmp_path / "assembled.md"
    doc.write_text("# Session\n\n---\n\n## Vuk\nA quiet scene.\n")
    recap = tmp_path / "recap.md"
    recap.write_text("# Recap\n\nA quiet scene.\n")
    party = tmp_path / "party.md"
    party.write_text("## Vuk\n")
    party_config = tmp_path / "party.yaml"
    party_config.write_text("placeholder: true\n")
    voice_dir = tmp_path / "voices"
    voice_dir.mkdir()

    monkeypatch.setattr(polish, "load_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(polish, "load_party_config_arg", lambda *_args: None)
    monkeypatch.setattr(polish, "load_players_config_arg", lambda *_args: None)
    monkeypatch.setattr(
        polish, "require_from_config", lambda *_args, **_kwargs: "- Vuk (player)"
    )
    monkeypatch.setattr(
        polish, "run_agent_loop",
        lambda *_args, **_kwargs: pytest.fail("agent loop started for Codex --batch"),
    )
    from campaignlib.api import client as client_mod
    monkeypatch.setattr(
        client_mod, "make_client",
        lambda *_args, **_kwargs: pytest.fail("client factory ran for Codex --batch"),
    )
    monkeypatch.setattr(sys, "argv", [
        "polish.py", str(doc), "--recap", str(recap), "--voice-dir",
        str(voice_dir), "--party", str(party), "--party-config",
        str(party_config), "--output", str(tmp_path / "out.md"),
        "--changelog", str(tmp_path / "changes.md"), "--backend", "codex-cli",
        "--model", "gpt-5-codex", "--batch",
    ])
    with pytest.raises(SystemExit, match=r"--batch.*codex-cli"):
        polish.main()



# ── Codex forwarding (016 parity) ────────────────────────────────────────────

def _batch_args(tmp_path, *extra):
    chapter = tmp_path / "chapter.md"
    chapter.write_text("chapter\n")
    return ensemble_batch._build_parser().parse_args([
        "--chapters", str(chapter), *extra,
    ])


def test_ensemble_batch_forwards_codex_backend_and_explicit_model(tmp_path):
    args = _batch_args(
        tmp_path, "--backend", "codex-cli", "--model", "gpt-5-codex",
    )
    cmd = ensemble_batch._build_ensemble_cmd(
        tmp_path / "chapter.md", tmp_path / "work", args,
    )
    assert cmd[0] == sys.executable
    assert "codex" not in cmd[0].lower()
    assert cmd[cmd.index("--backend") + 1] == "codex-cli"
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"


def test_ensemble_batch_omits_codex_model_when_not_explicit(tmp_path):
    args = _batch_args(tmp_path, "--backend", "codex-cli")
    cmd = ensemble_batch._build_ensemble_cmd(
        tmp_path / "chapter.md", tmp_path / "work", args,
    )
    assert cmd[cmd.index("--backend") + 1] == "codex-cli"
    assert "--model" not in cmd


def test_ensemble_batch_empty_selection_starts_no_codex_child(
    tmp_path, monkeypatch
):
    """An unmatched explicit chapter set stays empty instead of meaning all."""
    monkeypatch.setattr(
        ensemble_batch.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("dispatcher started a child"),
    )
    monkeypatch.setattr(sys, "argv", [
        "ensemble_batch.py",
        "--chapters", str(tmp_path / "missing-*.md"),
        "--backend", "codex-cli",
    ])
    with pytest.raises(SystemExit) as exc:
        ensemble_batch.main()
    assert exc.value.code == 1


def test_polish_batch_notice_only_under_batch(capsys):
    polish._warn_batch_unsupported(False)
    assert capsys.readouterr().err == ""
    polish._warn_batch_unsupported(True)
    err = capsys.readouterr().err
    assert "--batch has no effect on polish.py" in err
