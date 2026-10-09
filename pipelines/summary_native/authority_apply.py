"""Recoverable authority locking, journals, and immutable mutation history."""
from __future__ import annotations

import contextlib
import difflib
import fcntl
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from campaignlib.util import atomic_write_bytes
from pipelines.summary_native import parse, schema, validate
from pipelines.summary_native.authority import AuthorityError, AuthorityLedger, DOCUMENT_ANCHOR, RulingRecord, ledger_bytes, ledger_digest, ledger_path, load_ledger, now_utc, sha256_bytes
from pipelines.summary_native.authority_sources import allowed_summary_path, exact_replace


NONTERMINAL = {"prepared", "writing", "source_written", "ledger_written"}
_TX_ID_PREFIX = "tx-"


def authority_dir(campaign_dir: Path) -> Path:
    return Path(campaign_dir) / "docs" / "authority"


def ledger_tip_path(campaign_dir: Path) -> Path:
    """Mutable pointer to the immutable event that produced the live ledger."""
    return authority_dir(campaign_dir) / "events" / "tip.json"


def _tip_bytes(event_id: str, after: bytes) -> bytes:
    return _json_bytes({"event_id": event_id, "ledger_sha256": sha256_bytes(after)})


def write_ledger_tip(campaign_dir: Path, *, event_id: str, after: bytes) -> None:
    """Initialize the history anchor for a newly created ledger."""
    atomic_write_bytes(ledger_tip_path(campaign_dir), _tip_bytes(event_id, after))


def validate_ledger_tip(campaign_dir: Path) -> None:
    """Refuse a ledger whose bytes were not produced by the recorded mutation tip."""
    path = ledger_tip_path(campaign_dir)
    try:
        tip = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuthorityError("AUTH_STALE: authority ledger has no valid mutation-history tip", "AUTH_STALE") from exc
    if tip.get("ledger_sha256") != ledger_digest(campaign_dir):
        raise AuthorityError("AUTH_STALE: authority ledger bytes differ from the recorded mutation-history tip", "AUTH_STALE")


def initialize_ledger(
    campaign_dir: Path,
    ledger: AuthorityLedger,
    *,
    actor: str,
    _already_locked: bool = False,
) -> str:
    """Create the initial ledger, immutable event, and tip in one recoverable journal.

    The first ledger has the same missing-versus-existing semantics as every
    later authority mutation: all targets begin absent and recovery can finish
    forward if a process stops after writing the ledger but before its tip.
    """
    root = Path(campaign_dir).resolve()
    with (contextlib.nullcontext() if _already_locked else authority_lock(root, exclusive=True)):
        require_no_pending_transaction(root)
        path = ledger_path(root)
        tip = ledger_tip_path(root)
        if path.exists() and tip.exists():
            raise AuthorityError("authority ledger already exists; use validate or status")
        if path.exists() or tip.exists():
            raise AuthorityError(
                "authority initialization is incomplete; recover the pending transaction or inspect the orphaned authority files",
                "AUTH_RECOVERY",
            )
        after = ledger_bytes(ledger)
        event_id = f"event-init-{uuid.uuid4().hex}"
        event = {
            "id": event_id,
            "reason": "init",
            "actor": actor,
            "recorded_at": now_utc(),
            "before_sha256": sha256_bytes(b""),
            "after_sha256": sha256_bytes(after),
        }
        event_path = authority_dir(root) / "events" / f"{event_id}.json"
        journal = _prepare_transaction_locked(
            root,
            proposal_id=event_id,
            proposal_sha256=sha256_bytes(_json_bytes(event)),
            targets=[
                (path, b"", after),
                (event_path, b"", _json_bytes(event)),
                (tip, b"", _tip_bytes(event_id, after)),
            ],
        )
        recover_transaction(root, journal["id"], _already_locked=True)
        return sha256_bytes(after)


def _journal_dir(campaign_dir: Path) -> Path:
    return authority_dir(campaign_dir) / "transactions"


