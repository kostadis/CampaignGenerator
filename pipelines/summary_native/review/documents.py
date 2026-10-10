"""Grounding document review, exact signoff, and deterministic promotion."""
from __future__ import annotations
import base64, hashlib, json, tempfile, uuid
from datetime import datetime, timezone
from pathlib import Path

from pipelines.summary_native import pointers, state_sections, synth
from pipelines.summary_native.authority import AuthorityLedger, ReviewArtifactRef, ReviewDecisionRecord, ledger_bytes, ledger_path, load_ledger, sha256_bytes
from pipelines.summary_native.authority_apply import TransactionTarget, _prepare_transaction_locked, authority_dir, authority_lock, ledger_tip_path, recover_transaction, require_no_pending_transaction, validate_ledger_tip, _json_bytes, _tip_bytes
from pipelines.summary_native.review.models import DocumentPromotionProposal, DocumentPromotionReceipt, ReviewItem, ReviewManifest, SourceCustodyGeneration, canonical_bytes, model_from_json
from pipelines.summary_native.review.store import ReviewStoreError, _events, _reject_symlinks, _review_dir, create_review, history, load_campaign_identity, read_snapshot, save_decisions

class DocumentReviewError(ReviewStoreError): pass

def _safe(root:Path,value:str)->Path:
    candidate=_reject_symlinks(root,root/value)
    try: candidate.relative_to(root)
    except ValueError as exc: raise DocumentReviewError("REVIEW_DOCUMENT_PATH: path escapes campaign") from exc
    if not candidate.is_file(): raise DocumentReviewError("REVIEW_DOCUMENT_POINTER: selected document is missing")
    return candidate

def create_document_review(campaign_dir:Path,review_id:str,selection_path:Path,*,created_by:str)->dict:
    root=Path(campaign_dir).resolve(); identity=load_campaign_identity(root); raw=json.loads(Path(selection_path).read_bytes()); selected=raw.get("documents")
    if not isinstance(selected,list) or not selected: raise DocumentReviewError("REVIEW_INVALID_SELECTION: documents required")
    now=datetime.now(timezone.utc); items=[]; sources=[]
    for entry in selected:
        document=str(entry["id"]); relative=str(entry["path"]); path=_safe(root,relative); data=path.read_bytes(); digest=sha256_bytes(data); source_id=f"document-{document}"
        sources.append({"source_id":source_id,"path":relative,"sha256":digest,"size":len(data)})
        destination=str(Path(relative).parent.parent/"reviewed"/f"{document}.md")
        items.append(ReviewItem(item_id=f"document-{document}",revision=1,campaign_id=identity.campaign_id,review_id=review_id,domain="grounding_document",subject_ref={"subject_id":uuid.uuid5(identity.campaign_id,f"document:{document}"),"kind":"document"},occurrence_id=uuid.uuid5(identity.campaign_id,f"document-occurrence:{document}"),locator={"source_path":relative,"anchor":"whole-document"},claim_text=f"Approve exact {document} draft for promotion.",evidence=({"source_id":source_id,"source_path":relative,"anchor":"whole-document","exact_excerpt":data.decode("utf-8")[:4096],"selected_span_sha256":sha256_bytes(data.decode("utf-8")[:4096].encode()),"citation_resolved":True},),diagnostics=({"diagnostic_id":f"document-signoff-{document}","legacy_code":"document-signoff-required","message":"Independent exact-document approval is required.","blocking":False},),categories={"citation_non_entailment"},severity="needs_judgment",assignment_basis="gm_confirmed",rationale="Publication requires a separate exact-byte GM signoff.",proposed_action={"action":"signoff_document","details":{"document_id":document,"document_sha256":digest,"destination":destination}},scope={"kind":"document","value":document},rule_versions=({"rule_id":"grounding-document-signoff","version":"1"},),input_bindings=({"source_id":source_id,"path":relative,"custody_sha256":digest,"semantic_sha256":digest},)))
    custody=SourceCustodyGeneration(campaign_id=identity.campaign_id,review_id=review_id,generation=1,recorded_at=now,sources=tuple(sources))
    manifest=ReviewManifest(campaign_id=identity.campaign_id,review_id=review_id,kind="grounding_documents",generation=1,created_at=now,created_by=created_by,selection=tuple({"kind":"document","id":str(entry["id"])} for entry in selected),items=tuple({"campaign_id":identity.campaign_id,"review_id":review_id,"item_id":item.item_id,"revision":1,"review_digest":item.review_digest} for item in items),source_manifest={"campaign_id":identity.campaign_id,"review_id":review_id,"generation":1,"digest":custody.custody_digest},rule_versions=({"rule_id":"grounding-document-signoff","version":"1"},))
    return create_review(root,manifest,custody,items)

