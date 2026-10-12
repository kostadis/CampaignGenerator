"""Regression tests for the #548 review findings on whole-bundle promotion.

Each test's docstring names the defect it pins. They exercise the engine
(``pipelines/summary_native/promotion``) directly or through the installed
``summary_native`` argv, against the deterministic promotion fixture campaign.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipelines.summary_native import cli as summary_cli
from pipelines.summary_native.authority import AuthorityError
from pipelines.summary_native.promotion import cli as promotion_cli
from pipelines.summary_native.promotion import publish
from pipelines.summary_native.promotion.errors import PromotionError, PromotionMigrationRequired
from pipelines.summary_native.promotion.history import joined_receipt
from pipelines.summary_native.promotion.manifest import build_bundle_selection
from pipelines.summary_native.promotion.models import PublicationReceiptCandidate
from pipelines.summary_native.promotion.preview import preview_bundle
from pipelines.summary_native.promotion.recovery import recover_publication
from pipelines.summary_native.promotion.review_bindings import load_signoff_bindings
from pipelines.summary_native.review.documents import create_document_review, sign_document
from pipelines.summary_native.review.models import canonical_digest
from pipelines.summary_native.review.store import read_snapshot


FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
SPEC = importlib.util.spec_from_file_location("promotion_findings_548_factory", FACTORY_PATH)
assert SPEC and SPEC.loader
FACTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FACTORY)

RULES = ("grounding-claims/1", "grounding-bundle-signoff/2")
FIXED_NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
ALIASES = (
    "world_state.md", "campaign_state.md", "party.md", "planning.md",
    "canon_events_timeline.md", "reference",
)


class InjectedFailure(RuntimeError):
    pass


def _bundle(root: Path):
    return build_bundle_selection(
        root, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="promotion-v2", rule_versions=RULES,
        config_path=root / "config/grounding.yaml",
    )


def _preview(root: Path, bundle, signoffs):
    return preview_bundle(
        root, bundle, signoffs=signoffs, analysis_digest="a" * 64,
        resolution_digest="b" * 64, claims_complete=True,
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
        created_by="findings-548", signoff_rule_version=2, signoff_context=context,
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
    preview = _preview(root, bundle, signoffs)
    assert preview.eligible, preview.refusal_codes
    return root, bundle, signoffs, preview


def _publish(root, bundle, signoffs, preview, *, operation="op-one", generation="generation-one",
             request="request-one", fault=None):
    return publish._publish_bundle_for_recovery_test(
        root, bundle, preview, signoffs=signoffs, analysis_digest="a" * 64,
        resolution_digest="b" * 64, request_id=request, operation_id=operation,
        generation_id=generation, actor="fixture-gm", now=lambda: FIXED_NOW, fault=fault,
    )


def _fail_at(point: str):
    def fault(observed: str) -> None:
        if observed == point:
            raise InjectedFailure(point)
    return fault


def _current(root: Path) -> str:
    return os.readlink(root / "docs/grounding/current")


def _state(root: Path, operation: str = "op-one") -> str:
    return json.loads((root / f"docs/grounding/operations/{operation}/state.json").read_text())["state"]


def _tree(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*")}


def _cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    rc = summary_cli.main(argv)
    return rc, json.loads(capsys.readouterr().out)


def _promote(root: Path, *extra: str, check_report: str = "claims-unavailable") -> list[str]:
    return [
        "promote", "--config", str(root / "config/config.yaml"), "--since", "1", "--until", "3",
        "--review", "promotion-v2", "--check-report", check_report, "--json", *extra,
    ]


# -- 1. --config means config/config.yaml, optional, auto-detected (XII) -------


def test_promote_config_is_optional_config_yaml_and_out_root_is_campaign_relative(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: ``promote``/``promotion`` required ``--config`` and resolved
    ``summary_native.out_root`` against ``config/`` instead of the campaign root,
    so drafts written by build/synth were never found (and the UI, which passes
    config/config.yaml, saw a path error)."""
    root, _bundle_value, _signoffs, _preview_value = _prepared(tmp_path)
    monkeypatch.chdir(root)
    rc, payload = _cli([
        "promote", "--since", "1", "--until", "3", "--review", "promotion-v2",
        "--check-report", "claims-unavailable", "--dry-run", "--json",
    ], capsys)
    assert rc == 5, payload
    selection = payload["data"]["selection"]
    assert selection is not None
    assert selection["selected_range"]["out_root"] == "docs/summary_native"
    assert selection["config_identity"]["path"] == "config/grounding.yaml"
    assert _cli(["promotion", "status", "--json"], capsys)[0] == 0


