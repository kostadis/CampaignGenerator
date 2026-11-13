"""Delegated decision helpers: carry approvals forward and apply a GM policy.

Both helpers record decisions the GM has delegated, so neither may ever run
implicitly.  They plan first (a dry run that writes nothing), and only an
explicit ``write`` submits the planned decisions through ``save_decisions`` --
the same validated, journaled path as ``review decide``.  Every note they write
names the mechanism that produced it, so the decision history always shows
which approvals a human made item by item and which were made by rule.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from campaignlib.review_config import load_campaign_review_config
from pipelines.summary_native import noise
from pipelines.summary_native.review import custody
from pipelines.summary_native.review.store import (
    ReviewStoreError,
    _refuse_stale_custody,
    _validate_action_decision,
    read_review_state,
    read_snapshot,
    save_decisions,
)


class EventIndex:
    """Per item: the latest event, and the decision revision ``save_decisions`` expects next.

    The one place the latest-decision rule lives (spec 043 T046).  Build it once per snapshot and pass
    it to ``_latest`` / ``_active_revision`` to turn the per-item scans into dict lookups.
    """

    __slots__ = ("latest", "revision")

    def __init__(self, events: list[dict]):
        self.latest: dict[str, dict] = {}
        self.revision: dict[str, int] = {}
        for event in events:
            item_id = event.get("item_id")
            if item_id is None:
                continue
            self.latest[item_id] = event
            if "decision_revision" in event:
                self.revision[item_id] = int(event["decision_revision"])


def index_events(events: list[dict]) -> EventIndex:
    return EventIndex(events)


def _latest(events: list[dict], item_id: str, index: EventIndex | None = None) -> dict | None:
    return (index or EventIndex(events)).latest.get(item_id)


def _active_revision(events: list[dict], item_id: str, index: EventIndex | None = None) -> int:
    """The decision revision ``save_decisions`` expects next for ``item_id``."""
    return (index or EventIndex(events)).revision.get(item_id, 0)


def _current_decision(event: dict | None, item, stale_ids: set[str]) -> bool:
    """A live decision bound to the item's present revision and digest."""
    return bool(
        event
        and event.get("kind") != "withdrawal"
        and event.get("decision_revision") is not None
        and event.get("item_revision") == item.revision
        and event.get("review_digest") == item.review_digest
        and item.item_id not in stale_ids
    )


def _signature(item) -> tuple:
    return (
        item.proposed_action.action,
        item.claim_text,
        tuple(sorted(diagnostic.message for diagnostic in item.diagnostics)),
        item.locator.source_path,
    )


def _legacy_codes(item) -> list[str]:
    return sorted({str(diagnostic.legacy_code) for diagnostic in item.diagnostics})


def _summary(item, reason: str) -> dict:
    return {
        "item_id": item.item_id,
        "action": item.proposed_action.action,
        "source_path": item.locator.source_path,
        "display_line": item.locator.display_line,
        "legacy_codes": _legacy_codes(item),
        "reason": reason,
    }


def npc_signoff_blocker(root: Path, item) -> tuple[str, str] | None:
    """Why an exact NPC draft may not be approved now, or ``None`` if it may.

    Shared by ``review npc sign`` and ``review carry`` so a carried sign-off
    meets exactly the bar of a hand-made one.
    """
    details = item.proposed_action.details
    if details.get("verification_complete") is not True:
        return ("REVIEW_NPC_RECHECK_REQUIRED", "run the complete dossier verification selection")
    if details.get("mechanical_verdict") != "pass":
        return ("REVIEW_NPC_MECHANICAL_BLOCK", "repair hard verification failures and run a real recheck")
    path = (Path(root) / str(details.get("draft_path"))).resolve()
    try:
        path.relative_to(Path(root).resolve())
    except ValueError:
        return ("REVIEW_PATH", "draft outside campaign")
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != details.get("draft_sha256"):
        return ("REVIEW_NPC_SIGNOFF_STALE", "draft bytes changed")
    return None


def _decision(item, *, expected: int, disposition: str, note: str, verdict: str = "approve") -> dict:
    return {
        "item_id": item.item_id,
        "item_revision": item.revision,
        "review_digest": item.review_digest,
        "expected_decision_revision": expected,
        "verdict": verdict,
        "disposition": disposition,
        "note": note,
    }


