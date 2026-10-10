"""Campaign-local durable storage for review manifests and immutable records."""
from __future__ import annotations

import uuid
import contextlib
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from pydantic import ValidationError

from pipelines.summary_native.authority import AuthorityError, load_ledger, sha256_bytes
from pipelines.summary_native.authority_apply import (
    TransactionTarget,
    _prepare_transaction_locked,
    authority_lock,
    recover_transaction,
    require_no_pending_transaction,
    validate_ledger_tip,
    ledger_tip_path,
    _json_bytes,
    _tip_bytes,
    authority_dir,
)
from pipelines.summary_native.authority import AuthorityLedger, ReviewArtifactRef, ReviewDecisionRecord, ledger_bytes, ledger_path
from pipelines.summary_native.review.models import (
    ReviewItem,
    ReviewKind,
    ReviewManifest,
    SourceCustodyGeneration,
    canonical_bytes,
    model_from_json,
    parse_json_strict,
    DecisionEvent,
)


class ReviewStoreError(ValueError):
    """A safe, actionable refusal at the review storage boundary."""

    def __init__(self, message: str, code: str = "REVIEW_INVALID"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CampaignReviewIdentity:
    version: int
    campaign_id: uuid.UUID
    canonical_root: str

    def bytes(self) -> bytes:
        return canonical_bytes(
            {"version": self.version, "campaign_id": self.campaign_id, "canonical_root": self.canonical_root}
        )


def review_root(campaign_dir: Path) -> Path:
    return Path(campaign_dir).resolve() / "docs" / "reviews"


def _occurrence_context(text: str, excerpt: str) -> str | None:
    """Bind an exact occurrence to its heading ancestry and containing paragraph."""
    if not excerpt or text.count(excerpt) != 1:
        return None
    start = text.index(excerpt)
    before = text[:start]
    headings: dict[int, str] = {}
    for line in before.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            headings = {depth: value for depth, value in headings.items() if depth < level}
            headings[level] = stripped.strip()
    paragraph_start = before.rfind("\n\n") + 2
    after_end = start + len(excerpt)
    paragraph_stop = text.find("\n\n", after_end)
    if paragraph_stop < 0:
        paragraph_stop = len(text)
    paragraph = text[paragraph_start:paragraph_stop].strip()
    return sha256_bytes(canonical_bytes({
        "heading_ancestry": [headings[level] for level in sorted(headings)],
        "paragraph": paragraph,
        "excerpt": excerpt,
    }))


def _item_contexts(root: Path, items: Iterable[ReviewItem]) -> dict:
    contexts: dict[str, dict[str, str]] = {}
    for item in items:
        per_source: dict[str, str] = {}
        for binding in item.input_bindings:
            try:
                text = _reject_symlinks(root, root / binding.path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            excerpts = [
                evidence.exact_excerpt for evidence in item.evidence
                if evidence.source_id == binding.source_id and evidence.exact_excerpt
            ]
            if item.locator.source_path == binding.path and item.claim_text:
                excerpts.append(item.claim_text)
            digests = [_occurrence_context(text, excerpt) for excerpt in excerpts]
            if digests and all(digests):
                per_source[binding.source_id] = sha256_bytes(canonical_bytes(digests))
        contexts[item.item_id] = per_source
    return contexts


def _reject_symlinks(root: Path, path: Path) -> Path:
    root = root.resolve()
    candidate = Path(path)
    absolute = candidate if candidate.is_absolute() else root / candidate
    try:
        absolute.relative_to(root)
    except ValueError as exc:
        raise ReviewStoreError(f"REVIEW_PATH: path outside campaign root: {path}") from exc
    cursor = root
    for part in absolute.relative_to(root).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ReviewStoreError(f"REVIEW_PATH: symlink is not allowed: {cursor}")
    return absolute


def _identity_path(root: Path) -> Path:
    return review_root(root) / "campaign.json"


def initialize_campaign(campaign_dir: Path) -> CampaignReviewIdentity:
    """Deliberately initialize review storage; never migrate authority implicitly."""
    root = Path(campaign_dir).resolve()
    path = _identity_path(root)
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        if not (root / "docs" / "authority.yaml").is_file():
            raise ReviewStoreError("REVIEW_AUTHORITY_REQUIRED: initialize authority before review storage")
        try:
            ledger = load_ledger(root)
            validate_ledger_tip(root)
        except AuthorityError as exc:
            raise ReviewStoreError(
                "REVIEW_AUTHORITY_MIGRATION_REQUIRED: validate or migrate the authority ledger before review init"
            ) from exc
        if ledger.version != 2:
            raise ReviewStoreError("REVIEW_AUTHORITY_MIGRATION_REQUIRED: run review migrate before review init")
        if path.exists():
            identity = load_campaign_identity(root)
            if identity.canonical_root != str(root):
                raise ReviewStoreError("REVIEW_CAMPAIGN_MOVED: deliberate verified rebind is required")
            return identity
        _reject_symlinks(root, path)
        identity = CampaignReviewIdentity(1, uuid.uuid4(), str(root))
        journal = _prepare_transaction_locked(
            root,
            proposal_id=f"review-init-{identity.campaign_id.hex}",
            proposal_sha256=sha256_bytes(identity.bytes()),
            targets=[TransactionTarget.create(path, identity.bytes())],
        )
        recover_transaction(root, journal["id"], _already_locked=True)
        return identity


def load_campaign_identity(campaign_dir: Path) -> CampaignReviewIdentity:
    root = Path(campaign_dir).resolve()
    path = _reject_symlinks(root, _identity_path(root))
    try:
        raw = parse_json_strict(path.read_bytes())
        if (
            not isinstance(raw, dict)
            or set(raw) != {"version", "campaign_id", "canonical_root"}
            or type(raw["version"]) is not int
            or raw["version"] != 1
        ):
            raise ValueError("unsupported or unknown identity fields")
        identity = CampaignReviewIdentity(1, uuid.UUID(raw["campaign_id"]), raw["canonical_root"])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ReviewStoreError("REVIEW_NOT_INITIALIZED: run review init") from exc
    if identity.canonical_root != str(root):
        raise ReviewStoreError("REVIEW_CAMPAIGN_MOVED: deliberate verified rebind is required")
    return identity


def _review_dir(root: Path, review_id: str) -> Path:
    if not review_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in review_id):
        raise ReviewStoreError("REVIEW_ID: invalid opaque review id")
    return _reject_symlinks(root, review_root(root) / review_id)


def create_review(
    campaign_dir: Path,
    manifest: ReviewManifest,
    custody: SourceCustodyGeneration,
    items: Iterable[ReviewItem],
) -> dict:
    root = Path(campaign_dir).resolve()
    identity = load_campaign_identity(root)
    materialized = tuple(items)
    if manifest.campaign_id != identity.campaign_id or custody.campaign_id != identity.campaign_id:
        raise ReviewStoreError("REVIEW_CAMPAIGN_MISMATCH: records belong to another campaign")
    if (
        custody.review_id != manifest.review_id
        or custody.generation != manifest.source_manifest.generation
        or custody.custody_digest != manifest.source_manifest.digest
    ):
        raise ReviewStoreError("REVIEW_CUSTODY_MISMATCH: source generation does not match manifest")
    expected_domain = {
        ReviewKind.NPC_VERIFICATION: "npc_finding",
        ReviewKind.DUPLICATE_IDENTITY: "duplicate_identity",
        ReviewKind.GROUNDING_DOCUMENTS: "grounding_document",
    }[manifest.kind]
    by_id = {item.item_id: item for item in materialized}
    if len(by_id) != len(materialized):
        raise ReviewStoreError("REVIEW_DUPLICATE_ITEM: duplicate item id")
    for ref in manifest.items:
        item = by_id.get(ref.item_id)
        if item is None or item.revision != ref.revision or item.review_digest != ref.review_digest:
            raise ReviewStoreError(f"REVIEW_ITEM_MISMATCH: {ref.item_id}")
        if item.review_id != manifest.review_id or item.domain.value != expected_domain:
            raise ReviewStoreError(f"REVIEW_DOMAIN_MISMATCH: {ref.item_id}")
        if item.campaign_id != identity.campaign_id:
            raise ReviewStoreError(f"REVIEW_CAMPAIGN_MISMATCH: {ref.item_id}")
        custody_sources = {source.source_id: source for source in custody.sources}
        for binding in item.input_bindings:
            source = custody_sources.get(binding.source_id)
            if source is None or source.path != binding.path or source.sha256 != binding.custody_sha256:
                raise ReviewStoreError(f"REVIEW_CUSTODY_MISMATCH: {ref.item_id}/{binding.source_id}")
    if set(by_id) != {ref.item_id for ref in manifest.items}:
        raise ReviewStoreError("REVIEW_ITEM_MISMATCH: unreferenced item supplied")
    directory = _review_dir(root, manifest.review_id)
    targets = [
        TransactionTarget.create(directory / "manifest.json", canonical_bytes(manifest)),
        TransactionTarget.create(directory / "sources" / f"{custody.generation}.json", canonical_bytes(custody)),
        TransactionTarget.create(
            directory / "sources" / f"{custody.generation}-contexts.json",
            canonical_bytes({"version": 1, "generation": custody.generation, "items": _item_contexts(root, materialized)}),
        ),
    ]
    targets.extend(
        TransactionTarget.create(directory / "items" / item.item_id / f"{item.revision}.json", canonical_bytes(item))
        for item in materialized
    )
    proposal = canonical_bytes({"manifest": manifest, "custody": custody, "items": materialized})
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        journal = _prepare_transaction_locked(
            root,
            proposal_id=f"review-create-{manifest.review_id}",
            proposal_sha256=sha256_bytes(proposal),
            targets=targets,
        )
        recover_transaction(root, journal["id"], _already_locked=True)
    return {"review_id": manifest.review_id, "item_count": len(materialized), "transaction_id": journal["id"]}


def read_snapshot(campaign_dir: Path, review_id: str, *, _already_locked: bool = False) -> tuple[ReviewManifest, SourceCustodyGeneration, tuple[ReviewItem, ...]]:
    root = Path(campaign_dir).resolve()
    load_campaign_identity(root)
    directory = _review_dir(root, review_id)
    with (contextlib.nullcontext() if _already_locked else authority_lock(root, exclusive=False)):
        require_no_pending_transaction(root)
        try:
            manifest_path = _reject_symlinks(root, directory / "manifest.json")
            manifest = model_from_json(ReviewManifest, manifest_path.read_bytes())
            if manifest.campaign_id != load_campaign_identity(root).campaign_id or manifest.review_id != review_id:
                raise ReviewStoreError("REVIEW_CAMPAIGN_MISMATCH: manifest identity")
            source_path = _reject_symlinks(root, directory / "sources" / f"{manifest.source_manifest.generation}.json")
            custody = model_from_json(
                SourceCustodyGeneration,
                source_path.read_bytes(),
            )
            custody_history = tuple(
                model_from_json(SourceCustodyGeneration, _reject_symlinks(root, path).read_bytes())
                for path in sorted((directory / "sources").glob("*.json"))
                if path.stem.isdigit()
            )
            items = tuple(
                model_from_json(ReviewItem, _reject_symlinks(root, directory / "items" / ref.item_id / f"{ref.revision}.json").read_bytes())
                for ref in manifest.items
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise ReviewStoreError(f"REVIEW_CORRUPT: cannot read coherent review {review_id}") from exc
    if (
        custody.campaign_id != manifest.campaign_id
        or custody.review_id != manifest.review_id
        or custody.generation != manifest.source_manifest.generation
        or custody.custody_digest != manifest.source_manifest.digest
    ):
        raise ReviewStoreError("REVIEW_CORRUPT: source custody reference mismatch")
    expected_domain = {
        ReviewKind.NPC_VERIFICATION: "npc_finding",
        ReviewKind.DUPLICATE_IDENTITY: "duplicate_identity",
        ReviewKind.GROUNDING_DOCUMENTS: "grounding_document",
    }[manifest.kind]
    for ref, item in zip(manifest.items, items):
        if (
            item.campaign_id != manifest.campaign_id or item.review_id != manifest.review_id
            or item.item_id != ref.item_id or item.revision != ref.revision
            or item.review_digest != ref.review_digest or item.domain.value != expected_domain
        ):
            raise ReviewStoreError(f"REVIEW_CORRUPT: item reference mismatch: {ref.item_id}")
        current_sources = {source.source_id: source for source in custody.sources}
        for binding in item.input_bindings:
            current = current_sources.get(binding.source_id)
            historical_match = any(
                source.source_id == binding.source_id
                and source.path == binding.path
                and source.sha256 == binding.custody_sha256
                for generation in custody_history
                for source in generation.sources
            )
            if current is None or current.path != binding.path or not historical_match:
                raise ReviewStoreError(f"REVIEW_CORRUPT: item custody mismatch: {ref.item_id}/{binding.source_id}")
    return manifest, custody, items


def _events(root: Path, review_id: str) -> list[dict]:
    directory = _review_dir(root, review_id) / "events"
    result = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else ():
        _reject_symlinks(root, path)
        value = parse_json_strict(path.read_bytes())
        if not isinstance(value, dict):
            raise ReviewStoreError("REVIEW_CORRUPT: event is not an object")
        result.append(value)
    return sorted(result, key=lambda event: (event.get("recorded_at", ""), event.get("event_id", "")))


def history(campaign_dir: Path, review_id: str, *, item_id: str | None = None) -> list[dict]:
    root = Path(campaign_dir).resolve()
    with authority_lock(root, exclusive=False):
        require_no_pending_transaction(root)
        events = _events(root, review_id)
    return [event for event in events if item_id is None or event.get("item_id") == item_id]


def read_review_state(campaign_dir: Path, review_id: str):
    """Read manifest, items, history and semantic staleness under one lock."""
    root=Path(campaign_dir).resolve()
    with authority_lock(root,exclusive=False):
        require_no_pending_transaction(root); manifest,_,items=read_snapshot(root,review_id,_already_locked=True); events=_events(root,review_id)
    stale:set[str]=set()
    for event in events:
        if event.get("kind")=="rebind":
            stale.update(event.get("stale_item_ids",[])); stale.difference_update(event.get("preserved_item_ids",[]))
        elif event.get("kind")=="decision" and event.get("item_id"):
            stale.discard(event["item_id"])
    return manifest,items,events,stale


def save_decisions(
    campaign_dir: Path,
    review_id: str,
    request: dict,
    *,
    grant_check: Callable[[], None] | None = None,
) -> dict:
    """Atomically append a batch and its accepted audit authority records."""
    root = Path(campaign_dir).resolve()
    manifest, custody, items = read_snapshot(root, review_id)
    item_by_id = {item.item_id: item for item in items}
    required = {"version", "request_id", "review_generation", "reviewer", "decisions"}
    if set(request) != required or request.get("version") != 1 or not isinstance(request.get("decisions"), list) or not request["decisions"]:
        raise ReviewStoreError("REVIEW_INVALID_BATCH: malformed decision batch")
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not request_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in request_id):
        raise ReviewStoreError("REVIEW_INVALID_BATCH: invalid request id")
    if request["review_generation"] != manifest.generation:
        raise ReviewStoreError("REVIEW_STALE_GENERATION: review generation changed", "REVIEW_STALE_GENERATION")
    request_digest = sha256_bytes(canonical_bytes(request))
    receipt_path = _review_dir(root, review_id) / "requests" / f"{request['request_id']}.json"
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        if grant_check is not None:
            # Remote authorization is checked at the mutation boundary while
            # revocation uses this same lock. A grant revoked before lock
            # acquisition can therefore never authorize a decision commit.
            grant_check()
        manifest_path = _review_dir(root, review_id) / "manifest.json"
        if manifest_path.read_bytes() != canonical_bytes(manifest):
            raise ReviewStoreError("REVIEW_STALE_GENERATION: manifest changed before save", "REVIEW_STALE_GENERATION")
        if receipt_path.exists():
            receipt = parse_json_strict(receipt_path.read_bytes())
            if receipt.get("request_sha256") != request_digest:
                raise ReviewStoreError("REVIEW_REQUEST_ID_CONFLICT: request id was reused", "REVIEW_REQUEST_ID_CONFLICT")
            return receipt["result"]
        for source in custody.sources:
            current_path = _reject_symlinks(root, root / source.path)
            if not current_path.is_file() or sha256_bytes(current_path.read_bytes()) != source.sha256:
                raise ReviewStoreError("REVIEW_STALE_CUSTODY: source bytes changed", "REVIEW_STALE_CUSTODY")
        existing = _events(root, review_id)
        active = {}
        for event in existing:
            if event.get("kind") == "withdrawal":
                active[event["item_id"]] = event["decision_revision"]
            elif "decision_revision" in event:
                active[event["item_id"]] = event["decision_revision"]
        now = datetime.now(timezone.utc)
        new_events: list[DecisionEvent] = []
        seen = set()
        for index, supplied in enumerate(request["decisions"]):
            if not isinstance(supplied, dict) or supplied.get("item_id") in seen:
                raise ReviewStoreError("REVIEW_INVALID_BATCH: duplicate or malformed decision")
            seen.add(supplied["item_id"])
            item = item_by_id.get(supplied["item_id"])
            if item is None or supplied.get("item_revision") != item.revision or supplied.get("review_digest") != item.review_digest:
                raise ReviewStoreError("REVIEW_STALE_DECISION: item revision changed", "REVIEW_STALE_DECISION")
            expected = supplied.get("expected_decision_revision")
            if expected != active.get(item.item_id, 0):
                raise ReviewStoreError("REVIEW_STALE_DECISION: decision revision changed", "REVIEW_STALE_DECISION")
            namespace = f"{manifest.campaign_id}:{review_id}:{request['request_id']}"
            event_id = f"decision-{sha256_bytes(namespace.encode())[:16]}-{index:04d}"
            approved = supplied.get("verdict") == "approve"
            authority_id = f"review-decision-{sha256_bytes(event_id.encode())[:16]}" if approved else None
            event = DecisionEvent(
                event_id=event_id, request_id=request["request_id"], campaign_id=manifest.campaign_id,
                review_id=review_id, item_id=item.item_id, item_revision=item.revision,
                review_digest=item.review_digest, expected_decision_revision=expected,
                decision_revision=expected + 1, verdict=supplied.get("verdict"), disposition=supplied.get("disposition"),
                note=supplied.get("note", ""), reviewer=request["reviewer"], recorded_at=now,
                supersedes_event=next((e["event_id"] for e in reversed(existing) if e.get("item_id") == item.item_id and e.get("kind") != "withdrawal"), None),
                authority_record_id=authority_id, proposal_id=supplied.get("proposal_id"), proposal_digest=supplied.get("proposal_digest"),
            )
            new_events.append(event)
        ledger = load_ledger(root)
        validate_ledger_tip(root)
        additions = []
        superseded_authority_ids: set[str] = set()
        for event in new_events:
            prior_authority_id = None
            if event.supersedes_event:
                prior = next((entry for entry in existing if entry.get("event_id") == event.supersedes_event), None)
                if prior is not None:
                    prior_authority_id = prior.get("authority_record_id")
                    if prior_authority_id:
                        superseded_authority_ids.add(prior_authority_id)
            if event.authority_record_id is None:
                continue
            item = item_by_id[event.item_id]
            proposal_ref = None
            if event.proposal_id is not None:
                proposal_path = _reject_symlinks(root, _review_dir(root, review_id) / "proposals" / f"{event.proposal_id}.json")
                if not proposal_path.is_file():
                    raise ReviewStoreError("REVIEW_INVALID_PROPOSAL: approved proposal is missing", "REVIEW_INVALID_PROPOSAL")
                proposal_payload = parse_json_strict(proposal_path.read_bytes())
                if proposal_payload.get("proposal_digest") != event.proposal_digest:
                    raise ReviewStoreError("REVIEW_INVALID_PROPOSAL: approved proposal digest differs", "REVIEW_INVALID_PROPOSAL")
                proposal_ref = ReviewArtifactRef(kind=proposal_payload.get("kind"), id=event.proposal_id, digest=event.proposal_digest)
            additions.append(ReviewDecisionRecord(
                id=event.authority_record_id, revision=1, kind="review_decision", status="accepted", classification="RULED",
                subject={"kind":"entity" if item.subject_ref.kind == "entity" else "topic", "id":str(item.subject_ref.subject_id)}, effective={"horizon":"open"},
                audience={"grants":["gm"]}, projections=["planning"], recorded_at=event.recorded_at,
                recorded_by=event.reviewer, campaign_id=manifest.campaign_id, review_id=review_id,
                supersedes=prior_authority_id,
                item_id=item.item_id, item_revision=item.revision, event_id=event.event_id,
                decision_revision=event.decision_revision, event_digest=sha256_bytes(canonical_bytes(event)),
                review_digest=item.review_digest, domain=item.domain.value, disposition=event.disposition.value,
                proposal=proposal_ref,
            ))
        retained_records = [
            record.model_copy(update={"revision": record.revision + 1, "status": "superseded"})
            if isinstance(record, ReviewDecisionRecord) and record.id in superseded_authority_ids
            else record
            for record in ledger.records
        ]
        after_ledger = AuthorityLedger(version=ledger.version, campaign=ledger.campaign, revision=ledger.revision + 1, records=[*retained_records, *additions], conflicts=ledger.conflicts)
        before_ledger = ledger_path(root).read_bytes()
        after_bytes = ledger_bytes(after_ledger)
        audit_id = f"event-review-{uuid.uuid4().hex}"
        audit = {"id":audit_id,"reason":"review-decision","actor":request["reviewer"],"recorded_at":now.isoformat().replace("+00:00","Z"),"before_sha256":sha256_bytes(before_ledger),"after_sha256":sha256_bytes(after_bytes)}
        result = {"request_id": request["request_id"], "events":[{"event_id":event.event_id,"item_id":event.item_id,"decision_revision":event.decision_revision} for event in new_events]}
        targets = [TransactionTarget.create(_review_dir(root, review_id)/"events"/f"{event.event_id}.json", canonical_bytes(event)) for event in new_events]
        targets += [TransactionTarget.replace(ledger_path(root), before_ledger, after_bytes), TransactionTarget.create(authority_dir(root)/"events"/f"{audit_id}.json", _json_bytes(audit)), TransactionTarget.replace(ledger_tip_path(root), ledger_tip_path(root).read_bytes(), _tip_bytes(audit_id, after_bytes)), TransactionTarget.create(receipt_path, canonical_bytes({"request_sha256":request_digest,"result":result}))]
        journal = _prepare_transaction_locked(root, proposal_id=f"review-request-{request['request_id']}", proposal_sha256=request_digest, targets=targets)
        recover_transaction(root, journal["id"], _already_locked=True)
        return result


def retract_decision(campaign_dir: Path, review_id: str, *, event_id: str, expected_revision: int, reason: str) -> dict:
    root = Path(campaign_dir).resolve()
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        events = _events(root, review_id)
        original = next((event for event in events if event.get("event_id") == event_id and event.get("kind") != "withdrawal"), None)
        if original is None:
            raise ReviewStoreError("REVIEW_UNKNOWN_EVENT: decision event not found")
        current = max((int(e.get("decision_revision", 0)) for e in events if e.get("item_id") == original["item_id"]), default=0)
        if current != expected_revision:
            raise ReviewStoreError("REVIEW_STALE_DECISION: decision revision changed", "REVIEW_STALE_DECISION")
        if int(original.get("decision_revision", 0)) != expected_revision:
            raise ReviewStoreError("REVIEW_STALE_DECISION: only the current decision may be withdrawn", "REVIEW_STALE_DECISION")
        if not reason.strip():
            raise ReviewStoreError("REVIEW_INVALID: retraction reason is required")
        withdrawal_id = f"withdrawal-{sha256_bytes(f'{event_id}:{expected_revision}'.encode())[:20]}"
        withdrawal = {
            "version": 1, "kind": "withdrawal", "event_id": withdrawal_id,
            "campaign_id": original["campaign_id"], "review_id": review_id,
            "item_id": original["item_id"], "item_revision": original["item_revision"],
            "review_digest": original["review_digest"], "decision_revision": expected_revision + 1,
            "supersedes_event": event_id, "withdrawal_reason": reason,
            "reviewer": original["reviewer"], "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        ledger = load_ledger(root)
        validate_ledger_tip(root)
        records = []
        found = False
        for record in ledger.records:
            if isinstance(record, ReviewDecisionRecord) and record.event_id == event_id:
                records.append(record.model_copy(update={"revision": record.revision + 1, "status": "withdrawn"}))
                found = True
            else:
                records.append(record)
        after = AuthorityLedger(version=ledger.version, campaign=ledger.campaign, revision=ledger.revision + (1 if found else 0), records=records, conflicts=ledger.conflicts)
        before_bytes = ledger_path(root).read_bytes(); after_bytes = ledger_bytes(after)
        audit_id = f"event-review-withdraw-{uuid.uuid4().hex}"
        audit = {"id":audit_id,"reason":"review-withdrawal","actor":original["reviewer"],"recorded_at":withdrawal["recorded_at"],"before_sha256":sha256_bytes(before_bytes),"after_sha256":sha256_bytes(after_bytes)}
        targets = [TransactionTarget.create(_review_dir(root, review_id)/"events"/f"{withdrawal_id}.json", canonical_bytes(withdrawal))]
        if found:
            targets += [
                TransactionTarget.replace(ledger_path(root), before_bytes, after_bytes),
                TransactionTarget.create(authority_dir(root)/"events"/f"{audit_id}.json", _json_bytes(audit)),
                TransactionTarget.replace(ledger_tip_path(root), ledger_tip_path(root).read_bytes(), _tip_bytes(audit_id, after_bytes)),
            ]
        digest = sha256_bytes(canonical_bytes(withdrawal))
        journal = _prepare_transaction_locked(root, proposal_id=withdrawal_id, proposal_sha256=digest, targets=targets)
        recover_transaction(root, journal["id"], _already_locked=True)
        return {"event_id": withdrawal_id, "decision_revision": expected_revision + 1, "inverse_applied": False}


def list_reviews(campaign_dir: Path) -> list[dict]:
    root = Path(campaign_dir).resolve(); load_campaign_identity(root)
    result = []
    with authority_lock(root, exclusive=False):
        require_no_pending_transaction(root)
        base = review_root(root)
        for path in sorted(base.iterdir() if base.is_dir() else ()):
            if not path.is_dir() or path.is_symlink():
                continue
            manifest_path = _reject_symlinks(root, path / "manifest.json")
            if manifest_path.is_file():
                manifest = model_from_json(ReviewManifest, manifest_path.read_bytes())
                result.append({"review_id":manifest.review_id,"kind":manifest.kind.value,"generation":manifest.generation,"item_count":len(manifest.items)})
    return result


def show_review(campaign_dir: Path, review_id: str, *, item_id: str | None = None) -> dict:
    root=Path(campaign_dir).resolve()
    with authority_lock(root,exclusive=False):
        require_no_pending_transaction(root)
        manifest,custody,items=read_snapshot(root,review_id,_already_locked=True)
        selected=[item for item in items if item_id is None or item.item_id==item_id]
        if item_id is not None and not selected: raise ReviewStoreError("REVIEW_UNKNOWN_ITEM: item not found")
        events=[event for event in _events(root,review_id) if item_id is None or event.get("item_id")==item_id]
    return {"manifest":manifest.model_dump(mode="json"),"source_custody":custody.model_dump(mode="json"),"items":[item.model_dump(mode="json") for item in selected],"events":events}


def review_status(campaign_dir: Path, review_id: str) -> dict:
    manifest,items,events,stale_ids=read_review_state(campaign_dir,review_id)
    current = {}
    for event in events:
        if event.get("item_id"): current[event["item_id"]] = event
    counts = {"pending":0,"approved":0,"rejected":0,"discussed":0,"withdrawn":0,"stale":0}
    for item in items:
        event = current.get(item.item_id)
        if item.item_id in stale_ids: counts["stale"] += 1; counts["pending"] += 1
        elif event is None: counts["pending"] += 1
        elif event.get("kind") == "withdrawal": counts["withdrawn"] += 1; counts["pending"] += 1
        else:
            key={"approve":"approved","reject":"rejected","discuss":"discussed"}[event["verdict"]]; counts[key] += 1
            if key != "approved": counts["pending"] += 1
    return {"review_id":review_id,"generation":manifest.generation,"item_count":len(items),"counts":counts}


def refresh_review(campaign_dir: Path, review_id: str, *, expected_generation: int, current_rule_versions=None) -> dict:
    root=Path(campaign_dir).resolve()
    with authority_lock(root,exclusive=True):
        require_no_pending_transaction(root)
        manifest,custody,items=read_snapshot(root,review_id,_already_locked=True)
        if manifest.generation!=expected_generation: raise ReviewStoreError("REVIEW_STALE_GENERATION: review generation changed","REVIEW_STALE_GENERATION")
        rules=tuple(current_rule_versions) if current_rule_versions is not None else manifest.rule_versions
        rules_changed=canonical_bytes(rules)!=canonical_bytes(manifest.rule_versions)
        new_sources=[]
        for source in custody.sources:
            path=_reject_symlinks(root,root/source.path)
            if not path.is_file(): raise ReviewStoreError(f"REVIEW_STALE_SOURCE: missing {source.path}","REVIEW_STALE_SOURCE")
            data=path.read_bytes();new_sources.append({"source_id":source.source_id,"path":source.path,"sha256":sha256_bytes(data),"size":len(data)})
        source_by_id={source["source_id"]:source for source in new_sources};preserved=[];stale=[]
        prior_stale: set[str] = set()
        for prior_event in _events(root, review_id):
            if prior_event.get("kind") == "rebind":
                prior_stale.update(prior_event.get("stale_item_ids", []))
                prior_stale.difference_update(prior_event.get("preserved_item_ids", []))
        context_path = _review_dir(root, review_id) / "sources" / f"{manifest.source_manifest.generation}-contexts.json"
        old_contexts = parse_json_strict(_reject_symlinks(root, context_path).read_bytes()).get("items", {}) if context_path.exists() else {}
        new_contexts = _item_contexts(root, items)
        for item in items:
            unchanged=not rules_changed and item.item_id not in prior_stale
            for binding in item.input_bindings:
                source=source_by_id.get(binding.source_id)
                if source is None: unchanged=False;break
                if source["sha256"]!=binding.custody_sha256:
                    old = old_contexts.get(item.item_id, {}).get(binding.source_id)
                    new = new_contexts.get(item.item_id, {}).get(binding.source_id)
                    if not old or old != new: unchanged=False;break
            (preserved if unchanged else stale).append(item.item_id)
        revised_items: dict[str, ReviewItem] = {}
        for item in items:
            if item.item_id not in stale:
                continue
            raw=item.model_dump(mode="json"); raw["revision"]=item.revision+1; raw["rule_versions"]=list(rules)
            for binding in raw["input_bindings"]:
                current=source_by_id.get(binding["source_id"])
                if current: binding["custody_sha256"]=current["sha256"]
            for evidence in raw["evidence"]:
                current=source_by_id.get(evidence["source_id"])
                if current and evidence.get("exact_excerpt"):
                    current_text=(root/current["path"]).read_text(encoding="utf-8")
                    if current_text.count(evidence["exact_excerpt"])!=1:
                        evidence.pop("exact_excerpt",None); evidence.pop("selected_span_sha256",None); evidence["missing_reason"]="Previously reviewed evidence changed during refresh; select current evidence before approval."; evidence["citation_resolved"]=False; evidence["support"]="candidate_issue"
            raw.pop("review_digest",None); revised_items[item.item_id]=ReviewItem.model_validate(raw)
        generation=manifest.generation+1
        new_custody=SourceCustodyGeneration(campaign_id=manifest.campaign_id,review_id=review_id,generation=generation,previous_generation=manifest.generation,recorded_at=datetime.now(timezone.utc),sources=tuple(new_sources))
        references=[{"campaign_id":manifest.campaign_id,"review_id":review_id,"item_id":item.item_id,"revision":revised_items.get(item.item_id,item).revision,"review_digest":revised_items.get(item.item_id,item).review_digest} for item in items]
        new_manifest=ReviewManifest.model_validate({**manifest.model_dump(mode="json"),"generation":generation,"source_manifest":{"campaign_id":manifest.campaign_id,"review_id":review_id,"generation":generation,"digest":new_custody.custody_digest},"rule_versions":rules,"items":references})
        event_id=f"rebind-{uuid.uuid4().hex}";event={"version":1,"kind":"rebind","event_id":event_id,"campaign_id":str(manifest.campaign_id),"review_id":review_id,"from_generation":manifest.generation,"to_generation":generation,"recorded_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"preserved_item_ids":preserved,"stale_item_ids":stale,"old_custody_digest":custody.custody_digest,"new_custody_digest":new_custody.custody_digest}
        directory=_review_dir(root,review_id);before=(directory/"manifest.json").read_bytes();targets=[TransactionTarget.replace(directory/"manifest.json",before,canonical_bytes(new_manifest)),TransactionTarget.create(directory/"sources"/f"{generation}.json",canonical_bytes(new_custody)),TransactionTarget.create(directory/"sources"/f"{generation}-contexts.json",canonical_bytes({"version":1,"generation":generation,"items":new_contexts})),TransactionTarget.create(directory/"events"/f"{event_id}.json",canonical_bytes(event))]
        targets.extend(TransactionTarget.create(directory/"items"/item.item_id/f"{item.revision}.json",canonical_bytes(item)) for item in revised_items.values())
        digest=sha256_bytes(canonical_bytes(event));journal=_prepare_transaction_locked(root,proposal_id=event_id,proposal_sha256=digest,targets=targets);recover_transaction(root,journal["id"],_already_locked=True)
    return {"generation":generation,"preserved_item_ids":preserved,"stale_item_ids":stale,"rebind_event_id":event_id}


def export_review(campaign_dir: Path, review_id: str, item_ids: list[str]) -> dict:
    root = Path(campaign_dir).resolve()
    if not item_ids or len(item_ids) != len(set(item_ids)):
        raise ReviewStoreError("REVIEW_INVALID_SELECTION: explicit unique items required")
    with authority_lock(root,exclusive=True):
        require_no_pending_transaction(root)
        manifest,custody,items=read_snapshot(root,review_id,_already_locked=True)
        chosen=[item for item in items if item.item_id in set(item_ids)]
        if {item.item_id for item in chosen} != set(item_ids): raise ReviewStoreError("REVIEW_INVALID_SELECTION: unknown item")
        ledger=load_ledger(root)
        bundle={"version":1,"campaign_id":str(manifest.campaign_id),"review_id":review_id,"generation":manifest.generation,"items":[item.model_dump(mode="json") for item in chosen],"events":[event for event in _events(root,review_id) if event.get("item_id") in set(item_ids)],"authority_records":[record.model_dump(mode="json",exclude_none=True) for record in ledger.records if isinstance(record,ReviewDecisionRecord) and record.review_id==review_id and record.item_id in set(item_ids)],"custody_digest":custody.custody_digest}
        digest=sha256_bytes(canonical_bytes(bundle));bundle["bundle_sha256"]=digest
        path=_review_dir(root,review_id)/"exports"/f"export-{digest[:20]}.json"
        if not path.exists():
            journal=_prepare_transaction_locked(root,proposal_id=f"review-export-{digest[:20]}",proposal_sha256=digest,targets=[TransactionTarget.create(path,canonical_bytes(bundle))]);recover_transaction(root,journal["id"],_already_locked=True)
    return {"export_id":path.stem,"path":str(path.relative_to(root)),"bundle_sha256":digest}


def import_review_bundle(campaign_dir: Path, bundle_path: Path, *, expected_generation: int) -> dict:
    root = Path(campaign_dir).resolve(); identity = load_campaign_identity(root)
    raw = parse_json_strict(Path(bundle_path).read_bytes())
    if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("bundle_sha256"), str):
        raise ReviewStoreError("REVIEW_INVALID_IMPORT: malformed bundle")
    unsigned = dict(raw); claimed = unsigned.pop("bundle_sha256")
    if sha256_bytes(canonical_bytes(unsigned)) != claimed:
        raise ReviewStoreError("REVIEW_INVALID_IMPORT: bundle digest mismatch")
    if raw.get("campaign_id") != str(identity.campaign_id):
        raise ReviewStoreError("REVIEW_CAMPAIGN_MISMATCH: foreign decision bundle")
    review_id = raw.get("review_id")
    manifest, custody, local_items = read_snapshot(root, review_id)
    if manifest.generation != expected_generation or raw.get("generation") != expected_generation:
        raise ReviewStoreError("REVIEW_STALE_GENERATION: import generation changed", "REVIEW_STALE_GENERATION")
    if raw.get("custody_digest") != custody.custody_digest:
        raise ReviewStoreError("REVIEW_STALE_CUSTODY: import custody changed", "REVIEW_STALE_CUSTODY")
    local = {item.item_id:item for item in local_items}
    for payload in raw.get("items", []):
        imported = ReviewItem.model_validate(payload)
        current = local.get(imported.item_id)
        if current is None or current.revision != imported.revision or current.review_digest != imported.review_digest:
            raise ReviewStoreError("REVIEW_STALE_DECISION: imported item differs", "REVIEW_STALE_DECISION")
    events = raw.get("events", [])
    if not isinstance(events, list):
        raise ReviewStoreError("REVIEW_INVALID_IMPORT: events must be a list")
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("item_id"), str):
            raise ReviewStoreError("REVIEW_INVALID_IMPORT: malformed event")
    authority_payloads=raw.get("authority_records",[])
    if not isinstance(authority_payloads,list): raise ReviewStoreError("REVIEW_INVALID_IMPORT: authority_records must be a list")
    imported_records=[ReviewDecisionRecord.model_validate(payload) for payload in authority_payloads]
    with authority_lock(root,exclusive=True):
        require_no_pending_transaction(root)
        manifest_now,_,_=read_snapshot(root,review_id,_already_locked=True)
        if manifest_now.generation!=expected_generation: raise ReviewStoreError("REVIEW_STALE_GENERATION: import generation changed","REVIEW_STALE_GENERATION")
        local_events=[event for event in _events(root,review_id) if isinstance(event.get("item_id"),str)]
        local_by_id={event["event_id"]:event for event in local_events}
        local_by_item:dict[str,list[dict]]={}
        for event in local_events: local_by_item.setdefault(event["item_id"],[]).append(event)
        bundle_by_item:dict[str,list[dict]]={}
        for event in events: bundle_by_item.setdefault(event["item_id"],[]).append(event)
        missing=[]
        for item_id,bundle_history in bundle_by_item.items():
            ordered=sorted(bundle_history,key=lambda event:int(event.get("decision_revision",0)))
            local_ordered=sorted(local_by_item.get(item_id,[]),key=lambda event:int(event.get("decision_revision",0)))
            if len(local_ordered)>len(ordered) or any(canonical_bytes(a)!=canonical_bytes(b) for a,b in zip(local_ordered,ordered)):
                raise ReviewStoreError("REVIEW_STALE_DECISION: imported history is not the current history prefix","REVIEW_STALE_DECISION")
            missing.extend(ordered[len(local_ordered):])
        ledger=load_ledger(root);validate_ledger_tip(root);by_record={record.id:record for record in ledger.records};additions=[]
        for record in imported_records:
            prior=by_record.get(record.id)
            if prior is not None and canonical_bytes(prior)!=canonical_bytes(record): raise ReviewStoreError("REVIEW_STALE_DECISION: authority history differs","REVIEW_STALE_DECISION")
            if prior is None: additions.append(record)
        if not missing and not additions: return {"review_id":review_id,"bundle_sha256":claimed,"imported_events":0}
        before=ledger_path(root).read_bytes();after_ledger=AuthorityLedger(version=ledger.version,campaign=ledger.campaign,revision=ledger.revision+1,records=[*ledger.records,*additions],conflicts=ledger.conflicts);after=ledger_bytes(after_ledger)
        audit_id=f"event-review-import-{uuid.uuid4().hex}";now=datetime.now(timezone.utc).isoformat().replace("+00:00","Z");audit={"id":audit_id,"reason":"review-import","actor":"import","recorded_at":now,"before_sha256":sha256_bytes(before),"after_sha256":sha256_bytes(after)}
        targets=[TransactionTarget.create(_review_dir(root,review_id)/"events"/f"{event['event_id']}.json",canonical_bytes(event)) for event in missing]
        targets += [TransactionTarget.replace(ledger_path(root),before,after),TransactionTarget.create(authority_dir(root)/"events"/f"{audit_id}.json",_json_bytes(audit)),TransactionTarget.replace(ledger_tip_path(root),ledger_tip_path(root).read_bytes(),_tip_bytes(audit_id,after))]
        journal=_prepare_transaction_locked(root,proposal_id=f"review-import-{claimed[:20]}",proposal_sha256=claimed,targets=targets);recover_transaction(root,journal["id"],_already_locked=True)
    return {"review_id":review_id,"bundle_sha256":claimed,"imported_events":len(missing)}
