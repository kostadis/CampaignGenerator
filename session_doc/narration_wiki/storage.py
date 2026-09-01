"""Canonical persistence, locking, journaling, recovery, and human Gate writes."""

from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from campaignlib.util import atomic_write_bytes, atomic_write_text

from .models import (
    BaselineBinding,
    CampaignScope,
    ConflictRuling,
    Gate1Ruling,
    ImpactEntry,
    MutationError,
    StateError,
    ValidationError,
    WikiIteration,
    canonical_json,
    normalize_slug,
    require_stable_id,
    sha256_bytes,
    sha256_file,
)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StateError(f"required artifact is missing: {path.name}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid JSON artifact {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"JSON artifact must be an object: {path.name}")
    return value


def write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, canonical_json(value))


def write_bytes(path: Path, value: bytes) -> None:
    atomic_write_bytes(path, value)


@contextmanager
def campaign_lock(scope: CampaignScope) -> Iterator[None]:
    lock_path = scope.campaign_root / ".narration-wiki.lock"
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_iteration(scope: CampaignScope) -> WikiIteration:
    value = read_json(scope.iteration_root / "iteration.json")
    return WikiIteration(**value)


def save_iteration(scope: CampaignScope, iteration: WikiIteration) -> None:
    write_json(scope.iteration_root / "iteration.json", iteration.to_dict())


def baseline_binding(scope: CampaignScope) -> BaselineBinding:
    measurement_path = scope.iteration_root / "measurement-before.json"
    measurement = read_json(measurement_path)
    if measurement.get("phase") != "before":
        raise StateError("baseline measurement is not a before-phase snapshot")
    guidance = measurement.get("guidance") or {}
    return BaselineBinding(
        measurement_path="measurement-before.json",
        measurement_sha256=sha256_file(measurement_path),
        corpus_id=str(measurement.get("corpus_id", "")),
        guidance_sha256=str(guidance.get("guidance_sha256") or guidance.get("sha256") or ""),
    )


def _file_hash(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() else None


def _transaction_id(scope: CampaignScope, operation: str, subject: str) -> str:
    raw = f"{scope.iteration_id}-{operation}-{subject}".replace("_", "-")
    if len(raw) > 64:
        # Bare truncation lets two subjects sharing a 64-character prefix write
        # the same journal, so the earlier mutation loses its audit record.
        raw = f"{raw[:52]}-{sha256_bytes(raw.encode('utf-8'))[:11]}"
    return require_stable_id(raw, "transaction-id")


def _relative_artifact(scope: CampaignScope, path: Path) -> str:
    for root, prefix in ((scope.iteration_root, ""), (scope.campaign_root, "campaign/")):
        try:
            rel = path.relative_to(root).as_posix()
            return f"{prefix}{rel}"
        except ValueError:
            pass
    raise MutationError("transaction target is outside authorized roots")


def _journaled_writes(
    scope: CampaignScope,
    operation: str,
    subject: str,
    writes: Sequence[tuple[Path, bytes]],
    *,
    terminal_state: str = "committed",
) -> Path:
    transaction_id = _transaction_id(scope, operation, subject)
    journal_path = scope.iteration_root / "transactions" / f"{transaction_id}.json"
    rows = []
    for path, after in writes:
        before_hash = _file_hash(path)
        rows.append({
            "path": _relative_artifact(scope, path),
            "before_sha256": before_hash,
            "after_sha256": sha256_bytes(after),
        })
    journal = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "operation": operation,
        "state": "intent",
        "preconditions": [
            {"path": row["path"], "sha256": row["before_sha256"]} for row in rows
        ],
        "writes": rows,
        "next_action": "write_targets",
    }
    write_json(journal_path, journal)
    try:
        for path, content in writes:
            write_bytes(path, content)
        journal["state"] = "target_done"
        journal["next_action"] = "verify_targets"
        write_json(journal_path, journal)
        for row, (path, _) in zip(rows, writes):
            if _file_hash(path) != row["after_sha256"]:
                raise MutationError(f"transaction verification failed for {path.name}")
        journal["state"] = terminal_state
        journal["next_action"] = "none"
        write_json(journal_path, journal)
    except BaseException:
        journal["state"] = "needs_attention"
        journal["next_action"] = "inspect_hashes"
        try:
            write_json(journal_path, journal)
        except BaseException:
            pass
        raise
    return journal_path