def plan_carry(root: Path, review_id: str, *, source_review_id: str) -> dict:
    """Plan which current approvals in ``source_review_id`` carry to ``review_id``.

    An item carries only when the same item id holds a current *approve*
    decision in the source review and nothing the GM judged has changed: the
    same action, claim text, diagnostic messages and source path, and for an
    NPC draft sign-off the identical draft sha256 (which must also still pass
    the sign-off guard).  Everything else is listed as needing review.
    """
    if review_id == source_review_id:
        raise ReviewStoreError("REVIEW_CARRY_INVALID: source and target review are the same", "REVIEW_CARRY_INVALID")
    old_manifest, old_items, old_events, old_stale = read_review_state(root, source_review_id)
    manifest, items, events, stale = read_review_state(root, review_id)
    if old_manifest.kind != manifest.kind:
        raise ReviewStoreError(
            f"REVIEW_CARRY_INVALID: review kinds differ ({old_manifest.kind.value} vs {manifest.kind.value})",
            "REVIEW_CARRY_INVALID",
        )
    old_by_id = {item.item_id: item for item in old_items}
    max_note = load_campaign_review_config(root).max_note_chars
    carried, needs_review, already = [], [], []
    for item in items:
        current = _latest(events, item.item_id)
        if _current_decision(current, item, stale):
            already.append(item.item_id)
            continue
        old = old_by_id.get(item.item_id)
        old_event = _latest(old_events, item.item_id) if old is not None else None
        reason = None
        if old is None:
            reason = "absent from source review"
        elif not _current_decision(old_event, old, old_stale):
            reason = "no current decision in source review"
        elif old_event.get("verdict") != "approve":
            reason = f"source decision was {old_event.get('verdict')}, not approve"
        elif old_event.get("proposal_id"):
            reason = "source approval is bound to a proposal; not carried"
        elif item.proposed_action.action == "signoff_npc_draft":
            old_sha = old.proposed_action.details.get("draft_sha256")
            new_sha = item.proposed_action.details.get("draft_sha256")
            if old_sha != new_sha:
                reason = "draft bytes changed"
            else:
                blocker = npc_signoff_blocker(root, item)
                if blocker is not None:
                    reason = f"{blocker[0]}: {blocker[1]}"
        elif _signature(old) != _signature(item):
            reason = "claim, finding, action or source path changed"
        disposition = old_event.get("disposition") if old_event else None
        if reason is None:
            try:
                _validate_action_decision(item, verdict="approve", disposition=disposition)
            except ReviewStoreError as exc:
                reason = str(exc)
        if reason is not None:
            needs_review.append(_summary(item, reason))
            continue
        basis = (
            f"draft bytes identical, sha256 {item.proposed_action.details.get('draft_sha256')}"
            if item.proposed_action.action == "signoff_npc_draft"
            else "identical claim, findings and source path"
        )
        note = (
            f"Carried forward by `summary_native review carry` from {source_review_id} "
            f"(event {old_event.get('event_id')}, approved by {old_event.get('reviewer')}); {basis}."
        )
        if len(note) > max_note:
            raise ReviewStoreError("REVIEW_INVALID_BATCH: carry note exceeds the configured note limit", "REVIEW_INVALID_BATCH")
        carried.append({
            "reviewer": str(old_event.get("reviewer")),
            "decision": _decision(item, expected=_active_revision(events, item.item_id), disposition=disposition, note=note),
        })
    needs_review.sort(key=lambda value: (value["source_path"], value["display_line"] or 0, value["item_id"]))
    return {
        "review_id": review_id,
        "source_review_id": source_review_id,
        "review_generation": manifest.generation,
        "carried": carried,
        "needs_review": needs_review,
        "already_decided": already,
    }


def load_policy(path: Path) -> dict[str, str]:
    """Read a ``legacy_code: note`` mapping (YAML or JSON)."""
    import yaml

    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ReviewStoreError(f"REVIEW_POLICY_INVALID: {exc}", "REVIEW_POLICY_INVALID") from exc
    if not isinstance(raw, dict) or not raw:
        raise ReviewStoreError("REVIEW_POLICY_INVALID: policy must map legacy_code to note", "REVIEW_POLICY_INVALID")
    policy = {}
    for code, note in raw.items():
        if not isinstance(code, str) or not code.strip() or not isinstance(note, str) or not note.strip():
            raise ReviewStoreError(
                f"REVIEW_POLICY_INVALID: entry {code!r} needs a nonblank code and nonblank note", "REVIEW_POLICY_INVALID"
            )
        policy[code.strip()] = note.strip()
    return policy