@contextlib.contextmanager
def authority_lock(campaign_dir: Path, *, exclusive: bool) -> Iterator[None]:
    """A flock-based campaign lock.  Shared readers get a coherent snapshot."""
    directory = authority_dir(campaign_dir)
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def journal_path(campaign_dir: Path, transaction_id: str) -> Path:
    if not transaction_id.startswith(_TX_ID_PREFIX) or len(transaction_id) != len(_TX_ID_PREFIX) + 32 or any(ch not in "0123456789abcdef" for ch in transaction_id[len(_TX_ID_PREFIX):]):
        raise AuthorityError("AUTH_RECOVERY: invalid transaction id", "AUTH_RECOVERY")
    return _journal_dir(campaign_dir) / f"{transaction_id}.json"


def _inside(path: Path, root: Path) -> Path:
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AuthorityError(f"AUTH_RECOVERY: path outside campaign root: {path}", "AUTH_RECOVERY") from exc
    return resolved


def _load_journal(campaign_dir: Path, transaction_id: str) -> dict:
    root = Path(campaign_dir).resolve()
    try:
        journal = json.loads(journal_path(root, transaction_id).read_text(encoding="utf-8"))
    except AuthorityError:
        raise
    except (OSError, ValueError) as exc:
        raise AuthorityError(f"AUTH_RECOVERY: no readable transaction {transaction_id}", "AUTH_RECOVERY") from exc
    if not isinstance(journal, dict) or journal.get("id") != transaction_id or not isinstance(journal.get("targets"), list):
        raise AuthorityError("AUTH_RECOVERY: malformed transaction journal", "AUTH_RECOVERY")
    for target in journal["targets"]:
        if not isinstance(target, dict):
            raise AuthorityError("AUTH_RECOVERY: malformed transaction target", "AUTH_RECOVERY")
        _inside(Path(target.get("path", "")), root)
        for field in ("before_snapshot", "after_snapshot"):
            snapshot = _inside(root / str(target.get(field, "")), root)
            if not snapshot.is_file():
                raise AuthorityError(f"AUTH_RECOVERY: missing immutable snapshot {field}", "AUTH_RECOVERY")
        for field in ("before_sha256", "after_sha256"):
            value = target.get(field)
            if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise AuthorityError(f"AUTH_RECOVERY: invalid {field}", "AUTH_RECOVERY")
        if not isinstance(target.get("before_exists"), bool) or not isinstance(target.get("after_exists"), bool):
            raise AuthorityError("AUTH_RECOVERY: target existence metadata is required", "AUTH_RECOVERY")
    return journal


def write_json_immutable(path: Path, data: dict) -> None:
    encoded = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise AuthorityError(f"immutable authority artifact already exists: {path}")
        return
    atomic_write_bytes(path, encoded)


def pending_transaction(campaign_dir: Path) -> dict | None:
    for path in sorted(_journal_dir(campaign_dir).glob("*.json")) if _journal_dir(campaign_dir).exists() else []:
        try:
            journal = _load_journal(campaign_dir, path.stem)
        except AuthorityError:
            raise
        if journal.get("state") in NONTERMINAL or journal.get("state") == "attention_required":
            return journal
    return None


def require_no_pending_transaction(campaign_dir: Path) -> None:
    pending = pending_transaction(campaign_dir)
    if pending:
        identifier = pending.get("id", "unknown")
        raise AuthorityError(f"AUTH_PENDING_TRANSACTION: recover with `summary_native authority recover {identifier}`", "AUTH_RECOVERY")


@dataclass(frozen=True)
class TransactionTarget:
    path: str
    before_sha256: str
    after_sha256: str
    before_snapshot: str
    after_snapshot: str


