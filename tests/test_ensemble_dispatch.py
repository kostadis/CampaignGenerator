"""Tests for ensemble_extract.py's speculative-dispatch selector.

The concurrent dispatcher itself spawns subprocesses and is exercised in
integration runs, but the eligibility logic — which in-flight unit (if any) a
free endpoint should speculatively re-run — is a pure function and is where the
straggler-mitigation correctness lives. These cover it directly.
"""
import sys
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipelines.ensemble import ensemble_extract as ee  # noqa: E402

MIN_AGE = 60.0
MAX_COPIES = 2


def _inf(start, copies=1):
    return {"start": start, "copies": copies, "procs": set(), "unit": None}


def test_empty_inflight_returns_none():
    assert ee.pick_straggler({}, set(), now=1000.0,
                             min_age=MIN_AGE, max_copies=MAX_COPIES) is None


def test_fresh_units_not_duplicated():
    # running 30s, below the 60s floor → leave it alone
    inflight = {"temporal#1": _inf(start=970.0)}
    assert ee.pick_straggler(inflight, set(), now=1000.0,
                             min_age=MIN_AGE, max_copies=MAX_COPIES) is None


def test_aged_straggler_is_picked():
    inflight = {"temporal#1": _inf(start=900.0)}  # 100s old
    assert ee.pick_straggler(inflight, set(), now=1000.0,
                             min_age=MIN_AGE, max_copies=MAX_COPIES) == "temporal#1"


def test_oldest_eligible_wins():
    inflight = {
        "temporal#1": _inf(start=900.0),       # 100s
        "interiority#2": _inf(start=800.0),    # 200s — the real tail
        "small#1": _inf(start=985.0),          # 15s, too fresh
    }
    assert ee.pick_straggler(inflight, set(), now=1000.0,
                             min_age=MIN_AGE, max_copies=MAX_COPIES) == "interiority#2"


def test_already_at_max_copies_skipped():
    # the oldest is already duplicated; fall through to the next eligible one
    inflight = {
        "interiority#2": _inf(start=800.0, copies=MAX_COPIES),
        "temporal#1": _inf(start=900.0, copies=1),
    }
    assert ee.pick_straggler(inflight, set(), now=1000.0,
                             min_age=MIN_AGE, max_copies=MAX_COPIES) == "temporal#1"


def test_settled_key_skipped():
    # a still-running copy of an already-won unit is never re-duplicated
    inflight = {"temporal#1": _inf(start=800.0)}
    assert ee.pick_straggler(inflight, {"temporal#1"}, now=1000.0,
                             min_age=MIN_AGE, max_copies=MAX_COPIES) is None



# ── build_extract_cmd ────────────────────────────────────────────────────────

PASS = {"name": "small", "chunk_size": 6000, "agent": "extract_facts"}


# ── Codex forwarding and dispatcher boundaries (016 parity) ─────────────────

def test_extract_child_command_forwards_codex_and_explicit_model(tmp_path):
    cmd = ee.build_extract_cmd(
        tmp_path / "doc.txt", PASS, tmp_path / "small.json",
        tmp_path / "cache", endpoint=None, model="gpt-5-codex",
        backend="codex-cli",
    )
    assert cmd[cmd.index("--backend") + 1] == "codex-cli"
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"
    assert cmd[0] == sys.executable
    assert "codex" not in cmd[0].lower()


def test_extract_child_command_omits_inherited_codex_model(tmp_path):
    cmd = ee.build_extract_cmd(
        tmp_path / "doc.txt", PASS, tmp_path / "small.json",
        tmp_path / "cache", endpoint=None, model=None, backend="codex-cli",
    )
    assert cmd[cmd.index("--backend") + 1] == "codex-cli"
    assert "--model" not in cmd


def test_codex_extract_dispatcher_dry_run_starts_no_validation_child(
    tmp_path, monkeypatch, capsys
):
    """ensemble_extract only dispatches generation work; dry-run starts none."""
    document = tmp_path / "chapter.md"
    document.write_text("chapter\n")
    monkeypatch.setattr(
        ee.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("dispatcher started a child"),
    )
    monkeypatch.setattr(sys, "argv", [
        "ensemble_extract.py", str(document), "--workdir", str(tmp_path / "run"),
        "--dry-run", "--backend", "codex-cli",
    ])
    ee.main()
    assert "Backend:  codex-cli" in capsys.readouterr().out


def test_build_extract_cmd_forwards_chunk_parallel(tmp_path):
    cmd = ee.build_extract_cmd(tmp_path / "doc.txt", PASS,
                               tmp_path / "small.json", tmp_path / "cache",
                               endpoint="http://spark:8001/v1",
                               model="m", backend="dgx", chunk_parallel=4)
    assert cmd[:2] == [sys.executable, str(ee.EXTRACT_SCRIPT)]
    assert cmd[2] == str(tmp_path / "doc.txt")
    i = cmd.index("--parallel")
    assert cmd[i + 1] == "4"
    assert cmd[cmd.index("--backend") + 1] == "dgx"
    assert cmd[cmd.index("--endpoint") + 1] == "http://spark:8001/v1"
    assert cmd[cmd.index("--model") + 1] == "m"
    assert cmd[cmd.index("--chunk-size") + 1] == "6000"
    assert cmd[cmd.index("--agent") + 1] == "extract_facts"


def test_build_extract_cmd_defaults_sequential(tmp_path):
    cmd = ee.build_extract_cmd(tmp_path / "doc.txt", PASS,
                               tmp_path / "small.json", tmp_path / "cache",
                               endpoint=None, model=None, backend="dgx")
    assert cmd[cmd.index("--parallel") + 1] == "1"
    assert cmd[cmd.index("--backend") + 1] == "dgx"
    assert "--endpoint" not in cmd
    assert "--model" not in cmd


# ── --scene-chunks plumbing (issue #202) ─────────────────────────────────────


def test_build_extract_cmd_omits_scene_chunks_by_default(tmp_path):
    """OPT-IN: a pass_spec with no 'structural' key (every built-in PASS,
    absent --scene-chunks) must not forward the flag at all."""
    cmd = ee.build_extract_cmd(tmp_path / "doc.txt", PASS,
                               tmp_path / "small.json", tmp_path / "cache",
                               endpoint=None, model=None, backend="dgx")
    assert "--scene-chunks" not in cmd


def test_build_extract_cmd_forwards_scene_chunks_when_structural(tmp_path):
    pass_spec = {**PASS, "structural": True}
    cmd = ee.build_extract_cmd(tmp_path / "doc.txt", pass_spec,
                               tmp_path / "small.json", tmp_path / "cache",
                               endpoint=None, model=None, backend="dgx")
    assert "--scene-chunks" in cmd