def plan_policy(root: Path, review_id: str, *, policy: dict[str, str], policy_label: str) -> dict:
    """Plan approvals for items whose *only* diagnostic code is in ``policy``.

    Items with several distinct codes are never approved by policy, nor are
    items whose action cannot be approved with ``accept_no_change`` (mechanical
    and GM-confirmed blockers, draft sign-offs).
    """
    manifest, items, events, stale = read_review_state(root, review_id)
    max_note = load_campaign_review_config(root).max_note_chars
    approvable, ineligible, already = [], [], []
    counts: dict[str, int] = {code: 0 for code in policy}
    for item in items:
        codes = _legacy_codes(item)
        if len(codes) != 1 or codes[0] not in policy:
            continue
        code = codes[0]
        if _current_decision(_latest(events, item.item_id), item, stale):
            already.append(item.item_id)
            continue
        try:
            _validate_action_decision(item, verdict="approve", disposition="accept_no_change")
        except ReviewStoreError as exc:
            ineligible.append(_summary(item, str(exc)))
            continue
        note = f"Approved by `summary_native review policy` under GM-delegated policy {policy_label} [{code}]: {policy[code]}"
        if len(note) > max_note:
            raise ReviewStoreError(
                f"REVIEW_POLICY_INVALID: note for {code} exceeds the configured note limit", "REVIEW_POLICY_INVALID"
            )
        counts[code] += 1
        approvable.append(_decision(item, expected=_active_revision(events, item.item_id), disposition="accept_no_change", note=note))
    return {
        "review_id": review_id,
        "review_generation": manifest.generation,
        "policy": policy_label,
        "counts_by_code": counts,
        "approvable": approvable,
        "ineligible": ineligible,
        "already_decided": already,
    }


# ---------------------------------------------------------------- classified noise (spec 041 US4)

def _noise_members(items, noise_class: str):
    """Items whose single legacy_code is ``noise-<class>`` (the same single-code rule as ``plan_policy``)."""
    code = noise.legacy_code(noise_class)
    return [item for item in items if _legacy_codes(item) == [code]]


def _noise_details(item) -> dict:
    return next((dict(d.details) for d in item.diagnostics if str(d.legacy_code).startswith("noise-")), {})


def _occurrence(item, event: dict | None, current: bool) -> dict:
    details = _noise_details(item)
    return {
        "item_id": item.item_id,
        # One NPC-label rule, shared with per-item custody (spec 042 R12).
        "npc": custody.npc_label(item),
        "draft_path": item.locator.source_path,
        "line": details.get("line", item.locator.display_line),
        "token": details.get("token"),
        "sentence": details.get("sentence"),
        "cited_scenes": list(details.get("cited_scenes", [])),
        "resolved_by": details.get("resolved_by"),
        "decision": (
            {"verdict": event.get("verdict"), "disposition": event.get("disposition"), "reviewer": event.get("reviewer")}
            if current and event else None
        ),
    }


def list_noise(root: Path, review_id: str) -> dict:
    """Read-only: every noise class (precedence order, empty ones included) with its occurrences."""
    manifest, items, events, stale = read_review_state(root, review_id)
    classes = []
    for cls in noise.CLASSES:
        occurrences, tally = [], {"approve": 0, "reject": 0, "undecided": 0, "discuss": 0}
        for item in _noise_members(items, cls):
            event = _latest(events, item.item_id)
            current = _current_decision(event, item, stale)
            occurrences.append(_occurrence(item, event, current))
            tally[event.get("verdict") if current else "undecided"] += 1
        classes.append({
            "noise_class": cls,
            "legacy_code": noise.legacy_code(cls),
            "count": len(occurrences),
            "undecided": tally["undecided"],
            "approved": tally["approve"],
            "rejected": tally["reject"],
            "occurrences": occurrences,
        })
    return {"review_id": review_id, "review_generation": manifest.generation, "classes": classes}


_NOISE_VERDICTS = {"approve": "accept_no_change", "reject": "reject_action"}