def prepare_transaction(campaign_dir: Path, *, proposal_id: str, proposal_sha256: str, targets: list[tuple[Path, bytes, bytes]]) -> dict:
    """Persist exact snapshots and journal while holding the campaign writer lock."""
    with authority_lock(campaign_dir, exclusive=True):
        require_no_pending_transaction(campaign_dir)
        return _prepare_transaction_locked(campaign_dir, proposal_id=proposal_id, proposal_sha256=proposal_sha256, targets=targets)


def _prepare_transaction_locked(campaign_dir: Path, *, proposal_id: str, proposal_sha256: str, targets: list[tuple[Path, bytes, bytes]]) -> dict:
    transaction_id = f"tx-{uuid.uuid4().hex}"
    root = Path(campaign_dir).resolve()
    snapshot_dir = authority_dir(root) / "snapshots" / transaction_id
    entries = []
    for index, (target, before, after) in enumerate(targets):
        target = _inside(target, root)
        before_exists = target.exists()
        if before_exists and target.read_bytes() != before:
            raise AuthorityError("AUTH_STALE_PROPOSAL: target changed before transaction preparation", "AUTH_STALE")
        if not before_exists and before:
            raise AuthorityError("AUTH_STALE_PROPOSAL: missing target has non-empty before bytes", "AUTH_STALE")
        before_path = snapshot_dir / f"{index:02d}-before.bin"
        after_path = snapshot_dir / f"{index:02d}-after.bin"
        atomic_write_bytes(before_path, before)
        atomic_write_bytes(after_path, after)
        entries.append({
            "path": str(target.resolve()), "before_sha256": sha256_bytes(before), "after_sha256": sha256_bytes(after),
            "before_snapshot": str(before_path.relative_to(root)), "after_snapshot": str(after_path.relative_to(root)),
            "before_exists": before_exists, "after_exists": True,
        })
    journal = {"id": transaction_id, "proposal_id": proposal_id, "proposal_sha256": proposal_sha256, "state": "prepared", "targets": entries, "started_at": now_utc(), "updated_at": now_utc()}
    atomic_write_bytes(journal_path(root, transaction_id), (json.dumps(journal, sort_keys=True, indent=2) + "\n").encode())
    return journal


def _save_journal(campaign_dir: Path, journal: dict) -> None:
    journal["updated_at"] = now_utc()
    atomic_write_bytes(journal_path(campaign_dir, journal["id"]), (json.dumps(journal, sort_keys=True, indent=2) + "\n").encode())


def recover_transaction(campaign_dir: Path, transaction_id: str, *, _already_locked: bool = False) -> dict:
    """Resume only expected bytes; unexpected data is never overwritten."""
    root = Path(campaign_dir).resolve()
    with (contextlib.nullcontext() if _already_locked else authority_lock(root, exclusive=True)):
        journal = _load_journal(root, transaction_id)
        if journal.get("state") == "committed":
            return journal
        statuses = []
        for target in journal["targets"]:
            target_path = _inside(Path(target["path"]), root)
            # Missing and empty are materially different for recovery.  A
            # journal only permits a missing target when its approved before
            # snapshot is itself empty and has the matching digest.
            if not target_path.exists():
                current = None
            else:
                current = target_path.read_bytes()
            digest = None if current is None else sha256_bytes(current)
            before_snapshot = _inside(root / target["before_snapshot"], root).read_bytes()
            after_snapshot = _inside(root / target["after_snapshot"], root).read_bytes()
            if sha256_bytes(before_snapshot) != target["before_sha256"] or sha256_bytes(after_snapshot) != target["after_sha256"]:
                raise AuthorityError("AUTH_RECOVERY: immutable snapshot digest does not match approved journal", "AUTH_RECOVERY")
            if target["after_exists"] and digest == target["after_sha256"]:
                statuses.append("after")
            elif target["before_exists"] and digest == target["before_sha256"]:
                statuses.append("before")
            elif not target["before_exists"] and current is None and before_snapshot == b"":
                statuses.append("before")
            else:
                journal["state"] = "attention_required"
                observed = "MISSING" if digest is None else digest
                journal["error"] = f"AUTH_UNEXPECTED_RECOVERY_BYTES: {target_path} expected {target['before_sha256']} or {target['after_sha256']}, got {observed}"
                _save_journal(root, journal)
                raise AuthorityError(journal["error"], "AUTH_RECOVERY")
        journal["state"] = "writing"
        _save_journal(root, journal)
        for target, state in zip(journal["targets"], statuses):
            if state == "before":
                approved = _inside(root / target["after_snapshot"], root).read_bytes()
                atomic_write_bytes(_inside(Path(target["path"]), root), approved)
        for target in journal["targets"]:
            written = _inside(Path(target["path"]), root)
            actual = sha256_bytes(written.read_bytes()) if written.exists() else None
            if not target["after_exists"] or actual != target["after_sha256"]:
                raise AuthorityError("AUTH_RECOVERY: target write did not produce approved digest", "AUTH_RECOVERY")
        journal["state"] = "committed"
        _save_journal(root, journal)
        return journal


