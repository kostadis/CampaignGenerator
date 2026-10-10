"""Immutable private JSON/Markdown claim reports and current resolution evaluation."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Literal

from pipelines.summary_native.claims.check import CheckAnalysis, annotations_from_active_ledger, bind_extraction_run, check_claims
from pipelines.summary_native.claims.models import (
    CandidateRun, CheckReport, ClaimAnnotation, FindingResolution, SourceSelection,
)
from pipelines.summary_native.claims.selection import _write_owner_only, validate_selection_against_bundle
from pipelines.summary_native.claims.review import load_confirmed_annotations, load_current_resolutions
from pipelines.summary_native.claims.review import mapping_annotation_digest
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.models import BundleSelection
from pipelines.summary_native.review.models import canonical_bytes, canonical_digest
from pipelines.summary_native.review.store import read_review_state


Disposition = Literal["dismiss", "accept_uncertainty", "confirm_incorrect", "discuss", "pending"]


def _require_current_run_revision(run_root: Path, revision: int) -> None:
    revisions = sorted(
        int(path.name.removeprefix("rev-"))
        for path in run_root.glob("rev-[0-9][0-9][0-9][0-9]")
        if path.is_dir() and not path.is_symlink()
    )
    if not revisions or revisions[-1] != revision:
        raise PromotionError(
            "report extraction run is no longer the current declared revision",
            code="CLAIMS_REPORT_STALE",
        )


def evaluate_report(
    selection: SourceSelection,
    analysis: CheckAnalysis,
    *,
    resolutions: tuple[FindingResolution, ...] = (),
    review_id: str | None = None,
) -> CheckReport:
    finding_ids = {item.finding_id for item in analysis.findings}
    by_finding = {item.finding_id: item for item in resolutions}
    if len(by_finding) != len(resolutions) or not set(by_finding) <= finding_ids:
        raise ValueError("disposition names an unknown finding")
    findings_by_id = {item.finding_id: item for item in analysis.findings}
    for finding_id, resolution in by_finding.items():
        if findings_by_id[finding_id].basis in {"mechanical", "gm_confirmed"} and resolution.disposition in {"dismiss", "accept_uncertainty"}:
            raise ValueError(
                "mechanical findings and GM-confirmed findings cannot be dismissed "
                "or accepted as uncertainty"
            )
    ordered_resolutions = tuple(sorted(resolutions, key=lambda item: item.finding_id))
    resolution_digest = canonical_digest({
        "analysis_digest": analysis.analysis_digest,
        "review_id": review_id,
        "resolutions": [item.model_dump(mode="json") for item in ordered_resolutions],
    })
    report_id = f"report-{resolution_digest[:20]}"
    range_dir = f"ch{selection.range_since:03d}-{selection.range_until:03d}"
    base = f"{selection.out_root}/{range_dir}/state/promotion/checks/{report_id}"
    unresolved = [
        finding for finding in analysis.findings
        if by_finding.get(finding.finding_id) is None
        or by_finding[finding.finding_id].disposition not in {"dismiss", "accept_uncertainty"}
    ]
    if not analysis.complete or analysis.extraction_complete is False:
        outcome = "incomplete"
    elif unresolved:
        outcome = "blocked"
    else:
        outcome = "complete"
    values = dict(
        report_id=report_id, review_id=review_id, bundle_digest=selection.bundle_digest,
        source_selection_digest=selection.selection_digest,
        mapping_set_digest=analysis.mapping_set_digest, analysis_digest=analysis.analysis_digest,
        resolution_digest=resolution_digest, annotations=analysis.annotations, findings=analysis.findings,
        resolutions=ordered_resolutions,
        rule_outcomes=analysis.rule_outcomes, effective_horizon=selection.effective_horizon,
        audience=selection.audience, selected_chunk_ids=tuple(item.chunk_id for item in selection.chunks),
        extraction_complete=analysis.extraction_complete, coverage_limitations=analysis.coverage_limitations,
        extraction_run=analysis.extraction_run,
        review_event_ids=tuple(sorted(item.event_id for item in ordered_resolutions if item.event_id)),
        authority_record_ids=analysis.authority_record_ids,
        json_path=f"{base}/report.json", markdown_path=f"{base}/report.md", outcome=outcome,
        report_digest="0" * 64,
    )
    provisional = CheckReport.model_construct(**values)
    values["report_digest"] = canonical_digest(provisional, exclude_fields=frozenset({"report_digest"}))
    return CheckReport.model_validate(values)


def render_markdown(report: CheckReport) -> str:
    resolutions = {item.finding_id: item for item in report.resolutions}
    lines = [
        f"# Claim report {report.report_id}", "",
        f"- Outcome: **{report.outcome}**",
        f"- Analysis: `{report.analysis_digest}`",
        f"- Resolution: `{report.resolution_digest}`",
        f"- Selection: `{report.source_selection_digest}`", "",
        "## Findings", "",
    ]
    if not report.findings:
        lines.append("No specific findings.")
    for finding in report.findings:
        resolution = resolutions.get(finding.finding_id)
        lines.extend([
            f"### {finding.finding_id}", "",
            f"- Category: {', '.join(finding.categories)}",
            f"- Basis: {finding.basis}",
            f"- Severity: {finding.severity}",
            f"- Disposition: {resolution.disposition if resolution else 'pending'}",
            f"- Resolution rationale: {resolution.rationale if resolution else 'No resolution recorded.'}",
            f"- Decision event: {resolution.event_id if resolution and resolution.event_id else 'none'}",
            f"- Decision revision: {resolution.decision_revision if resolution and resolution.decision_revision else 'none'}",
            f"- Evidence identities: {', '.join((*finding.annotation_ids, *finding.source_ids))}",
            f"- Rationale: {finding.rationale}",
            f"- Next action: {finding.next_action}", "",
        ])
        for evidence in finding.evidence:
            lines.append(f"> {evidence.replace(chr(10), ' ')}")
        lines.append("")
    lines.extend(["## Coverage", ""])
    if report.coverage_limitations:
        lines.extend(f"- {item}" for item in report.coverage_limitations)
    else:
        lines.append("- All declared deterministic inputs were checked.")
    return "\n".join(lines).rstrip() + "\n"


def write_report(
    campaign_dir: Path, report: CheckReport,
) -> tuple[Path, Path]:
    root = Path(campaign_dir).resolve()
    json_path = root / report.json_path
    markdown_path = root / report.markdown_path
    _write_owner_only(root, json_path, canonical_bytes(report), conflict_code="CLAIMS_REPORT_CONFLICT")
    _write_owner_only(root, markdown_path, render_markdown(report).encode("utf-8"), conflict_code="CLAIMS_REPORT_CONFLICT")
    return json_path, markdown_path


def _private_read(root: Path, path: Path) -> bytes:
    """Read a campaign-contained artifact without following any symlink component."""
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PromotionError("claim artifact escapes campaign", code="CLAIMS_REPORT_INVALID") from exc
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(root, flags)
    try:
        for component in relative.parts[:-1]:
            child = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd); directory_fd = child
        descriptor = os.open(relative.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), dir_fd=directory_fd)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise PromotionError("claim artifact is not a regular file", code="CLAIMS_REPORT_INVALID")
        with os.fdopen(descriptor, "rb") as stream:
            return stream.read()
    except OSError as exc:
        raise PromotionError("claim artifact is missing or unsafe", code="CLAIMS_REPORT_INVALID") from exc
    finally:
        os.close(directory_fd)


def _current_review_candidates(
    root: Path, selection: SourceSelection, review_id: str, *, _already_locked: bool,
) -> tuple[ClaimAnnotation, ...]:
    """Resolve every current mapping item to its exact immutable candidate payload."""
    _manifest, items, _events, _stale = read_review_state(
        root, review_id, _already_locked=_already_locked,
    )
    wanted = {
        item.item_id.removeprefix("mapping-"): item.proposed_action.details.get("annotation_digest")
        for item in items
        if item.item_id.startswith("mapping-")
        and not item.proposed_action.details.get("authority_record_digests")
    }
    if not wanted:
        return ()
    range_dir = f"ch{selection.range_since:03d}-{selection.range_until:03d}"
    base = root / selection.out_root / range_dir / "state/promotion/claims"
    found: dict[str, ClaimAnnotation] = {}
    paths = sorted((*base.glob("imports/*.json"), *base.glob("runs/*/rev-*/annotations.json")))
    for path in paths:
        try:
            raw = json.loads(_private_read(root, path))
        except (OSError, ValueError) as exc:
            raise PromotionError("candidate evidence is malformed", code="CLAIMS_REPORT_STALE") from exc
        rows = raw.get("annotations", raw) if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            raise PromotionError("candidate evidence is malformed", code="CLAIMS_REPORT_STALE")
        for row in rows:
            try:
                candidate = ClaimAnnotation.model_validate_json(canonical_bytes(row))
            except ValueError as exc:
                raise PromotionError(
                    "candidate evidence is malformed", code="CLAIMS_REPORT_STALE",
                ) from exc
            expected = wanted.get(candidate.occurrence_id)
            if expected is None or mapping_annotation_digest(candidate) != expected:
                continue
            prior = found.get(candidate.occurrence_id)
            if prior is not None and canonical_bytes(prior) != canonical_bytes(candidate):
                raise PromotionError("review candidate identity is ambiguous", code="CLAIMS_REPORT_STALE")
            found[candidate.occurrence_id] = candidate
    missing = sorted(set(wanted) - set(found))
    if missing:
        raise PromotionError(
            "review candidate evidence is missing: " + ", ".join(missing),
            code="CLAIMS_REPORT_STALE",
        )
    return tuple(found[key] for key in sorted(found))


def _report_path(root: Path, bundle: BundleSelection, value: str) -> Path:
    range_dir = f"ch{bundle.selected_range.since:03d}-{bundle.selected_range.until:03d}"
    checks = root / bundle.selected_range.out_root / range_dir / "state/promotion/checks"
    supplied = Path(value)
    if len(supplied.parts) == 1 and not value.endswith(".json"):
        candidate = checks / value / "report.json"
    elif len(supplied.parts) == 1:
        candidate = checks / value
    else:
        candidate = supplied if supplied.is_absolute() else root / supplied
    try:
        candidate.relative_to(checks)
    except ValueError as exc:
        raise PromotionError("check report is outside the selected claims store", code="CLAIMS_REPORT_INVALID") from exc
    return candidate


def load_current_report(
    campaign_dir: Path, value: str, bundle: BundleSelection,
    *, _already_locked: bool = False,
) -> CheckReport:
    """Recompute a persisted report from current selection, review, authority and run evidence."""
    root = Path(campaign_dir).resolve()
    path = _report_path(root, bundle, value)
    if not os.path.lexists(path):
        raise PromotionError("check report is not available", code="CLAIMS_INCOMPLETE")
    try:
        persisted = CheckReport.model_validate_json(_private_read(root, path))
    except ValueError as exc:
        raise PromotionError("check report is malformed", code="CLAIMS_REPORT_INVALID") from exc
    if persisted.json_path != path.relative_to(root).as_posix():
        raise PromotionError("check report path binding differs", code="CLAIMS_REPORT_INVALID")
    expected_digest = canonical_digest(persisted, exclude_fields=frozenset({"report_digest"}))
    if persisted.report_digest != expected_digest:
        raise PromotionError("check report digest differs", code="CLAIMS_REPORT_INVALID")
    range_dir = f"ch{bundle.selected_range.since:03d}-{bundle.selected_range.until:03d}"
    selection_path = (
        root / bundle.selected_range.out_root / range_dir / "state/promotion/selections"
        / f"{persisted.source_selection_digest}.json"
    )
    try:
        selection = SourceSelection.model_validate_json(_private_read(root, selection_path))
    except ValueError as exc:
        raise PromotionError("report selection is malformed", code="CLAIMS_REPORT_INVALID") from exc
    if selection.confirmed_digest is None:
        raise PromotionError("report selection is not confirmed", code="CLAIMS_REPORT_INVALID")
    validate_selection_against_bundle(root, selection, bundle)
    if persisted.bundle_digest != selection.bundle_digest:
        raise PromotionError("report belongs to another source bundle", code="CLAIMS_REPORT_STALE")

    extraction_run = None
    if persisted.extraction_run is not None:
        binding = persisted.extraction_run
        run_path = (
            root / selection.out_root / range_dir / "state/promotion/claims/runs" / binding.run_id
            / f"rev-{binding.revision:04d}" / "run.json"
        )
        run_root = run_path.parent.parent
        _require_current_run_revision(run_root, binding.revision)
        try:
            extraction_run = CandidateRun.model_validate_json(_private_read(root, run_path))
        except ValueError as exc:
            raise PromotionError("report extraction run is malformed", code="CLAIMS_REPORT_STALE") from exc
        if bind_extraction_run(selection, extraction_run) != binding:
            raise PromotionError("report extraction run changed", code="CLAIMS_REPORT_STALE")

    candidates = _current_review_candidates(
        root, selection, bundle.review_id, _already_locked=_already_locked,
    )
    confirmed = load_confirmed_annotations(
        root, bundle.review_id, candidates, _already_locked=_already_locked,
    )
    confirmed_by_id = {item.occurrence_id: item for item in confirmed}
    reviewed_candidates = tuple(
        confirmed_by_id.get(item.occurrence_id, item) for item in candidates
    )
    structured = annotations_from_active_ledger(root, selection)
    authority = {
        record_id: digest
        for source in selection.sources
        for record_id, digest in source.authority_record_digests.items()
    }
    analysis = check_claims(
        selection, (*reviewed_candidates, *structured), active_authority_ids=authority,
        extraction_run=extraction_run,
    )
    resolutions = load_current_resolutions(
        root, bundle.review_id, analysis.findings, _already_locked=_already_locked,
    )
    current = evaluate_report(
        selection, analysis, resolutions=resolutions, review_id=bundle.review_id
    )
    if canonical_bytes(current) != canonical_bytes(persisted):
        raise PromotionError("check report is stale under current review inputs", code="CLAIMS_REPORT_STALE")
    return current


def report_freshness(campaign_dir: Path, value: str, config_path: Path) -> tuple[CheckReport, dict[str, str]]:
    """Read an immutable report and separately evaluate it against current inputs."""
    root = Path(campaign_dir).resolve()
    supplied = Path(value)
    path = supplied if supplied.is_absolute() else root / supplied
    persisted = CheckReport.model_validate_json(_private_read(root, path))
    if persisted.review_id is None:
        return persisted, {"state": "unknown", "code": "CLAIMS_REPORT_LEGACY", "message": "report has no review identity"}
    report_path = root / persisted.json_path
    if report_path != path:
        raise PromotionError("check report path binding differs", code="CLAIMS_REPORT_INVALID")
    promotion_dir = report_path.parent.parent.parent
    selection_path = promotion_dir / "selections" / f"{persisted.source_selection_digest}.json"
    selection = SourceSelection.model_validate_json(_private_read(root, selection_path))
    from pipelines.summary_native.promotion.manifest import build_bundle_selection
    bundle = build_bundle_selection(
        root, out_root=selection.out_root, since=selection.range_since, until=selection.range_until,
        campaign_id=selection.campaign_id, review_id=persisted.review_id,
        rule_versions=selection.rule_versions, config_path=config_path,
    )
    try:
        load_current_report(root, persisted.json_path, bundle)
    except PromotionError as exc:
        if "STALE" not in exc.code:
            raise
        return persisted, {"state": "stale", "code": exc.code, "message": str(exc)}
    return persisted, {"state": "current", "code": "OK", "message": "report matches current review inputs"}
