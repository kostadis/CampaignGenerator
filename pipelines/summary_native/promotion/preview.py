"""Zero-write whole-bundle preview orchestration."""

from __future__ import annotations

from pathlib import Path
import json

from campaignlib.grounding_bundle import open_grounding_snapshot
from pipelines.summary_native.promotion.aliases import detached_aliases, loose_alias_paths
from pipelines.summary_native.promotion.diff import diff_members, proposed_bytes
from pipelines.summary_native.promotion.errors import PromotionMigrationRequired
from pipelines.summary_native.promotion.gates import (
    check_bundle_structure,
    claims_gate,
    finalize_promotion_gates,
)
from pipelines.summary_native.promotion.history import current_activation
from pipelines.summary_native.promotion.models import (
    BundleSelection,
    GateOutcome,
    PromotionPreview,
    SignoffSet,
)
from pipelines.summary_native.promotion.review_bindings import validate_signoff_bindings


def preview_bundle(
    campaign_dir: Path,
    bundle: BundleSelection,
    *,
    signoffs: SignoffSet | None = None,
    analysis_digest: str | None = None,
    resolution_digest: str | None = None,
    claims_complete: bool = False,
    claims_blocking: bool = False,
    signoff_failure: GateOutcome | None = None,
) -> PromotionPreview:
    outcomes = list(check_bundle_structure(campaign_dir, bundle))
    signoff_outcome = signoff_failure or validate_signoff_bindings(bundle, signoffs)
    outcomes.append(signoff_outcome)
    outcomes.append(
        claims_gate(
            analysis_digest=analysis_digest,
            complete=claims_complete,
            blocking=claims_blocking,
        )
    )
    generation_id = None
    activation_id = None
    live_digest = None
    edited_since_publication = None
    before: dict[str, bytes] = {}
    try:
        with open_grounding_snapshot(campaign_dir) as snapshot:
            generation_id = snapshot.generation_id
            activation_id = current_activation(campaign_dir, generation_id)[0].activation_id
            live_digest = snapshot.live_digest
            edited_since_publication = snapshot.edited_since_publication
            before = dict(snapshot.members)
    except PromotionMigrationRequired:
        layout_path = Path(campaign_dir) / "docs/grounding/layout.json"
        try:
            layout_value = json.loads(layout_path.read_text(encoding="utf-8"))
            absent = layout_value.get("version") == 1 and layout_value.get("state") == "absent"
        except (OSError, ValueError):
            absent = False
        if not absent:
            refusal = PromotionMigrationRequired(campaign_dir=Path(campaign_dir).absolute())
            outcomes.append(GateOutcome(
                gate="managed-layout", state="blocked", code=refusal.code, message=str(refusal),
            ))
        elif loose := loose_alias_paths(campaign_dir):
            # Only a pristine campaign may start from an absent baseline, and
            # promotion never adopts loose output implicitly.
            outcomes.append(GateOutcome(
                gate="managed-aliases", state="blocked", code="PROMOTION_PATH_CONFLICT",
                message=(
                    "the absent baseline has loose output at managed alias paths: "
                    + ", ".join(loose)
                    + "; promotion never adopts them — move them out of docs/ and preview again"
                ),
            ))
        else:
            outcomes.append(GateOutcome(
                gate="managed-layout", state="passed", message="initialized absent baseline is ready",
            ))
    else:
        detached = detached_aliases(campaign_dir)
        if detached:
            outcomes.append(GateOutcome(
                gate="managed-aliases", state="blocked", code="PROMOTION_PATH_CONFLICT",
                message=(
                    "compatibility alias conflict: " + "; ".join(detached)
                    + ". Promotion refuses while the conflict exists: keep the wanted text in "
                    "the managed member, then restore the alias"
                ),
            ))
    after = proposed_bytes(campaign_dir, bundle)
    result, is_eligible, _ = finalize_promotion_gates(
        outcomes, source_signoffs_current=signoff_outcome.state == "passed"
    )
    refusals = tuple(sorted({outcome.code for outcome in result if outcome.code}))
    return PromotionPreview.with_digest(
        campaign_id=bundle.campaign_id,
        bundle_digest=bundle.digest,
        report_analysis_digest=analysis_digest,
        report_resolution_digest=resolution_digest,
        signoff_context_digest=signoffs.digest if signoffs is not None else None,
        expected_generation_id=generation_id,
        expected_activation_id=activation_id,
        live_digest=live_digest,
        destination_edited_since_publication=edited_since_publication,
        changes=diff_members(before, after),
        gates=result,
        eligible=is_eligible,
        refusal_codes=refusals,
    )
