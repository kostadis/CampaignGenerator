"""CLI boundary for pure claim selection and explicit confirmation saving."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from campaignlib import DEFAULT_MODEL, add_backend_args
from campaignlib.api.client import resolve_cli_model
from campaignlib.config import campaign_root_for_config
from campaignlib.grounding_config import promotion_config_from_summary_native
from pipelines.summary_native.resolve import resolve_extract
from pipelines.summary_native.claims.models import CandidateRun, CheckReport, ClaimAnnotation, SourceSelection
from pipelines.summary_native.claims.packets import assemble_packet, save_packet
from pipelines.summary_native.claims.imports import import_candidates
from pipelines.summary_native.claims.extract import ANNOTATIONS, campaign_model_invoker, extract_candidates
from pipelines.summary_native.claims.check import annotations_from_active_ledger, check_claims
from pipelines.summary_native.claims.report import evaluate_report, render_markdown, report_freshness, write_report
from pipelines.summary_native.claims.review import (
    create_claim_review, load_confirmed_annotations, load_current_resolutions,
    prepare_finding_disposition,
    build_signoff_context,
)
from pipelines.summary_native.claims.selection import confirm_selection, existing_confirmation, mandatory_source_closure, save_confirmed_selection, select_whole_source_chunks, validate_selection_against_bundle
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.manifest import build_bundle_selection
from pipelines.summary_native.review.store import load_campaign_identity
from pipelines.summary_native.review.store import append_review_items, create_review, read_review_state
from pipelines.summary_native.review.models import (
    ReviewItem, ReviewManifest, SourceCustodyGeneration, canonical_bytes,
)
from pipelines.summary_native.review.documents import create_document_review, DocumentReviewError
from pipelines.summary_native.review.models import canonical_digest
from pipelines.summary_native.claims.review import mapping_annotation_digest
from pipelines.summary_native.claims.selection import _write_owner_only


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="summary_native claims")
    sub = parser.add_subparsers(dest="command", required=True)
    select = sub.add_parser("select")
    select.add_argument("--config", required=True)
    select.add_argument("--since", type=int, required=True)
    select.add_argument("--until", type=int, required=True)
    select.add_argument("--out-root")
    select.add_argument("--sources")
    select.add_argument("--json", action="store_true")
    selection = sub.add_parser("selection")
    selection_sub = selection.add_subparsers(dest="selection_command", required=True)
    save = selection_sub.add_parser("save")
    save.add_argument("--config", required=True)
    save.add_argument("--input", required=True)
    save.add_argument("--reviewer")
    save.add_argument("--json", action="store_true")
    chunks = selection_sub.add_parser("chunks")
    chunks.add_argument("--config", required=True)
    chunks.add_argument("--input", required=True)
    chunks.add_argument("--source", action="append", default=[])
    chunks.add_argument("--json", action="store_true")
    for name in ("extract", "import", "review", "check"):
        command = sub.add_parser(name)
        command.add_argument("--config", required=True); command.add_argument("--selection", required=True)
        command.add_argument("--json", action="store_true")
        if name == "extract":
            # The shared registrar: canonical --backend choices plus the Codex/Claude Code effort and thinking
            # flags. No parser default, so a blank flag falls through to grounding.yaml (see below).
            add_backend_args(command, default_backend=None); command.add_argument("--model")
            command.add_argument("--max-tokens", type=int); command.add_argument("--chunk-chars", type=int)
            command.add_argument("--force", action="store_true"); command.add_argument("--verbose", action="store_true")
        if name == "import": command.add_argument("--candidates", required=True)
        if name == "review":
            command.add_argument("--candidates"); command.add_argument("--review", required=True)
        if name == "check": command.add_argument("--review", required=True)
    show = sub.add_parser("show"); show.add_argument("--config", required=True); show.add_argument("--report", required=True); show.add_argument("--json", action="store_true")
    disposition = sub.add_parser("prepare-disposition")
    disposition.add_argument("--config", required=True); disposition.add_argument("--review", required=True)
    disposition.add_argument("--item", required=True); disposition.add_argument("--expected-decision-revision", required=True, type=int)
    disposition.add_argument("--disposition", required=True, choices=("dismiss", "accept_uncertainty"))
    disposition.add_argument("--rationale", required=True); disposition.add_argument("--json", action="store_true")
    return parser


def _load_selection(path: str) -> SourceSelection:
    data = sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()
    return SourceSelection.model_validate_json(data)


def _envelope(ok: bool, code: str, message: str, data: dict) -> dict:
    return {"ok": ok, "code": code, "message": message, "artifacts": [], "data": data}


def _packet(root: Path, selection: SourceSelection):
    packet = assemble_packet(root, selection)
    save_packet(root, selection, packet)
    return packet


def _load_candidate_artifact(root: Path, selection: SourceSelection, value: str) -> tuple[tuple[ClaimAnnotation, ...], CandidateRun | None]:
    supplied = Path(value)
    path = supplied if supplied.is_absolute() else root / supplied
    if path.is_dir():
        run = CandidateRun.model_validate_json((path / "run.json").read_bytes())
        return ANNOTATIONS.validate_json((path / "annotations.json").read_bytes()), run
    raw = json.loads(path.read_text(encoding="utf-8"))
    annotations = tuple(ClaimAnnotation.model_validate_json(json.dumps(item)) for item in raw.get("annotations", []))
    return annotations, None


def _bundle(root: Path, config: Path, selection: SourceSelection, review: str):
    return build_bundle_selection(root, out_root=selection.out_root, since=selection.range_since,
        until=selection.range_until, campaign_id=selection.campaign_id, review_id=review,
        rule_versions=selection.rule_versions, config_path=config)


def _rules(selection: SourceSelection) -> tuple[tuple[str, str], ...]:
    return tuple(tuple(value.rsplit("/", 1)) if "/" in value else (value, "1") for value in selection.rule_versions)


def _resolve_extract_settings(config: Path, args) -> tuple[str, str | None, int, int]:
    """Backend and model: flag > grounding.yaml summary_native.extract > schema, the same chain as
    ``summary_native extract`` (claims extraction is an extraction step of the same pipeline). The
    configured model applies only to the backend it was written for, so a ``--backend`` with no
    ``--model`` gets that backend's own default rather than another backend's id."""
    raw = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    summary = raw.get("summary_native") if isinstance(raw, dict) else None
    promotion = promotion_config_from_summary_native(summary)
    settings = resolve_extract(summary if isinstance(summary, dict) else {}, backend=args.backend, model=args.model)
    return (
        settings.backend,
        settings.model,
        promotion.claim_max_tokens if args.max_tokens is None else args.max_tokens,
        promotion.claim_chunk_chars if args.chunk_chars is None else args.chunk_chars,
    )


def _create_coverage_review(root: Path, config: Path, selection: SourceSelection, review: str) -> dict:
    identity = load_campaign_identity(root); now = datetime.now(timezone.utc); data = config.read_bytes()
    digest = hashlib.sha256(data).hexdigest(); relative = config.relative_to(root).as_posix()
    rules = tuple({"rule_id": key, "version": version} for key, version in _rules(selection))
    item = ReviewItem(
        item_id="claims-coverage", revision=1, campaign_id=identity.campaign_id, review_id=review,
        domain="grounding_document", subject_ref={"subject_id": uuid.uuid5(identity.campaign_id, "claims-coverage"), "kind": "claim"},
        occurrence_id=uuid.uuid5(identity.campaign_id, "claims-coverage-occurrence"),
        locator={"source_path": relative, "anchor": "summary_native"},
        failure_context="No prose candidate chunks were selected; deterministic structured coverage remains explicit.",
        evidence=({"source_id": "claims-config", "source_path": relative, "anchor": "summary_native",
                   "missing_reason": "No model or imported candidate run was declared.", "citation_resolved": True},),
        diagnostics=({"diagnostic_id": "claims-coverage", "legacy_code": "claims-coverage-limited",
                      "message": "No semantic extraction was declared.", "blocking": False},),
        categories={"citation_non_entailment"}, severity="advisory", assignment_basis="mechanical",
        rationale="This item records coverage only and grants no claim authority.",
        proposed_action={"action": "acknowledge_claim_coverage", "details": {"selection_digest": selection.selection_digest}},
        scope={"kind": "global"}, rule_versions=rules,
        input_bindings=({"source_id": "claims-config", "path": relative, "custody_sha256": digest, "semantic_sha256": digest},),
    )
    custody = SourceCustodyGeneration(campaign_id=identity.campaign_id, review_id=review, generation=1,
        recorded_at=now, sources=({"source_id": "claims-config", "path": relative, "sha256": digest, "size": len(data)},))
    manifest = ReviewManifest(campaign_id=identity.campaign_id, review_id=review, kind="grounding_documents",
        generation=1, created_at=now, created_by="claims-cli", selection=({"kind": "document", "id": item.item_id},),
        items=({"campaign_id": identity.campaign_id, "review_id": review, "item_id": item.item_id,
                "revision": 1, "review_digest": item.review_digest},),
        source_manifest={"campaign_id": identity.campaign_id, "review_id": review, "generation": 1,
                         "digest": custody.custody_digest}, rule_versions=rules)
    return create_review(root, manifest, custody, (item,))


def _all_review_candidates(root: Path, selection: SourceSelection, review: str) -> tuple[ClaimAnnotation, ...]:
    _manifest, items, _events, _stale = read_review_state(root, review)
    wanted = {
        item.item_id.removeprefix("mapping-"): item.proposed_action.details.get("annotation_digest")
        for item in items if item.item_id.startswith("mapping-")
    }
    base = root / selection.out_root / f"ch{selection.range_since:03d}-{selection.range_until:03d}" / "state/promotion/claims"
    found: dict[str, ClaimAnnotation] = {}
    for path in sorted((*base.glob("imports/*.json"), *base.glob("runs/*/rev-*/annotations.json"))):
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw.get("annotations", raw) if isinstance(raw, dict) else raw
        for row in rows:
            item = ClaimAnnotation.model_validate_json(json.dumps(row))
            if item.occurrence_id in wanted and mapping_annotation_digest(item) == wanted[item.occurrence_id]:
                prior = found.get(item.occurrence_id)
                if prior is not None and canonical_bytes(prior) != canonical_bytes(item):
                    raise PromotionError("review-bound candidate identity is ambiguous", code="CLAIMS_STALE")
                found[item.occurrence_id] = item
    if set(found) != set(wanted):
        raise PromotionError("review-bound candidate artifact is absent or stale", code="CLAIMS_STALE")
    return tuple(found[key] for key in sorted(found))


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Path(args.config).expanduser().resolve()
    root = campaign_root_for_config(config)
    try:
        if args.command in {"extract", "import", "review", "check"}:
            selection = _load_selection(args.selection)
            review_id = getattr(args, "review", None) or "claims-selection"
            bundle = _bundle(root, config, selection, review_id)
            validate_selection_against_bundle(root, selection, bundle)
            packet = _packet(root, selection)
            if args.command == "extract":
                args.backend, args.model, args.max_tokens, args.chunk_chars = _resolve_extract_settings(config, args)
                # No model for a non-stored backend: that backend's own default, exactly as `summary_native extract`.
                args.model = resolve_cli_model(args, legacy_default=DEFAULT_MODEL).effective_model
                result_value = extract_candidates(root, selection, packet,
                    selected_chunk_ids=tuple(item.chunk_id for item in selection.chunks), backend=args.backend,
                    model=args.model, prompt_version="claims-v1", rules="claims/1",
                    invoke=campaign_model_invoker(args, system="claims candidate extraction", max_tokens=args.max_tokens),
                    max_tokens=args.max_tokens, chunk_chars=args.chunk_chars, force=args.force)
                transport_failed = any(item.outcome == "failed" for item in result_value.run.outcomes)
                result = _envelope(result_value.run.completed_at is not None,
                    "OK" if result_value.run.completed_at else ("CLAIMS_MODEL_FAILED" if transport_failed else "CLAIMS_INCOMPLETE"),
                    "candidate extraction completed" if result_value.run.completed_at else "candidate extraction incomplete",
                    {"run": result_value.run.model_dump(mode="json"), "path": result_value.path.relative_to(root).as_posix(), "cached": result_value.cached})
            elif args.command == "import":
                candidate_bytes = sys.stdin.buffer.read() if args.candidates == "-" else Path(args.candidates).read_bytes()
                path = import_candidates(root, selection, packet, candidate_bytes)
                result = _envelope(True, "OK", "candidate import saved", {"path": path.relative_to(root).as_posix()})
            elif args.command == "review":
                candidates, run_value = _load_candidate_artifact(root, selection, args.candidates) if args.candidates else ((), None)
                structured = annotations_from_active_ledger(root, selection)
                if candidates or structured:
                    review_result = create_claim_review(root, args.review, annotations=(*candidates, *structured), findings=(),
                        created_by="claims-cli", rule_versions=_rules(selection))
                else:
                    review_result = _create_coverage_review(root, config, selection, args.review)
                generation = int(review_result.get("generation", 1))
                binding_path = root / selection.out_root / f"ch{selection.range_since:03d}-{selection.range_until:03d}" / "state/promotion/claims/review-bindings" / f"{args.review}-g{generation}.json"
                _write_owner_only(root, binding_path, canonical_bytes({
                    "review": args.review, "selection_digest": selection.selection_digest,
                    "candidate_artifact": args.candidates, "run": run_value.model_dump(mode="json") if run_value else None,
                }), conflict_code="CLAIMS_REVIEW_CONFLICT")
                result = _envelope(True, "OK", "claim review created", {"review": args.review, "result": review_result,
                    "extraction_run": run_value.model_dump(mode="json") if run_value else None})
            else:
                candidates = _all_review_candidates(root, selection, args.review)
                confirmed = load_confirmed_annotations(root, args.review, candidates)
                confirmed_by_id = {item.occurrence_id: item for item in confirmed}
                reviewed_candidates = tuple(confirmed_by_id.get(item.occurrence_id, item) for item in candidates)
                structured = annotations_from_active_ledger(root, selection)
                authority = {key: value for source in selection.sources for key, value in source.authority_record_digests.items()}
                binding_dir = root / selection.out_root / f"ch{selection.range_since:03d}-{selection.range_until:03d}" / "state/promotion/claims/review-bindings"
                bindings = sorted(binding_dir.glob(f"{args.review}-g*.json"),
                    key=lambda path: int(path.stem.rsplit("-g", 1)[1]))
                if not bindings:
                    raise PromotionError("review candidate binding is absent", code="CLAIMS_STALE")
                binding_path = bindings[-1]
                binding_raw = json.loads(binding_path.read_text(encoding="utf-8"))
                extraction_run = CandidateRun.model_validate_json(json.dumps(binding_raw["run"])) if binding_raw.get("run") else None
                analysis = check_claims(selection, (*reviewed_candidates, *structured), active_authority_ids=authority,
                    extraction_run=extraction_run)
                resolutions = load_current_resolutions(root, args.review, analysis.findings)
                report = evaluate_report(
                    selection, analysis, resolutions=resolutions, review_id=args.review
                ); paths = write_report(root, report)
                if analysis.findings:
                    try: create_claim_review(root, args.review, annotations=(*reviewed_candidates, *structured), findings=analysis.findings, created_by="claims-cli", rule_versions=_rules(selection))
                    except PromotionError as exc:
                        if exc.code != "CLAIMS_REVIEW_EMPTY": raise
                if report.outcome == "complete":
                    support_digest = canonical_digest([
                        item.model_dump(mode="json") for item in sorted(
                            (bundle.timeline, *bundle.references, *bundle.retained_records, *bundle.dependencies),
                            key=lambda value: value.path,
                        )
                    ])
                    context = build_signoff_context(
                        analysis_digest=report.analysis_digest, resolution_digest=report.resolution_digest,
                        support_digest=support_digest, audience=report.audience,
                        rule_versions=_rules(selection),
                    )
                    document_selection = {"documents": [
                        {"id": item.document_id.value, "path": item.path} for item in bundle.documents
                    ]}
                    with tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=True) as stream:
                        stream.write(canonical_bytes(document_selection)); stream.flush()
                        try:
                            create_document_review(root, args.review, Path(stream.name), created_by="claims-cli",
                                signoff_rule_version=2, signoff_context=context)
                        except DocumentReviewError as exc:
                            if "already exist" not in str(exc): raise
                result = _envelope(report.outcome == "complete", "OK" if report.outcome == "complete" else "CLAIMS_INCOMPLETE",
                    "claims check completed", {"report": report.model_dump(mode="json"), "paths": [path.relative_to(root).as_posix() for path in paths]})
        elif args.command == "show":
            report, freshness = report_freshness(root, args.report, config)
            result = _envelope(True, "OK", "claim report loaded", {"report": report.model_dump(mode="json"), "markdown": render_markdown(report), "freshness": freshness})
        elif args.command == "prepare-disposition":
            manifest, items, _events, _stale = read_review_state(root, args.review)
            item = next((value for value in items if value.item_id == args.item), None)
            if item is None: raise PromotionError("claim finding item is absent", code="CLAIMS_DISPOSITION_INVALID")
            evidence = tuple(canonical_bytes(value).decode("utf-8") for value in item.evidence)
            prepared = prepare_finding_disposition(item, alternative=args.disposition, evidence=evidence,
                rationale=args.rationale, expected_decision_revision=args.expected_decision_revision)
            updated = append_review_items(root, args.review, expected_generation=manifest.generation,
                items=(prepared,), sources=())
            result = _envelope(True, "OK", "finding disposition prepared", {"item": prepared.model_dump(mode="json"), "result": updated})
        elif args.command == "selection":
            value = _load_selection(args.input)
            if args.selection_command == "chunks":
                value = select_whole_source_chunks(root, value, tuple(args.source))
                result = _envelope(True, "OK", "explicit chunk scope materialized", {"selection": value.model_dump(mode="json")})
                print(json.dumps(result, sort_keys=True))
                return 0
            if value.confirmed_digest is None:
                reviewer = args.reviewer.strip() if args.reviewer else ""
                if not reviewer:
                    raise PromotionError("selection confirmation requires an explicit reviewer", code="CLAIMS_SELECTION_UNCONFIRMED")
                value = existing_confirmation(root, value, reviewer=reviewer) or confirm_selection(
                    value, reviewer=reviewer, confirmed_at=datetime.now(timezone.utc)
                )
            if value.campaign_id != str(load_campaign_identity(root).campaign_id):
                raise PromotionError("selection belongs to another campaign", code="CLAIMS_SELECTION_INVALID")
            raw = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
            bundle = build_bundle_selection(
                root, out_root=value.out_root, since=value.range_since, until=value.range_until,
                campaign_id=value.campaign_id, review_id="claims-selection",
                rule_versions=value.rule_versions, config_path=config,
            )
            validate_selection_against_bundle(root, value, bundle)
            path = save_confirmed_selection(root, value)
            result = _envelope(True, "OK", "confirmed selection saved", {
                "path": path.relative_to(root).as_posix(), "selection_digest": value.selection_digest,
                "confirmed_digest": value.confirmed_digest,
            })
        else:
            raw = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
            summary = raw.get("summary_native") if isinstance(raw, dict) else {}
            settings = promotion_config_from_summary_native(summary)
            if args.out_root:
                out_path = (root / args.out_root).resolve()
            else:
                configured = summary.get("out_root") if isinstance(summary, dict) else None
                out_path = (config.parent / configured).resolve() if isinstance(configured, str) else root / "docs/summary_native"
            try:
                out_root = out_path.relative_to(root).as_posix()
            except ValueError as exc:
                raise PromotionError("summary_native out_root escapes campaign", code="CLAIMS_SELECTION_INVALID") from exc
            bundle = build_bundle_selection(
                root, out_root=out_root, since=args.since, until=args.until,
                campaign_id=str(load_campaign_identity(root).campaign_id), review_id="claims-selection",
                rule_versions=settings.rule_versions, config_path=config,
            )
            if args.sources:
                selection = _load_selection(args.sources)
                validate_selection_against_bundle(root, selection, bundle)
            else:
                selection = mandatory_source_closure(
                    root, bundle, effective_horizon=f"through-chapter-{args.until}",
                    audience=bundle.audience, rule_versions=settings.rule_versions,
                )
            result = _envelope(True, "OK", "source selection materialized", {
                "selection": selection.model_dump(mode="json"),
                "confirmed": selection.confirmed_digest is not None,
            })
        print(json.dumps(result, sort_keys=True))
        if result["ok"]:
            return 0
        return 70 if result["code"] == "CLAIMS_MODEL_FAILED" else 5
    except (OSError, ValueError, PromotionError) as exc:
        code = exc.code if isinstance(exc, PromotionError) else "CLAIMS_SELECTION_INVALID"
        print(json.dumps(_envelope(False, code, str(exc), {}), sort_keys=True))
        if code in {"CLAIMS_STALE", "CLAIMS_REPORT_STALE", "CLAIMS_REVIEW_STALE"}:
            return 3
        if code in {"CLAIMS_INCOMPLETE", "CLAIMS_SOURCE_CORRECTION_REQUIRED"}:
            return 5
        if code == "CLAIMS_MODEL_FAILED":
            return 70
        return 2


def main() -> int:
    return run()