def test_promotion_config_refuses_grounding_yaml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defect: ``promotion`` read ``--config`` as grounding.yaml, a second meaning
    of the flag that every other summary_native subcommand spells config.yaml."""
    root, *_ = _prepared(tmp_path)
    rc, payload = _cli(["promotion", "status", "--config", str(root / "config/grounding.yaml"), "--json"], capsys)
    assert rc == 2
    assert payload["code"] == "PROMOTION_CONFIG_INVALID"


# -- 2. first promotion from an absent baseline installs the six aliases ------


def test_first_publication_installs_the_six_compatibility_aliases(tmp_path: Path) -> None:
    """Defect: publishing from an ``absent`` baseline never created
    docs/world_state.md … docs/reference, so ``verify_migration`` failed and
    ``classify_managed_path`` called the missing aliases detached."""
    root, bundle, signoffs, preview = _prepared(tmp_path, baseline="pristine")
    _publish(root, bundle, signoffs, preview)
    for name in ALIASES:
        assert os.readlink(root / "docs" / name) == f"grounding/current/{name}"
    from campaignlib.grounding_bundle import classify_managed_path
    from server.migrate_grounding_bundle import verify_migration
    assert verify_migration(root)["valid"] is True
    assert classify_managed_path(root / "docs/world_state.md", root) == "world_state.md"


def test_crash_after_first_activation_is_finished_by_recovery_including_aliases(tmp_path: Path) -> None:
    """Defect: a first publication interrupted after the pointer swap had no
    step that would ever install the aliases (recovery did not know about them)."""
    root, bundle, signoffs, preview = _prepared(tmp_path, baseline="pristine")
    with pytest.raises(InjectedFailure):
        _publish(root, bundle, signoffs, preview, fault=_fail_at("activated"))
    assert not (root / "docs/world_state.md").is_symlink()
    assert recover_publication(root, "op-one")["state"] == "committed"
    from server.migrate_grounding_bundle import verify_migration
    assert verify_migration(root)["valid"] is True


def test_absent_baseline_with_a_loose_file_at_an_alias_path_refuses(tmp_path: Path) -> None:
    """Defect: preview's absent-baseline branch never looked at the alias paths,
    so a loose docs/world_state.md was silently left beside the new bundle."""
    root, _bundle_value, _signoffs, _preview_value = _prepared(tmp_path, baseline="pristine")
    loose = root / "docs/world_state.md"
    loose.write_text("LOOSE HAND-WRITTEN WORLD STATE\n", encoding="utf-8")
    bundle = _bundle(root)
    signoffs = load_signoff_bindings(root, bundle)
    preview = _preview(root, bundle, signoffs)
    assert not preview.eligible
    gate = next(gate for gate in preview.gates if gate.gate == "managed-aliases")
    assert gate.code == "PROMOTION_PATH_CONFLICT" and "docs/world_state.md" in gate.message
    with pytest.raises(PromotionError) as caught:
        _publish(root, bundle, signoffs, preview)
    assert caught.value.code == "PROMOTION_PATH_CONFLICT"
    assert loose.read_text(encoding="utf-8") == "LOOSE HAND-WRITTEN WORLD STATE\n"
    assert not (root / "docs/grounding/current").is_symlink()


# -- 3. a detached alias is refused --------------------------------------------


def test_detached_alias_blocks_preview_and_publication_naming_both_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defect: an editor that saved over docs/world_state.md (replacing the
    symlink with a file) left preview eligible, and publication went ahead with
    the detached copy still shadowing the managed member (migration.md:
    "Promotion refuses while the conflict exists")."""
    root, _b, _s, _p = _prepared(tmp_path)
    alias = root / "docs/world_state.md"
    data = alias.read_bytes()
    alias.unlink()
    alias.write_bytes(data + b"\nGM edit saved by an editor that replaced the symlink\n")
    before = _current(root)
    bundle = _bundle(root)
    signoffs = load_signoff_bindings(root, bundle)
    preview = _preview(root, bundle, signoffs)
    assert not preview.eligible
    gate = next(gate for gate in preview.gates if gate.gate == "managed-aliases")
    assert gate.code == "PROMOTION_PATH_CONFLICT"
    assert "docs/world_state.md" in gate.message
    assert "docs/grounding/current/world_state.md" in gate.message
    with pytest.raises(PromotionError) as caught:
        _publish(root, bundle, signoffs, preview)
    assert caught.value.code == "PROMOTION_PATH_CONFLICT"
    assert _current(root) == before
    assert alias.is_file() and not alias.is_symlink()
    rc, payload = _cli(_promote(root, "--dry-run"), capsys)
    assert rc == 2
    assert "PROMOTION_PATH_CONFLICT" in payload["data"]["preview"]["refusal_codes"]