def sign_document(campaign_dir:Path,review_id:str,*,document_item_id:str,item_sha256:str,expected_decision_revision:int,reviewer:str)->dict:
    root=Path(campaign_dir); manifest,_,items=read_snapshot(root,review_id); item=next((value for value in items if value.item_id==document_item_id),None)
    if item is None or item.proposed_action.details.get("document_sha256")!=item_sha256: raise DocumentReviewError("REVIEW_DOCUMENT_STALE: exact draft binding differs")
    path=_safe(root,item.locator.source_path)
    if sha256_bytes(path.read_bytes())!=item_sha256: raise DocumentReviewError("REVIEW_DOCUMENT_STALE: draft bytes changed")
    return save_decisions(root,review_id,{"version":1,"request_id":f"document-signoff-{document_item_id}-{expected_decision_revision}","review_generation":manifest.generation,"reviewer":reviewer,"decisions":[{"item_id":item.item_id,"item_revision":item.revision,"review_digest":item.review_digest,"expected_decision_revision":expected_decision_revision,"verdict":"approve","disposition":"document_signoff","note":"Approved exact document bytes for promotion."}]})

def _check_document(root:Path,item:ReviewItem)->tuple[Path,bytes,dict,dict[str,str]]:
    path=_safe(root,item.locator.source_path); data=path.read_bytes(); expected=item.proposed_action.details["document_sha256"]
    if sha256_bytes(data)!=expected: raise DocumentReviewError("REVIEW_DOCUMENT_STALE: draft bytes changed")
    document=item.proposed_action.details["document_id"]; state_dir=path.parent.parent
    outline=synth.check_outline(data.decode("utf-8"),synth.load_outline(document))
    if outline: raise DocumentReviewError(f"REVIEW_DOCUMENT_OUTLINE: {outline[0]}")
    pointer_problems=pointers.check_paths(path,root)
    if pointer_problems: raise DocumentReviewError(f"REVIEW_DOCUMENT_POINTER: {pointer_problems[0]}")
    dependencies:dict[str,str]={}
    for kind in state_sections.CONTRACT_REFERENCES.get(document,()):
        reference=path.parent/"reference"/f"{kind}.md"
        if not reference.is_file(): raise DocumentReviewError("REVIEW_DOCUMENT_POINTER: reading-contract input is missing")
        relative=str(reference.relative_to(root)); dependencies[relative]=sha256_bytes(reference.read_bytes())
    timeline=path.parent/"timeline.md"
    if timeline.is_file(): dependencies[str(timeline.relative_to(root))]=sha256_bytes(timeline.read_bytes())
    record_match=__import__('re').search(r"record:\s*([^ |]+)",data.decode("utf-8"));
    if not record_match: raise DocumentReviewError("REVIEW_DOCUMENT_POINTER: run record is missing")
    record_path=_safe(root,str((state_dir/record_match.group(1)).relative_to(root))); record=json.loads(record_path.read_bytes()); inputs=record.get("inputs",{})
    notes_path=state_dir/"notes/manifest.json"; notes=json.loads(notes_path.read_bytes())
    if notes.get("audience")!="gm": raise DocumentReviewError("REVIEW_DOCUMENT_AUDIENCE: notes audience changed")
    registry=root/"docs/entity_registry.yaml"
    if inputs.get("registry_sha256")!=sha256_bytes(registry.read_bytes()): raise DocumentReviewError("REVIEW_DOCUMENT_STALE: registry changed")
    if inputs.get("notes_manifest_sha256")!=sha256_bytes(notes_path.read_bytes()): raise DocumentReviewError("REVIEW_DOCUMENT_STALE: notes changed")
    corpus_path=state_dir.parent/"manifest.json"
    if inputs.get("corpus_manifest_sha256")!=sha256_bytes(corpus_path.read_bytes()): raise DocumentReviewError("REVIEW_DOCUMENT_STALE: corpus changed")
    corpus_manifest=json.loads(corpus_path.read_bytes())
    for entry in corpus_manifest.get("files",[]):
        source=_safe(root,str(entry.get("path","")))
        if sha256_bytes(source.read_bytes())!=entry.get("sha256"): raise DocumentReviewError("REVIEW_DOCUMENT_STALE: corpus source changed")
        dependencies[str(source.relative_to(root))]=sha256_bytes(source.read_bytes())
    players=root/"config/players.yaml"
    if inputs.get("players_sha256")!=sha256_bytes(players.read_bytes()): raise DocumentReviewError("REVIEW_DOCUMENT_STALE: players changed")
    if "thread_registry_sha256" in inputs:
        threads=root/"docs/thread_registry.yaml"
        if inputs["thread_registry_sha256"]!=sha256_bytes(threads.read_bytes()): raise DocumentReviewError("REVIEW_DOCUMENT_STALE: thread registry changed")
    for dependency in (record_path,notes_path,registry,corpus_path,players):
        dependencies[str(dependency.relative_to(root))]=sha256_bytes(dependency.read_bytes())
    if "thread_registry_sha256" in inputs:
        dependencies[str(threads.relative_to(root))]=sha256_bytes(threads.read_bytes())
    return path,data,record,dependencies