def recover_transactions(scope: CampaignScope) -> dict[str, Any] | None:
    root = scope.iteration_root / "transactions"
    if not root.is_dir():
        return None
    for path in sorted(root.glob("*.json"), key=lambda item: item.name):
        journal = read_json(path)
        if journal.get("state") in {"committed", "rolled_back"}:
            continue
        all_after = True
        ambiguous = False
        for row in journal.get("writes", []):
            raw = str(row.get("path", ""))
            target = (
                scope.campaign_root / raw.removeprefix("campaign/")
                if raw.startswith("campaign/")
                else scope.iteration_root / raw
            )
            actual = _file_hash(target)
            if actual != row.get("after_sha256"):
                all_after = False
            if actual not in {row.get("before_sha256"), row.get("after_sha256")}:
                ambiguous = True
        if all_after:
            journal["state"] = "committed"
            journal["next_action"] = "none"
            write_json(path, journal)
            continue
        journal["state"] = "needs_attention" if ambiguous else str(journal.get("state", "intent"))
        journal["next_action"] = "inspect_hashes" if ambiguous else "resume_write"
        write_json(path, journal)
        return {
            "transaction_id": journal.get("transaction_id"),
            "operation": journal.get("operation"),
            "state": journal.get("state"),
            "next_action": journal.get("next_action"),
        }
    return None


def _gate1_document(scope: CampaignScope) -> dict[str, Any]:
    path = scope.iteration_root / "gate1.json"
    if not path.exists():
        return {"schema_version": 1, "gate": "gate1", "rulings": []}
    value = read_json(path)
    if not isinstance(value.get("rulings"), list):
        raise ValidationError("gate1.json rulings must be a list")
    return value


def record_conflict_ruling(
    scope: CampaignScope,
    conflict_id: str,
    resolution: str,
    rationale: str,
) -> dict[str, Any]:
    conflict_id = require_stable_id(conflict_id, "conflict-id")
    if not resolution.strip() or not rationale.strip():
        raise ValidationError("conflict resolution and rationale must be non-empty")
    draft = read_json(scope.iteration_root / "conflict-drafts" / f"{conflict_id}.json")
    sources = draft.get("sources")
    if not isinstance(sources, list) or len(sources) < 2:
        raise ValidationError("seed conflict requires at least two distinct sources")
    identities = {(row.get("source_ref"), row.get("source_sha256")) for row in sources if isinstance(row, dict)}
    if len(identities) < 2:
        raise ValidationError("seed conflict sources must be distinct")
    binding = baseline_binding(scope)
    ruling = ConflictRuling(
        conflict_id=conflict_id,
        campaign_id=scope.campaign_id,
        rule_key=str(draft.get("rule_key", "")),
        sources=sources,
        resolution=resolution,
        rationale=rationale,
        iteration_id=scope.iteration_id,
        baseline=binding,
    )
    durable_path = scope.campaign_wiki_root / "conflicts" / f"{conflict_id}.json"
    local_path = scope.iteration_root / "conflict-rulings.json"
    local = read_json(local_path) if local_path.exists() else {"schema_version": 1, "rulings": []}
    if any(row.get("conflict_id") == conflict_id for row in local.get("rulings", [])):
        raise StateError(f"conflict {conflict_id} already has a ruling")
    durable_bytes = canonical_json(asdict(ruling)).encode("utf-8")
    local["rulings"].append({
        "conflict_id": conflict_id,
        "path": durable_path.relative_to(scope.campaign_root).as_posix(),
        "sha256": sha256_bytes(durable_bytes),
    })
    local["rulings"] = sorted(local["rulings"], key=lambda row: row["conflict_id"])
    iteration = load_iteration(scope)
    iteration.state = "gate1_review"
    with campaign_lock(scope):
        _journaled_writes(scope, "conflict_rule", conflict_id, [
            (durable_path, durable_bytes),
            (local_path, canonical_json(local).encode("utf-8")),
            (scope.iteration_root / "iteration.json", canonical_json(iteration.to_dict()).encode("utf-8")),
        ])
    return {"conflict_id": conflict_id, "ruling": local["rulings"][-1]}