def plan_noise_class(root: Path, review_id: str, *, noise_class: str, verdict: str, note: str) -> dict:
    """Plan one GM class verdict as one decision per undecided occurrence of ``noise_class``.

    Already-decided occurrences are skipped and listed, never overwritten.  Writing goes through
    ``submit_decisions``; nothing here saves.
    """
    if noise_class not in noise.CLASSES:
        raise ReviewStoreError(
            f"REVIEW_NOISE_UNKNOWN_CLASS: {noise_class}; expected one of {', '.join(noise.CLASSES)}",
            "REVIEW_NOISE_UNKNOWN_CLASS",
        )
    if verdict not in _NOISE_VERDICTS:
        raise ReviewStoreError(f"REVIEW_INVALID_BATCH: verdict must be approve or reject, got {verdict!r}", "REVIEW_INVALID_BATCH")
    note = (note or "").strip()
    if not note:
        raise ReviewStoreError("REVIEW_NOISE_NOTE_REQUIRED: --note must be nonblank", "REVIEW_NOISE_NOTE_REQUIRED")
    snapshot = read_review_state(root, review_id)
    manifest, items, events, stale = snapshot
    max_note = load_campaign_review_config(root).max_note_chars
    disposition = _NOISE_VERDICTS[verdict]
    # One expansion rule (spec 043 R3).  Noise policy: a member that already has a fresh decision,
    # identical or not, is skipped and listed, never overwritten.  The note is built below, once the
    # undecided count is known, so the placeholder here only affects the identical/differs split.
    from pipelines.summary_native.review import cards  # local: cards imports this module lazily too
    members = _noise_members(items, noise_class)
    expansion = cards.expand(snapshot, member_ids=[item.item_id for item in members], verdict=verdict,
                             disposition_for=lambda _item: disposition, gm_note="")
    already = [m.item_id for m in expansion.members if m.category != "new"]
    pending = [item for item, m in zip(members, expansion.members) if m.category == "new"]
    if not pending:
        raise ReviewStoreError(
            f"REVIEW_NOISE_NOTHING_TO_DECIDE: class {noise_class} has no undecided occurrences",
            "REVIEW_NOISE_NOTHING_TO_DECIDE",
        )
    full_note = f"GM class verdict on batch card [{noise.legacy_code(noise_class)}] ({len(pending)} occurrences): {note}"
    if len(full_note) > max_note:
        raise ReviewStoreError(
            f"REVIEW_NOISE_NOTE_TOO_LONG: the note is {len(full_note)} characters once prefixed; the limit is {max_note}",
            "REVIEW_NOISE_NOTE_TOO_LONG",
        )
    # The written decisions come from the same expansion, with the final note (spec 043 T046).
    final = cards.expand(snapshot, member_ids=[item.item_id for item in pending], verdict=verdict,
                         disposition_for=lambda _item: disposition, gm_note=full_note)
    return {
        "review_id": review_id,
        "review_generation": manifest.generation,
        "noise_class": noise_class,
        "verdict": verdict,
        "planned": [item.item_id for item in pending],
        "already_decided": already,
        "decisions": [m.decision for m in final.members],
    }


def submit_decisions(root: Path, review_id: str, *, generation: int, reviewer: str, decisions: list[dict], prefix: str,
                     batches: list[list[dict]] | None = None) -> list[dict]:
    """Save ``decisions`` in configured-size batches through ``save_decisions``.

    Request ids are derived from the batch content, so re-running an
    interrupted write replays committed batches as idempotent no-ops.

    ``batches`` (spec 043) replaces fixed-size slicing with caller-packed batches (card-aligned);
    each must hold at most ``max_batch_decisions`` decisions.  When a batch after the first fails,
    the error's ``detail`` is ``{"recorded", "not_recorded", "cause"}`` (item ids) so a caller can
    report exactly what is on disk.
    """
    size = load_campaign_review_config(root).max_batch_decisions
    if batches is None:
        batches = [decisions[start:start + size] for start in range(0, len(decisions), size)]
    else:
        if any(len(batch) > size or not batch for batch in batches):
            raise ReviewStoreError(
                f"REVIEW_INVALID_BATCH: each batch must hold 1 to {size} decisions", "REVIEW_INVALID_BATCH")
        decisions = [d for batch in batches for d in batch]
    # Spec 042: every submitted item is checked BEFORE the first batch is written, so one stale
    # item in a late batch cannot leave earlier batches saved. ``save_decisions`` keeps its own
    # per-batch check (defence in depth, and the race between this check and a write).
    manifest, cust, snapshot_items = read_snapshot(root, review_id)
    known = {item.item_id for item in snapshot_items}
    submitted = [d["item_id"] for d in decisions
                 if isinstance(d, dict) and isinstance(d.get("item_id"), str) and d["item_id"] in known]
    _refuse_stale_custody(root, manifest, cust, snapshot_items, submitted, operation="decide")
    results = []
    for index, batch in enumerate(batches):
        digest = hashlib.sha256(
            json.dumps([reviewer, batch], sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        request = {
            "version": 1,
            "request_id": f"{prefix}-{digest}",
            "review_generation": generation,
            "reviewer": reviewer,
            "decisions": batch,
        }
        try:
            results.append(save_decisions(root, review_id, request))
        except ReviewStoreError as exc:
            inner = getattr(exc, "detail", None)
            detail = inner
            if index > 0:
                detail = {
                    "recorded": [d["item_id"] for earlier in batches[:index] for d in earlier],
                    "not_recorded": [d["item_id"] for later in batches[index:] for d in later],
                    "cause": inner,
                }
            raise ReviewStoreError(
                f"{exc} (after {len(results)} earlier batch(es) saved; rerun the dry run to see what remains)",
                getattr(exc, "code", None),
                detail=detail,
            ) from exc
    return results
