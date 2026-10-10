"""Pure adapter from selected NPC verifier results to common review items.

The verifier remains the source of mechanical observations. This module reads
no files, calls no model, and never infers an implicit selection. Its adapter
binds caller-supplied immutable bytes and results into strict ReviewItem
records; its selected runner invokes only explicitly named verifier checks.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence
from uuid import UUID, uuid5

from pipelines.summary_native import npc_check, npc_verify
from pipelines.summary_native.npc_verify import Finding, VerificationResult
from pipelines.summary_native.review.models import (
    AssignmentBasis,
    Diagnostic,
    Evidence,
    FindingCategory,
    InputBinding,
    ItemLocator,
    ProposedAction,
    ReviewItem,
    RuleBinding,
    Severity,
    SubjectReference,
    SupportAssessment,
    RerunSelection,
    SelectionMember,
    RunReport,
    RunMember,
    RunOutcome,
    canonical_bytes,
    canonical_digest,
    model_from_json,
)


class VerificationAdapterError(ValueError):
    """The selected verifier result cannot be represented without guessing."""


@dataclass(frozen=True)
class ExplicitEvidenceMetadata:
    """Already encoded evidence policy; its presence is what permits a mechanical finding."""

    line: int
    text: str
    source_id: str
    superseded_by_source_id: str | None = None
    allowed_audiences: frozenset[str] | None = None
    requested_audience: str | None = None


@dataclass(frozen=True)
class SelectedNpcVerification:
    """One explicitly selected dossier and its already-computed result."""

    selection_id: str
    subject_ref: SubjectReference
    draft_source_id: str
    draft_path: str
    draft_text: str
    evidence_source_id: str
    evidence_path: str
    evidence_text: str | None
    result: VerificationResult
    revision: int = 1
    rule_versions: tuple[RuleBinding, ...] = ()
    explicit_evidence_metadata: tuple[ExplicitEvidenceMetadata, ...] = ()


_DIRECT_CATEGORIES: dict[str, frozenset[FindingCategory]] = {
    "invalid": frozenset({FindingCategory.MISSING_SOURCE_OR_POINTER}),
    "outside-evidence": frozenset({FindingCategory.MISSING_SOURCE_OR_POINTER}),
    "uncited": frozenset({FindingCategory.MISSING_SOURCE_OR_POINTER}),
    "manual-invalid": frozenset({FindingCategory.MISSING_SOURCE_OR_POINTER}),
    "citation-mismatch": frozenset({
        FindingCategory.MISSING_SOURCE_OR_POINTER,
        FindingCategory.CITATION_NON_ENTAILMENT,
    }),
    "not-found": frozenset({FindingCategory.UNSUPPORTED_OR_CONTRADICTED}),
    "manual-dropped": frozenset({FindingCategory.UNSUPPORTED_OR_CONTRADICTED}),
    "typography-normalised": frozenset({FindingCategory.TYPOGRAPHY_PRESENTATION}),
    "placeholder-speaker": frozenset({FindingCategory.TYPOGRAPHY_PRESENTATION}),
    "status-claim-unsupported": frozenset({FindingCategory.CITATION_NON_ENTAILMENT}),
    "later-source-supersedes": frozenset({FindingCategory.LATER_SOURCE_SUPERSEDES}),
    "knowledge-leak": frozenset({FindingCategory.KNOWLEDGE_LEAK}),
}
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ORDINAL_WORDS = (
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
    "eighth", "ninth", "tenth", "eleventh", "twelfth",
)
_MARKER_RE = re.compile(
    r"\b(?:"
    + "|".join(_ORDINAL_WORDS)
    + r"|\d+(?:st|nd|rd|th)?)\b",
    re.IGNORECASE,
)


def _valid_opaque_id(value: str) -> bool:
    return bool(_OPAQUE_ID.fullmatch(value)) and ".." not in value


def _valid_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and "\\" not in value
        and not path.is_absolute()
        and value == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _categories(code: str, *, blocking: bool) -> frozenset[FindingCategory]:
    direct = _DIRECT_CATEGORIES.get(code)
    if direct is not None:
        return direct
    lowered = code.casefold()
    if "supersed" in lowered:
        return frozenset({FindingCategory.LATER_SOURCE_SUPERSEDES})
    if "knowledge" in lowered or "audience" in lowered:
        return frozenset({FindingCategory.KNOWLEDGE_LEAK})
    if any(token in lowered for token in ("timeout", "transport", "protocol", "unavailable", "malformed", "incomplete")):
        return frozenset({FindingCategory.VERIFIER_TRANSPORT_PROTOCOL})
    if any(token in lowered for token in ("status", "number", "numeric", "ordinal", "entail")):
        return frozenset({FindingCategory.CITATION_NON_ENTAILMENT})
    return frozenset({
        FindingCategory.UNSUPPORTED_OR_CONTRADICTED
        if blocking else FindingCategory.CITATION_NON_ENTAILMENT
    })


def _severity(code: str, *, blocking: bool) -> Severity:
    if blocking:
        return Severity.BLOCKING
    if code == "typography-normalised":
        return Severity.ADVISORY
    return Severity.NEEDS_JUDGMENT


def _basis(code: str, *, blocking: bool) -> AssignmentBasis:
    if blocking or code in {
        "typography-normalised",
        "later-source-supersedes",
        "knowledge-leak",
    }:
        return AssignmentBasis.MECHANICAL
    return AssignmentBasis.ADVISORY_CANDIDATE


def _action(code: str, categories: frozenset[FindingCategory]) -> ProposedAction:
    if FindingCategory.VERIFIER_TRANSPORT_PROTOCOL in categories:
        action = "rerun_selected_check"
    elif FindingCategory.MISSING_SOURCE_OR_POINTER in categories:
        action = "repair_or_recheck_pointer"
    elif FindingCategory.LATER_SOURCE_SUPERSEDES in categories:
        action = "review_supersession"
    elif FindingCategory.KNOWLEDGE_LEAK in categories:
        action = "review_audience_and_knowledge"
    elif FindingCategory.TYPOGRAPHY_PRESENTATION in categories:
        action = "review_presentation"
    else:
        action = "review_claim_against_evidence"
    return ProposedAction(action=action, details={"legacy_code": code})


def run_selected_npc_checks(
    selection: SelectedNpcVerification,
    *,
    corpus_index: npc_verify.CorpusIndex,
    summaries_text: str,
    manual: list[str],
    check_ids: Sequence[str],
) -> VerificationResult:
    """Run only the explicitly named real NPC checks for one materialized selection."""

    if selection.evidence_text is None:
        raise VerificationAdapterError(
            f"{selection.selection_id}: selected rerun has no exact evidence bytes"
        )
    try:
        return npc_verify.verify_scoped(
            selection.draft_text,
            selection.evidence_text,
            corpus_index,
            summaries_text,
            manual,
            check_ids,
        )
    except ValueError as exc:
        raise VerificationAdapterError(str(exc)) from exc


def _claim_without_pointers(line: str) -> str:
    value = npc_check.BRACKET_RE.sub("", line)
    return re.sub(r"\s+", " ", value).strip()


def _markers(text: str) -> frozenset[str]:
    return frozenset(match.group(0).casefold() for match in _MARKER_RE.finditer(text))


def _marker_skeleton(text: str) -> str:
    return re.sub(r"[^a-z]+", " ", _MARKER_RE.sub(" <value> ", text.casefold())).strip()


def _cited_claims(selection: SelectedNpcVerification):
    """Yield exact claim lines paired with the exact parsed evidence occurrence they cite."""

    evidence_text = selection.evidence_text or ""
    evidence = npc_check.EvidenceIndex.of(npc_check.split_chapters(evidence_text))
    candidates = []
    for line_number, line in enumerate(selection.draft_text.splitlines(), 1):
        claim = _claim_without_pointers(line)
        if not claim:
            continue
        for bracket, target in npc_check.citation_parts(line):
            chapter, item_id = target
            if chapter < 0:
                continue
            occurrences = evidence.items_at(chapter, item_id)
            if len(occurrences) == 1:
                candidates.append((line_number, claim, bracket, target, occurrences[0].text))
    if candidates:
        return tuple(candidates)

    # Some callers supply one already-selected evidence excerpt rather than a
    # structured dossier. It can bind one cited claim, but never broadens to a
    # whole-draft comparison or guesses among multiple occurrences.
    cited_lines = []
    for line_number, line in enumerate(selection.draft_text.splitlines(), 1):
        parts = npc_check.citation_parts(line)
        if len(parts) == 1:
            cited_lines.append((line_number, _claim_without_pointers(line), *parts[0]))
    if len(cited_lines) == 1 and evidence_text.strip():
        line_number, claim, bracket, target = cited_lines[0]
        return ((line_number, claim, bracket, target, evidence_text.strip()),)
    return ()


def _deterministic_semantic_advisories(selection: SelectedNpcVerification) -> tuple[Finding, ...]:
    cited = _cited_claims(selection)
    findings: list[Finding] = []
    by_occurrence: dict[tuple[tuple[int, str], str], list[tuple[int, str, frozenset[str]]]] = {}
    for line, claim, bracket, target, evidence_text in cited:
        claim_markers = _markers(claim)
        evidence_markers = _markers(evidence_text)
        if claim_markers and not claim_markers <= evidence_markers:
            ordinal = any(
                marker in _ORDINAL_WORDS or re.fullmatch(r"\d+(?:st|nd|rd|th)", marker)
                for marker in claim_markers
            )
            code = "ordinal-inconsistency" if ordinal else "number-inconsistency"
            findings.append(Finding(
                code,
                line,
                claim,
                f"{bracket} does not contain the claim's exact number/ordinal; GM semantic review required",
            ))
        if claim_markers:
            key = (target, _marker_skeleton(claim))
            by_occurrence.setdefault(key, []).append((line, claim, claim_markers))

    for (target, _skeleton), claims in by_occurrence.items():
        marker_sets = {markers for _, _, markers in claims}
        if len(claims) < 2 or len(marker_sets) < 2:
            continue
        first_line = min(line for line, _, _ in claims)
        for line, claim, _markers_for_claim in claims:
            if line == first_line:
                continue
            findings.append(Finding(
                "same-citation-inconsistency",
                line,
                claim,
                f"the same citation [ch {target[0]:03d} / {target[1]}] has a conflicting number/ordinal at line {first_line}",
            ))
    return tuple(findings)


def _explicit_metadata_findings(
    selection: SelectedNpcVerification,
) -> tuple[tuple[Finding, ...], tuple[Finding, ...]]:
    lines = selection.draft_text.splitlines()
    failures: list[Finding] = []
    advisories: list[Finding] = []
    for encoded in selection.explicit_evidence_metadata:
        if (
            encoded.line < 1
            or encoded.line > len(lines)
            or not encoded.text
            or encoded.text not in lines[encoded.line - 1]
            or not _valid_opaque_id(encoded.source_id)
        ):
            raise VerificationAdapterError(
                f"{selection.selection_id}: explicit evidence metadata is not bound to an exact claim"
            )
        if encoded.superseded_by_source_id is not None:
            if not _valid_opaque_id(encoded.superseded_by_source_id):
                raise VerificationAdapterError(
                    f"{selection.selection_id}: invalid explicit superseding source id"
                )
            advisories.append(Finding(
                "later-source-supersedes",
                encoded.line,
                encoded.text,
                f"encoded source {encoded.superseded_by_source_id} supersedes {encoded.source_id}; GM judges its semantic effect",
            ))
        if encoded.requested_audience is not None:
            if encoded.allowed_audiences is None:
                raise VerificationAdapterError(
                    f"{selection.selection_id}: requested audience has no encoded grants"
                )
            if encoded.requested_audience not in encoded.allowed_audiences:
                failures.append(Finding(
                    "knowledge-leak",
                    encoded.line,
                    encoded.text,
                    f"encoded audience grants exclude {encoded.requested_audience}",
                ))
    return tuple(failures), tuple(advisories)


def _stable_payload(selection: SelectedNpcVerification, finding: Finding, *, group: str, ordinal: int) -> str:
    return json.dumps(
        {
            "selection_id": selection.selection_id,
            "draft_path": selection.draft_path,
            "group": group,
            "ordinal": ordinal,
            "code": finding.code,
            "line": finding.line,
            "text": finding.text,
            "detail": finding.detail,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _evidence(selection: SelectedNpcVerification, finding: Finding) -> Evidence:
    evidence_text = selection.evidence_text
    if finding.code in {
        "ordinal-inconsistency",
        "number-inconsistency",
        "same-citation-inconsistency",
    }:
        occurrence = next(
            (
                cited_text
                for line, _claim, _bracket, _target, cited_text in _cited_claims(selection)
                if line == finding.line
            ),
            None,
        )
        if occurrence:
            return Evidence(
                source_id=selection.evidence_source_id,
                source_path=selection.evidence_path,
                anchor=f"verifier:{finding.code}:line:{finding.line}",
                exact_excerpt=occurrence,
                selected_span_sha256=hashlib.sha256(occurrence.encode("utf-8")).hexdigest(),
                citation_resolved=True,
                support=SupportAssessment.UNASSESSED,
            )
    if evidence_text is not None and finding.text and finding.text in evidence_text:
        excerpt = finding.text
        return Evidence(
            source_id=selection.evidence_source_id,
            source_path=selection.evidence_path,
            anchor=f"verifier:{finding.code}",
            exact_excerpt=excerpt,
            selected_span_sha256=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            citation_resolved=finding.code not in {"invalid", "outside-evidence", "uncited", "manual-invalid"},
            support=SupportAssessment.UNASSESSED,
        )
    reason = finding.detail or f"the {finding.code} result retained no exact supporting excerpt"
    return Evidence(
        source_id=selection.evidence_source_id,
        source_path=selection.evidence_path,
        anchor=f"verifier:{finding.code}",
        missing_reason=reason,
        citation_resolved=False,
        support=SupportAssessment.CANDIDATE_ISSUE,
    )


def _item(
    *,
    campaign_id: UUID,
    review_id: str,
    selection: SelectedNpcVerification,
    finding: Finding,
    group: str,
    ordinal: int,
) -> ReviewItem:
    lines = selection.draft_text.splitlines()
    if finding.line < 0 or finding.line > len(lines):
        raise VerificationAdapterError(
            f"{selection.selection_id}: diagnostic line {finding.line} is outside the exact draft"
        )
    exact_line = lines[finding.line - 1] if finding.line else None
    claim_text = exact_line if exact_line else None
    failure_context = None if claim_text is not None else (
        finding.text + (f" — {finding.detail}" if finding.detail else "")
    )
    if not failure_context and claim_text is None:
        raise VerificationAdapterError(f"{selection.selection_id}: diagnostic has no exact content")

    blocking = group == "failure" or (
        finding.code == "typography-normalised"
        and any(rule.rule_id == "claimed-verbatim" for rule in selection.rule_versions)
    )
    categories = _categories(finding.code, blocking=blocking)
    stable = _stable_payload(selection, finding, group=group, ordinal=ordinal)
    fingerprint = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    evidence = _evidence(selection, finding)
    draft_semantic = claim_text or failure_context or ""
    evidence_semantic = evidence.exact_excerpt or evidence.missing_reason or ""
    rules = selection.rule_versions or (RuleBinding(rule_id="npc-verify", version="1"),)
    try:
        return ReviewItem(
            item_id=f"npc-{fingerprint[:24]}",
            revision=selection.revision,
            campaign_id=campaign_id,
            review_id=review_id,
            domain="npc_finding",
            subject_ref=selection.subject_ref,
            occurrence_id=uuid5(campaign_id, stable),
            locator=ItemLocator(
                source_path=selection.draft_path,
                anchor=f"line:{finding.line}" if finding.line else "draft",
                display_line=finding.line or None,
            ),
            claim_text=claim_text,
            failure_context=failure_context,
            evidence=(evidence,),
            diagnostics=(Diagnostic(
                diagnostic_id=f"diagnostic-{fingerprint[:20]}",
                legacy_code=finding.code,
                message=finding.detail or finding.code,
                blocking=blocking,
                details={
                    "detail": finding.detail,
                    "line": finding.line,
                    "text": finding.text,
                    "verdict": "fail" if blocking else "advisory",
                },
            ),),
            categories=categories,
            severity=_severity(finding.code, blocking=blocking),
            assignment_basis=_basis(finding.code, blocking=blocking),
            rationale=finding.detail or f"Existing verifier reported {finding.code}.",
            proposed_action=_action(finding.code, categories),
            scope={"kind": "evidence", "value": f"{selection.evidence_source_id}:{finding.line or 'draft'}"},
            audience="gm",
            rule_versions=rules,
            input_bindings=(
                InputBinding(
                    source_id=selection.draft_source_id,
                    path=selection.draft_path,
                    custody_sha256=hashlib.sha256(selection.draft_text.encode("utf-8")).hexdigest(),
                    semantic_sha256=hashlib.sha256(draft_semantic.encode("utf-8")).hexdigest(),
                ),
                InputBinding(
                    source_id=selection.evidence_source_id,
                    path=selection.evidence_path,
                    custody_sha256=hashlib.sha256((selection.evidence_text or "").encode("utf-8")).hexdigest(),
                    semantic_sha256=hashlib.sha256(evidence_semantic.encode("utf-8")).hexdigest(),
                ),
            ),
        )
    except ValueError as exc:
        raise VerificationAdapterError(
            f"{selection.selection_id}: verifier result cannot form a strict review item: {exc}"
        ) from exc


def adapt_selected_verifications(
    *,
    campaign_id: UUID,
    review_id: str,
    selected: Sequence[SelectedNpcVerification],
) -> tuple[ReviewItem, ...]:
    """Adapt exactly the materialized NPC selections supplied by the caller."""
    materialized = tuple(selected)
    if not materialized:
        raise VerificationAdapterError("NPC review requires an explicit nonempty selection")
    if not _valid_opaque_id(review_id):
        raise VerificationAdapterError(f"invalid opaque review id {review_id!r}")
    ids = [entry.selection_id for entry in materialized]
    if len(ids) != len(set(ids)):
        raise VerificationAdapterError("duplicate selection id in NPC review")
    for entry in materialized:
        if not _valid_opaque_id(entry.selection_id):
            raise VerificationAdapterError(f"invalid opaque selection id {entry.selection_id!r}")
        for label, value in (
            ("draft source", entry.draft_source_id),
            ("evidence source", entry.evidence_source_id),
        ):
            if not _valid_opaque_id(value):
                raise VerificationAdapterError(f"invalid opaque {label} id {value!r}")
        for label, value in (("draft", entry.draft_path), ("evidence", entry.evidence_path)):
            if not _valid_relative_path(value):
                raise VerificationAdapterError(f"invalid {label} relative path {value!r}")
        if entry.revision < 1:
            raise VerificationAdapterError("selection revision must be positive")

    items: list[ReviewItem] = []
    for selection in materialized:
        metadata_failures, metadata_advisories = _explicit_metadata_findings(selection)
        failures = tuple(selection.result.failures) + metadata_failures
        advisories = (
            tuple(selection.result.advisories)
            + metadata_advisories
            + _deterministic_semantic_advisories(selection)
        )
        failures = tuple(dict.fromkeys(failures))
        advisories = tuple(dict.fromkeys(advisories))
        for ordinal, finding in enumerate(failures):
            items.append(_item(
                campaign_id=campaign_id,
                review_id=review_id,
                selection=selection,
                finding=finding,
                group="failure",
                ordinal=ordinal,
            ))
        for ordinal, finding in enumerate(advisories):
            items.append(_item(
                campaign_id=campaign_id,
                review_id=review_id,
                selection=selection,
                finding=finding,
                group="advisory",
                ordinal=ordinal,
            ))
    return tuple(items)


def preview_rerun(campaign_dir: Path, review_id: str, *, members: dict[str, tuple[str, ...]], mode: str) -> RerunSelection:
    from pipelines.summary_native.authority import sha256_bytes
    from pipelines.summary_native.authority_apply import TransactionTarget, _prepare_transaction_locked, authority_lock, recover_transaction, require_no_pending_transaction
    from pipelines.summary_native.review.store import read_review_state, read_snapshot
    if mode not in {"unresolved", "selected"} or not members:
        raise VerificationAdapterError("rerun requires an explicit nonempty selection")
    manifest, items, events, stale = read_review_state(campaign_dir, review_id)
    _, current_custody, _ = read_snapshot(campaign_dir, review_id)
    current_sources = {source.source_id: source for source in current_custody.sources}
    by_id = {item.item_id: item for item in items}
    latest = {}
    for event in events:
        if event.get("item_id"): latest[event["item_id"]] = event
    selected = []
    for item_id, check_ids in members.items():
        item = by_id.get(item_id)
        if item is None or not check_ids or len(check_ids) != len(set(check_ids)):
            raise VerificationAdapterError("rerun selection contains an unknown item or duplicate check")
        event = latest.get(item_id)
        current_verdict = event.get("verdict") if event and event.get("review_digest") == item.review_digest else None
        mechanical_failure = any(diagnostic.blocking for diagnostic in item.diagnostics)
        if mode == "unresolved" and (
            item_id in stale
            or current_verdict not in {"reject", "discuss"} and not mechanical_failure
        ):
            raise VerificationAdapterError("unresolved rerun accepts only rejected, discussed, or mechanical-failure items")
        if mode == "selected" and current_verdict == "approve" and item_id not in stale:
            raise VerificationAdapterError("current approved item does not require a selected pending/stale rerun")
        dependencies={}
        for binding in item.input_bindings:
            source=current_sources.get(binding.source_id)
            if source is None or source.path!=binding.path: raise VerificationAdapterError("rerun source custody is unavailable")
            dependencies[binding.source_id]=source.sha256
        selected.append(SelectionMember(campaign_id=manifest.campaign_id, review_id=review_id, item_id=item_id, item_revision=item.revision, review_digest=item.review_digest, check_ids=check_ids, dependency_hashes=dependencies))
    selection = RerunSelection(selection_id=f"selection-{uuid5(manifest.campaign_id, repr(members)).hex[:20]}", campaign_id=manifest.campaign_id, review_id=review_id, review_generation=manifest.generation, mode=mode, created_at=datetime.now(timezone.utc), members=tuple(selected))
    directory = Path(campaign_dir) / "docs/reviews" / review_id / "runs/selections"
    path = directory / f"{selection.selection_sha256}.json"
    with authority_lock(Path(campaign_dir),exclusive=True):
        require_no_pending_transaction(Path(campaign_dir)); current,_,_=read_snapshot(campaign_dir,review_id,_already_locked=True)
        if current.generation!=selection.review_generation: raise VerificationAdapterError("rerun selection became stale before persistence")
        data=canonical_bytes(selection)
        if path.exists():
            if path.read_bytes()!=data: raise VerificationAdapterError("rerun selection digest collision")
        else:
            journal=_prepare_transaction_locked(Path(campaign_dir),proposal_id=f"rerun-selection-{selection.selection_sha256[:20]}",proposal_sha256=selection.selection_sha256,targets=[TransactionTarget.create(path,data)]); recover_transaction(Path(campaign_dir),journal["id"],_already_locked=True)
    return selection


def execute_rerun(campaign_dir: Path, review_id: str, *, selection_sha256: str, checkers: dict[str, object]) -> RunReport:
    from pipelines.summary_native.authority import sha256_bytes
    from pipelines.summary_native.authority_apply import TransactionTarget, _prepare_transaction_locked, authority_lock, recover_transaction, require_no_pending_transaction
    from pipelines.summary_native.review.store import _reject_symlinks, read_review_state, read_snapshot
    root = Path(campaign_dir).resolve()
    path = root / "docs/reviews" / review_id / "runs/selections" / f"{selection_sha256}.json"
    path=_reject_symlinks(root,path)
    if not path.is_file(): raise VerificationAdapterError("rerun selection digest is unknown")
    selection = model_from_json(RerunSelection, path.read_bytes())
    manifest, custody, items = read_snapshot(root, review_id)
    if selection.selection_sha256 != selection_sha256 or manifest.generation != selection.review_generation:
        raise VerificationAdapterError("rerun selection changed or is stale")
    state_manifest,state_items,state_events,stale=read_review_state(root,review_id)
    latest={}
    for event in state_events:
        if event.get("item_id"): latest[event["item_id"]]=event
    by_id = {item.item_id: item for item in state_items}; results = []; failed = False; started = datetime.now(timezone.utc)
    custody_by_id={source.source_id:source for source in custody.sources}
    members_dir=root/"docs/reviews"/review_id/"runs/members"/selection_sha256

    def persist_member(index:int, result:RunMember) -> None:
        member_path=members_dir/f"{index:04d}-{result.item_id}-{result.check_id}.json"
        data=canonical_bytes(result)
        with authority_lock(root,exclusive=True):
            require_no_pending_transaction(root)
            if member_path.exists():
                if member_path.read_bytes()!=data: raise VerificationAdapterError("rerun member result conflicts with an immutable prior result")
                return
            journal=_prepare_transaction_locked(root,proposal_id=f"rerun-member-{selection_sha256[:16]}-{index:04d}",proposal_sha256=sha256_bytes(data),targets=[TransactionTarget.create(member_path,data)])
            recover_transaction(root,journal["id"],_already_locked=True)

    ordinal=0
    for member in selection.members:
        item = by_id.get(member.item_id)
        event=latest.get(member.item_id)
        current_verdict=event.get("verdict") if event and event.get("review_digest")==member.review_digest else None
        mechanical_failure=bool(item and any(diagnostic.blocking for diagnostic in item.diagnostics))
        eligible=(
            selection.mode=="unresolved" and member.item_id not in stale and (current_verdict in {"reject","discuss"} or mechanical_failure)
        ) or (
            selection.mode=="selected" and not (current_verdict=="approve" and member.item_id not in stale)
        )
        if item is None or item.revision!=member.item_revision or item.review_digest!=member.review_digest or not eligible:
            raise VerificationAdapterError("rerun selection member changed or is stale")
        for binding in item.input_bindings:
            source=custody_by_id.get(binding.source_id)
            source_path=_reject_symlinks(root,root/binding.path)
            if source is None or source.path!=binding.path or source.sha256!=member.dependency_hashes.get(binding.source_id) or not source_path.is_file() or sha256_bytes(source_path.read_bytes())!=source.sha256:
                raise VerificationAdapterError("rerun live dependency bytes changed or are stale")
        for check_id in member.check_ids:
            member_path=members_dir/f"{ordinal:04d}-{member.item_id}-{check_id}.json"
            if member_path.is_file():
                prior=model_from_json(RunMember,member_path.read_bytes()); results.append(prior)
                failed = failed or prior.outcome is not RunOutcome.COMPLETED
                ordinal+=1
                continue
            if failed:
                result=RunMember(item_id=member.item_id, item_revision=member.item_revision, check_id=check_id, outcome=RunOutcome.UNPROCESSED, message="an earlier selected checker failed")
                results.append(result); persist_member(ordinal,result); ordinal+=1; continue
            checker = checkers.get(check_id)
            if checker is None:
                result=RunMember(item_id=member.item_id, item_revision=member.item_revision, check_id=check_id, outcome=RunOutcome.REFUSED, message="selected checker is unavailable")
                results.append(result); persist_member(ordinal,result); ordinal+=1; failed = True; continue
            try:
                value = checker(item)
                result=RunMember(item_id=member.item_id, item_revision=member.item_revision, check_id=check_id, outcome=RunOutcome.COMPLETED, result_digest=canonical_digest(value))
            except Exception as exc:
                result=RunMember(item_id=member.item_id, item_revision=member.item_revision, check_id=check_id, outcome=RunOutcome.FAILED, message=str(exc) or type(exc).__name__); failed = True
            results.append(result); persist_member(ordinal,result); ordinal+=1
    report = RunReport(run_id=f"run-{uuid5(manifest.campaign_id, selection_sha256 + started.isoformat()).hex[:20]}", campaign_id=manifest.campaign_id, review_id=review_id, selection_id=selection.selection_id, selection_sha256=selection_sha256, started_at=started, finished_at=datetime.now(timezone.utc), members=tuple(results))
    report_path = root / "docs/reviews" / review_id / "runs" / f"{report.run_id}.json"
    data=canonical_bytes(report)
    with authority_lock(root,exclusive=True):
        require_no_pending_transaction(root); current,_,current_items=read_snapshot(root,review_id,_already_locked=True)
        current_by={item.item_id:item for item in current_items}
        if current.generation!=selection.review_generation or any(current_by.get(member.item_id) is None or current_by[member.item_id].review_digest!=member.review_digest for member in selection.members): raise VerificationAdapterError("rerun selection changed during execution")
        if report_path.exists():
            prior=model_from_json(RunReport,report_path.read_bytes())
            return prior
        journal=_prepare_transaction_locked(root,proposal_id=report.run_id,proposal_sha256=sha256_bytes(data),targets=[TransactionTarget.create(report_path,data)]); recover_transaction(root,journal["id"],_already_locked=True)
    return report


def add_attributable_findings(campaign_dir: Path, review_id: str, *, payload: dict, expected_generation: int) -> dict:
    """Append explicit evidence-bound candidate items without approving them."""
    from pipelines.summary_native.authority import sha256_bytes
    from pipelines.summary_native.authority_apply import TransactionTarget, _prepare_transaction_locked, authority_lock, recover_transaction, require_no_pending_transaction
    from pipelines.summary_native.review.store import ReviewStoreError, _review_dir, read_snapshot
    root=Path(campaign_dir).resolve()
    findings=payload.get("findings") if isinstance(payload,dict) else None
    actor=payload.get("attributed_by") if isinstance(payload,dict) else None
    if not isinstance(actor,str) or not actor.strip() or not isinstance(findings,list) or not findings:
        raise VerificationAdapterError("finding import requires nonempty attributed_by and findings")
    with authority_lock(root,exclusive=True):
        require_no_pending_transaction(root); manifest,custody,items=read_snapshot(root,review_id,_already_locked=True)
        if manifest.generation!=expected_generation: raise ReviewStoreError("REVIEW_STALE_GENERATION: review generation changed","REVIEW_STALE_GENERATION")
        existing={item.item_id for item in items}; additions=[]
        for raw in findings:
            if not isinstance(raw,dict): raise VerificationAdapterError("finding must be an object")
            enriched=dict(raw); diagnostics=[]
            for diagnostic in enriched.get("diagnostics",[]):
                value=dict(diagnostic); details=dict(value.get("details") or {}); details["attributed_by"]=actor.strip(); value["details"]=details; diagnostics.append(value)
            enriched["diagnostics"]=diagnostics
            item=ReviewItem.model_validate(enriched)
            if item.campaign_id!=manifest.campaign_id or item.review_id!=review_id or item.domain.value!={"npc_verification":"npc_finding","duplicate_identity":"duplicate_identity","grounding_documents":"grounding_document"}[manifest.kind.value]:
                raise VerificationAdapterError("finding identity/domain does not match review")
            if item.item_id in existing: raise VerificationAdapterError("finding item id already exists")
            current_sources={source.source_id:source for source in custody.sources}
            for binding in item.input_bindings:
                source=current_sources.get(binding.source_id)
                if source is None or source.path!=binding.path or source.sha256!=binding.custody_sha256: raise VerificationAdapterError("finding source custody is stale")
            existing.add(item.item_id); additions.append(item)
        refs=[*manifest.items,*({"campaign_id":manifest.campaign_id,"review_id":review_id,"item_id":item.item_id,"revision":item.revision,"review_digest":item.review_digest} for item in additions)]
        updated=ReviewManifest.model_validate({**manifest.model_dump(mode="json"),"generation":manifest.generation+1,"items":refs})
        directory=_review_dir(root,review_id); before=(directory/"manifest.json").read_bytes(); targets=[TransactionTarget.replace(directory/"manifest.json",before,canonical_bytes(updated))]
        targets.extend(TransactionTarget.create(directory/"items"/item.item_id/f"{item.revision}.json",canonical_bytes(item)) for item in additions)
        digest=sha256_bytes(canonical_bytes({"actor":actor.strip(),"items":additions,"expected_generation":expected_generation}))
        journal=_prepare_transaction_locked(root,proposal_id=f"finding-add-{digest[:20]}",proposal_sha256=digest,targets=targets); recover_transaction(root,journal["id"],_already_locked=True)
    return {"review_id":review_id,"generation":updated.generation,"added_item_ids":[item.item_id for item in additions],"attributed_by":actor.strip()}
