"""T040: per-subject NPC baselines come from the publish log, never the newest directory."""

from __future__ import annotations

import json
import shutil

from _delta_us2 import copy_fixture
from pipelines.summary_native.delta import npc_baseline as nb


def test_baseline_from_publish_log(tmp_path):
    root = copy_fixture(tmp_path)
    bls = nb.load_baselines(root)
    b = bls["brannoc-ironvein"]
    assert b.ok and b.subject == "Brannoc Ironvein" and b.horizon == 2
    assert b.publication["published_sha256"] == b.publication["body_sha256"]
    assert b.draft and b.composition and b.authored
    assert bls["envoy-sella-marr"].horizon == 1  # mixed horizons per subject


def test_unpublished_newer_draft_is_ignored(tmp_path):
    root = copy_fixture(tmp_path)
    npc = root / "docs/npcs/summary_native"
    newer = npc / "ch001-003"
    shutil.copytree(npc / "ch001-002", newer)
    (newer / "draft/npc_brannoc_ironvein.md").write_text("a newer, unpublished draft\n", encoding="utf-8")
    b = nb.load_baselines(root)["brannoc-ironvein"]
    assert b.ok and b.horizon == 2 and b.publication["range"] == "ch001-002"


def test_hand_edited_target_needs_repair(tmp_path):
    root = copy_fixture(tmp_path)
    f = root / "docs/npcs/brannoc-ironvein.md"
    f.write_text(f.read_text(encoding="utf-8") + "\nhand edit\n", encoding="utf-8")
    assert nb.baseline_for(root, "brannoc-ironvein").status == "repair_required:hand_edited_target"


def test_missing_draft_and_broken_lineage(tmp_path):
    root = copy_fixture(tmp_path)
    draft = root / "docs/npcs/summary_native/ch001-002/draft/npc_brannoc_ironvein.md"
    draft.write_text(draft.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
    assert nb.baseline_for(root, "brannoc-ironvein").status == "repair_required:draft_lineage_broken"
    draft.unlink()
    assert nb.baseline_for(root, "brannoc-ironvein").status == "repair_required:draft_missing"


def test_evidence_missing_is_warning_unless_required(tmp_path):
    root = copy_fixture(tmp_path)
    assert nb.baseline_for(root, "brannoc-ironvein").warnings == ["evidence_missing"]
    assert nb.baseline_for(root, "brannoc-ironvein", require_evidence=True).status == \
        "repair_required:evidence_missing"


def test_unlisted_slug_and_missing_target(tmp_path):
    root = copy_fixture(tmp_path)
    assert nb.baseline_for(root, "tobin-fenwick") is None
    (root / "docs/npcs/envoy-sella-marr.md").unlink()
    assert nb.baseline_for(root, "envoy-sella-marr").status == "repair_required:target_missing"
    log = json.loads((root / "docs/npcs/summary_native/publish_log.json").read_text())
    assert "envoy-sella-marr" in log
