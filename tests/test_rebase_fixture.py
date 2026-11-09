"""T002: the rebase fixture reproduces the production blocker (spec 040 quickstart scenario 1).

``claims select`` (``mandatory_source_closure``, the real one, never mocked) over the pending chapter-6 plan's
staged range raises ``CLAIMS_SOURCE_STALE`` once chapters 2-5 have been corrected.
"""

from __future__ import annotations

import pytest

from campaignlib.grounding_config import promotion_config_from_summary_native
from pipelines.summary_native.claims.selection import mandatory_source_closure
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.manifest import build_bundle_selection
from pipelines.summary_native.promotion.settings import load_settings
from pipelines.summary_native.review.store import load_campaign_identity
from tests import _rebase_fixture as rf  # noqa: E402


def _select_pending(fx):
    root = fx.root
    rules = promotion_config_from_summary_native(load_settings(str(root / "config/config.yaml")).summary_native).rule_versions
    bundle = build_bundle_selection(
        root, out_root=fx.staged["request"]["out_root"], since=6, until=6,
        campaign_id=str(load_campaign_identity(root).campaign_id), review_id="claims-selection",
        rule_versions=rules, config_path=root / "config/grounding.yaml")
    return mandatory_source_closure(root, bundle, effective_horizon="through-chapter-6", audience="gm",
                                    rule_versions=rules)


def test_fixture_state(tmp_path, capsys, monkeypatch):
    fx = rf.build(tmp_path, capsys, monkeypatch)
    assert fx.corrected == [2, 3, 4, 5]
    assert fx.pending_plan_id and fx.staged["range"] == "ch006-006"
    # old bytes are in git history; current bytes are the corrections
    for c in fx.corrected:
        old = rf.git_show_bytes(fx.root, fx.original_commit, fx.paths[c].relative_to(fx.root).as_posix())
        assert rf.sha(old) == fx.old_sha[c] != fx.new_sha[c]
    assert rf.git(fx.root, "status", "--porcelain") == ""


def test_real_claims_select_is_blocked_by_stale_custody(tmp_path, capsys, monkeypatch):
    fx = rf.build(tmp_path, capsys, monkeypatch)
    with pytest.raises(PromotionError) as err:
        _select_pending(fx)
    assert err.value.code == "CLAIMS_SOURCE_STALE"
    msg = str(err.value)
    # T008: names the chapter, path, expected and actual digests, and the next command
    assert any(f"chapter {c}" in msg and fx.paths[c].relative_to(fx.root).as_posix() in msg for c in fx.corrected)
    hit = next(c for c in fx.corrected if f"chapter {c}," in msg)
    assert f"expected sha256 {fx.old_sha[hit]}" in msg and f"actual sha256 {fx.new_sha[hit]}" in msg
    assert "run: summary_native delta rebase inspect" in msg


def test_uncorrected_fixture_is_not_blocked(tmp_path, capsys, monkeypatch):
    """Control: before the corrections the same selection succeeds, so the block is the stale pins."""
    fx = rf.build_active_through_ch5(tmp_path, capsys, monkeypatch)
    rf.stage_pending_ch6(fx, capsys, monkeypatch)
    assert _select_pending(fx) is not None


def test_whitespace_variant_changes_only_chapter_one(tmp_path, capsys, monkeypatch):
    fx = rf.build(tmp_path, capsys, monkeypatch, whitespace_ch1=True)
    assert fx.corrected == [1]
