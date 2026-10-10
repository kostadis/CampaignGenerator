"""T023 crash, fault, contention, and historical replay contracts."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import multiprocessing
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipelines.summary_native import cli as summary_cli
from pipelines.summary_native.promotion import publish, staging
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.history import joined_receipt
from pipelines.summary_native.promotion.manifest import build_bundle_selection
from pipelines.summary_native.promotion.preview import preview_bundle
from pipelines.summary_native.promotion.review_bindings import load_signoff_bindings
from pipelines.summary_native.review.documents import create_document_review, sign_document
from pipelines.summary_native.review.models import canonical_digest
from pipelines.summary_native.review.store import read_snapshot


FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
SPEC = importlib.util.spec_from_file_location("promotion_recovery_factory", FACTORY_PATH)
assert SPEC and SPEC.loader
FACTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FACTORY)

RULES = ("grounding-claims/1", "grounding-bundle-signoff/2")
FIXED_NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


class InjectedFailure(RuntimeError):
    pass


def _bundle(root: Path, review_id: str = "promotion-v2"):
    return build_bundle_selection(
        root, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id=review_id, rule_versions=RULES,
    )


def _prepared(tmp_path: Path, *, baseline: str = "legacy"):
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline=baseline)
    if baseline == "legacy":
        FACTORY.initialize_managed(root)
    else:
        from server.migrate_grounding_bundle import apply_migration, plan_migration
        plan = plan_migration(root)
        apply_migration(root, plan["plan_sha256"])
    initial = _bundle(root)
    context = {
        "support_digest": canonical_digest([
            item.model_dump(mode="json") for item in sorted(
                (initial.timeline, *initial.references, *initial.retained_records, *initial.dependencies),
                key=lambda value: value.path,
            )
        ]),
        "authority_digest": canonical_digest([]),
        "authority_record_ids": [],
        "audience_digest": canonical_digest({"audience": "gm"}),
        "rule_digest": canonical_digest({"rule_versions": sorted(initial.rule_versions)}),
    }
    create_document_review(
        root, "promotion-v2", root / "selections/promotion-documents.json",
        created_by="recovery-test", signoff_rule_version=2, signoff_context=context,
    )
    _manifest, _custody, items = read_snapshot(root, "promotion-v2")
    for item in items:
        sign_document(
            root, "promotion-v2", document_item_id=item.item_id,
            item_sha256=item.proposed_action.details["document_sha256"],
            expected_decision_revision=0, reviewer="fixture-gm",
        )
    bundle = _bundle(root)
    signoffs = load_signoff_bindings(root, bundle)
    preview = preview_bundle(
        root, bundle, signoffs=signoffs, analysis_digest="a" * 64,
        resolution_digest="b" * 64, claims_complete=True,
    )
    assert preview.eligible
    return root, bundle, signoffs, preview


def _publish(root, bundle, signoffs, preview, *, operation="op-one", generation="generation-one", request="request-one", fault=None):
    return publish._publish_bundle_for_recovery_test(
        root, bundle, preview, signoffs=signoffs, analysis_digest="a" * 64,
        resolution_digest="b" * 64, request_id=request, operation_id=operation,
        generation_id=generation, actor="fixture-gm", now=lambda: FIXED_NOW, fault=fault,
    )


def _current(root: Path) -> str:
    return os.readlink(root / "docs/grounding/current")


def test_public_publish_api_requires_a_current_claims_report(tmp_path: Path) -> None:
    root, bundle, signoffs, preview = _prepared(tmp_path)
    with pytest.raises(PromotionError) as caught:
        publish.publish_bundle(
            root, bundle, preview, signoffs=signoffs,
            analysis_digest="a" * 64, resolution_digest="b" * 64,
            request_id="request-no-report", operation_id="operation-no-report",
            generation_id="generation-no-report", actor="fixture-gm",
            check_report="claims-unavailable", now=lambda: FIXED_NOW,
        )
    assert caught.value.code == "CLAIMS_REPORT_REQUIRED"


@pytest.mark.parametrize("point", ["intent", "prepared", "generation_renamed", "receipt"])
def test_every_exposed_preactivation_fault_keeps_old_pointer_and_no_activation(
    tmp_path: Path, point: str
) -> None:
    root, bundle, signoffs, preview = _prepared(tmp_path)
    before = _current(root)

    def fail(stage: str) -> None:
        if stage == point:
            raise InjectedFailure(point)

    with pytest.raises(InjectedFailure, match=point):
        _publish(root, bundle, signoffs, preview, fault=fail)
    assert _current(root) == before
    assert not (root / "docs/grounding/activations/activation-op-one.json").exists()


@pytest.mark.parametrize("boundary", ["copy", "copy_sync", "copied_check", "receipt_write", "pointer_swap"])
def test_copy_check_write_sync_receipt_and_swap_failures_never_activate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    root, bundle, signoffs, preview = _prepared(tmp_path)
    before = _current(root)

    if boundary == "copy":
        monkeypatch.setattr(staging, "_write_tree", lambda *_args, **_kwargs: (_ for _ in ()).throw(InjectedFailure(boundary)))
    elif boundary == "copy_sync":
        monkeypatch.setattr(staging, "_sync_file", lambda *_args, **_kwargs: (_ for _ in ()).throw(InjectedFailure(boundary)))
    elif boundary == "copied_check":
        monkeypatch.setattr(staging, "check_copied_bundle", lambda *_args, **_kwargs: (_ for _ in ()).throw(InjectedFailure(boundary)))
    elif boundary == "receipt_write":
        original = publish._write_sync

        def fail_receipt(path: Path, data: bytes, **kwargs):
            if path.name == "publication-receipt.json":
                raise InjectedFailure(boundary)
            return original(path, data, **kwargs)

        monkeypatch.setattr(publish, "_write_sync", fail_receipt)
    else:
        original_replace = publish.os.replace

        def fail_swap(source, destination):
            if Path(destination).name == "current":
                raise InjectedFailure(boundary)
            return original_replace(source, destination)

        monkeypatch.setattr(publish.os, "replace", fail_swap)

    with pytest.raises(InjectedFailure, match=boundary):
        _publish(root, bundle, signoffs, preview)
    assert _current(root) == before
    assert not (root / "docs/grounding/activations/activation-op-one.json").exists()


def test_renamed_generation_or_receipt_is_an_orphan_and_never_implies_activation(tmp_path: Path) -> None:
    root, bundle, signoffs, preview = _prepared(tmp_path)
    before = _current(root)
    with pytest.raises(InjectedFailure):
        _publish(root, bundle, signoffs, preview,
                 fault=lambda point: (_ for _ in ()).throw(InjectedFailure(point)) if point == "receipt" else None)
    assert (root / "docs/grounding/generations/generation-one/publication-receipt.json").is_file()
    assert _current(root) == before
    with pytest.raises(PromotionError):
        joined_receipt(root, "activation-op-one")


@pytest.mark.parametrize("point", ["activated", "completed"])
def test_postswap_failure_is_durable_commit_unknown_not_failed_rollback(
    tmp_path: Path, point: str
) -> None:
    root, bundle, signoffs, preview = _prepared(tmp_path)
    with pytest.raises(InjectedFailure):
        _publish(root, bundle, signoffs, preview,
                 fault=lambda observed: (_ for _ in ()).throw(InjectedFailure(point)) if observed == point else None)
    assert _current(root) == "generations/generation-one/live"
    state = json.loads((root / "docs/grounding/operations/op-one/state.json").read_text())
    assert state["state"] == "commit_unknown"
    assert "recovery" in state["detail"]


def test_corrupt_intent_manifest_receipt_or_activation_refuses_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, bundle, signoffs, preview = _prepared(tmp_path)
    result = _publish(root, bundle, signoffs, preview)
    activation_id = result["activation"]["activation_id"]
    activation = root / f"docs/grounding/activations/{activation_id}.json"
    activation.write_bytes(activation.read_bytes() + b"\ncorrupt")
    with pytest.raises(PromotionError) as caught:
        joined_receipt(root, activation_id)
    assert caught.value.code == "PROMOTION_HISTORY_INVALID"


def test_recovery_refuses_corrupted_published_evidence_after_swap(tmp_path: Path) -> None:
    root, bundle, signoffs, preview = _prepared(tmp_path)
    with pytest.raises(InjectedFailure):
        _publish(root, bundle, signoffs, preview,
                 fault=lambda point: (_ for _ in ()).throw(InjectedFailure(point)) if point == "activated" else None)
    published = root / "docs/grounding/generations/generation-one/published/world_state.md"
    published.write_text("corrupt retained evidence\n", encoding="utf-8")
    recovery = importlib.import_module("pipelines.summary_native.promotion.recovery")
    with pytest.raises(PromotionError) as caught:
        recovery.recover_publication(root, "op-one")
    assert caught.value.code == "PROMOTION_RECOVERY_INTERVENTION_REQUIRED"


def test_two_contenders_from_one_preview_cannot_both_commit(tmp_path: Path) -> None:
    root, bundle, signoffs, preview = _prepared(tmp_path)
    first = _publish(root, bundle, signoffs, preview)
    with pytest.raises(PromotionError) as caught:
        _publish(root, bundle, signoffs, preview, operation="op-two", generation="generation-two", request="request-two")
    assert caught.value.code in {"PROMOTION_PREVIEW_STALE", "PROMOTION_DESTINATION_STALE"}
    assert _current(root) == "generations/generation-one/live"
    assert joined_receipt(root, first["activation"]["activation_id"])["publication"]["request_id"] == "request-one"


def test_replay_of_older_committed_request_after_later_publication_returns_history_without_reactivation(
    tmp_path: Path
) -> None:
    root, bundle, signoffs, preview = _prepared(tmp_path)
    first = _publish(root, bundle, signoffs, preview)
    later_preview = preview_bundle(
        root, bundle, signoffs=signoffs, analysis_digest="a" * 64,
        resolution_digest="b" * 64, claims_complete=True,
    )
    _publish(root, bundle, signoffs, later_preview, operation="op-two", generation="generation-two", request="request-two")
    assert _current(root) == "generations/generation-two/live"

    replay = _publish(root, bundle, signoffs, preview)
    assert replay == first
    assert _current(root) == "generations/generation-two/live"


def _crash_after_swap(root, bundle, signoffs, preview) -> None:
    _publish(root, bundle, signoffs, preview, fault=lambda point: os._exit(91) if point == "activated" else None)


def test_real_process_death_after_swap_is_discoverable_and_requires_explicit_recovery(tmp_path: Path) -> None:
    root, bundle, signoffs, preview = _prepared(tmp_path)
    process = multiprocessing.get_context("fork").Process(
        target=_crash_after_swap, args=(root, bundle, signoffs, preview)
    )
    process.start()
    process.join(15)
    assert process.exitcode == 91
    assert _current(root) == "generations/generation-one/live"
    state = json.loads((root / "docs/grounding/operations/op-one/state.json").read_text())
    assert state["state"] in {"activation_pending", "commit_unknown"}

    recovery = importlib.import_module("pipelines.summary_native.promotion.recovery")
    outcome = recovery.recover_publication(root, "op-one")
    assert outcome["state"] == "committed"
    assert _current(root) == "generations/generation-one/live"


def test_first_publication_from_initialized_absent_baseline_has_no_parent(tmp_path: Path) -> None:
    root, bundle, signoffs, preview = _prepared(tmp_path, baseline="pristine")
    assert preview.expected_generation_id is None
    assert preview.expected_activation_id is None
    result = _publish(root, bundle, signoffs, preview)
    assert result["activation"]["parent_activation_id"] is None
    assert _current(root) == "generations/generation-one/live"


def test_status_and_receipt_cli_join_committed_history(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, bundle, signoffs, preview = _prepared(tmp_path)
    _publish(root, bundle, signoffs, preview)
    config = str(root / "config/config.yaml")
    assert summary_cli.main(["promotion", "status", "--config", config, "--operation", "op-one", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["data"]["state"]["state"] == "committed"
    assert summary_cli.main(["promotion", "receipt", "--config", config, "--operation", "op-one", "--json"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["data"]["publication"]["request_id"] == "request-one"

    commit_args = [
        "promote", "--config", config, "--since", "1", "--until", "3",
        "--out-root", "docs/summary_native", "--review", "promotion-v2",
        "--check-report", "historical-report", "--preview-sha256", preview.preview_sha256,
        "--request-id", "request-one", "--json",
    ]
    assert summary_cli.main(commit_args) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["message"] == "promotion already committed"
    changed = [*commit_args]
    changed[changed.index(preview.preview_sha256)] = "f" * 64
    assert summary_cli.main(changed) == 2
    conflict = json.loads(capsys.readouterr().out)
    assert conflict["code"] == "PROMOTION_OPERATION_CONFLICT"
