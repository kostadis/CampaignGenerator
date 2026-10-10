"""Digest-bound global registry identity merge proposals and application."""
from __future__ import annotations

import base64
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from campaignlib.registry import (
    Entity,
    Registry,
    dump_registry,
    load_registry,
    validate as validate_registry,
)
from pipelines.summary_native import (
    corpus,
    duplicates,
    npc_compose,
    npc_config,
    npc_link,
    npc_slug,
    parse,
    resolve,
    schema,
    validate,
)
from pipelines.summary_native.authority import (
    AuthorityLedger,
    ReviewArtifactRef,
    ReviewDecisionRecord,
    ledger_bytes,
    ledger_digest,
    ledger_path,
    load_ledger,
    sha256_bytes,
)
from pipelines.summary_native.authority_apply import (
    TransactionTarget,
    _json_bytes,
    _prepare_transaction_locked,
    _tip_bytes,
    authority_dir,
    authority_lock,
    ledger_tip_path,
    recover_transaction,
    require_no_pending_transaction,
    validate_ledger_tip,
)
from pipelines.summary_native.review.models import (
    DecisionBinding,
    IdentityProposal,
    IdentityReceipt,
    ProposalTarget,
    SourceCustodyRef,
    canonical_bytes,
    canonicalize,
    model_from_json,
    parse_json_strict,
)
from pipelines.summary_native.review.store import (
    ReviewStoreError,
    _reject_symlinks,
    _review_dir,
    history,
    read_review_state,
    read_snapshot,
)


class IdentityReviewError(ReviewStoreError):
    pass


_REGENERATION_PREFIX = "regenerate and review "