def append_authority_event(campaign_dir: Path, *, reason: str, actor: str, before: bytes, after: bytes, transaction_id: str | None = None) -> Path:
    event_id = f"event-{uuid.uuid4().hex}"
    root = Path(campaign_dir)
    events = authority_dir(root) / "events"
    snapshots = authority_dir(root) / "events" / event_id
    atomic_write_bytes(snapshots / "before.yaml", before)
    atomic_write_bytes(snapshots / "after.yaml", after)
    event = {"id": event_id, "reason": reason, "actor": actor, "recorded_at": now_utc(), "before_sha256": sha256_bytes(before), "after_sha256": sha256_bytes(after), "before_snapshot": str((snapshots / "before.yaml").relative_to(root)), "after_snapshot": str((snapshots / "after.yaml").relative_to(root)), "transaction_id": transaction_id}
    path = events / f"{event_id}.json"
    write_json_immutable(path, event)
    return path


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _validate_maintained_summary(data: bytes, source_path: str) -> None:
    """Run the source-summary parser's normal structural checks before approval."""
    try:
        parsed = parse.parse_text(data.decode("utf-8"), source_path)
    except UnicodeDecodeError as exc:
        raise AuthorityError("AUTH_SOURCE_INVALID: source summary is not UTF-8", "AUTH_SOURCE_INVALID") from exc
    blocking = [
        finding for finding in validate._file_findings(parsed, True)
        if finding.code in schema.BLOCKING_CODES
    ]
    if blocking:
        raise AuthorityError(
            "AUTH_SOURCE_INVALID: proposed source fails summary validation: "
            + ", ".join(finding.code for finding in blocking),
            "AUTH_SOURCE_INVALID",
        )


def _proposal_path(campaign_dir: Path, proposal_id: str) -> Path:
    return authority_dir(campaign_dir) / "proposals" / proposal_id / "proposal.json"


def _replace_record(ledger: AuthorityLedger, record: RulingRecord) -> AuthorityLedger:
    return ledger.model_copy(update={"revision": ledger.revision + 1, "records": [record if item.id == record.id else item for item in ledger.records]})


def _write_ledger_event(campaign_dir: Path, *, before: bytes, after: bytes, actor: str, reason: str,
                        record_id: str | None = None, conflict_id: str | None = None) -> None:
    """Persist a ledger-only mutation as an event-bearing recoverable operation."""
    event_id = f"event-{uuid.uuid4().hex}"
    root = Path(campaign_dir).resolve()
    event_path = authority_dir(root) / "events" / f"{event_id}.json"
    event = {"id": event_id, "reason": reason, "actor": actor, "recorded_at": now_utc(), "before_sha256": sha256_bytes(before), "after_sha256": sha256_bytes(after), **({"record_id": record_id} if record_id else {}), **({"conflict_id": conflict_id} if conflict_id else {})}
    if record_id:
        event["ruling_id"] = record_id  # legacy readers use this name for both typed record kinds.
    tip = ledger_tip_path(root)
    journal = _prepare_transaction_locked(root, proposal_id=event_id, proposal_sha256=sha256_bytes(_json_bytes(event)), targets=[(ledger_path(root), before, after), (event_path, b"", _json_bytes(event)), (tip, tip.read_bytes() if tip.exists() else b"", _tip_bytes(event_id, after))])
    recover_transaction(root, journal["id"], _already_locked=True)


