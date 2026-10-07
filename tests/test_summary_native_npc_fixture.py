"""The 032 fixture builds, and the helpers in conftest_npc work (T004/T005)."""

from __future__ import annotations

import json

from tests.conftest_npc import npc_campaign, run_cli, sha_tree


def test_fixture_builds_a_corpus(tmp_path):
    root = npc_campaign(tmp_path)
    rd = root / "docs" / "summary_native" / "ch002-006"
    manifest = json.loads((rd / "manifest.json").read_text())
    assert manifest["kind"] == "summary_native"
    stems = {p.stem for p in (rd / "dossiers").glob("*.md")} if (rd / "dossiers").is_dir() else set()
    assert {"npc_jimjar", "npc_spider", "npc_kaelis", "npc_quaggoth", "npc_mantol"} <= stems


def test_fixture_has_no_blocking_findings(tmp_path):
    root = npc_campaign(tmp_path)
    report = json.loads((root / "docs/summary_native/ch002-006/validation_report.json").read_text())
    assert report["blocking_count"] == 0


def test_run_cli_returns_code_and_streams(tmp_path):
    root = npc_campaign(tmp_path)
    rc, out, err = run_cli(
        ["validate", "--config", str(root / "config/config.yaml"),
         "--summaries-dir", str(root / "docs/summaries"), "--since", "2", "--until", "6"]
    )
    assert rc == 0 and "# Validation report" in out and err == ""


def test_sha_tree_is_stable_and_sensitive(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_text("one")
    first = sha_tree(tmp_path / "a")
    assert first == sha_tree(tmp_path / "a") and list(first) == ["x.txt"]
    (tmp_path / "a" / "x.txt").write_text("two")
    assert sha_tree(tmp_path / "a") != first