def current_distinct_decisions(
    campaign_dir: Path,
) -> tuple[duplicates.ReviewedDistinctDecision, ...]:
    """Return only current, accepted, exact-scope/evidence distinct decisions.

    Review-owned distinct rulings remain in the review and authority stores.
    They are never projected into registry v1's global ``distinct`` list.
    """

    root = Path(campaign_dir).resolve()
    ledger = load_ledger(root, required=False)
    if ledger is None:
        return ()
    records = [
        record
        for record in ledger.records
        if isinstance(record, ReviewDecisionRecord)
        and record.status == "accepted"
        and record.domain == "duplicate_identity"
        and record.disposition == "distinct"
    ]
    states: dict[str, tuple[tuple, set[str]]] = {}
    result: list[duplicates.ReviewedDistinctDecision] = []
    for record in records:
        if record.review_id not in states:
            _manifest, items, _events, stale = read_review_state(root, record.review_id)
            states[record.review_id] = (items, stale)
        items, stale = states[record.review_id]
        if record.item_id in stale:
            continue
        item = next(
            (
                candidate
                for candidate in items
                if candidate.item_id == record.item_id
                and candidate.revision == record.item_revision
                and candidate.review_digest == record.review_digest
            ),
            None,
        )
        if item is None:
            continue
        details = item.proposed_action.details
        candidates = details.get("candidates") if isinstance(details, dict) else None
        category = details.get("category") if isinstance(details, dict) else None
        evidence_digest = details.get("evidence_digest") if isinstance(details, dict) else None
        if (
            not isinstance(candidates, list)
            or len(candidates) != 2
            or category not in duplicates.CATEGORIES
            or not isinstance(evidence_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", evidence_digest)
        ):
            continue
        names = [candidate.get("registry_name") for candidate in candidates if isinstance(candidate, dict)]
        if len(names) != 2 or not all(isinstance(name, str) and name.strip() for name in names):
            continue
        result.append(
            duplicates.ReviewedDistinctDecision(
                category=category,
                names=frozenset(name.casefold() for name in names),
                scope_kind=item.scope.kind,
                scope_value=item.scope.value,
                evidence_digest=evidence_digest,
                review_id=record.review_id,
                item_id=record.item_id,
                review_digest=record.review_digest,
            )
        )
    return tuple(
        sorted(
            result,
            key=lambda decision: (
                decision.category,
                sorted(decision.names),
                decision.scope_kind,
                decision.scope_value or "",
                decision.review_id,
                decision.item_id,
            ),
        )
    )


def _encoded(data: bytes | None) -> str | None:
    return None if data is None else base64.b64encode(data).decode("ascii")


def _target(path: str, before: bytes | None, after: bytes | None) -> ProposalTarget:
    if before is None:
        operation = "create"
    elif after is None:
        operation = "delete"
    else:
        operation = "replace"
    return ProposalTarget(
        path=path,
        operation=operation,
        before_exists=before is not None,
        before_sha256=sha256_bytes(before) if before is not None else None,
        before_bytes_b64=_encoded(before),
        after_exists=after is not None,
        after_sha256=sha256_bytes(after) if after is not None else None,
        after_bytes_b64=_encoded(after),
    )


def _bytes(target: ProposalTarget, side: str) -> bytes | None:
    encoded = getattr(target, f"{side}_bytes_b64")
    return None if encoded is None else base64.b64decode(encoded, validate=True)


def identity_resolution_instructions(proposal: IdentityProposal) -> dict | None:
    """Return a separate immutable, non-applicable resolution request for blockers.

    Guard removal and authored reconciliation have their own review authority.  This
    object describes that work without smuggling either mutation into a merge.
    """
    supported = {
        "REVIEW_DISTINCT_GUARD": (
            "review_guard_resolution",
            "Review the exact legacy distinct guard through its owning registry workflow.",
        ),
        "REVIEW_REJECTED_ALIAS_GUARD": (
            "review_guard_resolution",
            "Review the exact rejected-alias guard through its owning registry workflow.",
        ),
        "REVIEW_AUTHORED_DOSSIER_CONFLICT": (
            "review_authored_reconciliation",
            "Review the authored dossiers separately and select exact retained content; never concatenate them.",
        ),
        "REVIEW_PUBLISHED_PATH_COLLISION": (
            "review_published_collision",
            "Resolve the two published dossier destinations explicitly before preparing another merge.",
        ),
        "REVIEW_IDENTITY_PATH_COLLISION": (
            "review_path_collision",
            "Resolve the canonical path collision explicitly before preparing another merge.",
        ),
    }
    actions = [
        {"reason": reason, "action": supported[reason][0], "instruction": supported[reason][1]}
        for reason in proposal.blocked_reasons
        if reason in supported
    ]
    if not actions:
        return None
    for action in actions:
        if action["action"] == "review_guard_resolution":
            action["owner_workflow"] = {
                "prepare": [
                    "summary_native", "review", "identity", "guard-prepare",
                    proposal.review_id, "--proposal", proposal.proposal_id,
                    "--reviewer", "<reviewer>", "--note", "<review-note>",
                ],
                "apply": [
                    "summary_native", "review", "identity", "guard-apply",
                    proposal.review_id, "--resolution", "<resolution-id>",
                    "--resolution-sha256", "<resolution-digest>",
                ],
            }
    facts = {
        "kind": "identity_conflict_resolution",
        "blocked_proposal_id": proposal.proposal_id,
        "blocked_proposal_digest": proposal.proposal_digest,
        "actions": actions,
        "applicable": False,
        "mutations": [],
        "requires_new_identity_preview": True,
    }
    digest = sha256_bytes(canonical_bytes(facts))
    return {
        **facts,
        "resolution_id": f"identity-resolution-{digest[:24]}",
        "resolution_digest": digest,
    }


def prepare_guard_resolution(
    campaign_dir: Path,
    review_id: str,
    *,
    blocked_proposal_id: str,
    reviewer: str,
    note: str,
) -> dict:
    """Prepare an exact, separately reviewed removal of one two-name legacy guard."""
    if not reviewer.strip() or not note.strip():
        raise IdentityReviewError("REVIEW_INVALID_GUARD_RESOLUTION: reviewer and note required")
    root = Path(campaign_dir).resolve()
    proposal_path = _reject_symlinks(
        root, _review_dir(root, review_id) / "proposals" / f"{blocked_proposal_id}.json"
    )
    if not proposal_path.is_file():
        raise IdentityReviewError("REVIEW_INVALID_PROPOSAL: blocked proposal missing")
    proposal = model_from_json(IdentityProposal, proposal_path.read_bytes())
    reasons = set(proposal.blocked_reasons)
    if not reasons & {"REVIEW_DISTINCT_GUARD", "REVIEW_REJECTED_ALIAS_GUARD"}:
        raise IdentityReviewError("REVIEW_INVALID_GUARD_RESOLUTION: proposal has no legacy guard")
    _manifest, _custody, items = read_snapshot(root, review_id)
    binding = proposal.decision_bindings[0]
    item = next((candidate for candidate in items if candidate.item_id == binding.item_id), None)
    candidates = item.proposed_action.details.get("candidates") if item is not None else None
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise IdentityReviewError("REVIEW_INVALID_GUARD_RESOLUTION: exact pair unavailable")
    names = [str(candidate["registry_name"]) for candidate in candidates]
    pair = {name.casefold() for name in names}
    registry_path = _configured_registry_path(root)
    before = registry_path.read_bytes()
    if sha256_bytes(before) != proposal.registry_sha256:
        raise IdentityReviewError("REVIEW_STALE_IDENTITY: registry changed; prepare a new preview")
    registry = load_registry(registry_path)
    distinct = [
        guard for guard in registry.distinct
        if {value.casefold() for value in guard} != pair
    ]
    rejected = []
    removed_rejected = False
    for guard in registry.rejected_aliases:
        folded = {value.casefold() for value in guard}
        if pair.issubset(folded):
            if len(folded) != 2:
                raise IdentityReviewError(
                    "REVIEW_GUARD_RESOLUTION_AMBIGUOUS: multi-name rejected guard needs its own review"
                )
            removed_rejected = True
            continue
        rejected.append(list(guard))
    if len(distinct) == len(registry.distinct) and not removed_rejected:
        raise IdentityReviewError("REVIEW_STALE_IDENTITY: exact guard no longer exists")
    revised = Registry(
        version=registry.version,
        campaign=registry.campaign,
        entities=list(registry.entities),
        distinct=[list(guard) for guard in distinct],
        rejected_aliases=rejected,
    )
    validate_registry(revised)
    after = _registry_bytes_preserving_opaque(before, revised)
    target = _target(registry_path.relative_to(root).as_posix(), before, after)
    base = {
        "version": 1,
        "kind": "identity_guard_resolution",
        "campaign_id": str(proposal.campaign_id),
        "review_id": review_id,
        "blocked_proposal_id": proposal.proposal_id,
        "blocked_proposal_digest": proposal.proposal_digest,
        "item_id": binding.item_id,
        "pair": names,
        "reviewer": reviewer.strip(),
        "note": note.strip(),
        "target": canonicalize(target),
        "requires_new_identity_preview": True,
    }
    digest = sha256_bytes(canonical_bytes(base))
    resolution = {
        **base,
        "resolution_id": f"guard-resolution-{digest[:24]}",
        "resolution_digest": digest,
    }
    path = _review_dir(root, review_id) / "proposals" / f"{resolution['resolution_id']}.json"
    data = canonical_bytes(resolution)
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        if path.exists():
            if _reject_symlinks(root, path).read_bytes() != data:
                raise IdentityReviewError("REVIEW_PROPOSAL_CONFLICT")
        else:
            journal = _prepare_transaction_locked(
                root,
                proposal_id=resolution["resolution_id"],
                proposal_sha256=digest,
                targets=[TransactionTarget.create(path, data)],
            )
            recover_transaction(root, journal["id"], _already_locked=True)
    return resolution


def apply_guard_resolution(
    campaign_dir: Path,
    review_id: str,
    *,
    resolution_id: str,
    resolution_digest: str,
) -> dict:
    """Apply only the exact registry guard target previewed above."""
    root = Path(campaign_dir).resolve()
    path = _reject_symlinks(
        root, _review_dir(root, review_id) / "proposals" / f"{resolution_id}.json"
    )
    if not path.is_file():
        raise IdentityReviewError("REVIEW_INVALID_GUARD_RESOLUTION: proposal missing")
    resolution = parse_json_strict(path.read_bytes())
    if not isinstance(resolution, dict):
        raise IdentityReviewError("REVIEW_INVALID_GUARD_RESOLUTION")
    base = {
        key: value for key, value in resolution.items()
        if key not in {"resolution_id", "resolution_digest"}
    }
    if (
        resolution.get("resolution_id") != resolution_id
        or resolution.get("resolution_digest") != resolution_digest
        or sha256_bytes(canonical_bytes(base)) != resolution_digest
    ):
        raise IdentityReviewError("REVIEW_INVALID_GUARD_RESOLUTION: digest mismatch")
    if resolution.get("review_id") != review_id:
        raise IdentityReviewError("REVIEW_INVALID_GUARD_RESOLUTION: review binding mismatch")
    blocked_path = _reject_symlinks(
        root,
        _review_dir(root, review_id)
        / "proposals"
        / f"{resolution.get('blocked_proposal_id')}.json",
    )
    if not blocked_path.is_file():
        raise IdentityReviewError("REVIEW_INVALID_GUARD_RESOLUTION: blocked proposal missing")
    blocked = model_from_json(IdentityProposal, blocked_path.read_bytes())
    if (
        str(blocked.campaign_id) != resolution.get("campaign_id")
        or blocked.review_id != review_id
        or blocked.proposal_digest != resolution.get("blocked_proposal_digest")
        or blocked.decision_bindings[0].item_id != resolution.get("item_id")
    ):
        raise IdentityReviewError("REVIEW_INVALID_GUARD_RESOLUTION: proposal binding mismatch")
    target = ProposalTarget.model_validate(resolution["target"])
    event = {
        "version": 1,
        "kind": "identity_guard_resolution",
        "event_id": f"event-{resolution_id}",
        "review_id": review_id,
        "item_id": resolution["item_id"],
        "resolution_id": resolution_id,
        "resolution_digest": resolution_digest,
        "reviewer": resolution["reviewer"],
        "note": resolution["note"],
        "recorded_at": datetime.now(timezone.utc),
        "requires_new_identity_preview": True,
    }
    # Resolution audit is deliberately outside decision events: it has no verdict
    # or decision revision and must never enter decision projection/CAS.
    event_path = (
        _review_dir(root, review_id)
        / "runs"
        / "guard-resolutions"
        / f"event-{resolution_id}.json"
    )
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        if event_path.exists():
            return parse_json_strict(event_path.read_bytes())
        transaction_target = _transaction_target(root, target)
        if transaction_target is None:
            raise IdentityReviewError("REVIEW_STALE_IDENTITY: guard target already changed")
        event_data = canonical_bytes(event)
        journal = _prepare_transaction_locked(
            root,
            proposal_id=resolution_id,
            proposal_sha256=resolution_digest,
            targets=[transaction_target, TransactionTarget.create(event_path, event_data)],
        )
        recover_transaction(root, journal["id"], _already_locked=True)
    return event


def _regeneration_stage(path: str) -> str | None:
    parts = Path(path).parts
    if "evidence" in parts or Path(path).name.startswith("link_"):
        return "npc-link"
    if "draft" in parts or "drafts" in parts:
        return "npc-draft"
    if "gm" in parts:
        return "npc-compose"
    if len(parts) == 3 and parts[:2] == ("docs", "npcs"):
        return None
    return None


def _range_command(
    root: Path, path: str, stage: str, subject: str
) -> tuple[list[str], Path] | None:
    parts = Path(path).parts
    index = next(
        (i for i, part in enumerate(parts) if re.fullmatch(r"ch\d{3}-\d{3}", part)),
        None,
    )
    if index is None:
        return None
    match = re.fullmatch(r"ch(\d{3})-(\d{3})", parts[index])
    assert match is not None
    npc_root = Path(*parts[:index])
    argv = [
        "summary_native",
        stage,
        "--config",
        str(root / "config/config.yaml"),
        "--since",
        str(int(match.group(1))),
        "--until",
        str(int(match.group(2))),
        "--npc-root",
        npc_root.as_posix(),
    ]
    if stage == "npc-link":
        argv.append("--force")
    else:
        argv.extend(["--name", subject])
        if stage == "npc-draft":
            argv.append("--force")
    return argv, root / npc_root / parts[index]


def _link_outputs(range_dir: Path, root: Path) -> set[str]:
    paths = {
        range_dir / npc_link.LINK_MANIFEST,
        range_dir / npc_link.LINK_REPORT_JSON,
        range_dir / npc_link.LINK_REPORT_MD,
    }
    evidence = range_dir / npc_link.EVIDENCE_DIR
    if evidence.is_dir():
        paths.update(path for path in evidence.glob("*.md") if path.is_file())
    return {
        path.relative_to(root).as_posix()
        for path in paths
        if path.is_file()
    }


def prepare_identity_regeneration(
    campaign_dir: Path,
    review_id: str,
    *,
    receipt_id: str,
    selected_paths: list[str] | tuple[str, ...],
) -> dict:
    """Persist an affected-only regeneration schedule bound to an applied receipt.

    Execution remains in the existing NPC commands because draft generation may call a
    model.  The schedule is created under the campaign lock and never publishes or signs
    generated prose.
    """
    root = Path(campaign_dir).resolve()
    receipt_path = _reject_symlinks(
        root, _review_dir(root, review_id) / "receipts" / f"{receipt_id}.json"
    )
    if not receipt_path.is_file():
        raise IdentityReviewError("REVIEW_INVALID_RECEIPT: identity receipt missing")
    receipt = model_from_json(IdentityReceipt, receipt_path.read_bytes())
    if receipt.review_id != review_id or receipt.receipt_id != receipt_id:
        raise IdentityReviewError("REVIEW_INVALID_RECEIPT: identity receipt binding mismatch")
    allowed = {
        value.removeprefix(_REGENERATION_PREFIX)
        for value in receipt.remaining_review_work
        if value.startswith(_REGENERATION_PREFIX)
    }
    selected = tuple(dict.fromkeys(selected_paths))
    if not selected:
        raise IdentityReviewError("REVIEW_INVALID_SELECTION: regeneration selection is empty")
    if len(selected) != len(selected_paths):
        raise IdentityReviewError("REVIEW_INVALID_SELECTION: duplicate regeneration path")
    unknown = sorted(set(selected) - allowed)
    if unknown:
        raise IdentityReviewError(
            f"REVIEW_INVALID_SELECTION: regeneration would broaden receipt: {', '.join(unknown)}"
        )
    plan_dir = _review_dir(root, review_id) / "runs" / "identity-regeneration"
    if plan_dir.is_dir():
        for existing_path in sorted(plan_dir.glob("identity-regeneration-*.json")):
            if ".result." in existing_path.name or existing_path.name.endswith(".result.json"):
                continue
            existing = parse_json_strict(_reject_symlinks(root, existing_path).read_bytes())
            if (
                isinstance(existing, dict)
                and existing.get("receipt_digest") == receipt.receipt_digest
                and existing.get("selected_paths") == list(selected)
            ):
                return existing
    grouped: dict[tuple[str, tuple[str, ...]], dict] = {}
    for path in selected:
        stage = _regeneration_stage(path)
        if stage is None:
            continue
        command = _range_command(root, path, stage, receipt.canonical_registry_name)
        if command is None:
            raise IdentityReviewError(
                f"REVIEW_INVALID_SELECTION: no bounded producer command for {path}"
            )
        argv, range_dir = command
        if stage == "npc-link":
            complete = _link_outputs(range_dir, root)
            if not complete or not complete.issubset(allowed) or not complete.issubset(selected):
                raise IdentityReviewError(
                    "REVIEW_INVALID_SELECTION: npc-link would broaden beyond the complete "
                    f"receipt-bound range {range_dir.relative_to(root).as_posix()}"
                )
            inputs = sorted(complete)
            canonical_stem = npc_slug.stem_for("npc", receipt.canonical_registry_name)
            outputs_set = {
                (range_dir / npc_link.LINK_MANIFEST).relative_to(root).as_posix(),
                (range_dir / npc_link.LINK_REPORT_JSON).relative_to(root).as_posix(),
                (range_dir / npc_link.LINK_REPORT_MD).relative_to(root).as_posix(),
            }
            cleanup = []
            for candidate in inputs:
                candidate_path = root / candidate
                if candidate_path.parent.name != npc_link.EVIDENCE_DIR:
                    continue
                subject = _subject_metadata(candidate_path.read_bytes())
                if subject and subject != receipt.canonical_registry_name:
                    destination = candidate_path.with_name(f"{canonical_stem}.md")
                    outputs_set.add(destination.relative_to(root).as_posix())
                    cleanup.append(candidate)
                else:
                    outputs_set.add(candidate)
            outputs = sorted(outputs_set)
        else:
            inputs = sorted(
                candidate
                for candidate in selected
                if _regeneration_stage(candidate) == stage
                and _range_command(root, candidate, stage, receipt.canonical_registry_name)
                == command
            )
            canonical_stem = npc_slug.stem_for("npc", receipt.canonical_registry_name)
            outputs = sorted({
                (Path(candidate).with_name(f"{canonical_stem}{Path(candidate).suffix}"))
                .as_posix()
                for candidate in inputs
            })
            cleanup = sorted(set(inputs) - set(outputs))
            for output in outputs:
                output_path = root / output
                if output_path.exists() and output not in allowed:
                    raise IdentityReviewError(
                        f"REVIEW_INVALID_SELECTION: canonical output collision {output}"
                    )
        key = (stage, tuple(argv))
        cleanup_bindings = []
        for stale in cleanup:
            stale_path = _reject_symlinks(root, root / stale)
            before = stale_path.read_bytes() if stale_path.is_file() else None
            cleanup_bindings.append({
                "path": stale,
                "before_exists": before is not None,
                "before_sha256": sha256_bytes(before) if before is not None else None,
                "before_bytes_b64": _encoded(before),
            })
        grouped[key] = {
            "stage": stage,
            "subject": receipt.canonical_registry_name,
            "argv": argv,
            "input_paths": inputs,
            "selected_outputs": outputs,
            "stale_cleanup_paths": cleanup,
            "stale_cleanup_bindings": cleanup_bindings,
            "state": "pending_generation",
            "requires_review_signoff": True,
        }
    jobs = list(grouped.values())
    facts = {
        "version": 1,
        "kind": "identity_regeneration_selection",
        "campaign_id": str(receipt.campaign_id),
        "review_id": review_id,
        "receipt_id": receipt.receipt_id,
        "receipt_digest": receipt.receipt_digest,
        "proposal_id": receipt.proposal_id,
        "proposal_digest": receipt.proposal_digest,
        "selected_paths": list(selected),
        "jobs": jobs,
        "pending_signoff_paths": [
            path for path in selected if _regeneration_stage(path) is None
        ],
        "publication_state": "pending_review",
    }
    digest = sha256_bytes(canonical_bytes(facts))
    plan = {
        **facts,
        "selection_id": f"identity-regeneration-{digest[:24]}",
        "selection_digest": digest,
    }
    plan_path = (
        _review_dir(root, review_id)
        / "runs"
        / "identity-regeneration"
        / f"{plan['selection_id']}.json"
    )
    data = canonical_bytes(plan)
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        if plan_path.exists():
            if _reject_symlinks(root, plan_path).read_bytes() != data:
                raise IdentityReviewError("REVIEW_SELECTION_CONFLICT")
            return plan
        journal = _prepare_transaction_locked(
            root,
            proposal_id=plan["selection_id"],
            proposal_sha256=digest,
            targets=[TransactionTarget.create(plan_path, data)],
        )
        recover_transaction(root, journal["id"], _already_locked=True)
    return plan


def execute_identity_regeneration(
    campaign_dir: Path,
    review_id: str,
    *,
    receipt_id: str,
    selected_paths: list[str] | tuple[str, ...],
    runner=None,
) -> dict:
    """Execute parser-compatible bounded jobs, with every runner call outside the lock."""
    root = Path(campaign_dir).resolve()
    plan = prepare_identity_regeneration(
        root, review_id, receipt_id=receipt_id, selected_paths=selected_paths
    )
    if not plan["jobs"]:
        raise IdentityReviewError(
            "REVIEW_SIGNOFF_REQUIRED: selection contains only publication/signoff work; "
            "review the generated prose and use the exact NPC signoff/publish workflow"
        )
    if runner is None:
        runner = lambda argv, cwd: subprocess.run(  # noqa: E731
            argv,
            cwd=cwd,
            text=True,
            check=False,
            timeout=3600,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    from pipelines.summary_native.cli import build_parser

    def cleanup_job(job, ordinal: int) -> None:
        if not job["stale_cleanup_paths"]:
            return
        marker_path = (
            _review_dir(root, review_id)
            / "runs"
            / "identity-regeneration"
            / f"{plan['selection_id']}-{ordinal:03d}.cleanup.json"
        )
        with authority_lock(root, exclusive=True):
            require_no_pending_transaction(root)
            if marker_path.is_file():
                marker = parse_json_strict(_reject_symlinks(root, marker_path).read_bytes())
                if not isinstance(marker, dict) or marker.get("selection_digest") != plan["selection_digest"]:
                    raise IdentityReviewError("REVIEW_SELECTION_CONFLICT: cleanup marker mismatch")
                return
            cleanup_targets = []
            checked = []
            for binding in job["stale_cleanup_bindings"]:
                stale_path = _reject_symlinks(root, root / binding["path"])
                current = stale_path.read_bytes() if stale_path.is_file() else None
                expected = (
                    base64.b64decode(binding["before_bytes_b64"], validate=True)
                    if binding["before_bytes_b64"] is not None else None
                )
                if current is not None and current != expected:
                    raise IdentityReviewError(
                        f"REVIEW_STALE_IDENTITY: cleanup target changed during generation: {binding['path']}"
                    )
                checked.append((stale_path, current))
            for stale_path, current in checked:
                if current is not None:
                    cleanup_targets.append(TransactionTarget.delete(stale_path, current))
            marker = {
                "version": 1,
                "kind": "identity_regeneration_cleanup",
                "selection_digest": plan["selection_digest"],
                "paths": job["stale_cleanup_paths"],
                "state": "cleanup_complete",
            }
            marker_data = canonical_bytes(marker)
            cleanup_digest = sha256_bytes(marker_data)
            journal = _prepare_transaction_locked(
                root,
                proposal_id=f"{plan['selection_id']}-cleanup-{ordinal}",
                proposal_sha256=cleanup_digest,
                targets=[*cleanup_targets, TransactionTarget.create(marker_path, marker_data)],
            )
            recover_transaction(root, journal["id"], _already_locked=True)

    results = []
    for job in plan["jobs"]:
        result_path = (
            _review_dir(root, review_id)
            / "runs"
            / "identity-regeneration"
            / f"{plan['selection_id']}-{len(results) + 1:03d}.result.json"
        )
        if result_path.is_file():
            prior = parse_json_strict(_reject_symlinks(root, result_path).read_bytes())
            if not isinstance(prior, dict) or prior.get("argv") != job["argv"]:
                raise IdentityReviewError("REVIEW_SELECTION_CONFLICT: regeneration result mismatch")
            results.append(prior)
            if prior.get("returncode") != 0:
                break
            cleanup_job(job, len(results))
            if prior.get("state") == "generated_pending_cleanup":
                prior = {**prior, "state": "generated_pending_review"}
                results[-1] = prior
            continue
        # Prove each saved argv is accepted by the public parser before execution.
        build_parser().parse_args(job["argv"][1:])
        completed = runner(list(job["argv"]), root)
        returncode = int(getattr(completed, "returncode", completed))
        if returncode == 0:
            missing = [path for path in job["selected_outputs"] if not (root / path).is_file()]
            if missing:
                returncode = 6
        result = {
            "stage": job["stage"],
            "argv": job["argv"],
            "selected_outputs": job["selected_outputs"],
            "returncode": returncode,
            "state": (
                "generated_pending_cleanup"
                if returncode == 0 and job["stale_cleanup_paths"]
                else "generated_pending_review" if returncode == 0 else "failed"
            ),
        }
        results.append(result)
        data = canonical_bytes(result)
        with authority_lock(root, exclusive=True):
            require_no_pending_transaction(root)
            if not result_path.exists():
                journal = _prepare_transaction_locked(
                    root,
                    proposal_id=f"{plan['selection_id']}-result-{len(results)}",
                    proposal_sha256=sha256_bytes(data),
                    targets=[TransactionTarget.create(result_path, data)],
                )
                recover_transaction(root, journal["id"], _already_locked=True)
        if returncode == 0:
            cleanup_job(job, len(results))
            if result["state"] == "generated_pending_cleanup":
                result["state"] = "generated_pending_review"
        if returncode != 0:
            break
    pending_publication = plan["pending_signoff_paths"]
    pending_review = sorted({
        path
        for job in plan["jobs"]
        for path in job["selected_outputs"]
    } | set(pending_publication))
    return {
        "selection_id": plan["selection_id"],
        "selection_digest": plan["selection_digest"],
        "results": results,
        "pending_review_signoff": pending_review,
        "pending_publication": pending_publication,
        "complete": (
            len(results) == len(plan["jobs"])
            and all(result["returncode"] == 0 for result in results)
            and not pending_publication
        ),
    }


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def _subject(entity: Entity) -> str:
    return f"{entity.type}:{_slug(entity.name)}"


_REGISTRY_KEYS = {"version", "campaign", "entities", "distinct", "rejected_aliases"}
_ENTITY_KEYS = {"name", "type", "aliases", "provenance", "source", "scope", "note"}


def _registry_bytes_preserving_opaque(
    before: bytes, revised: Registry, *, removed_name: str | None = None
) -> bytes:
    raw = yaml.safe_load(before) or {}
    if not isinstance(raw, dict) or not isinstance(raw.get("entities"), list):
        raise IdentityReviewError("REVIEW_IDENTITY_INVENTORY_INCOMPLETE: invalid raw registry")
    by_name = {
        entity.get("name"): entity
        for entity in raw["entities"]
        if isinstance(entity, dict) and isinstance(entity.get("name"), str)
    }
    if removed_name is not None:
        removed = by_name.get(removed_name, {})
        opaque = set(removed) - _ENTITY_KEYS
        if opaque:
            raise IdentityReviewError("REVIEW_IDENTITY_OPAQUE_METADATA")
    known = yaml.safe_load(dump_registry(revised)) or {}
    output = {key: value for key, value in raw.items() if key not in _REGISTRY_KEYS}
    output.update({key: value for key, value in known.items() if key != "entities"})
    entities = []
    for entity in known["entities"]:
        prior = by_name.get(entity["name"], {})
        preserved = {key: value for key, value in prior.items() if key not in _ENTITY_KEYS}
        preserved.update(entity)
        entities.append(preserved)
    output["entities"] = entities
    return yaml.safe_dump(output, sort_keys=False, allow_unicode=True).encode("utf-8")


def _merged(registry: Registry, survivor: Entity, loser: Entity) -> Registry:
    aliases: list[str] = []
    for value in [*survivor.aliases, loser.name, *loser.aliases]:
        if value != survivor.name and value not in aliases:
            aliases.append(value)
    loser_metadata = "; ".join(
        f"{key}={value}"
        for key, value in (
            ("name", loser.name),
            ("provenance", loser.provenance),
            ("source", loser.source),
            ("note", loser.note),
        )
        if value is not None
    )
    notes = [
        value
        for value in (
            survivor.note,
            f"Merged identity metadata: {loser_metadata}" if loser_metadata else None,
        )
        if value
    ]
    replacement = Entity(
        name=survivor.name,
        type=survivor.type,
        aliases=aliases,
        provenance=survivor.provenance,
        source=survivor.source,
        scope=survivor.scope,
        note="\n".join(notes) or None,
    )
    merged = Registry(
        version=registry.version,
        campaign=registry.campaign,
        entities=[
            replacement if entity is survivor else entity
            for entity in registry.entities
            if entity is not loser
        ],
        distinct=[list(group) for group in registry.distinct],
        rejected_aliases=[list(group) for group in registry.rejected_aliases],
    )
    validate_registry(merged)
    return merged


def _safe_relative(root: Path, value: str) -> tuple[str, Path]:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise IdentityReviewError("REVIEW_IDENTITY_INVENTORY_INCOMPLETE: path escapes campaign")
    path = _reject_symlinks(root, root / relative)
    return path.relative_to(root).as_posix(), path


def _read_exact(root: Path, value: str, expected: str | None = None) -> tuple[str, Path, bytes]:
    relative, path = _safe_relative(root, value)
    if not path.is_file():
        raise IdentityReviewError(
            f"REVIEW_IDENTITY_INVENTORY_INCOMPLETE: missing dependency {relative}"
        )
    data = path.read_bytes()
    if expected is not None and sha256_bytes(data) != expected:
        raise IdentityReviewError(
            f"REVIEW_STALE_IDENTITY: dependency changed: {relative}", "REVIEW_STALE_IDENTITY"
        )
    return relative, path, data


@dataclass
class _Inventory:
    targets: dict[str, ProposalTarget] = field(default_factory=dict)
    inspected: set[str] = field(default_factory=set)
    affected: set[str] = field(default_factory=set)
    generative: set[str] = field(default_factory=set)
    blocked: list[str] = field(default_factory=list)
    stale_reviews: dict[str, set[str]] = field(default_factory=dict)

    def add(self, path: str, before: bytes | None, after: bytes | None, *, affected: bool) -> None:
        candidate = _target(path, before, after)
        current = self.targets.get(path)
        if current is not None and current != candidate:
            current_no_op = (
                current.before_exists == current.after_exists
                and current.before_sha256 == current.after_sha256
            )
            candidate_no_op = (
                candidate.before_exists == candidate.after_exists
                and candidate.before_sha256 == candidate.after_sha256
            )
            same_before = (
                current.before_exists == candidate.before_exists
                and current.before_sha256 == candidate.before_sha256
            )
            if current_no_op and same_before:
                pass
            elif candidate_no_op and same_before:
                return
            else:
                self.blocked.append("REVIEW_IDENTITY_OVERLAPPING_TARGET")
                return
        self.targets[path] = candidate
        self.inspected.add(path)
        if affected and before != after:
            self.affected.add(path)


def _grounding_config(root: Path) -> tuple[dict, Path]:
    config = root / "config" / "grounding.yaml"
    if not config.is_file():
        return {}, _reject_symlinks(root, root / schema.DEFAULT_OUT_ROOT)
    try:
        raw = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        configured = raw.get("summary_native") or {}
        value = configured.get("out_root") or schema.DEFAULT_OUT_ROOT
        if not isinstance(raw, dict) or not isinstance(configured, dict) or not isinstance(value, str):
            raise ValueError
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError
        resolved = schema.resolve_under(root, value)
        _reject_symlinks(root, root / relative)
        return configured, resolved
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise IdentityReviewError(
            "REVIEW_IDENTITY_INVENTORY_INCOMPLETE: invalid grounding configuration"
        ) from exc


def _configured_out_root(root: Path) -> Path:
    return _grounding_config(root)[1]


def _configured_registry_path(root: Path) -> Path:
    configured, _out_root = _grounding_config(root)
    try:
        path = resolve.resolve_registry_path(root, None, configured)
    except (OSError, ValueError) as exc:
        raise IdentityReviewError(
            "REVIEW_IDENTITY_INVENTORY_INCOMPLETE: invalid registry configuration"
        ) from exc
    if path is None:
        raise IdentityReviewError("REVIEW_IDENTITY_INVENTORY_INCOMPLETE: registry not found")
    try:
        return _reject_symlinks(root, Path(path))
    except ReviewStoreError as exc:
        raise IdentityReviewError("REVIEW_IDENTITY_SYMLINK_ALIAS") from exc


def _configured_npc_roots(root: Path, out_root: Path) -> tuple[Path, ...]:
    try:
        configured = npc_config.load_npc_dossiers_config(root / "config/npc_dossiers.yaml")
        npc_relative = Path(configured.npc_root)
        if npc_relative.is_absolute() or ".." in npc_relative.parts:
            raise ValueError
        roots = {root / npc_relative}
    except (OSError, UnicodeError, ValueError) as exc:
        raise IdentityReviewError(
            "REVIEW_IDENTITY_INVENTORY_INCOMPLETE: invalid NPC dossier configuration"
        ) from exc
    if out_root.is_dir():
        for range_dir in out_root.iterdir():
            nested = range_dir / "npcs"
            if nested.exists():
                roots.add(nested)
    return tuple(sorted(roots))


def _corpus_plan(
    root: Path,
    out_root: Path,
    merged: Registry,
    registry_after: bytes,
    affected_subject_ids: set[str],
    inventory: _Inventory,
) -> None:
    if not out_root.exists():
        return
    if out_root.is_symlink() or not out_root.is_dir():
        inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
        return
    children = sorted(out_root.iterdir())
    if any(path.is_symlink() for path in children):
        inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
    range_dirs = [path for path in children if path.is_dir() and not path.is_symlink()]
    loose_manifests = sorted(out_root.glob("manifest.json"))
    manifest_paths = [*loose_manifests, *(path / "manifest.json" for path in range_dirs)]
    for manifest_path in manifest_paths:
        if not manifest_path.is_file() or manifest_path.is_symlink():
            inventory.blocked.append("REVIEW_IDENTITY_INVENTORY_INCOMPLETE")
            continue
        relative = manifest_path.relative_to(root).as_posix()
        before_manifest = manifest_path.read_bytes()
        try:
            manifest = parse_json_strict(before_manifest)
        except ValueError:
            inventory.blocked.append("REVIEW_IDENTITY_INVENTORY_INCOMPLETE")
            continue
        dependencies = manifest.get("identity_dependencies") if isinstance(manifest, dict) else None
        if (
            not isinstance(manifest, dict)
            or manifest.get("kind") != "summary_native"
            or manifest.get("complete") is not True
            or not isinstance(manifest.get("files"), list)
            or not manifest.get("files")
            or not isinstance(dependencies, dict)
            or dependencies.get("version") != 2
            or dependencies.get("precision") != "subject"
            or dependencies.get("inventory_complete") is not True
            or not isinstance(dependencies.get("artifacts"), list)
        ):
            inventory.blocked.append("REVIEW_IDENTITY_INVENTORY_INCOMPLETE")
            continue

        range_affected = any(
            isinstance(artifact, dict)
            and bool(set(artifact.get("subject_ids") or ()) & affected_subject_ids)
            for artifact in dependencies["artifacts"]
        )
        if not range_affected:
            inventory.add(relative, before_manifest, before_manifest, affected=False)
            failed = False
            for entry in [*manifest["files"], *dependencies["artifacts"]]:
                if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                    failed = True
                    break
                try:
                    entry_relative, _entry_path, entry_data = _read_exact(
                        root, entry["path"], entry.get("sha256")
                    )
                except IdentityReviewError:
                    failed = True
                    break
                inventory.add(entry_relative, entry_data, entry_data, affected=False)
            if failed:
                inventory.blocked.append("REVIEW_IDENTITY_INVENTORY_INCOMPLETE")
            continue

        files = []
        failed = False
        for source in manifest["files"]:
            if not isinstance(source, dict) or not isinstance(source.get("path"), str):
                failed = True
                break
            try:
                source_relative, source_path, source_data = _read_exact(
                    root, source["path"], source.get("sha256")
                )
                files.append(parse.parse_file(source_path, root))
                inventory.add(source_relative, source_data, source_data, affected=False)
            except (IdentityReviewError, OSError, UnicodeError, ValueError):
                failed = True
                break
        if failed:
            inventory.blocked.append("REVIEW_IDENTITY_INVENTORY_INCOMPLETE")
            continue

        artifact_entries: list[dict] = []
        current_dossiers: set[str] = set()
        for artifact in dependencies["artifacts"]:
            if (
                not isinstance(artifact, dict)
                or not isinstance(artifact.get("path"), str)
                or not isinstance(artifact.get("sha256"), str)
                or not isinstance(artifact.get("subject_ids", []), list)
            ):
                failed = True
                break
            try:
                artifact_relative, _artifact_path, artifact_data = _read_exact(
                    root, artifact["path"], artifact["sha256"]
                )
            except IdentityReviewError:
                failed = True
                break
            inventory.add(artifact_relative, artifact_data, artifact_data, affected=False)
            if (
                artifact.get("consumer") == "summary_native.build"
                and "/dossiers/" in f"/{artifact_relative}"
                and artifact_relative.endswith(".md")
            ):
                current_dossiers.add(artifact_relative)
            elif artifact_relative.endswith(("/validation_report.json", "/validation_report.md")):
                # Rebuilt below with the proposed registry. Keeping the old
                # report while advancing dependency metadata would falsely
                # certify findings calculated for the losing identity.
                pass
            else:
                artifact_entries.append(dict(artifact))
        if failed:
            inventory.blocked.append("REVIEW_IDENTITY_INVENTORY_INCOMPLETE")
            continue

        dossier_dir = manifest_path.parent / "dossiers"
        actual_dossiers: set[str] = set()
        if dossier_dir.exists():
            if dossier_dir.is_symlink():
                inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
                continue
            for dossier in dossier_dir.glob("*.md"):
                if dossier.is_symlink():
                    inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
                    failed = True
                    break
                actual_dossiers.add(dossier.relative_to(root).as_posix())
        if failed or actual_dossiers != current_dossiers:
            inventory.blocked.append("REVIEW_IDENTITY_INVENTORY_INCOMPLETE")
            continue

        observations = corpus.build_observations(files, duplicates.make_grouper(merged))
        report_json_path = manifest_path.parent / "validation_report.json"
        report_md_path = manifest_path.parent / "validation_report.md"
        try:
            report_before_json = report_json_path.read_bytes()
            report_before_md = report_md_path.read_bytes()
            old_report = parse_json_strict(report_before_json)
            summaries_relative = old_report["summaries_dir"]
            since = old_report["range"]["since"]
            until = old_report["range"]["until"]
            configured, _ = _grounding_config(root)
            canon_path = resolve.resolve_canon_path(root, out_root, None, configured)
            rulings = duplicates.load_rulings(canon_path)
            proposed_report = validate.scan(
                _reject_symlinks(root, root / summaries_relative),
                root,
                since,
                until,
                registry=merged,
                rulings=rulings,
                dup_threshold=old_report.get("dup_threshold", schema.DEFAULT_DUP_THRESHOLD),
            )
            report_after_json = proposed_report.to_json().encode("utf-8")
            report_after_md = proposed_report.to_markdown().encode("utf-8")
        except (
            KeyError,
            OSError,
            UnicodeError,
            ValueError,
            duplicates.RulingsError,
            validate.ValidationRefusal,
        ):
            inventory.blocked.append("REVIEW_IDENTITY_VALIDATION_REBUILD_REQUIRED")
            continue
        inventory.add(
            report_json_path.relative_to(root).as_posix(),
            report_before_json,
            report_after_json,
            affected=report_before_json != report_after_json,
        )
        inventory.add(
            report_md_path.relative_to(root).as_posix(),
            report_before_md,
            report_after_md,
            affected=report_before_md != report_after_md,
        )
        groups = corpus._group_dossiers(observations)
        expected_dossiers: dict[str, bytes] = {}
        for (category, subject, members), filename in zip(groups, corpus.dossier_filenames(groups)):
            target_path = manifest_path.parent / "dossiers" / filename
            target_relative = target_path.relative_to(root).as_posix()
            rendered = corpus.render_dossier(category, subject, members).encode("utf-8")
            expected_dossiers[target_relative] = rendered
            artifact_entries.append({
                "consumer": "summary_native.build",
                "path": target_relative,
                "sha256": sha256_bytes(rendered),
                "subject_ids": [f"{schema.CATEGORY_REGISTRY_TYPE.get(category, category)}:{_slug(subject)}"],
                "ownership": "generated",
            })

        report_subjects = sorted({
            f"{schema.CATEGORY_REGISTRY_TYPE.get(observation.category, observation.category)}:{_slug(observation.canonical)}"
            for observation in observations
        })
        for report_path, report_data in (
            (report_json_path, report_after_json),
            (report_md_path, report_after_md),
        ):
            artifact_entries.append({
                "consumer": "summary_native.validation",
                "path": report_path.relative_to(root).as_posix(),
                "sha256": sha256_bytes(report_data),
                "subject_ids": report_subjects,
                "ownership": "generated",
            })

        for dossier_path in sorted(current_dossiers | set(expected_dossiers)):
            path = root / dossier_path
            old = path.read_bytes() if path.is_file() else None
            new = expected_dossiers.get(dossier_path)
            inventory.add(dossier_path, old, new, affected=old != new)

        registry_raw = yaml.safe_load(registry_after) or {}
        rebuilt_dependencies = corpus.build_dependency_manifest(
            registry=registry_raw,
            registry_sha256=sha256_bytes(registry_after),
            artifacts=artifact_entries,
            precision="subject",
        )
        revised = dict(manifest)
        revised["identity_dependencies"] = rebuilt_dependencies
        canon = dict(revised.get("canon") or {})
        canon["registry_sha256"] = sha256_bytes(registry_after)
        revised["canon"] = canon
        counts = dict(revised.get("counts") or {})
        counts["dossiers"] = len(expected_dossiers)
        revised["counts"] = counts
        after_manifest = (json.dumps(revised, indent=2, sort_keys=True) + "\n").encode("utf-8")
        inventory.add(relative, before_manifest, after_manifest, affected=before_manifest != after_manifest)


def _subject_metadata(data: bytes) -> str | None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    match = re.search(r"^subject:\s*([^\n#]+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip(" '\"") if match else None


def _replace_subject(data: bytes, old: str, new: str) -> bytes | None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    pattern = re.compile(rf"^(subject:\s*){re.escape(old)}(\s*)$", re.MULTILINE)
    if len(pattern.findall(text)) != 1:
        return None
    return pattern.sub(lambda match: f"{match.group(1)}{new}{match.group(2)}", text).encode("utf-8")


def _existing_file(root: Path, path: Path, inventory: _Inventory) -> bytes | None:
    """Read one expected dossier path while refusing aliases at any path component."""
    try:
        checked = _reject_symlinks(root, path)
    except ReviewStoreError:
        inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
        return None
    if not checked.exists():
        return None
    if not checked.is_file():
        inventory.blocked.append("REVIEW_IDENTITY_INVENTORY_INCOMPLETE")
        return None
    try:
        return checked.read_bytes()
    except OSError:
        inventory.blocked.append("REVIEW_IDENTITY_INVENTORY_INCOMPLETE")
        return None


def _bind_generated(path: Path, root: Path, data: bytes, inventory: _Inventory) -> None:
    relative = path.relative_to(root).as_posix()
    inventory.add(relative, data, data, affected=False)
    inventory.generative.add(relative)


def _move_authored(
    root: Path,
    old_path: Path,
    new_path: Path,
    loser: Entity,
    survivor: Entity,
    inventory: _Inventory,
) -> None:
    old_data = _existing_file(root, old_path, inventory)
    new_data_existing = _existing_file(root, new_path, inventory)
    if old_data is not None:
        inventory.add(old_path.relative_to(root).as_posix(), old_data, old_data, affected=False)
    if new_data_existing is not None:
        inventory.add(
            new_path.relative_to(root).as_posix(),
            new_data_existing,
            new_data_existing,
            affected=False,
        )
    if old_data is not None and new_data_existing is not None:
        inventory.blocked.append("REVIEW_AUTHORED_DOSSIER_CONFLICT")
        return
    if old_data is None:
        return
    replacement = _replace_subject(old_data, loser.name, survivor.name)
    if replacement is None:
        inventory.blocked.append("REVIEW_IDENTITY_REFERENCE_AMBIGUOUS")
        return
    if old_path.as_posix().casefold() == new_path.as_posix().casefold():
        inventory.blocked.append("REVIEW_AUTHORED_DOSSIER_CONFLICT")
        return
    inventory.add(old_path.relative_to(root).as_posix(), old_data, None, affected=True)
    inventory.add(new_path.relative_to(root).as_posix(), None, replacement, affected=True)


def _legacy_dossier_dirs(
    root: Path, survivor: Entity, loser: Entity, inventory: _Inventory
) -> None:
    """Inventory pre-032 layouts still found in older campaigns."""
    base = root / schema.NPCS_DIR
    survivor_slug = npc_slug.slug_for(survivor.name)
    loser_slug = npc_slug.slug_for(loser.name)
    for ownership in ("published", "draft"):
        folder = base / ownership
        if not folder.exists():
            continue
        if folder.is_symlink():
            inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
            continue
        related: list[tuple[Path, bytes, str | None]] = []
        for path in sorted(folder.rglob("*")):
            if path.is_symlink():
                inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
                continue
            if not path.is_file():
                continue
            data = path.read_bytes()
            subject = _subject_metadata(data)
            stem = path.stem.casefold().replace(".authored", "")
            if subject in {survivor.name, loser.name} or stem in {survivor_slug, loser_slug}:
                related.append((path, data, subject))
        survivor_files = [
            entry for entry in related
            if entry[2] == survivor.name or entry[0].stem.casefold() == survivor_slug
        ]
        loser_files = [
            entry for entry in related
            if entry[2] == loser.name or entry[0].stem.casefold() == loser_slug
        ]
        for path, data, _subject_name in related:
            inventory.add(path.relative_to(root).as_posix(), data, data, affected=False)
        if ownership == "published" and survivor_files and loser_files:
            inventory.blocked.append("REVIEW_PUBLISHED_PATH_COLLISION")
        else:
            for path, data, _subject_name in loser_files:
                _bind_generated(path, root, data, inventory)


def _range_dossier_plan(
    root: Path,
    out_root: Path,
    registry: Registry,
    merged: Registry,
    survivor: Entity,
    loser: Entity,
    inventory: _Inventory,
) -> None:
    old_subjects = [(entity.type, entity.name) for entity in registry.entities if entity.type == "npc"]
    new_subjects = [(entity.type, entity.name) for entity in merged.entities if entity.type == "npc"]
    old_stems = npc_slug.stems_for(old_subjects)
    new_stems = npc_slug.stems_for(new_subjects)
    stems = {
        old_stems.get(("npc", survivor.name)),
        old_stems.get(("npc", loser.name)),
        new_stems.get(("npc", survivor.name)),
    } - {None}
    names = {survivor.name, loser.name}
    seen: set[str] = set()
    for npc_root in _configured_npc_roots(root, out_root):
        if not npc_root.exists():
            continue
        if npc_root.is_symlink() or not npc_root.is_dir():
            inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
            continue
        for path in sorted(npc_root.rglob("*")):
            if path.is_symlink():
                inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
                continue
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if relative in seen:
                continue
            seen.add(relative)
            try:
                data = path.read_bytes()
            except OSError:
                inventory.blocked.append("REVIEW_IDENTITY_INVENTORY_INCOMPLETE")
                continue
            filename_related = any(
                path.name == stem or path.name.startswith(f"{stem}.") for stem in stems
            )
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = ""
            content_related = any(name in text for name in names) or any(
                stem in text for stem in stems
            )
            if filename_related or content_related:
                _bind_generated(path, root, data, inventory)


def _dossier_plan(
    root: Path,
    out_root: Path,
    registry: Registry,
    merged: Registry,
    survivor: Entity,
    loser: Entity,
    inventory: _Inventory,
) -> None:
    base = root / schema.NPCS_DIR
    if base.exists() and (base.is_symlink() or not base.is_dir()):
        inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
        return
    survivor_slug = npc_slug.slug_for(survivor.name)
    loser_slug = npc_slug.slug_for(loser.name)
    if survivor_slug == loser_slug:
        inventory.blocked.append("REVIEW_IDENTITY_PATH_COLLISION")

    # Published dossiers live directly under schema.NPCS_DIR in the real producer
    # layout. They are generated prose, so a merge binds their current bytes and
    # leaves explicit regeneration work rather than silently rewriting content.
    survivor_published = base / f"{survivor_slug}.md"
    loser_published = base / f"{loser_slug}.md"
    survivor_published_data = _existing_file(root, survivor_published, inventory)
    loser_published_data = _existing_file(root, loser_published, inventory)
    for path, data in (
        (survivor_published, survivor_published_data),
        (loser_published, loser_published_data),
    ):
        if data is not None:
            inventory.add(path.relative_to(root).as_posix(), data, data, affected=False)
    if survivor_published_data is not None and loser_published_data is not None:
        inventory.blocked.append("REVIEW_PUBLISHED_PATH_COLLISION")
    elif loser_published_data is not None:
        _bind_generated(loser_published, root, loser_published_data, inventory)

    # Authored YAML is the one deterministic NPC artifact that can be retained:
    # its schema carries an exact subject field and its canonical path is shared
    # with npc-compose.
    _move_authored(
        root,
        npc_compose.authored_path_for(root, loser.name),
        npc_compose.authored_path_for(root, survivor.name),
        loser,
        survivor,
        inventory,
    )

    # Older hand-built authored Markdown also uses the canonical published slug.
    # It can move only when it contains the same unambiguous subject field.
    authored_root = root / schema.AUTHORED_DIR
    if authored_root.exists():
        if authored_root.is_symlink() or not authored_root.is_dir():
            inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
        elif any(path.is_symlink() for path in authored_root.rglob("*")):
            inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
    _move_authored(
        root,
        authored_root / f"{loser_slug}.md",
        authored_root / f"{survivor_slug}.md",
        loser,
        survivor,
        inventory,
    )

    _legacy_dossier_dirs(root, survivor, loser, inventory)
    _range_dossier_plan(root, out_root, registry, merged, survivor, loser, inventory)


def _review_plan(
    root: Path, names: set[str], subject_ids: set[str], inventory: _Inventory
) -> None:
    reviews = root / "docs" / "reviews"
    if not reviews.exists():
        return
    for path in sorted(reviews.glob("*/items/*/*.json")):
        if path.is_symlink():
            inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
            continue
        data = path.read_bytes()
        try:
            raw = parse_json_strict(data)
        except ValueError:
            inventory.blocked.append("REVIEW_IDENTITY_INVENTORY_INCOMPLETE")
            continue
        serialized = json.dumps(raw, sort_keys=True)
        if any(name in serialized for name in names) or any(value in serialized for value in subject_ids):
            inventory.add(path.relative_to(root).as_posix(), data, data, affected=False)
            review_id = raw.get("review_id")
            item_id = raw.get("item_id")
            if isinstance(review_id, str) and isinstance(item_id, str):
                inventory.stale_reviews.setdefault(review_id, set()).add(item_id)


def _stage_review_staleness(
    root: Path, proposal_id: str, inventory: _Inventory, recorded_at: datetime
) -> None:
    for review_id, item_ids in sorted(inventory.stale_reviews.items()):
        event_id = f"rebind-{proposal_id}-{sha256_bytes(canonical_bytes(sorted(item_ids)))[:12]}"
        event = {
            "version": 1,
            "kind": "rebind",
            "event_id": event_id,
            "review_id": review_id,
            "recorded_at": recorded_at,
            "preserved_item_ids": [],
            "stale_item_ids": sorted(item_ids),
            "reason": "identity_dependency_changed",
            "identity_proposal_id": proposal_id,
        }
        path = _review_dir(root, review_id) / "events" / f"{event_id}.json"
        relative = path.relative_to(root).as_posix()
        before = path.read_bytes() if path.is_file() else None
        inventory.add(relative, before, canonical_bytes(event), affected=True)


def _has_overlapping_merge_chain(
    root: Path, item_id: str, names: set[str], subject_ids: set[str]
) -> bool:
    proposal_root = root / "docs" / "reviews"
    if not proposal_root.exists():
        return False
    for path in sorted(proposal_root.glob("*/proposals/*.json")):
        if path.is_symlink():
            return True
        try:
            raw = parse_json_strict(path.read_bytes())
        except (OSError, ValueError):
            return True
        if not isinstance(raw, dict) or raw.get("kind") != "identity_merge":
            continue
        bindings = raw.get("decision_bindings") or []
        if any(
            isinstance(binding, dict) and binding.get("item_id") == item_id
            for binding in bindings
        ):
            # Historical previews for this item are immutable audit artifacts,
            # not a second concurrent merge chain.
            continue
        referenced_names = {
            raw.get("canonical_registry_name"),
            *(raw.get("retained_aliases") or []),
        }
        referenced_ids = {raw.get("survivor_subject_id"), raw.get("loser_subject_id")}
        if names & referenced_names or subject_ids & referenced_ids:
            return True
    return False


def _collision_check(root: Path, inventory: _Inventory) -> None:
    destinations: dict[str, str] = {}
    resolved: dict[Path, str] = {}
    for relative, target in inventory.targets.items():
        if not target.after_exists:
            continue
        folded = relative.casefold()
        if folded in destinations and destinations[folded] != relative:
            inventory.blocked.append("REVIEW_IDENTITY_PATH_COLLISION")
        destinations[folded] = relative
        resolved_path = (root / relative).resolve()
        if resolved_path in resolved and resolved[resolved_path] != relative:
            inventory.blocked.append("REVIEW_IDENTITY_SYMLINK_ALIAS")
        resolved[resolved_path] = relative


def _build_inventory(
    root: Path,
    registry_path: Path,
    registry_before: bytes,
    registry_after: bytes,
    registry: Registry,
    merged: Registry,
    survivor: Entity,
    loser: Entity,
    subject_ids: set[str],
    item,
) -> _Inventory:
    inventory = _Inventory()
    inventory.add(
        registry_path.relative_to(root).as_posix(), registry_before, registry_after, affected=True
    )
    for binding in item.input_bindings:
        relative, _path, data = _read_exact(root, binding.path, binding.custody_sha256)
        inventory.add(relative, data, data, affected=False)
    out_root = _configured_out_root(root)
    _corpus_plan(
        root,
        out_root,
        merged,
        registry_after,
        {_subject(survivor), _subject(loser)},
        inventory,
    )
    _dossier_plan(root, out_root, registry, merged, survivor, loser, inventory)
    _review_plan(root, {survivor.name, loser.name}, subject_ids, inventory)
    _collision_check(root, inventory)
    return inventory


def prepare_identity_alternatives(
    campaign_dir: Path,
    review_id: str,
    item_id: str,
    *,
    expected_decision_revision: int,
    requested_scope: dict,
) -> tuple[IdentityProposal, IdentityProposal]:
    root = Path(campaign_dir).resolve()
    manifest, custody, items = read_snapshot(root, review_id)
    item = next((candidate for candidate in items if candidate.item_id == item_id), None)
    if item is None or item.domain.value != "duplicate_identity":
        raise IdentityReviewError("REVIEW_INVALID_IDENTITY: unknown duplicate item")
    if any(diagnostic.blocking for diagnostic in item.diagnostics):
        raise IdentityReviewError(
            "REVIEW_IDENTITY_EVIDENCE_REQUIRED: complete parsed evidence is required before preview",
            "REVIEW_IDENTITY_EVIDENCE_REQUIRED",
        )
    details = item.proposed_action.details
    candidates = details.get("candidates") if isinstance(details, dict) else None
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise IdentityReviewError("REVIEW_INVALID_IDENTITY: item has no exact pair")
    registry_path = _configured_registry_path(root)
    before = registry_path.read_bytes()
    registry = load_registry(registry_path)
    names = [str(candidate["registry_name"]) for candidate in candidates]
    entities = []
    for name in names:
        matches = [entity for entity in registry.entities if entity.name == name]
        if len(matches) != 1:
            raise IdentityReviewError("REVIEW_STALE_IDENTITY: registry pair changed")
        entities.append(matches[0])
    latest = max(
        (int(event.get("decision_revision", 0)) for event in history(root, review_id, item_id=item_id)),
        default=0,
    )
    if latest != expected_decision_revision:
        raise IdentityReviewError(
            "REVIEW_STALE_DECISION: decision revision changed", "REVIEW_STALE_DECISION"
        )

    preview_facts = {
        "generation": manifest.generation,
        "item_id": item.item_id,
        "item_revision": item.revision,
        "review_digest": item.review_digest,
        "decision_revision": expected_decision_revision,
        "scope": requested_scope,
        "registry_sha256": sha256_bytes(before),
        "input_bindings": [binding.model_dump(mode="json") for binding in item.input_bindings],
        "rule_versions": [rule.model_dump(mode="json") for rule in item.rule_versions],
    }
    preview_digest = sha256_bytes(
        json.dumps(preview_facts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )[:24]
    proposal_ids = [
        f"identity-{item_id}-g{manifest.generation}-{preview_digest}-{index}"
        for index in (1, 2)
    ]
    existing_paths = [
        _review_dir(root, review_id) / "proposals" / f"{proposal_id}.json"
        for proposal_id in proposal_ids
    ]
    if all(path.is_file() for path in existing_paths):
        existing = tuple(
            model_from_json(IdentityProposal, _reject_symlinks(root, path).read_bytes())
            for path in existing_paths
        )
        valid = all(
            proposal.registry_sha256 == sha256_bytes(before)
            and proposal.scope.model_dump(mode="json", exclude_none=True) == requested_scope
            and proposal.decision_bindings[0].item_id == item.item_id
            and proposal.decision_bindings[0].item_revision == item.revision
            and proposal.decision_bindings[0].review_digest == item.review_digest
            and proposal.decision_bindings[0].decision_revision == expected_decision_revision
            for proposal in existing
        )
        if valid:
            for proposal in existing:
                for target in proposal.targets:
                    expected = _bytes(target, "before")
                    path = _reject_symlinks(root, root / target.path)
                    current = path.read_bytes() if path.is_file() else None
                    if current != expected:
                        raise IdentityReviewError(
                            f"REVIEW_STALE_IDENTITY: dependency changed: {target.path}",
                            "REVIEW_STALE_IDENTITY",
                        )
            return existing
        raise IdentityReviewError("REVIEW_PROPOSAL_CONFLICT: proposal id exists")

    common: list[str] = []
    if requested_scope.get("kind") != "global":
        common.append("REVIEW_SCOPED_ALIAS_UNSUPPORTED")
    if any(entity.scope != "persistent" for entity in entities):
        common.append("REVIEW_NONPERSISTENT_IDENTITY")
    if entities[0].type != entities[1].type:
        common.append("REVIEW_IDENTITY_TYPE_MISMATCH")
    pair = {name.casefold() for name in names}
    if any({value.casefold() for value in guard} == pair for guard in registry.distinct):
        common.append("REVIEW_DISTINCT_GUARD")
    if any(pair.issubset({value.casefold() for value in guard}) for guard in registry.rejected_aliases):
        common.append("REVIEW_REJECTED_ALIAS_GUARD")
    if _has_overlapping_merge_chain(
        root,
        item_id,
        set(names),
        {str(candidate["subject_id"]) for candidate in candidates},
    ):
        common.append("REVIEW_IDENTITY_MERGE_CHAIN")

    ledger_sha = ledger_digest(root)
    proposals: list[IdentityProposal] = []
    now = datetime.now(timezone.utc)
    for survivor_index in (0, 1):
        survivor, loser = entities[survivor_index], entities[1 - survivor_index]
        blocked = list(common)
        inventory = _Inventory()
        if not blocked:
            try:
                merged = _merged(registry, survivor, loser)
            except ValueError:
                blocked.append("REVIEW_IDENTITY_AMBIGUOUS_NORMALIZATION")
            else:
                try:
                    after = _registry_bytes_preserving_opaque(
                        before, merged, removed_name=loser.name
                    )
                except IdentityReviewError as exc:
                    blocked.append(str(exc))
                else:
                    inventory = _build_inventory(
                        root,
                        registry_path,
                        before,
                        after,
                        registry,
                        merged,
                        survivor,
                        loser,
                        {str(candidate["subject_id"]) for candidate in candidates},
                        item,
                    )
                    _stage_review_staleness(
                        root, proposal_ids[survivor_index], inventory, now
                    )
                    blocked.extend(inventory.blocked)
        blocked = list(dict.fromkeys(blocked))
        applicable = not blocked
        retained: list[str] = []
        for value in [*survivor.aliases, loser.name, *loser.aliases]:
            if value != survivor.name and value not in retained:
                retained.append(value)
        proposal = IdentityProposal(
            proposal_id=proposal_ids[survivor_index],
            campaign_id=manifest.campaign_id,
            review_id=review_id,
            custody=SourceCustodyRef(
                campaign_id=manifest.campaign_id,
                review_id=review_id,
                generation=custody.generation,
                digest=custody.custody_digest,
            ),
            decision_bindings=(DecisionBinding(
                event_id=None,
                item_id=item.item_id,
                item_revision=item.revision,
                review_digest=item.review_digest,
                decision_revision=expected_decision_revision,
            ),),
            applicable=applicable,
            blocked_reasons=tuple(blocked),
            targets=tuple(inventory.targets[path] for path in sorted(inventory.targets)) if applicable else (),
            affected_paths=tuple(sorted(inventory.affected)) if applicable else (),
            inspected_paths=tuple(sorted(inventory.inspected)),
            registry_sha256=sha256_bytes(before),
            ledger_sha256=ledger_sha,
            generative_rebuilds=tuple(sorted(inventory.generative)),
            created_at=now,
            survivor_subject_id=candidates[survivor_index]["subject_id"],
            loser_subject_id=candidates[1 - survivor_index]["subject_id"],
            canonical_registry_name=survivor.name,
            retained_aliases=tuple(retained),
            scope=requested_scope,
        )
        proposals.append(proposal)

    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        validate_ledger_tip(root)
        if registry_path.read_bytes() != before or ledger_digest(root) != ledger_sha:
            raise IdentityReviewError(
                "REVIEW_STALE_IDENTITY: inputs changed while preparing proposal",
                "REVIEW_STALE_IDENTITY",
            )
        for proposal in proposals:
            if not proposal.applicable:
                continue
            for target in proposal.targets:
                expected = _bytes(target, "before")
                path = _reject_symlinks(root, root / target.path)
                current = path.read_bytes() if path.is_file() else None
                if current != expected:
                    raise IdentityReviewError(
                        f"REVIEW_STALE_IDENTITY: dependency changed: {target.path}",
                        "REVIEW_STALE_IDENTITY",
                    )
        targets = []
        for proposal in proposals:
            path = _review_dir(root, review_id) / "proposals" / f"{proposal.proposal_id}.json"
            if path.exists():
                if path.read_bytes() != canonical_bytes(proposal):
                    raise IdentityReviewError("REVIEW_PROPOSAL_CONFLICT: proposal id exists")
            else:
                targets.append(TransactionTarget.create(path, canonical_bytes(proposal)))
        if targets:
            digest = sha256_bytes(canonical_bytes(proposals))
            journal = _prepare_transaction_locked(
                root,
                proposal_id=f"identity-prepare-{item_id}-{preview_digest}",
                proposal_sha256=digest,
                targets=targets,
            )
            recover_transaction(root, journal["id"], _already_locked=True)
    return tuple(proposals)


def _approval(ledger: AuthorityLedger, review_id: str, proposal: IdentityProposal) -> ReviewDecisionRecord:
    binding = proposal.decision_bindings[0]
    records = [
        record
        for record in ledger.records
        if isinstance(record, ReviewDecisionRecord)
        and record.review_id == review_id
        and record.item_id == binding.item_id
        and record.status == "accepted"
        and record.disposition == "merge"
        and record.proposal is not None
        and record.proposal.id == proposal.proposal_id
        and record.proposal.digest == proposal.proposal_digest
    ]
    if not records:
        raise IdentityReviewError("REVIEW_APPROVAL_REQUIRED: exact proposal is not approved")
    record = records[-1]
    if (
        record.item_revision != binding.item_revision
        or record.review_digest != binding.review_digest
        or record.decision_revision != binding.decision_revision + 1
    ):
        raise IdentityReviewError("REVIEW_STALE_IDENTITY: approval binding changed")
    return record


def _review_only_chain(root: Path, before: str, after: str) -> bool:
    if before == after:
        return True
    by_after: dict[str, list[dict]] = {}
    for path in (authority_dir(root) / "events").glob("*.json"):
        if path.name == "tip.json" or path.is_symlink():
            continue
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if isinstance(event, dict) and isinstance(event.get("after_sha256"), str):
            by_after.setdefault(event["after_sha256"], []).append(event)
    cursor = after
    seen = set()
    while cursor != before:
        if cursor in seen:
            return False
        seen.add(cursor)
        events = by_after.get(cursor, [])
        if len(events) != 1 or events[0].get("reason") != "review-decision":
            return False
        cursor = events[0].get("before_sha256")
        if not isinstance(cursor, str):
            return False
    return True


def _transaction_target(root: Path, target: ProposalTarget) -> TransactionTarget | None:
    before = _bytes(target, "before")
    after = _bytes(target, "after")
    path = _reject_symlinks(root, root / target.path)
    current = path.read_bytes() if path.is_file() else None
    if current != before:
        raise IdentityReviewError(
            f"REVIEW_STALE_IDENTITY: dependency changed: {target.path}", "REVIEW_STALE_IDENTITY"
        )
    if before == after:
        return None
    if before is None:
        return TransactionTarget.create(path, after)
    if after is None:
        return TransactionTarget.delete(path, before)
    return TransactionTarget.replace(path, before, after)


def apply_identity_proposal(
    campaign_dir: Path,
    review_id: str,
    *,
    proposal_id: str,
    proposal_sha256: str,
) -> IdentityReceipt:
    root = Path(campaign_dir).resolve()
    proposal_path = _reject_symlinks(
        root, _review_dir(root, review_id) / "proposals" / f"{proposal_id}.json"
    )
    if not proposal_path.is_file():
        raise IdentityReviewError("REVIEW_INVALID_PROPOSAL: proposal missing")
    proposal = model_from_json(IdentityProposal, proposal_path.read_bytes())
    if proposal.proposal_digest != proposal_sha256:
        raise IdentityReviewError("REVIEW_INVALID_PROPOSAL: digest mismatch")
    if not proposal.applicable:
        raise IdentityReviewError(proposal.blocked_reasons[0])
    if proposal.scope.kind != "global":
        raise IdentityReviewError("REVIEW_SCOPED_ALIAS_UNSUPPORTED")
    receipt_id = f"receipt-{proposal_id}"
    receipt_path = _review_dir(root, review_id) / "receipts" / f"{receipt_id}.json"

    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        validate_ledger_tip(root)
        ledger = load_ledger(root)
        record = _approval(ledger, review_id, proposal)
        if receipt_path.exists():
            receipt = model_from_json(IdentityReceipt, receipt_path.read_bytes())
            if (
                receipt.proposal_digest != proposal_sha256
                or record.receipt is None
                or record.receipt.id != receipt.receipt_id
                or record.receipt.digest != receipt.receipt_digest
            ):
                raise IdentityReviewError("REVIEW_RECEIPT_CONFLICT")
            return receipt
        if not _review_only_chain(root, proposal.ledger_sha256, ledger_digest(root)):
            raise IdentityReviewError("REVIEW_STALE_IDENTITY: authority ledger changed")

        mutation_targets: list[TransactionTarget] = []
        changed_paths: list[str] = []
        before_hashes: dict[str, str | None] = {}
        after_hashes: dict[str, str | None] = {}
        for target in proposal.targets:
            transaction_target = _transaction_target(root, target)
            if transaction_target is not None:
                mutation_targets.append(transaction_target)
                changed_paths.append(target.path)
                before_hashes[target.path] = target.before_sha256
                after_hashes[target.path] = target.after_sha256

        now = datetime.now(timezone.utc)
        receipt = IdentityReceipt(
            receipt_id=receipt_id,
            campaign_id=proposal.campaign_id,
            review_id=review_id,
            proposal_id=proposal_id,
            proposal_digest=proposal_sha256,
            decision_event_ids=(record.event_id,),
            changed_paths=tuple(changed_paths),
            before_hashes=before_hashes,
            after_hashes=after_hashes,
            authority_record_ids=(record.id,),
            ledger_sha256=ledger_digest(root),
            remaining_review_work=tuple(
                f"regenerate and review {path}" for path in proposal.generative_rebuilds
            ),
            committed_at=now,
            survivor_subject_id=proposal.survivor_subject_id,
            loser_subject_id=proposal.loser_subject_id,
            canonical_registry_name=proposal.canonical_registry_name,
        )
        updated = [
            candidate.model_copy(update={
                "revision": candidate.revision + 1,
                "receipt": ReviewArtifactRef(
                    kind="identity_merge", id=receipt_id, digest=receipt.receipt_digest
                ),
            }) if candidate.id == record.id else candidate
            for candidate in ledger.records
        ]
        after_ledger = AuthorityLedger(
            version=ledger.version,
            campaign=ledger.campaign,
            revision=ledger.revision + 1,
            records=updated,
            conflicts=ledger.conflicts,
        )
        ledger_before = ledger_path(root).read_bytes()
        ledger_after = ledger_bytes(after_ledger)
        audit_id = f"event-{receipt_id}"
        audit = {
            "id": audit_id,
            "reason": "identity-merge",
            "actor": record.recorded_by,
            "recorded_at": now.isoformat().replace("+00:00", "Z"),
            "before_sha256": sha256_bytes(ledger_before),
            "after_sha256": sha256_bytes(ledger_after),
            "record_id": record.id,
        }
        mutation_targets.extend([
            TransactionTarget.create(receipt_path, canonical_bytes(receipt)),
            TransactionTarget.replace(ledger_path(root), ledger_before, ledger_after),
            TransactionTarget.create(
                authority_dir(root) / "events" / f"{audit_id}.json", _json_bytes(audit)
            ),
            TransactionTarget.replace(
                ledger_tip_path(root),
                ledger_tip_path(root).read_bytes(),
                _tip_bytes(audit_id, ledger_after),
            ),
        ])
        journal = _prepare_transaction_locked(
            root,
            proposal_id=proposal_id,
            proposal_sha256=proposal_sha256,
            targets=mutation_targets,
        )
        recover_transaction(root, journal["id"], _already_locked=True)
        return receipt
