"""US2 whole-publication integration acceptance."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pipelines.summary_native.promotion.diff import proposed_bytes
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.preview import preview_bundle
from tests.test_summary_native_promotion_recovery import _prepared, _publish


def _hash_tree(path: Path) -> dict[str, str]:
    return {
        item.relative_to(path).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(path.rglob("*")) if item.is_file()
    }


def test_complete_publication_preserves_old_live_edits_and_sources(tmp_path: Path) -> None:
    root, bundle, signoffs, _preview = _prepared(tmp_path)
    summaries_before = _hash_tree(root / "docs/summaries")
    edited = root / "docs/grounding/current/world_state.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "\nGM live edit.\n", encoding="utf-8")
    preview = preview_bundle(
        root, bundle, signoffs=signoffs, analysis_digest="a" * 64,
        resolution_digest="b" * 64, claims_complete=True,
    )
    expected = proposed_bytes(root, bundle)
    result = _publish(root, bundle, signoffs, preview)
    generation = root / "docs/grounding/generations/generation-one"
    for tree_name in ("published", "live"):
        tree = generation / tree_name
        assert {path: (tree / path).read_bytes() for path in expected} == expected
    assert b"GM live edit" in (root / "docs/grounding/operations/op-one/previous/world_state.md").read_bytes()
    assert _hash_tree(root / "docs/summaries") == summaries_before
    assert not (root / ".git").exists()
    assert result["receipt"]["previous_snapshot_sha256"]


def test_old_preview_cannot_publish_after_destination_changes(tmp_path: Path) -> None:
    root, bundle, signoffs, preview = _prepared(tmp_path)
    (root / "docs/grounding/current/party.md").write_text("manual destination edit\n")
    with pytest.raises(PromotionError) as caught:
        _publish(root, bundle, signoffs, preview)
    assert caught.value.code in {"PROMOTION_PREVIEW_STALE", "PROMOTION_DESTINATION_STALE"}
    assert "legacy-fixture" in (root / "docs/grounding/current").readlink().as_posix()
