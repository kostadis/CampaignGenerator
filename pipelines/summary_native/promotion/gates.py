"""Pure eligibility gates shared by preview and commit."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pipelines.summary_native import pointers
from pipelines.summary_native.outline import check_outline, load_outline
from pipelines.summary_native.promotion.models import (
    BundleSelection,
    GateOutcome,
    GroundingDocument,
    SignoffSet,
)


def check_bundle_structure(campaign_dir: Path, bundle: BundleSelection) -> tuple[GateOutcome, ...]:
    root = Path(campaign_dir).resolve()
    outcomes: list[GateOutcome] = []
    identities = (
        tuple(bundle.documents)
        + (bundle.timeline,)
        + bundle.references
        + bundle.retained_records
        + bundle.dependencies
    )
    for member in identities:
        path = root / member.path
        try:
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != member.sha256 or len(data) != member.size:
                raise ValueError("bytes changed after enumeration")
            if member in bundle.retained_records:
                record = json.loads(data)
                if record.get("step") != "synth" or record.get("check", "passed") != "passed":
                    raise ValueError("retained run record is incomplete")
        except (OSError, ValueError) as exc:
            outcomes.append(
                GateOutcome(
                    gate="bundle-custody",
                    state="blocked",
                    code="PROMOTION_DEPENDENCY_STALE",
                    message=f"{member.path}: {exc}",
                )
            )
    for member in bundle.documents:
        path = root / member.path
        try:
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != member.sha256:
                raise ValueError("bytes changed after enumeration")
            text = data.decode("utf-8")
            outline = check_outline(text, load_outline(member.document_id.value))
            if outline:
                raise ValueError(outline[0])
            pointer_problems = pointers.check_paths(path, root)
            if pointer_problems:
                raise ValueError(pointer_problems[0])
        except (OSError, UnicodeError, ValueError) as exc:
            outcomes.append(
                GateOutcome(
                    gate=f"document-{member.document_id.value}",
                    state="blocked",
                    code="PROMOTION_DOCUMENT_INVALID",
                    message=str(exc),
                )
            )
        else:
            outcomes.append(
                GateOutcome(
                    gate=f"document-{member.document_id.value}",
                    state="passed",
                    message="draft outline, pointers, and enumerated bytes are current",
                    relevant_digest=member.sha256,
                )
            )
    return tuple(outcomes)


def check_copied_bundle(
    campaign_dir: Path, bundle: BundleSelection, destination: Path
) -> tuple[GateOutcome, ...]:
    """Validate exact copied membership and document contracts in final layout."""
    root = Path(campaign_dir).resolve()
    target = Path(destination)
    from pipelines.summary_native.promotion.diff import proposed_bytes

    expected = proposed_bytes(root, bundle)
    actual: dict[str, bytes] = {}
    try:
        if target.is_symlink() or not target.is_dir():
            raise ValueError("destination is missing or is not a regular directory")
        for directory, names, files in os.walk(target, followlinks=False):
            base = Path(directory)
            for name in names:
                if (base / name).is_symlink():
                    raise ValueError(f"destination contains symlink: {(base / name).relative_to(target)}")
            for name in files:
                path = base / name
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f"destination contains unsafe member: {path.relative_to(target)}")
                actual[path.relative_to(target).as_posix()] = path.read_bytes()
        if set(actual) != set(expected):
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            raise ValueError(f"destination membership differs (missing={missing}, extra={extra})")
        for relative, source_bytes in expected.items():
            if actual[relative] != source_bytes:
                raise ValueError(f"copied bytes differ: {relative}")
        for member in bundle.documents:
            document = target / f"{member.document_id.value}.md"
            problems = check_outline(document.read_text(encoding="utf-8"), load_outline(member.document_id.value))
            problems.extend(pointers.check_paths(document, root))
            if problems:
                raise ValueError(f"{member.document_id.value}: {problems[0]}")
    except (OSError, UnicodeError, ValueError) as exc:
        return (
            GateOutcome(
                gate="copied-bundle",
                state="blocked",
                code="PROMOTION_COPIED_BUNDLE_INVALID",
                message=str(exc),
            ),
        )
    return (
        GateOutcome(
            gate="copied-bundle",
            state="passed",
            message="copied bytes, membership, outlines, and pointers match the reviewed bundle",
            relevant_digest=bundle.digest,
        ),
    )


def check_signoffs(bundle: BundleSelection, signoffs: SignoffSet | None) -> GateOutcome:
    if signoffs is None:
        return GateOutcome(
            gate="document-signoffs",
            state="blocked",
            code="PROMOTION_SIGNOFF_REQUIRED",
            message="four current grounding-bundle-signoff/2 decisions are required",
        )
    expected = {member.document_id: member.sha256 for member in bundle.documents}
    for binding in signoffs.bindings:
        if binding.review_id != bundle.review_id or expected[binding.document_id] != binding.document_sha256:
            return GateOutcome(
                gate="document-signoffs",
                state="blocked",
                code="PROMOTION_SIGNOFF_STALE",
                message=f"sign-off is stale for {binding.document_id.value}",
            )
    return GateOutcome(
        gate="document-signoffs",
        state="passed",
        message="four exact current v2 document sign-offs are present",
        relevant_digest=signoffs.digest,
    )


def claims_gate(*, analysis_digest: str | None, complete: bool = False, blocking: bool = False) -> GateOutcome:
    if analysis_digest is None:
        return GateOutcome(
            gate="claims",
            state="not_available",
            code="CLAIMS_INCOMPLETE",
            message="no current cross-document check report was supplied",
        )
    if not complete:
        return GateOutcome(
            gate="claims",
            state="incomplete",
            code="CLAIMS_INCOMPLETE",
            message="the selected cross-document check did not complete",
            relevant_digest=analysis_digest,
        )
    if blocking:
        return GateOutcome(
            gate="claims",
            state="blocked",
            code="PROMOTION_BLOCKED",
            message="the current check has unresolved blocking findings",
            relevant_digest=analysis_digest,
        )
    return GateOutcome(
        gate="claims",
        state="passed",
        message="current deterministic claim evaluation is nonblocking",
        relevant_digest=analysis_digest,
    )


def eligible(outcomes: tuple[GateOutcome, ...]) -> bool:
    return bool(outcomes) and all(outcome.state == "passed" for outcome in outcomes)


class _GateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _DocumentInput(_GateModel):
    path: str
    sha256: str
    complete: bool


class _AuthorityInput(_GateModel):
    relevant_digest: str
    ledger_digest: str
    integrity: Literal["valid", "invalid"]
    unrelated_event_ids: list[str] = Field(default_factory=list)


class _SignoffContext(_GateModel):
    documents: dict[str, str]
    support: dict[str, str]
    authority: dict[str, str]
    audience: str
    rules: dict[str, str]
    analysis_digest: str
    resolution_digest: str


class _SignoffInput(_GateModel):
    document: str
    rule_version: int
    decision: str
    event_id: str
    context: _SignoffContext


class _FindingInput(_GateModel):
    finding_id: str
    analysis_digest: str
    state: str
    blocking: bool


class _PromotionGateContext(_GateModel):
    version: Literal[1]
    documents: dict[str, _DocumentInput]
    support: dict[str, str]
    authority: _AuthorityInput
    audience: str
    rules: dict[str, str]
    findings: list[_FindingInput]
    checks_complete: bool
    signoffs: dict[str, _SignoffInput]
    expected_destination_digest: str
    actual_destination_digest: str
    analysis_digest: str | None = None
    resolution_digest: str | None = None


def finalize_promotion_gates(
    outcomes: list[GateOutcome], *, source_signoffs_current: bool
) -> tuple[tuple[GateOutcome, ...], bool, bool]:
    """Apply the single final eligibility rule used by preview and commit.

    Callers must recompute their current facts before entering this seam.  An
    editable report's prior verdict is therefore never an input.
    """
    if not outcomes:
        outcomes.append(GateOutcome(gate="promotion", state="passed", message="all promotion gates passed"))
    result = tuple(outcomes)
    return result, eligible(result), source_signoffs_current


def evaluate_promotion_gates(campaign_dir: Path, context: dict[str, Any]) -> dict[str, Any]:
    """Compatibility envelope for pure eligibility tests and CLI adapters.

    The dict boundary is immediately converted into strict typed input. It
    does not trust editable report JSON as a verdict: document custody,
    current relevant bindings, findings, and destination identity are
    recomputed from the supplied current context by the caller.
    """
    del campaign_dir  # Path-dependent integrity gates are composed separately.
    value = _PromotionGateContext.model_validate(context)
    outcomes: list[GateOutcome] = []

    def add(state: str, code: str | None, message: str) -> None:
        outcomes.append(GateOutcome(gate="promotion", state=state, code=code, message=message))

    expected_documents = {document: item.sha256 for document, item in value.documents.items()}
    incomplete = [document for document, item in value.documents.items() if not item.complete]
    if incomplete:
        add("blocked", "PROMOTION_DRAFT_INCOMPLETE", f"incomplete drafts: {', '.join(sorted(incomplete))}")

    signoff_analysis = {item.context.analysis_digest for item in value.signoffs.values()}
    signoff_resolution = {item.context.resolution_digest for item in value.signoffs.values()}
    analysis_digest = value.analysis_digest
    resolution_digest = value.resolution_digest
    if analysis_digest is None and len(signoff_analysis) == 1:
        analysis_digest = next(iter(signoff_analysis))
    if resolution_digest is None and len(signoff_resolution) == 1:
        resolution_digest = next(iter(signoff_resolution))
    current_context = {
        "documents": expected_documents,
        "support": value.support,
        "authority": {"relevant_digest": value.authority.relevant_digest},
        "audience": value.audience,
        "rules": value.rules,
        "analysis_digest": analysis_digest,
        "resolution_digest": resolution_digest,
    }
    signoffs_current = True
    required = {document.value for document in GroundingDocument}
    missing = required - set(value.signoffs)
    if missing:
        signoffs_current = False
        add("blocked", "PROMOTION_SIGNOFF_REQUIRED", f"missing sign-offs: {', '.join(sorted(missing))}")
    for document in sorted(required & set(value.signoffs)):
        signoff = value.signoffs[document]
        if signoff.rule_version != 2 or signoff.decision != "document_signoff":
            signoffs_current = False
            add("blocked", "PROMOTION_SIGNOFF_RULE_UNSUPPORTED", f"unsupported sign-off for {document}")
            continue
        bound = signoff.context.model_dump()
        # Ledger custody may advance for an unrelated decision; semantic
        # continuity binds only the relevant projection digest.
        bound_authority = bound.get("authority", {})
        bound["authority"] = {"relevant_digest": bound_authority.get("relevant_digest")}
        if bound != current_context or signoff.document != document:
            signoffs_current = False
            add("blocked", "PROMOTION_SIGNOFF_STALE", f"sign-off context changed for {document}")

    unresolved = [finding for finding in value.findings if finding.blocking and finding.state in {"pending", "discuss", "confirmed"}]
    if unresolved:
        signoffs_current = False
        add("blocked", "PROMOTION_FINDING_UNRESOLVED", "new or unresolved blocking findings exist")
    if not value.checks_complete:
        add("incomplete", "CLAIMS_INCOMPLETE", "required checks did not complete")
    if value.authority.integrity != "valid":
        add("blocked", "PROMOTION_AUTHORITY_INVALID", "authority ledger integrity failed")
    if value.expected_destination_digest != value.actual_destination_digest:
        add("blocked", "PROMOTION_DESTINATION_STALE", "live destination changed after preview")
    finalized, result_eligible, signoffs_current = finalize_promotion_gates(
        outcomes, source_signoffs_current=signoffs_current
    )
    return {
        "eligible": result_eligible,
        "source_signoffs_current": signoffs_current,
        "gates": [gate.model_dump(mode="json") for gate in finalized],
    }