# -- 4. staged bytes are compared with the reviewed bytes ----------------------


def test_draft_saved_and_reverted_around_staging_never_reaches_a_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect (ABA): staging re-read the drafts, and the pre-activation check
    re-read them again, so an unreviewed save that was reverted before the
    check was published as if it had been signed."""
    root, bundle, signoffs, preview = _prepared(tmp_path)
    draft = root / next(item.path for item in bundle.documents if item.document_id.value == "world_state")
    signed = draft.read_bytes()
    original = publish.stage_generation

    def racing(*args, **kwargs):
        draft.write_bytes(signed + b"\nUNREVIEWED LINE\n")
        try:
            return original(*args, **kwargs)
        finally:
            draft.write_bytes(signed)

    monkeypatch.setattr(publish, "stage_generation", racing)
    before = _current(root)
    with pytest.raises(PromotionError) as caught:
        _publish(root, bundle, signoffs, preview)
    assert caught.value.code == "PROMOTION_STALE_PREVIEW"
    assert _current(root) == before


def test_staged_member_differing_from_the_signed_digest_refuses_before_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: inside the lock nothing compared the staged members with the
    bundle's reviewed sha256, so bytes that changed after staging went live."""
    root, bundle, signoffs, preview = _prepared(tmp_path)
    original = publish.stage_generation

    def tampered(*args, **kwargs):
        stage, manifest = original(*args, **kwargs)
        target = stage / "live/world_state.md"
        target.write_bytes(target.read_bytes() + b"\nchanged after staging\n")
        return stage, manifest

    monkeypatch.setattr(publish, "stage_generation", tampered)
    before = _current(root)
    with pytest.raises(PromotionError) as caught:
        _publish(root, bundle, signoffs, preview)
    assert caught.value.code == "PROMOTION_STALE_PREVIEW"
    assert "world_state.md" in str(caught.value)
    assert _current(root) == before
    assert not (root / "docs/grounding/activations/activation-op-one.json").exists()


# -- 5. state.json / layout.json are written atomically; status never skips ----


def test_state_and_layout_are_never_truncated_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: ``_write_sync`` opened state.json and layout.json with O_TRUNC and
    rewrote them in place, so a crash mid-write left an empty or torn record."""
    root, bundle, signoffs, preview = _prepared(tmp_path)
    opened: list[tuple[str, int]] = []
    real_open = os.open

    def spy(path, flags, *args, **kwargs):
        opened.append((os.fspath(path), flags))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(publish.os, "open", spy)
    _publish(root, bundle, signoffs, preview)
    monkeypatch.undo()
    writes = [
        Path(path).name for path, flags in opened
        if flags & (os.O_WRONLY | os.O_RDWR) and Path(path).name in {"state.json", "layout.json"}
    ]
    assert writes == []
    assert _state(root) == "committed"
    assert json.loads((root / "docs/grounding/layout.json").read_text())["generation_id"] == "generation-one"


def test_status_lists_an_unreadable_operation_and_recovery_reconciles_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defect: ``promotion status`` silently skipped an operation whose
    state.json was unreadable, and recovery refused it forever."""
    root, bundle, signoffs, preview = _prepared(tmp_path)
    with pytest.raises(InjectedFailure):
        _publish(root, bundle, signoffs, preview, fault=_fail_at("completed"))
    (root / "docs/grounding/operations/op-one/state.json").write_bytes(b"")
    rc, payload = _cli(["promotion", "status", "--config", str(root / "config/config.yaml"), "--json"], capsys)
    assert rc == 0
    rows = {row["operation_id"]: row for row in payload["data"]["operations"]}
    assert rows["op-one"]["state"] == "unreadable"
    assert rows["op-one"]["recover"] == "summary_native promotion recover --operation op-one"
    rc, single = _cli(["promotion", "status", "--config", str(root / "config/config.yaml"),
                       "--operation", "op-one", "--json"], capsys)
    assert rc == 0 and single["data"]["state"]["state"] == "unreadable"
    assert recover_publication(root, "op-one")["state"] == "committed"
    assert _state(root) == "committed"


