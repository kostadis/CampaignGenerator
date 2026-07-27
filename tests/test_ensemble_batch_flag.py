"""T022 — ensemble.py forwards --batch to extract_facts; polish.py's notice.

ensemble.py is a subprocess orchestrator: the forwarding test monkeypatches
subprocess.run and uses --dry-run so main() returns after the generation
phase. polish.py accepts --batch for vocabulary uniformity but its agentic
tool-use loop (multi-turn messages + tools) has no Message Batches request
shape — the notice must be loud, once, and only under --batch.
"""
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipelines.ensemble import ensemble  # noqa: E402
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
    captured = _run_ensemble(monkeypatch, tmp_path, ["--batch"])
    assert captured, "generation subprocess never launched"
    assert "--batch" in captured[0]


def test_ensemble_omits_batch_by_default(monkeypatch, tmp_path):
    captured = _run_ensemble(monkeypatch, tmp_path, [])
    assert captured
    assert "--batch" not in captured[0]


def test_polish_batch_notice_only_under_batch(capsys):
    polish._warn_batch_unsupported(False)
    assert capsys.readouterr().err == ""
    polish._warn_batch_unsupported(True)
    err = capsys.readouterr().err
    assert "--batch has no effect on polish.py" in err