def create_proposal(campaign_dir: Path, ruling_id: str, *, summaries_dir: Path) -> dict:
    """Create one immutable exact-replacement proposal and stage its ledger binding."""
    root = Path(campaign_dir).resolve()
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        ledger = load_ledger(root)
        record = next((item for item in ledger.records if item.id == ruling_id), None)
        if not isinstance(record, RulingRecord):
            raise AuthorityError(f"unknown ruling {ruling_id!r}")
        if record.source.anchor == DOCUMENT_ANCHOR:
            raise AuthorityError("AUTH_TARGET_NOT_ALLOWED: __document__ is reserved for read-only support", "AUTH_VALIDATION")
        if record.status not in {"draft", "proposed"}:
            raise AuthorityError(f"ruling {ruling_id} cannot propose from {record.status}")
        source = allowed_summary_path(root, summaries_dir, record.source)
        # Compare resolved targets.  Authored spellings such as ``./`` and an
        # in-root symlink must not create two simultaneously approvable edits
        # of the same anchor.
        competing = []
        for item in ledger.records:
            if not (isinstance(item, RulingRecord) and item.id != record.id
                    and item.source.anchor == record.source.anchor
                    and item.status in {"proposed", "reversal_proposed"}):
                continue
            try:
                item_source = allowed_summary_path(root, summaries_dir, item.source)
            except AuthorityError:
                # An invalid competing authority record remains a validation
                # refusal elsewhere; it cannot authorize an alternate target.
                continue
            if item_source.resolve() == source.resolve():
                competing.append(item.id)
        if competing:
            raise AuthorityError(
                f"AUTH_CONFLICT: incompatible staged proposal(s) for target: {', '.join(competing)}",
                "AUTH_CONFLICT",
            )
        before = source.read_bytes()
        span = record.rejected_claim.encode("utf-8")
        after = record.replacement_fact.encode("utf-8")
        from pipelines.summary_native.authority_inputs import resolve_anchor_span
        anchored = resolve_anchor_span(before, record.source.anchor)
        if span not in anchored:
            raise AuthorityError("AUTH_TARGET_NOT_ALLOWED: reviewed replacement span is outside its declared anchor", "AUTH_TARGET_NOT_ALLOWED")
        proposed = exact_replace(source, span, after, expected_file_sha256=None)
        # A replacement must leave a real maintained summary with the declared
        # anchor.  This is deliberately validated before creating any review
        # artifact, so no malformed source can be approved later.
        if not resolve_anchor_span(proposed, record.source.anchor).strip():
            raise AuthorityError("AUTH_SOURCE_INVALID: proposed source has an empty declared anchor", "AUTH_SOURCE_INVALID")
        _validate_maintained_summary(proposed, record.source.path)
        proposal_id = f"{record.id}-r{ledger.revision + 1}-{uuid.uuid4().hex[:8]}"
        staged_record = record.model_copy(update={"status": "proposed", "proposal_id": proposal_id, "source": record.source.model_copy(update={"before_sha256": sha256_bytes(before), "before_span_sha256": sha256_bytes(span)})})
        staged = _replace_record(ledger, staged_record)
        before_ledger = ledger_path(root).read_bytes()
        after_ledger = ledger_bytes(staged)
        proposal = {"id": proposal_id, "ruling_id": record.id, "campaign": staged.campaign, "ledger_revision": staged.revision, "ledger_sha256": sha256_bytes(after_ledger), "summaries_root": str(Path(summaries_dir).resolve().relative_to(root)), "target": staged_record.source.model_dump(mode="json", exclude_none=True), "before_sha256": sha256_bytes(before), "after_sha256": sha256_bytes(proposed), "before_bytes_sha256": sha256_bytes(before), "after_bytes_sha256": sha256_bytes(proposed), "operation": "replace", "before_bytes": before.decode("utf-8"), "after_bytes": proposed.decode("utf-8"), "projections": sorted(p.value for p in record.projections)}
        proposal["diff"] = "".join(difflib.unified_diff(before.decode("utf-8").splitlines(keepends=True), proposed.decode("utf-8").splitlines(keepends=True), fromfile=record.source.path, tofile=record.source.path))
        proposal["proposal_sha256"] = sha256_bytes(_json_bytes(proposal))
        directory = _proposal_path(root, proposal_id).parent
        event_id = f"event-{uuid.uuid4().hex}"
        event = {"id": event_id, "reason": "proposal-stage", "actor": record.recorded_by,
                 "recorded_at": now_utc(), "before_sha256": sha256_bytes(before_ledger),
                 "after_sha256": sha256_bytes(after_ledger), "record_id": record.id, "ruling_id": record.id}
        journal = _prepare_transaction_locked(
            root, proposal_id=proposal_id, proposal_sha256=proposal["proposal_sha256"],
            targets=[
                (ledger_path(root), before_ledger, after_ledger),
                (directory / "before.bin", b"", before),
                (directory / "after.bin", b"", proposed),
                (_proposal_path(root, proposal_id), b"", _json_bytes(proposal)),
                (authority_dir(root) / "events" / f"{event_id}.json", b"", _json_bytes(event)),
                (ledger_tip_path(root), ledger_tip_path(root).read_bytes() if ledger_tip_path(root).exists() else b"", _tip_bytes(event_id, after_ledger)),
            ],
        )
        recover_transaction(root, journal["id"], _already_locked=True)
        return proposal


