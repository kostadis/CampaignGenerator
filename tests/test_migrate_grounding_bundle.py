from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest
import yaml

from server import migrate_grounding_bundle as migration


FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
SPEC = importlib.util.spec_from_file_location("migration_factory", FACTORY_PATH)
assert SPEC and SPEC.loader
FACTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FACTORY)


def _tree(root: Path):
    rows = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            rows.append((rel, "link", os.readlink(path)))
        elif path.is_dir():
            rows.append((rel, "dir", ""))
        else:
            rows.append((rel, "file", hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(rows)


def _campaign(tmp_path: Path, baseline: str = "legacy") -> Path:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline=baseline)
    (root / "docs/authority/.lock").touch()
    return root


def test_preview_is_pure_complete_and_digest_bound(tmp_path: Path) -> None:
    root = _campaign(tmp_path)
    raw = yaml.safe_load((root / "config/config.yaml").read_text())
    raw["unknown_future_key"] = {"keep": [1, 2, 3]}
    (root / "config/config.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
    before = _tree(root)
    plan = migration.plan_migration(root)
    assert _tree(root) == before
    assert plan["baseline"] == "legacy_adoption"
    assert len(plan["aliases"]) == 6
    assert {item["path"] for item in plan["members"]} >= {
        "world_state.md", "campaign_state.md", "party.md", "planning.md",
        "canon_events_timeline.md", "reference/nested/deeper/provenance.md",
    }
    assert len(plan["plan_sha256"]) == 64
    assert migration.plan_migration(root)["plan_sha256"] == plan["plan_sha256"]


def test_partial_legacy_bundle_refuses_and_pristine_is_explicit_absence(tmp_path: Path) -> None:
    partial = _campaign(tmp_path / "partial")
    (partial / "docs/planning.md").unlink()
    with pytest.raises(migration.MigrationError, match="incomplete"):
        migration.plan_migration(partial)

    pristine = _campaign(tmp_path / "pristine", baseline="pristine")
    plan = migration.plan_migration(pristine)
    assert plan["baseline"] == "absent"
    assert plan["members"] == []
    result = migration.apply_migration(pristine, plan["plan_sha256"])
    assert result["baseline"] == "absent"
    assert not (pristine / "docs/grounding/current").exists()
    assert not any((pristine / "docs" / name).exists() for name in migration.MANAGED_ALIASES)
    assert not (pristine / migration.PENDING_RELATIVE).exists()


def test_apply_retains_originals_installs_exact_aliases_and_preserves_unknowns(tmp_path: Path) -> None:
    root = _campaign(tmp_path)
    config_path = root / "config/config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["unknown_future_key"] = {"keep": "verbatim-value"}
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    unrelated = (root / "docs/unrelated-gm-notes.md").read_bytes()
    originals = {name: (root / "docs" / name).read_bytes() for name in migration.MANAGED_FILES}
    plan = migration.plan_migration(root)
    receipt = migration.apply_migration(root, plan["plan_sha256"])

    assert (root / "docs/unrelated-gm-notes.md").read_bytes() == unrelated
    loaded = yaml.safe_load(config_path.read_text())
    assert loaded["unknown_future_key"] == {"keep": "verbatim-value"}
    operation = root / "docs/grounding/migrations" / receipt["operation_id"]
    assert (operation / "originals/config/config.yaml").is_file()
    for name, data in originals.items():
        assert (operation / "originals/docs" / name).read_bytes() == data
        alias = root / "docs" / name
        assert alias.is_symlink()
        assert os.readlink(alias) == f"grounding/current/{name}"
    assert (root / "docs/reference").is_symlink()
    assert os.readlink(root / "docs/reference") == "grounding/current/reference"
    assert migration.verify_migration(root)["valid"] is True


def test_legacy_baseline_activation_binds_receipt_and_manifest(tmp_path: Path) -> None:
    root = _campaign(tmp_path)
    plan = migration.plan_migration(root)
    receipt = migration.apply_migration(root, plan["plan_sha256"])
    activation = json.loads((root / receipt["activation_path"]).read_text())
    assert activation["baseline_kind"] == "legacy_baseline"
    assert activation["migration_receipt_sha256"] == receipt["receipt_sha256"]
    assert activation["receipt_candidate_sha256"] is None
    manifest = root / receipt["manifest_path"]
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == activation["manifest_sha256"]
    assert migration.apply_migration(root, plan["plan_sha256"]) == receipt

    live_world = root / "docs/grounding/current/world_state.md"
    live_world.write_text("corrupt\n")
    checked = migration.verify_migration(root)
    assert checked["valid"] is False
    assert any("member hash mismatch" in problem for problem in checked["problems"])


def test_stale_plan_and_unsafe_reference_refuse_without_mutation(tmp_path: Path) -> None:
    root = _campaign(tmp_path)
    plan = migration.plan_migration(root)
    (root / "docs/world_state.md").write_text("changed after consent\n")
    before = _tree(root)
    with pytest.raises(migration.MigrationError, match="changed"):
        migration.apply_migration(root, plan["plan_sha256"])
    assert _tree(root) == before

    root = _campaign(tmp_path / "unsafe")
    os.symlink("../../unrelated-gm-notes.md", root / "docs/reference/unsafe.md")
    with pytest.raises(migration.MigrationError, match="symlink"):
        migration.plan_migration(root)


@pytest.mark.parametrize("stopping_phase", [
    "prepared", "backed_up", "generation_installed", "aliases_installed",
    "config_installed", "receipt_installed", "activation_installed",
])
def test_interrupted_apply_keeps_pending_and_explicit_recovery_finishes_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stopping_phase: str
) -> None:
    root = _campaign(tmp_path)
    plan = migration.plan_migration(root)

    def fail(phase: str) -> None:
        if phase == stopping_phase:
            raise RuntimeError("injected interruption")

    monkeypatch.setattr(migration, "_failpoint", fail)
    with pytest.raises(RuntimeError, match="injected"):
        migration.apply_migration(root, plan["plan_sha256"])
    pending = json.loads((root / migration.PENDING_RELATIVE).read_text())
    assert pending["operation_id"] == plan["operation_id"]
    assert migration.status(root)["state"] == "recovery_required"

    monkeypatch.setattr(migration, "_failpoint", lambda _phase: None)
    receipt = migration.recover_migration(root, plan["operation_id"])
    assert receipt["state"] == "committed"
    assert migration.verify_migration(root)["valid"] is True
    assert not (root / migration.PENDING_RELATIVE).exists()


def test_status_and_verify_never_initialize_or_fallback(tmp_path: Path) -> None:
    root = _campaign(tmp_path, baseline="pristine")
    before = _tree(root)
    assert migration.status(root)["state"] == "migration_required"
    assert migration.verify_migration(root)["valid"] is False
    assert _tree(root) == before


def test_interrupted_tree_copy_resumes_every_member_and_verifies_exactly(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir(); destination.mkdir()
    (source / "a.md").write_text("a\n")
    (source / "b.md").write_text("b\n")
    (destination / "a.md").write_text("a\n")
    migration._copy_tree_exact(source, destination)
    migration._verify_tree_exact(source, destination)
    assert (destination / "b.md").read_text() == "b\n"

    (destination / "b.md").write_text("changed\n")
    with pytest.raises(migration.MigrationError, match="conflicting"):
        migration._copy_tree_exact(source, destination)


def test_callable_cli_dry_run_emits_envelope_without_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _campaign(tmp_path)
    before = _tree(root)
    assert migration.main(["--campaign-dir", str(root), "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["baseline"] == "legacy_adoption"
    assert _tree(root) == before