# -- 6. the receipt identifies range, paths, previous generation and claims ----


def test_receipt_records_range_paths_previous_generation_and_claims_basis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect (FR-008): the receipt named neither the selected range, the
    affected paths, the previous generation, nor the check report and its
    accepted-uncertainty resolutions / coverage limits; the generation manifest
    hard-coded ``analysis_digest`` to None."""
    root, bundle, signoffs, preview = _prepared(tmp_path)
    report = SimpleNamespace(
        report_id="report-548", outcome="complete",
        analysis_digest="a" * 64, resolution_digest="b" * 64,
        resolutions=(SimpleNamespace(
            finding_id="finding-1", disposition="accept_uncertainty",
            rationale="The GM accepts the open question.", event_id="event-1", decision_revision=1,
        ),),
        coverage_limitations=("prose chunks without extraction were not checked",),
    )
    import pipelines.summary_native.claims.report as claims_report
    monkeypatch.setattr(claims_report, "load_current_report", lambda *_a, **_k: report)
    result = publish.publish_bundle(
        root, bundle, preview, signoffs=signoffs, analysis_digest="a" * 64,
        resolution_digest="b" * 64, request_id="request-one", operation_id="op-one",
        generation_id="generation-one", actor="fixture-gm", check_report="report-548",
        now=lambda: FIXED_NOW,
    )
    receipt = joined_receipt(root, result["activation"]["activation_id"])["publication"]
    assert receipt["schema_version"] == 2
    assert receipt["selected_range"] == {"since": 1, "until": 3, "out_root": "docs/summary_native"}
    changes = {item["path"]: item["kind"] for item in receipt["changes"]}
    assert changes["reference/obsolete/old-watch.md"] == "remove"
    assert changes["reference/new/eastern-survey.md"] == "add"
    assert changes["world_state.md"] == "replace"
    assert receipt["previous_generation_id"] == "legacy-fixture"
    assert receipt["previous_activation_id"] == "baseline-fixture"
    assert receipt["claims_report_id"] == "report-548"
    assert receipt["analysis_digest"] == "a" * 64 and receipt["resolution_digest"] == "b" * 64
    assert receipt["finding_resolutions"][0]["disposition"] == "accept_uncertainty"
    assert receipt["coverage_limitations"] == ["prose chunks without extraction were not checked"]
    manifest = json.loads((root / "docs/grounding/generations/generation-one/manifest.json").read_text())
    assert manifest["analysis_digest"] == "a" * 64


def test_version_one_receipts_still_validate_and_cannot_carry_new_fields() -> None:
    """Guard for the receipt schema bump: a receipt sealed before FR-008's fields
    existed keeps validating against its original digest."""
    values = dict(
        schema_version=1, receipt_id="receipt-op", operation_id="op", request_id="req",
        campaign_id="campaign", generation_id="generation", generation_manifest_sha256="c" * 64,
        preview_sha256="d" * 64, bundle_digest="e" * 64,
        review_event_ids=("event-1",), gates=(), prepared_at="2026-10-10T00:00:00Z",
    )
    values["receipt_sha256"] = canonical_digest(values)
    old = PublicationReceiptCandidate.model_validate_json(json.dumps(values))
    assert old.schema_version == 1 and old.selected_range is None
    with pytest.raises(ValueError):
        PublicationReceiptCandidate.model_validate_json(json.dumps({**values, "claims_report_id": "report-1"}))


# -- 7. unresolved prior operations, retries and request ids -------------------


def test_publication_refuses_while_a_prior_operation_is_unresolved(tmp_path: Path) -> None:
    """Defect: a second promotion committed while an earlier attempt was still
    ``staged``, after which that attempt could never be recovered."""
    root, bundle, signoffs, preview = _prepared(tmp_path)
    with pytest.raises(InjectedFailure):
        _publish(root, bundle, signoffs, preview, fault=_fail_at("receipt"))
    assert _state(root) == "staged"
    before = _current(root)
    with pytest.raises(PromotionError) as caught:
        _publish(root, bundle, signoffs, preview, operation="op-two", generation="generation-two",
                 request="request-two")
    assert caught.value.code == "PROMOTION_RECOVERY_REQUIRED"
    assert "summary_native promotion recover --operation op-one" in str(caught.value)
    assert _current(root) == before
    assert recover_publication(root, "op-one")["state"] == "aborted"
    _publish(root, bundle, signoffs, preview, operation="op-two", generation="generation-two",
             request="request-two")
    assert _current(root) == "generations/generation-two/live"


def test_recovering_a_staged_orphan_whose_generation_never_became_current_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: a staged operation overtaken by another publication raised
    intervention-required forever, though its generation was never current."""
    root, bundle, signoffs, preview = _prepared(tmp_path)
    with pytest.raises(InjectedFailure):
        _publish(root, bundle, signoffs, preview, fault=_fail_at("receipt"))
    with monkeypatch.context() as patch:
        # History written before the unresolved-operation guard existed.
        patch.setattr(publish, "require_no_unresolved", lambda *_a, **_k: None)
        _publish(root, bundle, signoffs, preview, operation="op-two", generation="generation-two",
                 request="request-two")
    assert recover_publication(root, "op-one")["state"] == "aborted"
    assert _current(root) == "generations/generation-two/live"


