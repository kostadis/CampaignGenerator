"""Integration tests for the split ensemble pipeline (extract -> merge -> driver).

These run the scripts as subprocesses but never hit an LLM or embed server: each
pass's output is pre-seeded in the workdir so generation reuses it from cache,
and the subject merge needs no network. They exercise the manifest handoff and
the driver wiring end to end.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from pipelines.ensemble import ensemble_extract as extract_mod

ROOT = Path(__file__).resolve().parent.parent
ENSEMBLE_DIR = ROOT / "pipelines" / "ensemble"
PY = sys.executable
EXTRACT = ENSEMBLE_DIR / "ensemble_extract.py"
MERGE = ENSEMBLE_DIR / "ensemble_merge.py"
DRIVER = ENSEMBLE_DIR / "ensemble.py"


def _seed(workdir: Path) -> Path:
    """Create a tiny 2-pass plan + document + pre-seeded per-pass outputs."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "doc.txt").write_text("Some session text.\n", encoding="utf-8")
    (workdir / "plan.yaml").write_text(
        "document: doc.txt\n"
        "passes:\n"
        "  - {name: a, agent: extract_facts, chunk_size: 6000}\n"
        "  - {name: b, agent: extract_facts, chunk_size: 6000}\n",
        encoding="utf-8")
    # Pre-seed per-pass facts so run_unit hits the [cached] path (no spawn).
    (workdir / "a.json").write_text(json.dumps(
        [{"type": "npc", "subject": "Daz", "fact": "Daz is brave.",
          "source_quote": "q1"}]), encoding="utf-8")
    (workdir / "b.json").write_text(json.dumps([
        {"type": "npc", "subject": "Daz", "fact": "Daz is brave.",
         "source_quote": "q1-longer"},
        {"type": "event", "subject": "Fight", "fact": "A fight happened.",
         "source_quote": ""},
    ]), encoding="utf-8")
    return workdir