def record_pattern_ruling(
    scope: CampaignScope,
    pattern_slug: str,
    decision: str,
    *,
    tier: str | None,
    named_portable_override: bool = False,
    rationale: str | None = None,
) -> dict[str, Any]:
    from .indexes import parse_pattern_page, render_campaign_index, render_confirmed_pattern

    slug = normalize_slug(pattern_slug)
    decision = decision.casefold()
    if decision not in {"accept", "reject"}:
        raise ValidationError("pattern decision must be accept or reject")
    if decision == "accept" and tier not in {"campaign", "portable"}:
        raise ValidationError("accepted pattern requires --tier campaign|portable")
    if decision == "reject" and tier is not None:
        raise ValidationError("--tier is forbidden when rejecting a pattern")
    draft_path = scope.iteration_root / "drafts" / f"{slug}.md"
    draft = parse_pattern_page(draft_path, expected_slug=slug, draft=True)
    gate1 = _gate1_document(scope)
    if any(row.get("subject_id") == slug for row in gate1["rulings"]):
        raise StateError(f"pattern {slug} already has a Gate 1 ruling")
    binding = baseline_binding(scope)
    conflicts = read_json(scope.iteration_root / "conflict-rulings.json") if (
        scope.iteration_root / "conflict-rulings.json"
    ).exists() else {"rulings": []}
    ruled = {row.get("conflict_id"): row for row in conflicts.get("rulings", [])}
    missing = sorted(set(draft.conflict_ids) - set(ruled))
    if decision == "accept" and missing:
        raise StateError(f"pattern is blocked by unresolved conflicts: {', '.join(missing)}")
    if decision == "accept" and tier == "portable" and draft.mentions_campaign_identity:
        if not named_portable_override or not str(rationale or "").strip():
            raise ValidationError("named portable placement requires explicit override and rationale")
    # Only an acceptance is blocked by an open conflict, so a rejection cites
    # the rulings that exist rather than raising KeyError on the ones that do not.
    refs = [ruled[key] for key in sorted(draft.conflict_ids) if key in ruled]
    ruling = Gate1Ruling(
        subject_id=slug,
        ruling="accepted" if decision == "accept" else "rejected",
        tier=tier or draft.proposed_tier,
        named_portable_override=named_portable_override,
        rationale=rationale,
        iteration_id=scope.iteration_id,
        baseline=binding,
        conflict_ruling_refs=refs,
    )
    gate1["rulings"].append(asdict(ruling))
    gate1["rulings"] = sorted(gate1["rulings"], key=lambda row: row["subject_id"])
    writes: list[tuple[Path, bytes]] = [
        (scope.iteration_root / "gate1.json", canonical_json(gate1).encode("utf-8"))
    ]
    status = "rejected"
    operation = "gate1_campaign"
    if decision == "accept" and tier == "campaign":
        status = "accepted"
        page_path = scope.campaign_wiki_root / "patterns" / f"{slug}.md"
        page = render_confirmed_pattern(draft, ruling)
        writes.append((page_path, page.encode("utf-8")))
        index = render_campaign_index(scope, pending=(slug, page))
        writes.append((scope.campaign_wiki_root / "index.md", index.encode("utf-8")))
        logs_path = scope.campaign_wiki_root / "logs.md"
        prior_log = logs_path.read_text(encoding="utf-8") if logs_path.is_file() else "# Narration Wiki Log\n\n"
        writes.append((logs_path, (prior_log + f"- Gate 1 accepted `{slug}` from `{scope.iteration_id}`.\n").encode("utf-8")))
    elif decision == "accept":
        status = "pending_portable_sync"
        operation = "gate1_portable_handoff"
        handoff = render_confirmed_pattern(draft, ruling, status="pending_portable_sync")
        writes.append((scope.iteration_root / "portable-promotions" / f"{slug}.md", handoff.encode("utf-8")))
    iteration = load_iteration(scope)
    draft_slugs = {path.stem for path in (scope.iteration_root / "drafts").glob("*.md")}
    ruled_slugs = {str(row.get("subject_id")) for row in gate1["rulings"]}
    iteration.state = "ready_for_proposal" if draft_slugs <= ruled_slugs else "gate1_review"
    writes.append((
        scope.iteration_root / "iteration.json",
        canonical_json(iteration.to_dict()).encode("utf-8"),
    ))
    with campaign_lock(scope):
        _journaled_writes(scope, operation, slug, writes)
    return {"pattern_slug": slug, "decision": decision, "tier": tier, "status": status}


