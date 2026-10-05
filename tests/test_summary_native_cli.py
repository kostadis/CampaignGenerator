"""CLI tests for summary_native validate/build (T012): exit codes and writes."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pipelines.summary_native.cli import main

FIX = Path(__file__).parent / "fixtures" / "summary_native"


@pytest.fixture
def camp(tmp_path, monkeypatch):
    root = tmp_path / "camp"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("paths: {}\n")
    monkeypatch.chdir(root)
    return root


def _corpus(camp, name="clean", dest="summaries"):
    shutil.copytree(FIX / name, camp / dest)
    return camp / dest


def _tree(root: Path):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_validate_writes_only_report_in_range_dir(camp, capsys):
    _corpus(camp)
    rc = main(["validate", "--summaries-dir", "summaries", "--since", "2", "--until", "5"])
    assert rc == 0
    rd = camp / "docs" / "summary_native" / "ch002-005"
    assert _tree(rd) == ["validation_report.json", "validation_report.md"]
    assert _tree(camp / "docs") == [
        "summary_native/ch002-005/validation_report.json",
        "summary_native/ch002-005/validation_report.md",
    ]
    out = capsys.readouterr().out
    assert "# Validation report" in out and "range-gap" in out
    assert json.loads((rd / "validation_report.json").read_text())["blocking_count"] == 0


def test_validate_exit_1_on_blocking(camp, capsys):
    _corpus(camp, "multi_error")
    assert main(["validate", "--summaries-dir", "summaries"]) == 1
    assert (camp / "docs/summary_native/ch010-012/validation_report.md").exists()


def test_unset_range_uses_first_and_last(camp):
    _corpus(camp)
    assert main(["validate", "--summaries-dir", "summaries"]) == 0
    assert (camp / "docs/summary_native/ch002-005").is_dir()


def test_refusals_exit_2_and_write_nothing(camp, capsys):
    _corpus(camp)
    (camp / "empty").mkdir()
    assert main(["validate", "--summaries-dir", "empty"]) == 2
    assert main(["validate", "--summaries-dir", "missing"]) == 2
    assert main(["validate", "--summaries-dir", "summaries", "--since", "1"]) == 2
    assert "2, 3, 5" in capsys.readouterr().err
    assert main(["validate", "--summaries-dir", "summaries", "--since", "5", "--until", "2"]) == 2
    assert not (camp / "docs").exists()


def test_no_summaries_dir_is_error(camp, capsys):
    assert main(["validate"]) == 2
    assert "no summaries directory" in capsys.readouterr().err


def test_summaries_dir_from_grounding_yaml(camp):
    _corpus(camp)
    (camp / "config" / "grounding.yaml").write_text(
        "summary_native:\n  summaries_dir: summaries\n  out_root: out/sn\n  dup_threshold: 0.9\n"
    )
    assert main(["build"]) == 0
    assert (camp / "out/sn/ch002-005/manifest.json").exists()


def test_ensemble_input_refused(camp):
    d = camp / "docs" / "ensemble" / "s"
    d.parent.mkdir(parents=True)
    shutil.copytree(FIX / "clean", d)
    assert main(["validate", "--summaries-dir", "docs/ensemble/s"]) == 2


def test_build_ok_then_exists_needs_force(camp):
    _corpus(camp)
    base = ["build", "--summaries-dir", "summaries"]
    assert main(base) == 0
    rd = camp / "docs/summary_native/ch002-005"
    assert {"manifest.json", "chronology.md", "memorable_moments.md", "validation_report.md"} <= set(
        _tree(rd)
    )
    assert main(base) == 2
    assert main([*base, "--force"]) == 0


def test_validate_then_build_same_range_dir(camp):
    _corpus(camp)
    assert main(["validate", "--summaries-dir", "summaries"]) == 0
    assert main(["build", "--summaries-dir", "summaries"]) == 0


def test_build_blocked_writes_report_only(camp):
    _corpus(camp, "multi_error")
    assert main(["build", "--summaries-dir", "summaries"]) == 1
    assert _tree(camp / "docs/summary_native/ch010-012") == [
        "validation_report.json",
        "validation_report.md",
    ]


def test_build_refuses_ensemble_out_root(camp):
    _corpus(camp)
    rd = camp / "docs/summary_native/ch002-005"
    rd.mkdir(parents=True)
    (rd / "merged.json").write_text("{}")
    assert main(["build", "--summaries-dir", "summaries"]) == 2
    assert main(["validate", "--summaries-dir", "summaries"]) == 2


def test_manifest_records_registry_and_canon_digests(camp):
    _corpus(camp)
    (camp / "docs").mkdir()
    (camp / "docs" / "entity_registry.yaml").write_text("version: 1\nentities: []\n")
    (camp / "docs" / "summary_native").mkdir()
    (camp / "docs" / "summary_native" / "canon.yaml").write_text("not_duplicates: []\n")
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    m = json.loads((camp / "docs/summary_native/ch002-005/manifest.json").read_text())
    assert len(m["canon"]["registry_sha256"]) == 64 and len(m["canon"]["canon_sha256"]) == 64


def test_synth_and_compare_are_stubs(camp, capsys):
    assert main(["synth"]) == 2
    assert main(["compare"]) == 2
    assert "not implemented yet" in capsys.readouterr().err


def test_unreadable_file_reported_with_other_findings_exit_1(camp, capsys):
    d = camp / "summaries"
    d.mkdir()
    (d / "002-bad.md").write_bytes(b"\xff\xfe\x00bad")
    (d / "003-m.md").write_text("# Chapter 4\n\n## Scenes\n\n### 003.01 X\nS.\n")
    assert main(["validate", "--summaries-dir", "summaries"]) == 1
    md = (camp / "docs/summary_native/ch002-003/validation_report.md").read_text()
    assert "unreadable-file" in md and "title-chapter-mismatch" in md