def test_retrying_a_request_id_after_a_failed_attempt_is_an_operation_conflict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defect: reusing a request id after a non-committed attempt hit
    ``intent.json`` with O_EXCL and surfaced as FileExistsError /
    PROMOTION_COMMAND_FAILED instead of "use a new --request-id"."""
    root, bundle, signoffs, preview = _prepared(tmp_path)
    with pytest.raises(InjectedFailure):
        _publish(root, bundle, signoffs, preview, operation="operation-req-x", request="req-x",
                 fault=_fail_at("receipt"))
    assert recover_publication(root, "operation-req-x")["state"] == "aborted"
    with pytest.raises(PromotionError) as caught:
        _publish(root, bundle, signoffs, preview, operation="operation-req-x", request="req-x")
    assert caught.value.code == "PROMOTION_OPERATION_CONFLICT"
    assert "new --request-id" in str(caught.value)
    rc, payload = _cli(_promote(root, "--preview-sha256", preview.preview_sha256, "--request-id", "req-x"), capsys)
    assert (rc, payload["code"]) == (2, "PROMOTION_OPERATION_CONFLICT")


def test_request_id_longer_than_the_route_cap_is_refused_not_truncated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defect: the CLI truncated request ids to 96 characters, so two ids
    sharing that prefix named the same operation."""
    root, _bundle_value, _signoffs, preview = _prepared(tmp_path)
    rc, payload = _cli(_promote(root, "--preview-sha256", preview.preview_sha256, "--request-id", "r" * 97), capsys)
    assert (rc, payload["code"]) == (2, "PROMOTION_REQUEST_INVALID")
    assert not (root / "docs/grounding/operations").exists()


# -- 8. one spelling for the stale-preview code; dry-run excludes commit flags -


def test_stale_preview_has_one_spelling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defect: promotion raised PROMOTION_PREVIEW_STALE while the contract and
    PromotionStaleError spell it PROMOTION_STALE_PREVIEW."""
    root, bundle, signoffs, preview = _prepared(tmp_path)
    _publish(root, bundle, signoffs, preview)
    with pytest.raises(PromotionError) as caught:
        _publish(root, bundle, signoffs, preview, operation="op-two", generation="generation-two",
                 request="request-two")
    assert caught.value.code == "PROMOTION_STALE_PREVIEW"
    rc, payload = _cli(_promote(root, "--preview-sha256", "f" * 64, "--request-id", "request-three"), capsys)
    assert (rc, payload["code"]) == (3, "PROMOTION_STALE_PREVIEW")


@pytest.mark.parametrize("extra", [("--request-id", "req-1"), ("--preview-sha256", "f" * 64)])
def test_dry_run_combined_with_commit_flags_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: tuple[str, str]
) -> None:
    """Defect: ``--dry-run`` silently ignored ``--preview-sha256``/``--request-id``
    although the contract makes the two modes mutually exclusive."""
    root, *_ = _prepared(tmp_path)
    rc, payload = _cli(_promote(root, "--dry-run", *extra), capsys)
    assert rc == 2
    assert payload["data"]["refusal"]["code"] == "PROMOTION_REQUEST_INVALID"


# -- 9. dry-run creates nothing -------------------------------------------------


def test_dry_run_on_a_campaign_without_an_authority_lock_creates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defect: ``promote --dry-run`` recreated docs/authority/.lock through the
    review store's creating lock, breaking the zero-write preview contract."""
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    (root / "docs/authority/.lock").unlink()
    before = _tree(root)
    rc, payload = _cli(_promote(root, "--dry-run"), capsys)
    assert _tree(root) == before
    assert rc == 2
    assert "PROMOTION_MIGRATION_REQUIRED" in payload["data"]["preview"]["refusal_codes"]


