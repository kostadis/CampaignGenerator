from __future__ import annotations

import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from campaignlib.grounding_bundle import (
    MANAGED_FILES,
    classify_managed_path,
    inspect_layout,
    open_grounding_snapshot,
    write_managed_member,
)
from pipelines.summary_native.authority_apply import authority_lock
from pipelines.summary_native.promotion.errors import (
    PromotionMigrationRequired,
    PromotionPathError,
)
from pipelines.summary_native.promotion.models import (
    ActivationRecord, BaselineKind, ContentIdentity, GenerationKind, GenerationManifest,
)
from pipelines.summary_native.review.models import canonical_bytes, canonical_digest


def _managed(tmp_path: Path) -> Path:
    campaign = tmp_path / "campaign"
    authority = campaign / "docs/authority"
    authority.mkdir(parents=True)
    (authority / ".lock").write_bytes(b"")
    grounding = campaign / "docs/grounding"
    live = grounding / "generations/g-1/live"
    published = live.parent / "published"
    for tree in (live, published):
        (tree / "reference/nested").mkdir(parents=True)
        for name in MANAGED_FILES:
            (tree / name).write_text(f"# {name}\n", encoding="utf-8")
        (tree / "reference/nested/item.md").write_text("item\n", encoding="utf-8")
    os.symlink("generations/g-1/live", grounding / "current")
    for name in MANAGED_FILES:
        os.symlink(f"grounding/current/{name}", campaign / "docs" / name)
    os.symlink("grounding/current/reference", campaign / "docs/reference")
    members = tuple(
        ContentIdentity(path=p.relative_to(published).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest(), size=p.stat().st_size)
        for p in sorted(published.rglob("*")) if p.is_file()
    )
    values = dict(
        generation_id="g-1", operation_id="fixture-op", campaign_id="fixture",
        selected_range=None, kind=GenerationKind.LEGACY_ADOPTION, members=members,
        retained_records=(), external_dependencies=(),
        published_path="docs/grounding/generations/g-1/published",
        live_path="docs/grounding/generations/g-1/live", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        manifest_sha256="0" * 64,
    )
    provisional = GenerationManifest.model_validate(values)
    values["manifest_sha256"] = canonical_digest(provisional, exclude_fields=frozenset({"manifest_sha256"}))
    manifest_bytes = canonical_bytes(GenerationManifest.model_validate(values))
    (live.parent / "manifest.json").write_bytes(manifest_bytes)
    activation = ActivationRecord(
        activation_id="baseline-fixture", operation_id="fixture-op", generation_id="g-1",
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        migration_receipt_sha256=canonical_digest({
            "version": 1, "state": "committed", "operation_id": "fixture-op",
            "baseline": "legacy_adoption", "generation_id": "g-1",
        }),
        baseline_kind=BaselineKind.LEGACY_BASELINE, actor="fixture",
        completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    (grounding / "activations").mkdir()
    (grounding / "activations/baseline-fixture.json").write_bytes(canonical_bytes(activation))
    receipt_base = {"version": 1, "state": "committed", "operation_id": "fixture-op", "baseline": "legacy_adoption", "generation_id": "g-1"}
    (grounding / "migrations/fixture-op").mkdir(parents=True)
    (grounding / "migrations/fixture-op/receipt.json").write_text(__import__('json').dumps({**receipt_base, "receipt_sha256": canonical_digest(receipt_base)}))
    (grounding / "layout.json").write_text('{"generation_id":"g-1","state":"active","version":1}\n')
    return campaign


def test_strict_identity_rejects_coercion_dot_nul_and_unknown() -> None:
    digest = "0" * 64
    with pytest.raises(ValidationError):
        ContentIdentity(path=".", sha256=digest, size=0)
    with pytest.raises(ValidationError):
        ContentIdentity(path="bad\x00name", sha256=digest, size=0)
    with pytest.raises(ValidationError):
        ContentIdentity(path="x", sha256=digest, size="1")
    with pytest.raises(ValidationError):
        ContentIdentity(path="x", sha256=digest, size=1, surprise=True)


def test_existing_lock_mode_is_zero_write(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    before = sorted(str(path.relative_to(campaign)) for path in campaign.rglob("*"))
    with pytest.raises(Exception, match="AUTH_LOCK_MISSING"):
        with authority_lock(campaign, exclusive=False, create=False):
            pass
    after = sorted(str(path.relative_to(campaign)) for path in campaign.rglob("*"))
    assert after == before == []
    with pytest.raises(PromotionMigrationRequired):
        with open_grounding_snapshot(campaign):
            pass
    assert sorted(campaign.rglob("*")) == []


def test_snapshot_pins_all_bytes_and_alias_identity(tmp_path: Path) -> None:
    campaign = _managed(tmp_path)
    layout = inspect_layout(campaign)
    assert layout.generation_id == "g-1"
    assert classify_managed_path(campaign / "docs/world_state.md", campaign, layout) == "world_state.md"
    assert classify_managed_path(campaign / "docs/reference/nested/item.md", campaign, layout) == "reference/nested/item.md"
    with open_grounding_snapshot(campaign) as snapshot:
        assert snapshot.generation_id == "g-1"
        assert snapshot.edited_since_publication is False
        assert snapshot.read("reference/nested/item.md") == b"item\n"
        assert len(snapshot.members) == 6
        with pytest.raises(TypeError):
            snapshot.members["world_state.md"] = b"changed"  # type: ignore[index]


def test_detached_alias_and_unexpected_symlink_refuse(tmp_path: Path) -> None:
    campaign = _managed(tmp_path)
    alias = campaign / "docs/world_state.md"
    alias.unlink()
    alias.write_text("detached", encoding="utf-8")
    with pytest.raises(PromotionPathError, match="detached"):
        classify_managed_path(alias, campaign)

    alias.unlink()
    os.symlink("grounding/current/world_state.md", alias)
    ref = campaign / "docs/grounding/generations/g-1/live/reference/nested/item.md"
    ref.unlink()
    os.symlink("../other.md", ref)
    with pytest.raises(PromotionPathError, match="symlink"):
        with open_grounding_snapshot(campaign):
            pass


def test_unrelated_path_does_not_require_migration_and_traversal_refuses(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    assert classify_managed_path(campaign / "docs/mechanics.md", campaign) is None
    with pytest.raises(PromotionPathError, match="traversal"):
        classify_managed_path(Path("docs/notes/../world_state.md"), campaign)


def test_retired_generation_member_refuses(tmp_path: Path) -> None:
    campaign = _managed(tmp_path)
    retired = campaign / "docs/grounding/generations/g-old/live/world_state.md"
    with pytest.raises(PromotionPathError, match="retired"):
        classify_managed_path(retired, campaign)


def test_raw_campaign_symlink_refuses_before_resolve(tmp_path: Path) -> None:
    campaign = _managed(tmp_path)
    alias = tmp_path / "campaign-alias"
    alias.symlink_to(campaign, target_is_directory=True)
    with pytest.raises(Exception, match="UNSAFE_PATH"):
        with authority_lock(alias, exclusive=False, create=False):
            pass


def test_pending_activation_blocks_reads_and_managed_write_is_locked(tmp_path: Path) -> None:
    campaign = _managed(tmp_path)
    before = (campaign / "docs/grounding/current/party.md").read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    after_digest = write_managed_member(campaign, "party.md", b"edited party\n", expected_sha256=digest)
    assert after_digest == hashlib.sha256(b"edited party\n").hexdigest()
    assert (campaign / "docs/party.md").read_bytes() == b"edited party\n"
    operation = campaign / "docs/grounding/operations/op-1"
    operation.mkdir(parents=True)
    (operation / "state.json").write_text('{"state":"commit_unknown"}\n', encoding="utf-8")
    with pytest.raises(Exception, match="explicit recovery"):
        with open_grounding_snapshot(campaign):
            pass