def _subprocess_env() -> dict:
    """Env that makes a spawned CLI import THIS checkout's packages.

    Without it the child resolves `campaignlib` through the editable-install
    `.pth`, which hardcodes the main checkout — so in a worktree these tests
    silently exercise main's code, and any branch that adds a campaignlib
    symbol fails here with a confusing ImportError naming a path outside the
    worktree. Prepending the repo root is a no-op when the two are the same
    directory (see reference_worktree_editable_install_shadowing).
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{existing}" if existing else str(ROOT)
    return env


def _run(*argv) -> subprocess.CompletedProcess:
    return subprocess.run([PY, *map(str, argv)], capture_output=True, text=True,
                          env=_subprocess_env())


def test_extract_writes_manifest_and_no_merged(tmp_path):
    w = _seed(tmp_path / "run")
    r = _run(EXTRACT, "--workdir", w, "--plan", w / "plan.yaml")
    assert r.returncode == 0, r.stderr

    manifest = json.loads((w / "manifest.json").read_text())
    assert manifest["samples"] == 1
    assert [p["name"] for p in manifest["passes"]] == ["a", "b"]
    files = {p["name"]: p["outputs"][0]["file"] for p in manifest["passes"]}
    assert files == {"a": "a.json", "b": "b.json"}
    assert manifest["passes"][1]["document"].endswith("doc.txt")
    # generation does NOT merge
    assert not (w / "merged.json").exists()


def test_extract_manifest_records_structural_false_by_default(tmp_path):
    w = _seed(tmp_path / "run")
    r = _run(EXTRACT, "--workdir", w, "--plan", w / "plan.yaml")
    assert r.returncode == 0, r.stderr
    manifest = json.loads((w / "manifest.json").read_text())
    assert [p["structural"] for p in manifest["passes"]] == [False, False]


def test_extract_scene_chunks_flag_records_structural_true(tmp_path):
    w = _seed(tmp_path / "run")
    r = _run(EXTRACT, "--workdir", w, "--plan", w / "plan.yaml", "--scene-chunks")
    assert r.returncode == 0, r.stderr
    manifest = json.loads((w / "manifest.json").read_text())
    assert [p["structural"] for p in manifest["passes"]] == [True, True]


def test_extract_plan_can_set_structural_per_pass(tmp_path):
    """A --plan pass can opt into structural chunking on its own, without the
    blanket --scene-chunks flag, and without affecting its sibling pass."""
    w = tmp_path / "run"
    w.mkdir(parents=True, exist_ok=True)
    (w / "doc.txt").write_text("Some session text.\n", encoding="utf-8")
    (w / "plan.yaml").write_text(
        "document: doc.txt\n"
        "passes:\n"
        "  - {name: a, agent: extract_facts, chunk_size: 6000, structural: true}\n"
        "  - {name: b, agent: extract_facts, chunk_size: 6000}\n",
        encoding="utf-8")
    (w / "a.json").write_text(json.dumps([]))
    (w / "b.json").write_text(json.dumps([]))

    r = _run(EXTRACT, "--workdir", w, "--plan", w / "plan.yaml")
    assert r.returncode == 0, r.stderr
    manifest = json.loads((w / "manifest.json").read_text())
    by_name = {p["name"]: p["structural"] for p in manifest["passes"]}
    assert by_name == {"a": True, "b": False}


def test_extract_dry_run_shows_scene_chunks_passes(tmp_path):
    w = _seed(tmp_path / "run")
    r = _run(EXTRACT, "--workdir", w, "--plan", w / "plan.yaml",
             "--dry-run", "--scene-chunks")
    assert r.returncode == 0, r.stderr
    assert "Scene-chunks: a, b" in r.stdout


def test_extract_dry_run_writes_nothing(tmp_path):
    w = _seed(tmp_path / "run")
    r = _run(EXTRACT, "--workdir", w, "--plan", w / "plan.yaml", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "dry-run" in r.stdout
    assert not (w / "manifest.json").exists()


def test_extract_dry_run_shows_chunk_parallel(tmp_path):
    w = _seed(tmp_path / "run")
    r = _run(EXTRACT, "--workdir", w, "--plan", w / "plan.yaml",
             "--dry-run", "--chunk-parallel", "3")
    assert r.returncode == 0, r.stderr
    assert "Chunk-parallel: 3 per endpoint" in r.stdout


def test_driver_forwards_chunk_parallel(tmp_path):
    # the driver echoes the generation command (ensemble.py prints it before
    # running); --dry-run keeps this server-free
    w = _seed(tmp_path / "run")
    r = _run(DRIVER, "--workdir", w, "--plan", w / "plan.yaml",
             "--dry-run", "--chunk-parallel", "3")
    assert r.returncode == 0, r.stderr
    assert "--chunk-parallel 3" in r.stdout


def test_merge_subject_after_extract(tmp_path):
    w = _seed(tmp_path / "run")
    assert _run(EXTRACT, "--workdir", w, "--plan", w / "plan.yaml").returncode == 0
    r = _run(MERGE, "--workdir", w, "--method", "subject")
    assert r.returncode == 0, r.stderr

    merged = json.loads((w / "merged.json").read_text())
    by = {(f["type"], f["subject"]): f for f in merged}
    assert len(merged) == 2

    daz = by[("npc", "Daz")]
    assert daz["source_quote"] == "q1-longer"
    assert daz["passes"] == ["a", "b"]        # provenance collapsed to lens names
    assert daz["n_samples"] == 2
    assert by[("event", "Fight")]["passes"] == ["b"]


def test_merge_without_manifest_fails(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run(MERGE, "--workdir", empty, "--method", "subject")
    assert r.returncode != 0
    assert "manifest" in (r.stderr + r.stdout).lower()


def test_driver_runs_both_phases(tmp_path):
    w = _seed(tmp_path / "run")
    r = _run(DRIVER, "--workdir", w, "--plan", w / "plan.yaml", "--method", "subject")
    assert r.returncode == 0, r.stderr
    assert (w / "manifest.json").exists()
    merged = json.loads((w / "merged.json").read_text())
    assert len(merged) == 2


class _FakeExtractProcess:
    """Small Popen stand-in for mixed Codex fan-out unit results."""

    def __init__(self, cmd, *, payload, returncode, stderr):
        self.cmd = cmd
        self.returncode = returncode
        self._stderr = stderr
        if returncode == 0:
            output = Path(cmd[cmd.index("--output") + 1])
            output.write_text(json.dumps(payload), encoding="utf-8")

    def communicate(self, timeout=None):
        return "", self._stderr


def test_codex_fanout_preserves_mixed_unit_results(monkeypatch, tmp_path):
    """A successful Codex unit is retained while a sibling failure is explicit."""
    responses = iter([
        ([{"type": "npc", "subject": "Daz", "fact": "survived"}], 0, ""),
        (None, 23, "subscription child failed"),
    ])
    commands = []

    def fake_popen(cmd, **kwargs):
        commands.append(cmd)
        payload, returncode, stderr = next(responses)
        return _FakeExtractProcess(
            cmd, payload=payload, returncode=returncode, stderr=stderr
        )

    monkeypatch.setattr(extract_mod.subprocess, "Popen", fake_popen)
    input_path = tmp_path / "chapter.md"
    input_path.write_text("chapter", encoding="utf-8")
    pass_spec = {"name": "small", "chunk_size": 6000, "agent": "extract_facts"}

    ok_key, facts, error, timed_out = extract_mod.run_unit(
        input_path, pass_spec, 1, 1, tmp_path / "run",
        "codex://one", "gpt-5-codex", "codex-cli",
    )
    failed_key, failed_facts, failed_error, failed_timeout = extract_mod.run_unit(
        input_path, {**pass_spec, "name": "large"}, 1, 1, tmp_path / "run",
        "codex://two", "gpt-5-codex", "codex-cli",
    )

    assert (ok_key, facts, error, timed_out) == (
        "small#1", [{"type": "npc", "subject": "Daz", "fact": "survived"}],
        None, False,
    )
    assert failed_key == "large#1"
    assert failed_facts is None
    assert "exit 23" in failed_error
    assert failed_timeout is False
    assert all(cmd[cmd.index("--backend") + 1] == "codex-cli" for cmd in commands)
    assert all(cmd[cmd.index("--model") + 1] == "gpt-5-codex" for cmd in commands)
    assert "codex://one" in commands[0] and "codex://two" in commands[1]
    assert (tmp_path / "run" / "small.json").exists()
    assert not (tmp_path / "run" / "large.json").exists()


class _TimeoutExtractProcess:
    """Popen stand-in proving fan-out kills a timed-out local child."""

    def __init__(self, cmd):
        self.cmd = cmd
        self.returncode = None
        self.killed = False
        self.communicate_timeouts = []

    def communicate(self, timeout=None):
        self.communicate_timeouts.append(timeout)
        if not self.killed:
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        self.returncode = -9
        return "", ""

    def kill(self):
        self.killed = True


def test_codex_fanout_timeout_forwards_limit_kills_child_and_keeps_no_artifact(
    monkeypatch, tmp_path
):
    children = []

    def fake_popen(cmd, **kwargs):
        child = _TimeoutExtractProcess(cmd)
        children.append(child)
        return child

    monkeypatch.setattr(extract_mod.subprocess, "Popen", fake_popen)
    input_path = tmp_path / "chapter.md"
    input_path.write_text("chapter", encoding="utf-8")
    workdir = tmp_path / "run"
    key, facts, error, timed_out = extract_mod.run_unit(
        input_path,
        {"name": "slow", "chunk_size": 6000, "agent": "extract_facts"},
        1,
        1,
        workdir,
        "codex://slow",
        "gpt-5-codex",
        "codex-cli",
        timeout=2.5,
    )

    assert key == "slow#1"
    assert facts is None
    assert timed_out is True
    assert "exceeded 2s" in error
    assert children[0].killed is True
    assert children[0].communicate_timeouts == [2.5, 30]
    assert not (workdir / "slow.json").exists()


def test_codex_extract_resume_then_merge_preserves_stage_boundary(tmp_path):
    """Codex-selected extraction resumes cached units; merge remains separate."""
    workdir = _seed(tmp_path / "run")
    args = [
        EXTRACT, "--workdir", workdir, "--plan", workdir / "plan.yaml",
        "--backend", "codex-cli", "--model", "gpt-5-codex",
    ]
    first = _run(*args)
    assert first.returncode == 0, first.stderr
    assert not (workdir / "merged.json").exists()

    second = _run(*args)
    assert second.returncode == 0, second.stderr
    assert "[cached]" in second.stdout
    assert not (workdir / "merged.json").exists()

    merged = _run(MERGE, "--workdir", workdir, "--method", "subject")
    assert merged.returncode == 0, merged.stderr
    assert (workdir / "merged.json").exists()