def _load_proposal(campaign_dir: Path, proposal_id: str) -> dict:
    try:
        proposal = json.loads(_proposal_path(campaign_dir, proposal_id).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuthorityError(f"AUTH_STALE_PROPOSAL: no immutable proposal {proposal_id}", "AUTH_STALE") from exc
    supplied = proposal.get("proposal_sha256")
    canonical = dict(proposal); canonical.pop("proposal_sha256", None)
    if not isinstance(supplied, str) or supplied != sha256_bytes(_json_bytes(canonical)):
        raise AuthorityError("AUTH_STALE_PROPOSAL: proposal artifact digest is invalid", "AUTH_STALE")
    return proposal


def apply_proposal(campaign_dir: Path, ruling_id: str, *, proposal_sha256: str, actor: str = "GM") -> dict:
    root = Path(campaign_dir).resolve()
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        ledger = load_ledger(root)
        record = next((item for item in ledger.records if item.id == ruling_id), None)
        if not isinstance(record, RulingRecord) or not record.proposal_id:
            raise AuthorityError("AUTH_STALE_PROPOSAL: ruling has no staged proposal", "AUTH_STALE")
        proposal = _load_proposal(root, record.proposal_id)
        if proposal_sha256 != proposal["proposal_sha256"] or proposal["ledger_sha256"] != ledger_digest(root):
            raise AuthorityError("AUTH_STALE_PROPOSAL: proposal digest or reviewed ledger changed", "AUTH_STALE")
        source = allowed_summary_path(root, root / proposal["summaries_root"], record.source)
        current = source.read_bytes()
        if sha256_bytes(current) != proposal["before_sha256"]:
            raise AuthorityError("AUTH_STALE_PROPOSAL: source digest changed; refresh proposal", "AUTH_STALE")
        after_source = (authority_dir(root) / "proposals" / record.proposal_id / "after.bin").read_bytes()
        if sha256_bytes(after_source) != proposal["after_sha256"]:
            raise AuthorityError("AUTH_STALE_PROPOSAL: proposal snapshots changed", "AUTH_STALE")
        receipt_id = f"receipt-{uuid.uuid4().hex}"
        is_reversal = proposal.get("operation") == "withdrawal"
        if record.status not in ({"reversal_proposed"} if is_reversal else {"proposed"}):
            raise AuthorityError("AUTH_STALE_PROPOSAL: ruling status is no longer approvable", "AUTH_STALE")
        applied = record.model_copy(update={"status": "withdrawn" if is_reversal else "applied", "revision": record.revision + 1, "applied_receipt": receipt_id})
        final_ledger = _replace_record(ledger, applied)
        before_ledger = ledger_path(root).read_bytes()
        after_ledger = ledger_bytes(final_ledger)
        receipt = {"id": receipt_id, "ruling_id": record.id, "proposal_id": proposal["id"], "proposal_sha256": proposal_sha256, "campaign": ledger.campaign, "actor": actor, "before_source_sha256": sha256_bytes(current), "after_source_sha256": sha256_bytes(after_source), "before_ledger_sha256": sha256_bytes(before_ledger), "after_ledger_sha256": sha256_bytes(after_ledger), "resulting_ledger_revision": final_ledger.revision, "committed_at": now_utc()}
        receipt_path = authority_dir(root) / "receipts" / f"{receipt_id}.json"
        approval = {"id": f"approval-{uuid.uuid4().hex}", "reason": "source-apply", "record_id": record.id, "ruling_id": record.id, "proposal_id": proposal["id"], "proposal_sha256": proposal_sha256, "approved_at": now_utc(), "reviewer": actor, "actor": actor, "before_source_sha256": sha256_bytes(current), "after_source_sha256": sha256_bytes(after_source), "ledger_sha256": sha256_bytes(before_ledger), "after_ledger_sha256": sha256_bytes(after_ledger)}
        approval_path = authority_dir(root) / "events" / f"{approval['id']}.json"
        # Receipt is a target of the same journal as source and ledger; it does
        # not appear in the ledger digest, so the relationship is acyclic.
        journal = _prepare_transaction_locked(root, proposal_id=proposal["id"], proposal_sha256=proposal_sha256, targets=[(source, current, after_source), (ledger_path(root), before_ledger, after_ledger), (receipt_path, b"", _json_bytes(receipt)), (approval_path, b"", _json_bytes(approval)), (ledger_tip_path(root), ledger_tip_path(root).read_bytes() if ledger_tip_path(root).exists() else b"", _tip_bytes(approval["id"], after_ledger))])
        return {**receipt, "transaction_id": recover_transaction(root, journal["id"], _already_locked=True)["id"]}


def create_withdrawal_proposal(campaign_dir: Path, *, ruling_id: str, source_path: Path, applied_before: bytes, applied_after: bytes) -> dict:
    """Create a reviewable inverse only where current source still has one applied span."""
    current = Path(source_path).read_bytes()
    if current.count(applied_after) != 1:
        raise AuthorityError("AUTH_STALE_PROPOSAL: applied passage changed; author a new withdrawal replacement", "AUTH_STALE")
    after = current.replace(applied_after, applied_before, 1)
    return {"id": f"{ruling_id}-withdrawal", "ruling_id": ruling_id, "before_bytes": current, "after_bytes": after, "before_sha256": sha256_bytes(current), "after_sha256": sha256_bytes(after)}


def request_withdrawal(campaign_dir: Path, *, ruling_id: str, reason: str) -> dict:
    """Stage one digest-bound reversal without discarding later unrelated edits."""
    root = Path(campaign_dir).resolve()
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        ledger = load_ledger(root)
        record = next((item for item in ledger.records if item.id == ruling_id), None)
        if not isinstance(record, RulingRecord) or record.status != "applied" or not record.proposal_id:
            raise AuthorityError("withdrawal requires an applied ruling")
        original = _load_proposal(root, record.proposal_id)
        source = allowed_summary_path(root, root / original["summaries_root"], record.source)
        current = source.read_bytes()
        from pipelines.summary_native.authority_inputs import resolve_anchor_span
        anchored = resolve_anchor_span(current, record.source.anchor)
        replacement = record.replacement_fact.encode("utf-8")
        rejected = record.rejected_claim.encode("utf-8")
        if anchored.count(replacement) != 1:
            raise AuthorityError("AUTH_STALE_PROPOSAL: applied passage changed; author a new withdrawal replacement", "AUTH_STALE")
        anchor_start = current.index(anchored)
        span_start = anchor_start + anchored.index(replacement)
        inverse_after = current[:span_start] + rejected + current[span_start + len(replacement):]
        inverse = {"before_bytes": current, "after_bytes": inverse_after,
                   "before_sha256": sha256_bytes(current), "after_sha256": sha256_bytes(inverse_after)}
        proposal_id = f"{record.id}-withdrawal-r{ledger.revision + 1}-{uuid.uuid4().hex[:8]}"
        staged_record = record.model_copy(update={
            "status": "reversal_proposed", "revision": record.revision + 1,
            "proposal_id": proposal_id, "withdrawal_reason": reason,
        })
        staged = _replace_record(ledger, staged_record)
        before_ledger = ledger_path(root).read_bytes()
        after_ledger = ledger_bytes(staged)
        proposal = {
            "id": proposal_id, "ruling_id": record.id, "campaign": staged.campaign,
            "ledger_revision": staged.revision, "ledger_sha256": sha256_bytes(after_ledger),
            "summaries_root": original["summaries_root"],
            "target": staged_record.source.model_dump(mode="json", exclude_none=True),
            "before_sha256": inverse["before_sha256"], "after_sha256": inverse["after_sha256"],
            "before_bytes_sha256": inverse["before_sha256"], "after_bytes_sha256": inverse["after_sha256"],
            "operation": "withdrawal", "reason": reason,
            "before_bytes": inverse["before_bytes"].decode("utf-8"),
            "after_bytes": inverse["after_bytes"].decode("utf-8"),
            "projections": sorted(p.value for p in record.projections),
        }
        proposal["diff"] = "".join(difflib.unified_diff(
            proposal["before_bytes"].splitlines(keepends=True),
            proposal["after_bytes"].splitlines(keepends=True),
            fromfile=record.source.path, tofile=record.source.path,
        ))
        proposal["proposal_sha256"] = sha256_bytes(_json_bytes(proposal))
        directory = _proposal_path(root, proposal_id).parent
        event_id = f"event-{uuid.uuid4().hex}"
        event = {"id": event_id, "reason": "withdrawal-request", "actor": record.recorded_by,
                 "recorded_at": now_utc(), "before_sha256": sha256_bytes(before_ledger),
                 "after_sha256": sha256_bytes(after_ledger), "record_id": record.id, "ruling_id": record.id}
        journal = _prepare_transaction_locked(
            root, proposal_id=proposal_id, proposal_sha256=proposal["proposal_sha256"],
            targets=[
                (ledger_path(root), before_ledger, after_ledger),
                (directory / "before.bin", b"", inverse["before_bytes"]),
                (directory / "after.bin", b"", inverse["after_bytes"]),
                (_proposal_path(root, proposal_id), b"", _json_bytes(proposal)),
                (authority_dir(root) / "events" / f"{event_id}.json", b"", _json_bytes(event)),
                (ledger_tip_path(root), ledger_tip_path(root).read_bytes() if ledger_tip_path(root).exists() else b"", _tip_bytes(event_id, after_ledger)),
            ],
        )
        recover_transaction(root, journal["id"], _already_locked=True)
        return proposal
