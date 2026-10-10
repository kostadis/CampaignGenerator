"""Argument parser and dispatcher for the shared review workflow."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from campaignlib.review_config import (
    ReviewConfigError,
    load_campaign_review_config,
    resolve_review_scope,
)
from pipelines.summary_native.authority import AuthorityError
from pipelines.summary_native.authority_apply import recover_transaction
from pipelines.summary_native.review.migrate import apply_authority_migration, plan_authority_migration
from pipelines.summary_native.review.models import canonicalize, parse_json_strict, model_from_json, IdentityProposal, IdentityReceipt, ReviewItem, ReviewManifest, SourceCustodyGeneration
from pipelines.summary_native.review.store import (
    ReviewStoreError,
    history,
    initialize_campaign,
    read_snapshot,
    retract_decision,
    save_decisions,
    create_review,
    load_campaign_identity,
    list_reviews,
    review_status,
    export_review,
    import_review_bundle,
    read_review_state,
)


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    review = subparsers.add_parser("review", help="durable shared review and adjudication")
    commands = review.add_subparsers(dest="review_command", required=True)
    init = commands.add_parser("init", help="initialize campaign-local review storage")
    _scope_args(init)
    create = commands.add_parser("create", help="create a review from an explicit selection")
    create.add_argument("--kind", required=True, choices=("npc_verification","duplicate_identity","grounding_documents"))
    create.add_argument("--selection", required=True, metavar="FILE")
    _scope_args(create)
    listing = commands.add_parser("list", help="list campaign reviews"); _scope_args(listing)
    status = commands.add_parser("status", help="show review counts"); status.add_argument("review"); _scope_args(status)
    export = commands.add_parser("export", help="export selected review decisions"); export.add_argument("review"); export.add_argument("--selection",required=True); _scope_args(export)
    import_cmd = commands.add_parser("import", help="import a bound decision bundle"); import_cmd.add_argument("--bundle",required=True); import_cmd.add_argument("--expected-generation",required=True,type=int); _scope_args(import_cmd)
    migrate = commands.add_parser("migrate", help="plan or apply the authority v1-to-v2 migration")
    _scope_args(migrate)
    group = migrate.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--plan-sha256")
    dependencies = commands.add_parser("dependencies", help="adopt precise identity dependency manifests")
    dependency_commands = dependencies.add_subparsers(dest="dependency_command", required=True)
    dependency_migrate = dependency_commands.add_parser("migrate")
    _scope_args(dependency_migrate)
    dependency_group = dependency_migrate.add_mutually_exclusive_group(required=True)
    dependency_group.add_argument("--dry-run", action="store_true")
    dependency_group.add_argument("--plan-sha256")
    recover = commands.add_parser("recover", help="recover a pending shared transaction")
    recover.add_argument("transaction")
    _scope_args(recover)
    decide = commands.add_parser("decide", help="save an explicit decision batch")
    decide.add_argument("review")
    decide.add_argument("--decisions", required=True, metavar="FILE")
    decide.add_argument("--grant", default=None, help=argparse.SUPPRESS)
    _scope_args(decide)
    history_parser = commands.add_parser("history", help="read immutable decision history")
    history_parser.add_argument("review")
    history_parser.add_argument("--item", default=None)
    _scope_args(history_parser)
    show = commands.add_parser("show", help="read one bounded review page or item")
    show.add_argument("review")
    show.add_argument("--item", default=None)
    show.add_argument("--cursor", default=None)
    show.add_argument("--limit", type=int, default=None)
    show.add_argument("--section-offset", type=int, default=None)
    _scope_args(show)
    retract = commands.add_parser("retract", help="withdraw a decision without undoing applied artifacts")
    retract.add_argument("review")
    retract.add_argument("--event", required=True)
    retract.add_argument("--expected-decision-revision", required=True, type=int)
    retract.add_argument("--reason", required=True)
    _scope_args(retract)
    refresh = commands.add_parser("refresh", help="refresh source custody and approval freshness")
    refresh.add_argument("review"); refresh.add_argument("--expected-generation",required=True,type=int); _scope_args(refresh)
    finding = commands.add_parser("finding", help="add attributable semantic findings")
    finding_commands=finding.add_subparsers(dest="finding_command",required=True)
    finding_add=finding_commands.add_parser("add"); finding_add.add_argument("review"); finding_add.add_argument("--finding",required=True); finding_add.add_argument("--expected-generation",required=True,type=int); _scope_args(finding_add)
    rerun = commands.add_parser("rerun", help="preview or execute selected deterministic checks")
    rerun_commands=rerun.add_subparsers(dest="rerun_command",required=True)
    rerun_preview=rerun_commands.add_parser("preview"); rerun_preview.add_argument("review"); rerun_preview.add_argument("--selection",required=True); rerun_preview.add_argument("--mode",choices=("unresolved","selected"),required=True); _scope_args(rerun_preview)
    rerun_run=rerun_commands.add_parser("run"); rerun_run.add_argument("review"); rerun_run.add_argument("--selection-sha256",required=True); _scope_args(rerun_run)
    correction=commands.add_parser("correction",help="prepare or apply an exact correction")
    correction_commands=correction.add_subparsers(dest="correction_command",required=True)
    correction_prepare=correction_commands.add_parser("prepare"); correction_prepare.add_argument("review"); correction_prepare.add_argument("--item",required=True); correction_prepare.add_argument("--target-kind",choices=("source","draft"),required=True); correction_prepare.add_argument("--replacement",required=True); correction_prepare.add_argument("--expected-decision-revision",type=int,required=True); correction_prepare.add_argument("--summaries-dir"); _scope_args(correction_prepare)
    correction_apply=correction_commands.add_parser("apply"); correction_apply.add_argument("review"); correction_apply.add_argument("--proposal",required=True); correction_apply.add_argument("--proposal-sha256",required=True); correction_apply.add_argument("--summaries-dir"); _scope_args(correction_apply)
    npc=commands.add_parser("npc",help="sign an exact mechanically verified NPC draft")
    npc_commands=npc.add_subparsers(dest="npc_command",required=True)
    npc_sign=npc_commands.add_parser("sign"); npc_sign.add_argument("review"); npc_sign.add_argument("--item",required=True); npc_sign.add_argument("--draft-sha256",required=True); npc_sign.add_argument("--expected-decision-revision",type=int,required=True); npc_sign.add_argument("--reviewer",required=True); _scope_args(npc_sign)
    document=commands.add_parser("document",help="create, sign, prepare, or promote grounding documents")
    document_commands=document.add_subparsers(dest="document_command",required=True)
    document_create=document_commands.add_parser("create"); document_create.add_argument("review"); document_create.add_argument("--selection",required=True); _scope_args(document_create)
    document_sign=document_commands.add_parser("sign"); document_sign.add_argument("review"); document_sign.add_argument("--item",required=True); document_sign.add_argument("--document-sha256",required=True); document_sign.add_argument("--expected-decision-revision",type=int,required=True); document_sign.add_argument("--reviewer",required=True); _scope_args(document_sign)
    document_prepare=document_commands.add_parser("prepare"); document_prepare.add_argument("review"); document_prepare.add_argument("--documents",required=True); _scope_args(document_prepare)
    document_promote=document_commands.add_parser("promote"); document_promote.add_argument("review"); document_promote.add_argument("--proposals",required=True); _scope_args(document_promote)
    identity=commands.add_parser("identity",help="prepare, inspect, or apply an identity proposal")
    identity_commands=identity.add_subparsers(dest="identity_command",required=True)
    identity_prepare=identity_commands.add_parser("prepare"); identity_prepare.add_argument("review"); identity_prepare.add_argument("--item",required=True); identity_prepare.add_argument("--expected-decision-revision",required=True,type=int); identity_prepare.add_argument("--scope-kind",required=True,choices=("global","chapter","scene","location","document","evidence")); identity_prepare.add_argument("--scope-value"); _scope_args(identity_prepare)
    identity_detail=identity_commands.add_parser("detail"); identity_detail.add_argument("review"); identity_detail.add_argument("--proposal",required=True); _scope_args(identity_detail)
    identity_resolution=identity_commands.add_parser("resolution"); identity_resolution.add_argument("review"); identity_resolution.add_argument("--proposal",required=True); _scope_args(identity_resolution)
    identity_guard_prepare=identity_commands.add_parser("guard-prepare"); identity_guard_prepare.add_argument("review"); identity_guard_prepare.add_argument("--proposal",required=True); identity_guard_prepare.add_argument("--reviewer",required=True); identity_guard_prepare.add_argument("--note",required=True); _scope_args(identity_guard_prepare)
    identity_guard_apply=identity_commands.add_parser("guard-apply"); identity_guard_apply.add_argument("review"); identity_guard_apply.add_argument("--resolution",required=True); identity_guard_apply.add_argument("--resolution-sha256",required=True); _scope_args(identity_guard_apply)
    identity_apply=identity_commands.add_parser("apply"); identity_apply.add_argument("review"); identity_apply.add_argument("--proposal",required=True); identity_apply.add_argument("--proposal-sha256",required=True); _scope_args(identity_apply)
    identity_regenerate=identity_commands.add_parser("regenerate"); identity_regenerate.add_argument("review"); identity_regenerate.add_argument("--receipt",required=True); identity_regenerate.add_argument("--selection",required=True); identity_regenerate.add_argument("--execute",action="store_true"); _scope_args(identity_regenerate)
    serve = commands.add_parser("serve", help="run the dedicated review service in the foreground")
    serve.add_argument("review")
    _endpoint_args(serve)
    _scope_args(serve)
    access = commands.add_parser("access", help="issue or revoke a review capability")
    access_commands = access.add_subparsers(dest="access_command", required=True)
    issue = access_commands.add_parser("issue", help="issue one secret review link")
    issue.add_argument("review")
    issue.add_argument("--expires-in", type=int, default=None, metavar="SECONDS")
    _scope_args(issue)
    revoke = access_commands.add_parser("revoke", help="revoke one review capability")
    revoke.add_argument("review")
    revoke.add_argument("--grant", required=True)
    _scope_args(revoke)
    service = commands.add_parser("service", help="manage a background review service")
    service_commands = service.add_subparsers(dest="service_command", required=True)
    start = service_commands.add_parser("start", help="start a background review service")
    start.add_argument("review")
    _endpoint_args(start)
    _scope_args(start)
    for name in ("status", "stop"):
        command = service_commands.add_parser(name, help=f"{name} a background review service")
        command.add_argument("review")
        _scope_args(command)


def _endpoint_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", required=True, metavar="ADDRESS")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--origin", required=True, metavar="URL")
    parser.add_argument("--tls-cert", default=None, metavar="FILE")
    parser.add_argument("--tls-key", default=None, metavar="FILE")


def _scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--campaign-dir", default=None, metavar="DIR")
    parser.add_argument("--config", default=None, metavar="PATH")
    parser.add_argument("--json", action="store_true", help="emit stable JSON envelope")


def _emit(args: argparse.Namespace, *, ok: bool, code: str, message: str, data=None, artifacts=()) -> int:
    envelope = {"ok": ok, "code": code, "message": message, "artifacts": list(artifacts), "data": data}
    if getattr(args, "json", False):
        print(json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str))
    else:
        print(message)
        if data is not None:
            print(json.dumps(data, sort_keys=True, indent=2, default=str))
    return 0 if ok else _exit_for(code)


def _exit_for(code: str) -> int:
    if "STALE" in code:
        return 3
    if "RECOVER" in code or "PENDING" in code:
        return 4
    if "UNRESOLVED" in code or "BLOCK" in code or "CONFLICT" in code:
        return 5
    return 2


def _latest(events: list[dict], item_id: str) -> dict | None:
    matches = [event for event in events if event.get("item_id") == item_id]
    return matches[-1] if matches else None


def _fresh_decision(event: dict | None, item) -> bool:
    return bool(
        event
        and event.get("kind") != "withdrawal"
        and event.get("item_revision") == item.revision
        and event.get("review_digest") == item.review_digest
        and event.get("verdict") in {"approve", "reject", "discuss"}
    )


def _stale_decision(event: dict | None, item) -> bool:
    return bool(
        event
        and event.get("kind") != "withdrawal"
        and (
            event.get("item_revision") != item.revision
            or event.get("review_digest") != item.review_digest
        )
    )


def _document_section(root: Path, item, offset: int) -> dict:
    if item.domain.value != "grounding_document":
        raise ReviewStoreError("REVIEW_PAGE_INVALID: sections apply only to documents", "REVIEW_PAGE_INVALID")
    if offset < 0:
        raise ReviewStoreError("REVIEW_PAGE_INVALID: section offset must be nonnegative", "REVIEW_PAGE_INVALID")
    path = root / item.locator.source_path
    data = path.read_bytes()
    binding = next((value for value in item.input_bindings if value.path == item.locator.source_path), None)
    digest = hashlib.sha256(data).hexdigest()
    if binding is None or digest != binding.custody_sha256:
        raise ReviewStoreError("REVIEW_STALE_CUSTODY: document bytes changed", "REVIEW_STALE_CUSTODY")
    size = load_campaign_review_config(root).max_section_bytes
    end = min(len(data), offset + size)
    while end > offset:
        try:
            content = data[offset:end].decode("utf-8")
            break
        except UnicodeDecodeError:
            end -= 1
    else:
        raise ReviewStoreError("REVIEW_PAGE_INVALID: section offset splits encoded text", "REVIEW_PAGE_INVALID")
    return {"content": content, "offset": offset, "next_offset": end if end < len(data) else None,
            "total_bytes": len(data), "full_document_sha256": digest}


def _show_review(root: Path, review_id: str, *, item_id: str | None, cursor: str | None, limit: int | None, section_offset: int | None = None) -> dict:
    manifest, items, events, stale_ids = read_review_state(root, review_id)
    if item_id is not None:
        item = next((candidate for candidate in items if candidate.item_id == item_id), None)
        if item is None:
            raise ReviewStoreError(
                "REVIEW_UNKNOWN_ITEM: item does not exist", "REVIEW_UNKNOWN_ITEM"
            )
        event = _latest(events, item.item_id)
        fresh = _fresh_decision(event, item)
        result = {
            **canonicalize(item),
            "decision": event,
            "decision_revision": int(event.get("decision_revision", 0)) if event else 0,
            "freshness": "stale" if item.item_id in stale_ids or _stale_decision(event, item) else "current",
        }
        if section_offset is not None:
            result["document_section"] = _document_section(root, item, section_offset)
        if item.domain.value == "duplicate_identity":
            proposals=[]
            directory=root/"docs/reviews"/review_id/"proposals"
            paths=sorted(directory.glob(f"identity-{item.item_id}-*.json")) if directory.is_dir() else ()
            for path in paths:
                if path.is_symlink(): continue
                proposal=model_from_json(IdentityProposal,path.read_bytes())
                proposals.append({"proposal_id":proposal.proposal_id,"proposal_digest":proposal.proposal_digest,"canonical_registry_name":proposal.canonical_registry_name,"applicable":proposal.applicable,"blocked_reasons":list(proposal.blocked_reasons),"affected_paths":list(proposal.affected_paths),"inspected_paths":list(proposal.inspected_paths),"generative_rebuilds":list(proposal.generative_rebuilds),"targets":[{"path":target.path,"operation":target.operation,"before_sha256":target.before_sha256,"after_sha256":target.after_sha256} for target in proposal.targets]})
            result["identity_proposals"]=proposals
            proposal_id=event.get("proposal_id") if event else None
            receipt_path=directory.parent/"receipts"/f"receipt-{proposal_id}.json" if proposal_id else None
            if receipt_path is not None and receipt_path.is_file() and not receipt_path.is_symlink():
                receipt=model_from_json(IdentityReceipt,receipt_path.read_bytes())
                result["application"]={"state":"applied","receipt_id":receipt.receipt_id,"receipt_digest":receipt.receipt_digest,"proposal_id":receipt.proposal_id,"proposal_digest":receipt.proposal_digest,"changed_paths":list(receipt.changed_paths),"remaining_review_work":list(receipt.remaining_review_work),"committed_at":receipt.committed_at}
            elif proposal_id:
                result["application"]={"state":"approved_pending_apply","proposal_id":proposal_id,"proposal_digest":event.get("proposal_digest")}
        return result

    config = load_campaign_review_config(root)
    page_limit = config.max_page_items if limit is None else limit
    if not 1 <= page_limit <= config.max_page_items:
        raise ReviewStoreError(
            f"REVIEW_PAGE_INVALID: limit must be between 1 and {config.max_page_items}",
            "REVIEW_PAGE_INVALID",
        )
    start = 0
    if cursor is not None:
        indices = [index for index, item in enumerate(items) if item.item_id == cursor]
        if not indices:
            raise ReviewStoreError(
                "REVIEW_PAGE_INVALID: cursor is invalid", "REVIEW_PAGE_INVALID"
            )
        start = indices[0] + 1
    page = items[start : start + page_limit]
    summaries = []
    approved = rejected = discussed = stale = 0
    for item in items:
        event = _latest(events, item.item_id)
        if item.item_id in stale_ids or _stale_decision(event, item):
            stale += 1
        elif _fresh_decision(event, item):
            approved += event.get("verdict") == "approve"
            rejected += event.get("verdict") == "reject"
            discussed += event.get("verdict") == "discuss"
    for item in page:
        event = _latest(events, item.item_id)
        fresh = _fresh_decision(event, item)
        summaries.append(
            {
                "item_id": item.item_id,
                "revision": item.revision,
                "review_digest": item.review_digest,
                "claim_text": item.claim_text,
                "categories": sorted(category.value for category in item.categories),
                "severity": item.severity.value,
                "freshness": "stale" if item.item_id in stale_ids or _stale_decision(event, item) else "current",
                "disposition": event.get("verdict") if fresh and item.item_id not in stale_ids else "pending",
                "decision_revision": int(event.get("decision_revision", 0)) if event else 0,
            }
        )
    settled = approved
    next_cursor = page[-1].item_id if start + len(page) < len(items) else None
    return {
        "review_id": review_id,
        "kind": manifest.kind.value,
        "generation": manifest.generation,
        "title": f"{manifest.kind.value.replace('_', ' ').title()} review",
        "transport": _transport_label(root),
        "counts": {
            "total": len(items),
            "pending": len(items) - settled,
            "approved": approved,
            "rejected": rejected,
            "discussed": discussed,
            "stale": stale,
            "settled": settled,
        },
        "items": summaries,
        "next_cursor": next_cursor,
    }


def _transport_label(root:Path)->str:
    from ipaddress import ip_address,ip_network
    config=load_campaign_review_config(root)
    if config.bind_host is None: return "Private review capability; endpoint selected by the local launcher"
    address=ip_address(config.bind_host); scheme="HTTPS" if str(config.origin).startswith("https://") else "HTTP"
    if address.is_loopback: scope="this device only"
    elif address.version==4 and address in ip_network("100.64.0.0/10"): scope="private Tailscale network"
    else: scope="private local network"
    return f"{scheme} capability link on {scope}"


def _create_selected_review(root: Path, kind: str, selection_path: Path) -> dict:
    """Materialize the explicit prepared selection used by local producers."""
    if kind == "duplicate_identity":
        return _create_duplicate_review(root, selection_path)
    if kind != "npc_verification":
        raise ReviewStoreError(f"REVIEW_KIND_PENDING: {kind} adapter is not available yet")
    raw=parse_json_strict(selection_path.read_bytes())
    findings=raw.get("findings") if isinstance(raw,dict) else None
    dossiers=raw.get("dossiers") if isinstance(raw,dict) else None
    if isinstance(dossiers,list) and dossiers:
        return _create_verified_dossier_review(root,dossiers)
    if not isinstance(findings,list) or not findings:
        raise ReviewStoreError("REVIEW_INVALID_SELECTION: npc findings must be explicit and nonempty")
    from pipelines.summary_native.npc_verify import Finding,VerificationResult
    from pipelines.summary_native.review.models import SubjectReference
    from pipelines.summary_native.review.verification import SelectedNpcVerification,adapt_selected_verifications
    identity=load_campaign_identity(root);review_id=f"npc-review-{uuid.uuid4().hex[:12]}";now=datetime.now(timezone.utc);selected=[];source_map={}
    for finding in findings:
        required={"id","npc","draft_path","draft_line","evidence_path","diagnostic","severity"}
        if not isinstance(finding,dict) or not required.issubset(finding) or not isinstance(finding["diagnostic"],dict): raise ReviewStoreError("REVIEW_INVALID_SELECTION: prepared verifier result is malformed")
        texts={};source_ids={}
        for role,key in (("draft","draft_path"),("evidence","evidence_path")):
            relative=str(finding[key]);candidate=root/relative
            cursor=root
            for part in Path(relative).parts:
                cursor=cursor/part
                if cursor.is_symlink(): raise ReviewStoreError(f"REVIEW_PATH: symlink source refused: {relative}")
            resolved=candidate.resolve()
            try:resolved.relative_to(root)
            except ValueError as exc: raise ReviewStoreError("REVIEW_PATH: source outside campaign") from exc
            if not resolved.is_file(): raise ReviewStoreError(f"REVIEW_INVALID_SELECTION: missing {role} {relative}")
            texts[role]=resolved.read_text(encoding="utf-8")
            source_id=f"{role}-{hashlib.sha256(relative.encode()).hexdigest()[:16]}";source_ids[role]=source_id;data=resolved.read_bytes();source_map[source_id]={"source_id":source_id,"path":relative,"sha256":hashlib.sha256(data).hexdigest(),"size":len(data)}
        diagnostic=finding["diagnostic"];observation=Finding(str(diagnostic.get("code")),int(finding["draft_line"]),str(finding.get("evidence") or ""),str(diagnostic.get("detail") or ""));blocking=bool(diagnostic.get("blocking"))
        result=VerificationResult(verdict="fail" if blocking else "pass",failures=[observation] if blocking else [],advisories=[] if blocking else [observation],counts={observation.code:1})
        selected.append(SelectedNpcVerification(selection_id=str(finding["id"]),subject_ref=SubjectReference(subject_id=uuid.uuid5(identity.campaign_id,str(finding["npc"])),kind="entity"),draft_source_id=source_ids["draft"],draft_path=str(finding["draft_path"]),draft_text=texts["draft"],evidence_source_id=source_ids["evidence"],evidence_path=str(finding["evidence_path"]),evidence_text=texts["evidence"],result=result))
    items=list(adapt_selected_verifications(campaign_id=identity.campaign_id,review_id=review_id,selected=selected))
    items.extend(_npc_signoff_items(identity.campaign_id,review_id,selected,{
        value.draft_path: str(finding["npc"])
        for value, finding in zip(selected, findings)
    },verification_complete=False))
    sources=list(source_map.values())
    custody=SourceCustodyGeneration(campaign_id=identity.campaign_id,review_id=review_id,generation=1,recorded_at=now,sources=tuple(sources))
    manifest=ReviewManifest(campaign_id=identity.campaign_id,review_id=review_id,kind=kind,generation=1,created_at=now,created_by="local-cli",selection=tuple({"kind":"subject","id":str(f["id"])} for f in findings),items=tuple({"campaign_id":identity.campaign_id,"review_id":review_id,"item_id":item.item_id,"revision":item.revision,"review_digest":item.review_digest} for item in items),source_manifest={"campaign_id":identity.campaign_id,"review_id":review_id,"generation":1,"digest":custody.custody_digest},rule_versions=({"rule_id":"npc-verify","version":"1"},))
    return create_review(root,manifest,custody,items)


def _create_duplicate_review(root: Path, selection_path: Path) -> dict:
    from uuid import uuid5, NAMESPACE_URL
    from campaignlib.registry import load_registry
    from pipelines.summary_native import corpus, duplicates, parse
    from pipelines.summary_native.review.identity import _configured_registry_path

    identity = load_campaign_identity(root)
    try:
        relative = selection_path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ReviewStoreError("REVIEW_INVALID_SELECTION: duplicate selection must be inside campaign") from exc
    raw = parse_json_strict(selection_path.read_bytes())
    pairs = raw.get("pairs") if isinstance(raw, dict) else None
    summary_paths = raw.get("summary_paths") if isinstance(raw, dict) else None
    if not isinstance(pairs, list) or not pairs:
        raise ReviewStoreError("REVIEW_INVALID_SELECTION: duplicate pairs required")
    if not isinstance(summary_paths, list) or not summary_paths or any(
        not isinstance(value, str) or not value for value in summary_paths
    ):
        raise ReviewStoreError(
            "REVIEW_INVALID_SELECTION: explicit summary_paths are required for duplicate evidence"
        )
    registry_path = _configured_registry_path(root)
    registry = load_registry(registry_path)
    registry_digest = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    selection_data = selection_path.read_bytes()
    selection_digest = hashlib.sha256(selection_data).hexdigest()
    parsed = []
    sources = [{"source_id":"duplicate-selection","path":relative,"sha256":selection_digest,"size":len(selection_data)}]
    summary_bindings = []
    summary_source_ids = {}
    for index, value in enumerate(summary_paths, 1):
        candidate = (root / value).resolve()
        try:
            summary_relative = candidate.relative_to(root).as_posix()
        except ValueError as exc:
            raise ReviewStoreError("REVIEW_PATH: summary outside campaign") from exc
        cursor = root
        for part in Path(value).parts:
            cursor /= part
            if cursor.is_symlink():
                raise ReviewStoreError(f"REVIEW_PATH: symlink summary refused: {value}")
        if not candidate.is_file():
            raise ReviewStoreError(f"REVIEW_INVALID_SELECTION: missing summary {value}")
        data = candidate.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        source_id = f"duplicate-summary-{index}"
        summary_source_ids[summary_relative] = source_id
        sources.append({"source_id":source_id,"path":summary_relative,"sha256":digest,"size":len(data)})
        summary_bindings.append({"source_id":source_id,"path":summary_relative,"custody_sha256":digest,"semantic_sha256":digest})
        parsed.append(parse.parse_file(candidate, root))
    observations = corpus.build_observations(parsed, duplicates.make_grouper(registry))
    review_id = f"duplicate-review-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    items = []
    seen = set()
    entity_by_name = {entry.name: entry for entry in registry.entities}
    for pair in pairs:
        if not isinstance(pair, dict) or not {"id", "a", "b"}.issubset(pair):
            raise ReviewStoreError("REVIEW_INVALID_SELECTION: malformed duplicate pair")
        item_id, left, right = str(pair["id"]), str(pair["a"]), str(pair["b"])
        if item_id in seen or left == right or left not in entity_by_name or right not in entity_by_name:
            raise ReviewStoreError("REVIEW_INVALID_SELECTION: duplicate pair is ambiguous or absent from registry")
        seen.add(item_id)
        excerpt = item_id
        category = str(pair.get("category", pair.get("type", "")))
        if not category:
            raise ReviewStoreError(
                "REVIEW_INVALID_SELECTION: duplicate pair category is required"
            )
        pair_observations = [
            observation for observation in observations
            if observation.category == category
            and observation.heading.casefold() in {left.casefold(), right.casefold()}
        ]
        observed_names = {observation.heading.casefold() for observation in pair_observations}
        evidence_complete = {left.casefold(), right.casefold()} <= observed_names
        supplied_evidence_digest = duplicates.duplicate_evidence_digest(
            category, left, right, pair_observations, {"kind":"global","value":None}
        )
        evidence = tuple(
            {
                "source_id": summary_source_ids[observation.source_file],
                "source_path": observation.source_file,
                "anchor": observation.heading,
                "exact_excerpt": observation.body or observation.heading,
                "selected_span_sha256": hashlib.sha256(
                    (observation.body or observation.heading).encode("utf-8")
                ).hexdigest(),
                "citation_resolved": True,
            }
            for observation in pair_observations
        )
        if not evidence:
            evidence = ({"source_id":"duplicate-selection","source_path":relative,"anchor":item_id,"missing_reason":"Selected summaries contain no evidence for either candidate.","citation_resolved":False},)
        items.append(ReviewItem(
            item_id=item_id, revision=1, campaign_id=identity.campaign_id, review_id=review_id,
            domain="duplicate_identity",
            subject_ref={"subject_id":uuid5(NAMESPACE_URL,f"{identity.campaign_id}:pair:{item_id}"),"kind":"pair","registry_name":f"{left} / {right}","registry_type":"pair","registry_snapshot_sha256":registry_digest},
            occurrence_id=uuid5(NAMESPACE_URL,f"{identity.campaign_id}:pair-occurrence:{item_id}"),
            locator={"source_path":relative,"anchor":item_id},
            claim_text=f"{left} and {right} may be the same identity.",
            evidence=evidence,
            diagnostics=({"diagnostic_id":f"duplicate-{item_id}","legacy_code":"possible-duplicate" if evidence_complete else "duplicate-evidence-missing","message":"Explicit GM identity review required." if evidence_complete else "Both candidate headings must be present in the selected summary evidence.","blocking":not evidence_complete,"details":{"candidate_source":"parsed-summary-selection","evidence_complete":evidence_complete}},),
            categories={"unsupported_or_contradicted"}, severity="needs_judgment", assignment_basis="advisory_candidate",
            rationale="Similarity is a candidate, not merge authority.",
            proposed_action={"action":"adjudicate_identity","details":{"pair_id":item_id,"category":category,"evidence_digest":supplied_evidence_digest,"candidates":[{"subject_id":str(uuid5(NAMESPACE_URL,f"{identity.campaign_id}:{left}")),"registry_name":left},{"subject_id":str(uuid5(NAMESPACE_URL,f"{identity.campaign_id}:{right}")),"registry_name":right}]}},
            scope={"kind":"global"}, rule_versions=({"rule_id":"duplicate-review","version":"1"},),
            input_bindings=({"source_id":"duplicate-selection","path":relative,"custody_sha256":selection_digest,"semantic_sha256":hashlib.sha256(excerpt.encode()).hexdigest()},*summary_bindings),
        ))
    custody=SourceCustodyGeneration(campaign_id=identity.campaign_id,review_id=review_id,generation=1,recorded_at=now,sources=tuple(sources))
    manifest=ReviewManifest(campaign_id=identity.campaign_id,review_id=review_id,kind="duplicate_identity",generation=1,created_at=now,created_by="local-cli",selection=tuple({"kind":"pair","id":item.item_id} for item in items),items=tuple({"campaign_id":identity.campaign_id,"review_id":review_id,"item_id":item.item_id,"revision":1,"review_digest":item.review_digest} for item in items),source_manifest={"campaign_id":identity.campaign_id,"review_id":review_id,"generation":1,"digest":custody.custody_digest},rule_versions=({"rule_id":"duplicate-review","version":"1"},))
    return create_review(root,manifest,custody,items)


def _create_verified_dossier_review(root:Path,dossiers:list[dict])->dict:
    """Run the real aggregate verifier for a literal dossier selection."""
    from pipelines.summary_native import npc_verify,parse
    from pipelines.summary_native.review.models import SubjectReference
    from pipelines.summary_native.review.verification import SelectedNpcVerification,adapt_selected_verifications
    identity=load_campaign_identity(root); review_id=f"npc-review-{uuid.uuid4().hex[:12]}"; now=datetime.now(timezone.utc)
    selected=[]; source_map={}; selection_refs=[]
    for entry in dossiers:
        if not isinstance(entry,dict) or not {"id","npc","draft_path","evidence_path","summary_paths"}.issubset(entry):
            raise ReviewStoreError("REVIEW_INVALID_SELECTION: dossier selection is malformed")
        paths={}; texts={}
        named=[("draft",entry["draft_path"]),("evidence",entry["evidence_path"])]
        named.extend((f"summary-{index}",value) for index,value in enumerate(entry["summary_paths"],1))
        for role,value in named:
            relative=str(value); candidate=root/relative; cursor=root
            for part in Path(relative).parts:
                cursor=cursor/part
                if cursor.is_symlink(): raise ReviewStoreError(f"REVIEW_PATH: symlink source refused: {relative}")
            resolved=candidate.resolve()
            try: resolved.relative_to(root)
            except ValueError as exc: raise ReviewStoreError("REVIEW_PATH: source outside campaign") from exc
            if not resolved.is_file(): raise ReviewStoreError(f"REVIEW_INVALID_SELECTION: missing {role} {relative}")
            data=resolved.read_bytes(); texts[role]=data.decode("utf-8"); paths[role]=resolved
            source_id=f"{role}-{hashlib.sha256(relative.encode()).hexdigest()[:16]}"
            source_map[source_id]={"source_id":source_id,"path":relative,"sha256":hashlib.sha256(data).hexdigest(),"size":len(data)}
        summary_roles=[role for role,_ in named if role.startswith("summary-")]
        parsed=[parse.parse_file(paths[role],root) for role in summary_roles]
        index=npc_verify.CorpusIndex.from_parsed(parsed); summaries=npc_verify.load_summaries_text(paths[role] for role in summary_roles)
        manual=entry.get("manual",[])
        if not isinstance(manual,list) or any(not isinstance(value,str) for value in manual): raise ReviewStoreError("REVIEW_INVALID_SELECTION: manual edits must be strings")
        result=npc_verify.verify(texts["draft"],texts["evidence"],index,summaries,manual)
        draft_relative=str(entry["draft_path"]); evidence_relative=str(entry["evidence_path"])
        selected.append(SelectedNpcVerification(selection_id=str(entry["id"]),subject_ref=SubjectReference(subject_id=uuid.uuid5(identity.campaign_id,str(entry["npc"])),kind="entity"),draft_source_id=f"draft-{hashlib.sha256(draft_relative.encode()).hexdigest()[:16]}",draft_path=draft_relative,draft_text=texts["draft"],evidence_source_id=f"evidence-{hashlib.sha256(evidence_relative.encode()).hexdigest()[:16]}",evidence_path=evidence_relative,evidence_text=texts["evidence"],result=result))
        selection_refs.append({"kind":"subject","id":str(entry["id"])})
    items=list(adapt_selected_verifications(campaign_id=identity.campaign_id,review_id=review_id,selected=selected))
    items.extend(_npc_signoff_items(identity.campaign_id,review_id,selected,{
        value.draft_path: str(entry["npc"])
        for value, entry in zip(selected, dossiers)
    },verification_complete=True))
    sources=list(source_map.values())
    custody=SourceCustodyGeneration(campaign_id=identity.campaign_id,review_id=review_id,generation=1,recorded_at=now,sources=tuple(sources))
    manifest=ReviewManifest(campaign_id=identity.campaign_id,review_id=review_id,kind="npc_verification",generation=1,created_at=now,created_by="local-cli",selection=tuple(selection_refs),items=tuple({"campaign_id":identity.campaign_id,"review_id":review_id,"item_id":item.item_id,"revision":item.revision,"review_digest":item.review_digest} for item in items),source_manifest={"campaign_id":identity.campaign_id,"review_id":review_id,"generation":1,"digest":custody.custody_digest},rule_versions=({"rule_id":"npc-verify","version":"1"},))
    return create_review(root,manifest,custody,items)


def _npc_signoff_items(campaign_id,review_id,selections,names,*,verification_complete:bool):
    """Create one whole-draft signoff item per exact selected NPC draft."""
    items=[]; seen=set()
    for selection in selections:
        if selection.draft_path in seen: continue
        seen.add(selection.draft_path)
        data=selection.draft_text.encode("utf-8"); digest=hashlib.sha256(data).hexdigest()
        excerpt=selection.draft_text.splitlines()[0] if selection.draft_text.splitlines() else "empty NPC draft"
        item_id=f"npc-signoff-{hashlib.sha256(selection.draft_path.encode()).hexdigest()[:20]}"
        items.append(ReviewItem(
            item_id=item_id,revision=selection.revision,campaign_id=campaign_id,review_id=review_id,
            domain="npc_finding",subject_ref=selection.subject_ref,
            occurrence_id=uuid.uuid5(campaign_id,f"npc-draft-signoff:{selection.draft_path}"),
            locator={"source_path":selection.draft_path,"anchor":"whole-draft"},
            claim_text=f"Approve exact NPC draft bytes for {names.get(selection.draft_path,selection.draft_path)}.",
            evidence=({"source_id":selection.draft_source_id,"source_path":selection.draft_path,"anchor":"whole-draft","exact_excerpt":excerpt,"selected_span_sha256":hashlib.sha256(excerpt.encode()).hexdigest(),"citation_resolved":True},),
            diagnostics=({"diagnostic_id":f"npc-draft-signoff-{item_id[-12:]}","legacy_code":"npc-draft-signoff-required","message":"Independent exact-draft approval is required before publication.","blocking":False,"details":{"mechanical_verdict":selection.result.verdict,"verification_complete":verification_complete}},),
            categories={"citation_non_entailment"},severity="needs_judgment",assignment_basis="gm_confirmed",
            rationale="Publication requires a separate GM signoff for exact draft bytes after a complete mechanical verification.",
            proposed_action={"action":"signoff_npc_draft","details":{"npc":names.get(selection.draft_path,selection.draft_path),"draft_path":selection.draft_path,"draft_sha256":digest,"mechanical_verdict":selection.result.verdict,"verification_complete":verification_complete}},
            scope={"kind":"document","value":selection.draft_path},
            rule_versions=({"rule_id":"npc-draft-signoff","version":"1"},),
            input_bindings=({"source_id":selection.draft_source_id,"path":selection.draft_path,"custody_sha256":digest,"semantic_sha256":digest},),
        ))
    return items


def _sign_npc_draft(root:Path,review_id:str,*,item_id:str,draft_sha256:str,expected_decision_revision:int,reviewer:str)->dict:
    """Approve one exact draft only after its complete real verifier pass."""
    manifest,_custody,items=read_snapshot(root,review_id)
    item=next((value for value in items if value.item_id==item_id),None)
    if item is None or item.proposed_action.action!="signoff_npc_draft":
        raise ReviewStoreError("REVIEW_NPC_SIGNOFF_ITEM: exact NPC draft signoff item is missing","REVIEW_NPC_SIGNOFF_ITEM")
    details=item.proposed_action.details
    if details.get("verification_complete") is not True:
        raise ReviewStoreError("REVIEW_NPC_RECHECK_REQUIRED: run the complete dossier verification selection","REVIEW_NPC_RECHECK_REQUIRED")
    if details.get("mechanical_verdict")!="pass":
        raise ReviewStoreError("REVIEW_NPC_MECHANICAL_BLOCK: repair hard verification failures and run a real recheck","REVIEW_NPC_MECHANICAL_BLOCK")
    if details.get("draft_sha256")!=draft_sha256:
        raise ReviewStoreError("REVIEW_NPC_SIGNOFF_STALE: requested digest differs from reviewed draft","REVIEW_NPC_SIGNOFF_STALE")
    path=(Path(root)/str(details.get("draft_path"))).resolve()
    try: path.relative_to(Path(root).resolve())
    except ValueError as exc: raise ReviewStoreError("REVIEW_PATH: draft outside campaign") from exc
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=draft_sha256:
        raise ReviewStoreError("REVIEW_NPC_SIGNOFF_STALE: draft bytes changed","REVIEW_NPC_SIGNOFF_STALE")
    return save_decisions(root,review_id,{"version":1,"request_id":f"npc-signoff-{item_id}-{expected_decision_revision}","review_generation":manifest.generation,"reviewer":reviewer,"decisions":[{"item_id":item.item_id,"item_revision":item.revision,"review_digest":item.review_digest,"expected_decision_revision":expected_decision_revision,"verdict":"approve","disposition":"document_signoff","note":"Approved exact mechanically verified NPC draft bytes."}]})


def run(args: argparse.Namespace) -> int:
    try:
        root, _ = resolve_review_scope(config=args.config, campaign_dir=args.campaign_dir)
        if args.review_command == "init":
            identity = initialize_campaign(root)
            return _emit(
                args,
                ok=True,
                code="REVIEW_INITIALIZED",
                message="Review storage is initialized.",
                data={"campaign_id": str(identity.campaign_id), "campaign_root": identity.canonical_root},
                artifacts=[str(root / "docs" / "reviews" / "campaign.json")],
            )
        if args.review_command == "create":
            result=_create_selected_review(root,args.kind,Path(args.selection))
            return _emit(args,ok=True,code="REVIEW_CREATED",message="Review created.",data=result)
        if args.review_command == "list":
            return _emit(args,ok=True,code="REVIEW_LIST",message="Reviews loaded.",data={"reviews":list_reviews(root)})
        if args.review_command == "status":
            return _emit(args,ok=True,code="REVIEW_STATUS",message="Review status loaded.",data=review_status(root,args.review))
        if args.review_command == "export":
            selection=parse_json_strict(Path(args.selection).read_bytes());ids=selection.get("items") if isinstance(selection,dict) else None
            if not isinstance(ids,list): raise ReviewStoreError("REVIEW_INVALID_SELECTION: export needs items")
            return _emit(args,ok=True,code="REVIEW_EXPORTED",message="Review exported.",data=export_review(root,args.review,ids))
        if args.review_command == "import":
            return _emit(args,ok=True,code="REVIEW_IMPORTED",message="Review imported.",data=import_review_bundle(root,Path(args.bundle),expected_generation=args.expected_generation))
        if args.review_command == "migrate":
            result = (
                plan_authority_migration(root)
                if args.dry_run
                else apply_authority_migration(root, plan_sha256=args.plan_sha256)
            )
            return _emit(args, ok=True, code="REVIEW_MIGRATION_PLAN" if args.dry_run else "REVIEW_MIGRATED", message="Authority migration checked.", data=result)
        if args.review_command == "dependencies":
            from pipelines.summary_native.review.migrate import apply_dependency_adoption, plan_dependency_adoption
            result=plan_dependency_adoption(root) if args.dry_run else apply_dependency_adoption(root,plan_sha256=args.plan_sha256)
            return _emit(args,ok=True,code="REVIEW_DEPENDENCY_PLAN" if args.dry_run else "REVIEW_DEPENDENCIES_ADOPTED",message="Identity dependency migration checked.",data=result)
        if args.review_command == "recover":
            result = recover_transaction(root, args.transaction)
            return _emit(args, ok=True, code="REVIEW_RECOVERED", message="Transaction recovery completed.", data=result)
        if args.review_command == "decide":
            review_config = load_campaign_review_config(root)
            if args.decisions == "-":
                request_bytes = sys.stdin.buffer.read(review_config.max_request_bytes + 1)
            else:
                decision_path = Path(args.decisions)
                if decision_path.stat().st_size > review_config.max_request_bytes:
                    raise ReviewStoreError("REVIEW_INVALID_BATCH: decision request is too large", "REVIEW_INVALID_BATCH")
                request_bytes = decision_path.read_bytes()
            if len(request_bytes) > review_config.max_request_bytes:
                raise ReviewStoreError("REVIEW_INVALID_BATCH: decision request is too large", "REVIEW_INVALID_BATCH")
            request = parse_json_strict(request_bytes)
            decisions = request.get("decisions") if isinstance(request, dict) else None
            if not isinstance(decisions, list) or len(decisions) > review_config.max_batch_decisions:
                raise ReviewStoreError("REVIEW_INVALID_BATCH: too many decisions", "REVIEW_INVALID_BATCH")
            if any(not isinstance(member, dict) or len(str(member.get("note", ""))) > review_config.max_note_chars for member in decisions):
                raise ReviewStoreError("REVIEW_INVALID_BATCH: decision note is too long", "REVIEW_INVALID_BATCH")
            grant_check = None
            if args.grant is not None:
                token = os.environ.get("REVIEW_CAPABILITY_TOKEN")
                if not token:
                    raise ReviewStoreError("REVIEW_ACCESS_DENIED: capability is unavailable")
                from pipelines.summary_native.review.access import validate_grant

                grant_check = lambda: validate_grant(root, args.review, args.grant, token)
            result = save_decisions(root, args.review, request, grant_check=grant_check)
            return _emit(args, ok=True, code="REVIEW_DECISIONS_SAVED", message="Review decisions saved.", data=result)
        if args.review_command == "history":
            events = history(root, args.review, item_id=args.item)
            return _emit(args, ok=True, code="REVIEW_HISTORY", message="Review history loaded.", data={"events": events})
        if args.review_command == "show":
            result = _show_review(
                root, args.review, item_id=args.item, cursor=args.cursor, limit=args.limit,
                section_offset=args.section_offset,
            )
            return _emit(args, ok=True, code="REVIEW_SHOW", message="Review loaded.", data=result)
        if args.review_command == "retract":
            result = retract_decision(root, args.review, event_id=args.event, expected_revision=args.expected_decision_revision, reason=args.reason)
            return _emit(args, ok=True, code="REVIEW_RETRACTED", message="Decision withdrawn; applied artifacts were not changed.", data=result)
        if args.review_command == "refresh":
            from pipelines.summary_native.review.store import refresh_review
            result=refresh_review(root,args.review,expected_generation=args.expected_generation)
            return _emit(args,ok=True,code="REVIEW_REFRESHED",message="Review custody refreshed.",data=result)
        if args.review_command == "finding":
            from pipelines.summary_native.review.verification import add_attributable_findings
            payload=parse_json_strict(Path(args.finding).read_bytes())
            result=add_attributable_findings(root,args.review,payload=payload,expected_generation=args.expected_generation)
            return _emit(args,ok=True,code="REVIEW_FINDINGS_ADDED",message="Attributable findings added as pending candidates.",data=result)
        if args.review_command == "rerun":
            from pipelines.summary_native.review.verification import execute_rerun, preview_rerun
            if args.rerun_command == "preview":
                payload=parse_json_strict(Path(args.selection).read_bytes()); members=payload.get("members") if isinstance(payload,dict) else None
                if not isinstance(members,list): raise ReviewStoreError("REVIEW_INVALID_SELECTION: rerun members required")
                selected={str(member["item_id"]):tuple(str(value) for value in member["check_ids"]) for member in members}
                result=preview_rerun(root,args.review,members=selected,mode=args.mode)
                return _emit(args,ok=True,code="REVIEW_RERUN_PREVIEW",message="Immutable rerun selection prepared.",data=canonicalize(result))
            selection_path=root/"docs/reviews"/args.review/"runs/selections"/f"{args.selection_sha256}.json"
            selection_payload=parse_json_strict(selection_path.read_bytes()); check_ids={check for member in selection_payload.get("members",[]) for check in member.get("check_ids",[])}
            def checker(check_id):
                def run(item):
                    diagnostic=next((value for value in item.diagnostics if value.diagnostic_id==check_id or value.legacy_code==check_id),None)
                    if diagnostic is None: raise ReviewStoreError(f"REVIEW_UNKNOWN_CHECK: {check_id}")
                    return {"diagnostic":canonicalize(diagnostic),"input_bindings":canonicalize(item.input_bindings)}
                return run
            result=execute_rerun(root,args.review,selection_sha256=args.selection_sha256,checkers={check:checker(check) for check in check_ids})
            return _emit(args,ok=True,code="REVIEW_RERUN_COMPLETE",message="Selected deterministic checks completed.",data=canonicalize(result))
        if args.review_command == "correction":
            from pipelines.summary_native.review.corrections import apply_correction,prepare_correction
            summaries=Path(args.summaries_dir) if args.summaries_dir else None
            if args.correction_command=="prepare":
                result=prepare_correction(root,args.review,args.item,target_kind=args.target_kind,replacement_text=args.replacement,expected_decision_revision=args.expected_decision_revision,summaries_dir=summaries)
                return _emit(args,ok=True,code="REVIEW_CORRECTION_PREPARED",message="Exact correction preview prepared.",data=canonicalize(result))
            result=apply_correction(root,args.review,proposal_id=args.proposal,proposal_sha256=args.proposal_sha256,summaries_dir=summaries)
            return _emit(args,ok=True,code="REVIEW_CORRECTION_APPLIED",message="Reviewed source correction applied.",data=canonicalize(result))
        if args.review_command == "npc":
            result=_sign_npc_draft(root,args.review,item_id=args.item,draft_sha256=args.draft_sha256,expected_decision_revision=args.expected_decision_revision,reviewer=args.reviewer)
            return _emit(args,ok=True,code="REVIEW_NPC_SIGNED",message="Exact mechanically verified NPC draft signed.",data=result)
        if args.review_command == "document":
            from pipelines.summary_native.review.documents import WHOLE_BUNDLE_INSTRUCTION, create_document_review,sign_document
            if args.document_command=="create": result=create_document_review(root,args.review,Path(args.selection),created_by="local-cli")
            elif args.document_command=="sign": result=sign_document(root,args.review,document_item_id=args.item,item_sha256=args.document_sha256,expected_decision_revision=args.expected_decision_revision,reviewer=args.reviewer)
            else:
                raise ReviewStoreError(WHOLE_BUNDLE_INSTRUCTION, "PROMOTION_WHOLE_BUNDLE_REQUIRED")
            return _emit(args,ok=True,code=f"REVIEW_DOCUMENT_{args.document_command.upper()}",message="Grounding document operation completed.",data=canonicalize(result))
        if args.review_command == "identity":
            from pipelines.summary_native.review.identity import apply_guard_resolution,apply_identity_proposal,execute_identity_regeneration,identity_resolution_instructions,prepare_guard_resolution,prepare_identity_alternatives,prepare_identity_regeneration
            if args.identity_command == "prepare":
                scope={"kind":args.scope_kind}
                if args.scope_kind != "global":
                    if not args.scope_value: raise ReviewStoreError("REVIEW_INVALID_SCOPE: local scope needs --scope-value")
                    scope["value"]=args.scope_value
                elif args.scope_value:
                    raise ReviewStoreError("REVIEW_INVALID_SCOPE: global scope has no value")
                result=prepare_identity_alternatives(root,args.review,args.item,expected_decision_revision=args.expected_decision_revision,requested_scope=scope)
                resolutions=[value for value in (identity_resolution_instructions(proposal) for proposal in result) if value is not None]
                return _emit(args,ok=True,code="REVIEW_IDENTITY_PREPARED",message="Both canonical alternatives prepared.",data={"proposals":canonicalize(result),"resolutions":resolutions})
            if args.identity_command == "detail":
                path=root/"docs/reviews"/args.review/"proposals"/f"{args.proposal}.json"
                if not path.is_file() or path.is_symlink(): raise ReviewStoreError("REVIEW_INVALID_PROPOSAL: proposal missing")
                result=model_from_json(IdentityProposal,path.read_bytes())
                return _emit(args,ok=True,code="REVIEW_IDENTITY_DETAIL",message="Identity proposal loaded.",data=canonicalize(result))
            if args.identity_command == "resolution":
                path=root/"docs/reviews"/args.review/"proposals"/f"{args.proposal}.json"
                if not path.is_file() or path.is_symlink(): raise ReviewStoreError("REVIEW_INVALID_PROPOSAL: proposal missing")
                proposal=model_from_json(IdentityProposal,path.read_bytes()); result=identity_resolution_instructions(proposal)
                if result is None: raise ReviewStoreError("REVIEW_INVALID_PROPOSAL: proposal has no separately resolvable blocker")
                return _emit(args,ok=True,code="REVIEW_IDENTITY_RESOLUTION",message="Separate blocked resolution instructions loaded.",data=result)
            if args.identity_command == "guard-prepare":
                result=prepare_guard_resolution(root,args.review,blocked_proposal_id=args.proposal,reviewer=args.reviewer,note=args.note)
                return _emit(args,ok=True,code="REVIEW_IDENTITY_GUARD_PREPARED",message="Exact guard-resolution proposal prepared for separate review.",data=result)
            if args.identity_command == "guard-apply":
                result=apply_guard_resolution(root,args.review,resolution_id=args.resolution,resolution_digest=args.resolution_sha256)
                return _emit(args,ok=True,code="REVIEW_IDENTITY_GUARD_APPLIED",message="Reviewed exact guard resolution applied; prepare a new identity preview.",data=result)
            if args.identity_command == "regenerate":
                payload=parse_json_strict(Path(args.selection).read_bytes()); paths=payload.get("paths") if isinstance(payload,dict) else None
                if not isinstance(paths,list) or not all(isinstance(path,str) for path in paths): raise ReviewStoreError("REVIEW_INVALID_SELECTION: paths list required")
                if args.execute:
                    result=execute_identity_regeneration(root,args.review,receipt_id=args.receipt,selected_paths=paths)
                    return _emit(args,ok=True,code="REVIEW_IDENTITY_REGENERATION_EXECUTED",message="Affected-only regeneration executed; generated prose remains pending review.",data=result)
                result=prepare_identity_regeneration(root,args.review,receipt_id=args.receipt,selected_paths=paths)
                return _emit(args,ok=True,code="REVIEW_IDENTITY_REGENERATION_PREPARED",message="Affected-only regeneration prepared; pass --execute locally to run it.",data=result)
            result=apply_identity_proposal(root,args.review,proposal_id=args.proposal,proposal_sha256=args.proposal_sha256)
            return _emit(args,ok=True,code="REVIEW_IDENTITY_APPLIED",message="Reviewed identity proposal applied.",data=canonicalize(result))
        if args.review_command == "access":
            from pipelines.summary_native.review.access import issue_grant, revoke_grant

            if args.access_command == "issue":
                result = issue_grant(root, args.review, expires_in=args.expires_in)
                return _emit(args, ok=True, code="REVIEW_ACCESS_ISSUED", message="Review link issued.", data=result)
            result = revoke_grant(root, args.review, args.grant)
            return _emit(args, ok=True, code="REVIEW_ACCESS_REVOKED", message="Review link revoked.", data=result)
        if args.review_command == "serve":
            from pipelines.summary_native.review.service import serve_foreground

            return serve_foreground(
                root, args.review, host=args.host, port=args.port, origin=args.origin,
                tls_cert=args.tls_cert, tls_key=args.tls_key, json_output=args.json,
            )
        if args.review_command == "service":
            from pipelines.summary_native.review.service import service_status, start_service, stop_service

            if args.service_command == "start":
                result = start_service(
                    root, args.review, host=args.host, port=args.port, origin=args.origin,
                    tls_cert=args.tls_cert, tls_key=args.tls_key,
                )
                return _emit(args, ok=True, code="REVIEW_SERVICE_STARTED", message="Review service started.", data=result)
            if args.service_command == "status":
                result = service_status(root, args.review)
                return _emit(args, ok=True, code="REVIEW_SERVICE_STATUS", message="Review service status loaded.", data=result)
            result = stop_service(root, args.review)
            return _emit(args, ok=True, code="REVIEW_SERVICE_STOPPED", message="Review service stopped.", data=result)
        raise ReviewStoreError("REVIEW_COMMAND: unsupported command")
    except (ReviewConfigError, ReviewStoreError, AuthorityError, OSError, ValueError) as exc:
        code = getattr(exc, "code", None) or str(exc).split(":", 1)[0]
        return _emit(args, ok=False, code=code, message=str(exc))