def _ledger_entry(entry: ImpactEntry) -> str:
    payload = canonical_json(asdict(entry)).rstrip("\n")
    return (
        f"\n<!-- narration-wiki-proposal:{entry.proposal_id} -->\n"
        f"## {entry.proposal_id}: {entry.ruling}\n\n"
        f"```json narration-wiki-impact\n{payload}\n```\n"
    )


def finalize_proposal(scope: CampaignScope, proposal_id: str, decision: str) -> dict[str, Any]:
    proposal_id = require_stable_id(proposal_id, "proposal-id")
    decision = decision.casefold()
    if decision not in {"accept", "reject"}:
        raise ValidationError("proposal decision must be accept or reject")
    root = scope.iteration_root / "proposals" / proposal_id
    proposal = read_json(root / "proposal.json")
    existing_gate = root / "gate2.json"
    if existing_gate.exists():
        prior = read_json(existing_gate)
        if prior.get("decision") == decision:
            return prior
        raise StateError("proposal already has a different Gate 2 ruling")
    after_measurement = root / "measurement-after.json"
    if not after_measurement.is_file():
        raise StateError("Gate 2 requires an after measurement")
    target = scope.campaign_root / str(proposal["target_path"])
    if sha256_file(target) != proposal["after_sha256"]:
        raise StateError("live proposal target does not match the staged after snapshot")
    before_measurement = scope.iteration_root / "measurement-before.json"
    before = read_json(before_measurement)
    after = read_json(after_measurement)
    if before.get("corpus_id") != after.get("corpus_id"):
        raise StateError("Gate 2 measurements do not use the same corpus")
    ledger_path = scope.campaign_wiki_root / "skill-impact.md"
    ledger = ledger_path.read_text(encoding="utf-8") if ledger_path.is_file() else "# Narration Skill Impact\n"
    marker = f"narration-wiki-proposal:{proposal_id}"
    if marker in ledger:
        raise StateError(f"impact ledger already contains proposal {proposal_id}")
    diff = (root / "change.diff").read_text(encoding="utf-8")
    entry = ImpactEntry(
        proposal_id=proposal_id,
        proposal_fingerprint=str(proposal["proposal_fingerprint"]),
        iteration_id=scope.iteration_id,
        session_relative=scope.session_relative,
        corpus_id=str(before["corpus_id"]),
        pattern_slugs=proposal["pattern_slugs"],
        affected_rule=str(proposal["affected_rule"]),
        target_kind=str(proposal["target_kind"]),
        target_path=str(proposal["target_path"]),
        before_sha256=str(proposal["before_sha256"]),
        after_sha256=str(proposal["after_sha256"]),
        diff=diff,
        before_measurement={"path": "measurement-before.json", "sha256": sha256_file(before_measurement)},
        after_measurement={"path": f"proposals/{proposal_id}/measurement-after.json", "sha256": sha256_file(after_measurement)},
        ruling="Accepted" if decision == "accept" else "Rejected",
        reconsideration=proposal.get("reconsideration"),
    )
    gate2 = {
        "schema_version": 1,
        "gate": "gate2",
        "proposal_id": proposal_id,
        "decision": decision,
        "proposal_fingerprint": proposal["proposal_fingerprint"],
        "before_measurement_sha256": sha256_file(before_measurement),
        "after_measurement_sha256": sha256_file(after_measurement),
    }
    proposal["state"] = "accepted" if decision == "accept" else "rejected"
    writes: list[tuple[Path, bytes]] = [
        (ledger_path, (ledger + _ledger_entry(entry)).encode("utf-8")),
        (existing_gate, canonical_json(gate2).encode("utf-8")),
        (root / "proposal.json", canonical_json(proposal).encode("utf-8")),
    ]
    if decision == "reject":
        before_bytes = (root / "before.snapshot").read_bytes()
        if sha256_bytes(before_bytes) != proposal["before_sha256"]:
            raise ValidationError("before snapshot hash does not match proposal")
        writes.insert(0, (target, before_bytes))
    iteration = load_iteration(scope)
    iteration.state = "completed_accepted" if decision == "accept" else "completed_rejected"
    iteration.active_proposal_id = None
    writes.append((
        scope.iteration_root / "iteration.json",
        canonical_json(iteration.to_dict()).encode("utf-8"),
    ))
    with campaign_lock(scope):
        _journaled_writes(scope, f"gate2_{decision}", proposal_id, writes)
    return gate2