def prepare_document_promotion(campaign_dir:Path,review_id:str,*,document_ids:list[str]):
    root=Path(campaign_dir).resolve(); selected=[]
    with authority_lock(root,exclusive=True):
        require_no_pending_transaction(root); validate_ledger_tip(root)
        manifest,custody,items=read_snapshot(root,review_id,_already_locked=True); events=_events(root,review_id); latest={}
        for event in events: latest[event.get("item_id")]=event
        ledger=load_ledger(root); ledger_before=ledger_path(root).read_bytes(); records=list(ledger.records); targets=[]; changed=False
        for document in document_ids:
            item=next((value for value in items if value.proposed_action.details.get("document_id")==document),None); event=latest.get(item.item_id) if item else None
            if item is None or not event or event.get("verdict")!="approve" or event.get("disposition")!="document_signoff" or event.get("review_digest")!=item.review_digest: raise DocumentReviewError("REVIEW_DOCUMENT_SIGNOFF_REQUIRED: exact independent signoff is missing")
            record=next((value for value in records if isinstance(value,ReviewDecisionRecord) and value.event_id==event["event_id"] and value.status=="accepted"),None)
            if record is None: raise DocumentReviewError("REVIEW_DOCUMENT_SIGNOFF_REQUIRED: authority decision is missing")
            _path,data,_,dependencies=_check_document(root,item); destination=item.proposed_action.details["destination"]
            if (root/destination).exists(): raise DocumentReviewError("REVIEW_DOCUMENT_COLLISION: destination exists")
            proposal_path=_review_dir(root,review_id)/"proposals"/f"promote-{item.item_id}.json"
            if proposal_path.exists():
                proposal=model_from_json(DocumentPromotionProposal,proposal_path.read_bytes())
                if proposal.document_sha256!=sha256_bytes(data) or proposal.dependency_hashes!=dependencies or proposal.decision_bindings[0].event_id!=event["event_id"]: raise DocumentReviewError("REVIEW_DOCUMENT_STALE: existing proposal inputs changed")
            else:
                output_targets=[{"path":destination,"operation":"create","before_exists":False,"after_exists":True,"after_sha256":sha256_bytes(data),"after_bytes_b64":base64.b64encode(data).decode()}]
                draft_parent=Path(item.locator.source_path).parent; reviewed_parent=Path(destination).parent
                for dependency in sorted(dependencies):
                    dep_path=Path(dependency)
                    if dep_path.parent==draft_parent/"reference": out=reviewed_parent/"reference"/dep_path.name
                    elif dep_path==draft_parent/"timeline.md": out=reviewed_parent/"timeline.md"
                    else: continue
                    dep_bytes=(root/dependency).read_bytes(); output_targets.append({"path":str(out),"operation":"create","before_exists":False,"after_exists":True,"after_sha256":sha256_bytes(dep_bytes),"after_bytes_b64":base64.b64encode(dep_bytes).decode()})
                affected=tuple(target["path"] for target in output_targets)
                proposal=DocumentPromotionProposal(proposal_id=f"promote-{item.item_id}",campaign_id=manifest.campaign_id,review_id=review_id,custody={"campaign_id":manifest.campaign_id,"review_id":review_id,"generation":custody.generation,"digest":custody.custody_digest},decision_bindings=({"event_id":event["event_id"],"item_id":item.item_id,"item_revision":item.revision,"review_digest":item.review_digest,"decision_revision":event["decision_revision"]},),applicable=True,targets=tuple(output_targets),affected_paths=affected,inspected_paths=tuple(sorted({item.locator.source_path,*affected,*dependencies})),ledger_sha256=sha256_bytes(ledger_before),created_at=datetime.now(timezone.utc),document_item_id=item.item_id,document_sha256=sha256_bytes(data),destination=destination,dependency_hashes=dependencies)
                targets.append(TransactionTarget.create(proposal_path,canonical_bytes(proposal)))
            expected_ref=ReviewArtifactRef(kind="document_promotion",id=proposal.proposal_id,digest=proposal.proposal_digest)
            if record.proposal is None:
                records[records.index(record)]=record.model_copy(update={"revision":record.revision+1,"proposal":expected_ref}); changed=True
            elif record.proposal!=expected_ref: raise DocumentReviewError("REVIEW_DOCUMENT_STALE: decision names another proposal")
            selected.append(proposal)
        if changed:
            after_ledger=AuthorityLedger(version=ledger.version,campaign=ledger.campaign,revision=ledger.revision+1,records=records,conflicts=ledger.conflicts); ledger_after=ledger_bytes(after_ledger); audit_id=f"event-document-proposals-{sha256_bytes(canonical_bytes(selected))[:16]}"; audit={"id":audit_id,"reason":"document-proposals","actor":"review","recorded_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"before_sha256":sha256_bytes(ledger_before),"after_sha256":sha256_bytes(ledger_after)}
            targets.extend([TransactionTarget.replace(ledger_path(root),ledger_before,ledger_after),TransactionTarget.create(authority_dir(root)/"events"/f"{audit_id}.json",_json_bytes(audit)),TransactionTarget.replace(ledger_tip_path(root),ledger_tip_path(root).read_bytes(),_tip_bytes(audit_id,ledger_after))])
        if targets:
            digest=sha256_bytes(canonical_bytes(selected)); journal=_prepare_transaction_locked(root,proposal_id=f"document-proposals-{digest[:20]}",proposal_sha256=digest,targets=targets); recover_transaction(root,journal["id"],_already_locked=True)
    return tuple(selected)

def promote_document_bundle(campaign_dir:Path,review_id:str,*,proposals:list[dict]):
    root=Path(campaign_dir).resolve(); receipts=[]
    with authority_lock(root,exclusive=True):
        require_no_pending_transaction(root); validate_ledger_tip(root); ledger=load_ledger(root); targets=[]; records=list(ledger.records)
        manifest,_,items=read_snapshot(root,review_id,_already_locked=True); item_by_id={item.item_id:item for item in items}; event_history=_events(root,review_id); latest={}
        for event in event_history: latest[event.get("item_id")]=event
        planned_outputs:dict[str,bytes]={}
        for ref in proposals:
            path=_review_dir(root,review_id)/"proposals"/f"{ref['proposal_id']}.json"; proposal=model_from_json(DocumentPromotionProposal,path.read_bytes())
            if proposal.proposal_digest!=ref["proposal_digest"] or proposal.campaign_id!=manifest.campaign_id or proposal.review_id!=review_id: raise DocumentReviewError("REVIEW_DOCUMENT_STALE: proposal binding changed")
            target=proposal.targets[0]; data=base64.b64decode(target.after_bytes_b64); destination=root/target.path
            binding=proposal.decision_bindings[0]; record=next((value for value in records if isinstance(value,ReviewDecisionRecord) and value.event_id==binding.event_id),None)
            receipt_id=f"receipt-{proposal.proposal_id}"; receipt_path=_review_dir(root,review_id)/"receipts"/f"{receipt_id}.json"
            if receipt_path.exists():
                receipt=model_from_json(DocumentPromotionReceipt,receipt_path.read_bytes())
                if receipt.proposal_digest!=proposal.proposal_digest or not destination.is_file() or sha256_bytes(destination.read_bytes())!=receipt.published_sha256: raise DocumentReviewError("REVIEW_DOCUMENT_STALE: committed promotion receipt does not match live output")
                receipts.append(receipt); continue
            if destination.exists(): raise DocumentReviewError("REVIEW_DOCUMENT_COLLISION: destination exists")
            item=item_by_id.get(proposal.document_item_id); current=latest.get(proposal.document_item_id)
            expected_ref=ReviewArtifactRef(kind="document_promotion",id=proposal.proposal_id,digest=proposal.proposal_digest)
            if item is None or record is None or record.status!="accepted" or record.proposal!=expected_ref or record.receipt is not None or current is None or current.get("event_id")!=binding.event_id or current.get("verdict")!="approve" or current.get("disposition")!="document_signoff": raise DocumentReviewError("REVIEW_DOCUMENT_SIGNOFF_REQUIRED: current authority decision missing")
            _source,current_data,_record,current_dependencies=_check_document(root,item)
            if current_dependencies!=proposal.dependency_hashes: raise DocumentReviewError("REVIEW_DOCUMENT_STALE: publication dependencies changed")
            if sha256_bytes(current_data)!=proposal.document_sha256 or current_data!=data: raise DocumentReviewError("REVIEW_DOCUMENT_STALE: exact draft changed")
            changed=[]
            for output in proposal.targets:
                output_data=base64.b64decode(output.after_bytes_b64); prior=planned_outputs.get(output.path)
                if prior is not None:
                    if prior!=output_data: raise DocumentReviewError("REVIEW_DOCUMENT_COLLISION: selected bundles disagree")
                    continue
                output_path=root/output.path
                if output_path.exists(): raise DocumentReviewError("REVIEW_DOCUMENT_COLLISION: destination exists")
                planned_outputs[output.path]=output_data; changed.append(output.path); targets.append(TransactionTarget.create(output_path,output_data))
            receipt=DocumentPromotionReceipt(receipt_id=receipt_id,campaign_id=proposal.campaign_id,review_id=review_id,proposal_id=proposal.proposal_id,proposal_digest=proposal.proposal_digest,decision_event_ids=(binding.event_id,),changed_paths=tuple(changed),before_hashes={path:None for path in changed},after_hashes={path:sha256_bytes(planned_outputs[path]) for path in changed},authority_record_ids=(record.id,),ledger_sha256=sha256_bytes(ledger_path(root).read_bytes()),committed_at=datetime.now(timezone.utc),document_item_id=proposal.document_item_id,published_sha256=sha256_bytes(data))
            records[records.index(record)]=record.model_copy(update={"revision":record.revision+1,"receipt":ReviewArtifactRef(kind="document_promotion",id=receipt_id,digest=receipt.receipt_digest)})
            targets.append(TransactionTarget.create(receipt_path,canonical_bytes(receipt))); receipts.append(receipt)
        if targets:
            ledger_before=ledger_path(root).read_bytes(); after_ledger=AuthorityLedger(version=ledger.version,campaign=ledger.campaign,revision=ledger.revision+1,records=records,conflicts=ledger.conflicts); ledger_after=ledger_bytes(after_ledger); digest=sha256_bytes(canonical_bytes(receipts)); audit_id=f"event-document-promote-{digest[:16]}"; audit={"id":audit_id,"reason":"document-promotion","actor":"review","recorded_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"before_sha256":sha256_bytes(ledger_before),"after_sha256":sha256_bytes(ledger_after)}
            targets.extend([TransactionTarget.replace(ledger_path(root),ledger_before,ledger_after),TransactionTarget.create(authority_dir(root)/"events"/f"{audit_id}.json",_json_bytes(audit)),TransactionTarget.replace(ledger_tip_path(root),ledger_tip_path(root).read_bytes(),_tip_bytes(audit_id,ledger_after))])
            journal=_prepare_transaction_locked(root,proposal_id=f"document-promote-{digest[:20]}",proposal_sha256=digest,targets=targets); recover_transaction(root,journal["id"],_already_locked=True)
    return tuple(receipts)