# -- 10. exit codes and stable codes per contracts/cli-ui.md --------------------


def test_review_store_refusal_relays_its_code_not_command_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defect: a ReviewStoreError (here an uninitialized review identity)
    collapsed into PROMOTION_COMMAND_FAILED / exit 2."""
    root, _bundle_value, _signoffs, preview = _prepared(tmp_path)
    (root / "docs/reviews/campaign.json").unlink()
    rc, payload = _cli(_promote(root, "--preview-sha256", preview.preview_sha256, "--request-id", "req-1"), capsys)
    assert payload["code"] == "REVIEW_NOT_INITIALIZED"
    assert rc == 2


def test_authority_refusal_during_commit_relays_its_code_and_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: an AuthorityError from the commit (a pending authority
    transaction) was reported as PROMOTION_COMMAND_FAILED / exit 2 instead of
    its own code with the contract's pending-recovery exit."""
    root, *_ = _prepared(tmp_path)
    monkeypatch.setattr(promotion_cli, "_load_check_report",
                        lambda *_a, **_k: ("a" * 64, "b" * 64, True, False))
    rc, preview_payload = _cli(_promote(root, "--dry-run"), capsys)
    assert rc == 0, preview_payload
    digest = preview_payload["data"]["preview"]["preview_sha256"]

    def pending(*_args, **_kwargs):
        raise AuthorityError("AUTH_PENDING_TRANSACTION: run authority recover", "AUTH_PENDING_TRANSACTION")

    monkeypatch.setattr(promotion_cli, "publish_bundle", pending)
    rc, payload = _cli(_promote(root, "--preview-sha256", digest, "--request-id", "req-1"), capsys)
    assert (rc, payload["code"]) == (4, "AUTH_PENDING_TRANSACTION")


def test_mixed_range_dry_run_exits_invalid_without_a_fake_paths_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defect: a mixed-range refusal exited 5 (blocking finding) instead of 2
    (invalid selection) and was reported under an invented ``paths`` gate."""
    root, *_ = _prepared(tmp_path)
    party = root / "docs/summary_native/ch001-003/state/drafts/party.draft.md"
    party.write_text(party.read_text().replace("range: ch001-003", "range: ch004-004", 1))
    rc, payload = _cli(_promote(root, "--dry-run"), capsys)
    assert rc == 2
    assert payload["data"]["refusal"]["code"] == "PROMOTION_MIXED_RANGE"
    assert payload["data"]["preview"]["refusal_codes"] == ["PROMOTION_MIXED_RANGE"]
    assert not any(gate["gate"] == "paths" for gate in payload["data"]["preview"]["gates"])


def test_unmigrated_dry_run_exits_with_the_migration_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defect: previewing an unmigrated campaign exited 5 like a blocking
    finding; the contract gives migration refusals exit 2."""
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    rc, payload = _cli(_promote(root, "--dry-run"), capsys)
    assert rc == 2
    assert "PROMOTION_MIGRATION_REQUIRED" in payload["data"]["preview"]["refusal_codes"]


# -- 11. the migration refusal names the exact command (XIII) -------------------


def test_migration_required_names_the_exact_migration_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defect (XIII): PROMOTION_MIGRATION_REQUIRED said only "migration is
    required", never the command to run."""
    assert "migrate_grounding_bundle --campaign-dir <campaign> --dry-run --json" in str(PromotionMigrationRequired())
    filled = PromotionMigrationRequired(campaign_dir="/srv/campaign")
    assert "migrate_grounding_bundle --campaign-dir /srv/campaign --dry-run --json" in str(filled)
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    _rc, payload = _cli(_promote(root, "--dry-run"), capsys)
    gate = next(gate for gate in payload["data"]["preview"]["gates"] if gate["gate"] == "managed-layout")
    assert f"migrate_grounding_bundle --campaign-dir {root} --dry-run --json" in gate["message"]
