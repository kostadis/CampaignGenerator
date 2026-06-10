"""Integration tests for the split ensemble pipeline (extract -> merge -> driver).

These run the scripts as subprocesses but never hit an LLM or embed server: each
pass's output is pre-seeded in the workdir so generation reuses it from cache,
and the subject merge needs no network. They exercise the manifest handoff and
the driver wiring end to end.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
EXTRACT = ROOT / "ensemble_extract.py"
MERGE = ROOT / "ensemble_merge.py"
DRIVER = ROOT / "ensemble.py"


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


def _run(*argv) -> subprocess.CompletedProcess:
    return subprocess.run([PY, *map(str, argv)], capture_output=True, text=True)


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
