"""Review card contract (spec 043): packet and decisions models, and the one expansion rule.

A *packet* is the set of cards a GM reviews on a page; a *decisions file* is what the page saves.
CampaignGenerator owns both shapes (strict pydantic models here, published as JSON Schemas under
``review/schemas/``) and expands card verdicts into store decisions in exactly one place:
:func:`expand`.  Nothing in this module calls a model, and nothing in it records a verdict the
GM did not give (an unmarked card stays unmarked).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from pipelines.summary_native.review.models import canonical_bytes

SCHEMA_VERSION = 1
ACCEPTED_SCHEMA_VERSIONS = frozenset({1})

CARD_ID_PATTERN = r"^[A-Za-z0-9_.:-]{1,128}$"
SIGNOFF_ACTION = "signoff_npc_draft"

# Actions whose approve verdict is "accept_no_change" (research R4).
_FINDING_ACTIONS = (
    "review_claim_against_evidence",
    "review_presentation",
    "review_classified_noise",
    "rerun_selected_check",
    "repair_or_recheck_pointer",
    "review_supersession",
    "review_audience_and_knowledge",
    "acknowledge_claim_coverage",
)
_VERDICTS = ("approve", "reject", "discuss")


def _build_disposition_for() -> dict[tuple[str, str], str]:
    table: dict[tuple[str, str], str] = {}
    for action in (*_FINDING_ACTIONS, SIGNOFF_ACTION):
        table[(action, "approve")] = "document_signoff" if action == SIGNOFF_ACTION else "accept_no_change"
        table[(action, "reject")] = "reject_action"
        table[(action, "discuss")] = "defer"
    return table


DISPOSITION_FOR: dict[tuple[str, str], str] = _build_disposition_for()


class _Strict(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", frozen=True)


class EvidenceRow(_Strict):
    """Plain-text evidence for a card.  Never HTML."""

    source: str
    anchor: str | None = None
    excerpt: str | None = None
    missing_reason: str | None = None


class Member(_Strict):
    item_id: str
    action: str
    item_revision: int
    review_digest: str
    expected_decision_revision: int
    line: int | None = None


class Card(_Strict):
    id: str = Field(pattern=CARD_ID_PATTERN)
    kind: Literal["finding", "noise_class", "signoff"]
    npc: str | None = None
    title: str
    body: str = Field(description="Plain text. Render as text, never as HTML. A sign-off card's body is byte-identical to its draft.")
    approve_means: str
    reject_means: str
    evidence: tuple[EvidenceRow, ...] = ()
    members: tuple[Member, ...] = Field(min_length=1)
    draft_sha256: str | None = None
    previous_discussion: str | None = Field(
        default=None, description="Plain text, display only: 'Previously discussed by <reviewer>: <note>' when the item's current decision is a Discuss.")


class CardPacket(_Strict):
    schema_version: int
    packet_id: str = Field(pattern=r"^packet-[0-9a-f]{20}$")
    review_id: str
    review_kind: str
    generation: int
    cards: tuple[Card, ...] = Field(min_length=1)


class CardVerdict(_Strict):
    verdict: Literal["approve", "reject", "discuss"]
    note: str = ""
    members: tuple[str, ...]
    draft_sha256: str | None = None


class CardDecisions(_Strict):
    schema_version: int
    packet_id: str
    review_id: str
    saved_at: str = Field(min_length=1)
    cards: dict[str, CardVerdict]


class PlannedMember(_Strict):
    item_id: str
    category: Literal["record", "supersede", "noop", "refused"]
    disposition: str | None
    previous: dict | None = None
    decision: dict | None = None


class Refusal(_Strict):
    code: str
    message: str
    data: dict | None = None


class PlannedCard(_Strict):
    card_id: str
    verdict: Literal["approve", "reject", "discuss"] | None = None
    state: Literal["unmarked", "refused", "applied"]
    refusal: Refusal | None = None
    members: tuple[PlannedMember, ...] = ()


class PlanCounts(_Strict):
    record: int = 0
    supersede: int = 0
    noop: int = 0
    unmarked: int = 0
    refused: int = 0


class DecisionPlan(_Strict):
    review_id: str
    packet_id: str
    generation: int
    plan_sha256: str
    cards: tuple[PlannedCard, ...]
    counts: PlanCounts
    saved: tuple[dict, ...] | None = None


# ------------------------------------------------------------------ identity and notes

def packet_id_for(body: dict) -> str:
    """``packet-`` plus 20 hex of the canonical body with ``packetId`` omitted."""
    digest = hashlib.sha256(canonical_bytes(body, exclude_fields=frozenset({"packetId"}))).hexdigest()
    return "packet-" + digest[:20]


def card_note(card_id: str, gm_note: str) -> str:
    """The note stored with a card verdict.  Carries no packet id or count (R5), so a re-save is a no-op."""
    note = (gm_note or "").strip()
    head = f"GM card verdict [{card_id}]"
    return f"{head}: {note}" if note else head


# ------------------------------------------------------------------ schemas

def schemas_dir() -> Path:
    return Path(__file__).resolve().parent / "schemas"


def _schema_text(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(by_alias=True), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def schema_files() -> dict[str, str]:
    return {
        "card-packet.v1.schema.json": _schema_text(CardPacket),
        "card-decisions.v1.schema.json": _schema_text(CardDecisions),
    }


def write_schemas() -> list[Path]:
    directory = schemas_dir()
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in schema_files().items():
        path = directory / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


# ------------------------------------------------------------------ the one expansion rule

class ExpandedMember(_Strict):
    item_id: str
    category: Literal["new", "identical", "differs"]
    decision: dict[str, Any]
    previous: dict | None = None


class Expansion(_Strict):
    members: tuple[ExpandedMember, ...]


def expand(snapshot: tuple, *, member_ids: list[str], verdict: str,
           disposition_for: Callable[[Any], str], gm_note: str) -> Expansion:
    """Expand one verdict over ``member_ids`` against a ``read_review_state`` snapshot.

    ``snapshot`` is ``(manifest, items, events, stale_ids)``.  For every member the (verdict,
    disposition) pair is validated with the store's own rule, the member is classified against its
    current fresh decision (``new`` / ``identical`` / ``differs``), and the exact store decision is
    built with the live ``expected_decision_revision``.  Policy for ``identical`` and ``differs``
    belongs to the caller.
    """
    # Imported here: delegated.py imports this module for plan_noise_class, so a module-level
    # import in both directions would be a cycle.
    from pipelines.summary_native.review import delegated
    from pipelines.summary_native.review.store import ReviewStoreError, _validate_action_decision

    _manifest, items, events, stale = snapshot
    by_id = {item.item_id: item for item in items}
    out = []
    for item_id in member_ids:
        item = by_id.get(item_id)
        if item is None:
            raise ReviewStoreError(f"REVIEW_CARDS_MEMBER_MISSING: {item_id}", "REVIEW_CARDS_MEMBER_MISSING")
        disposition = disposition_for(item)
        _validate_action_decision(item, verdict=verdict, disposition=disposition)
        latest = delegated._latest(events, item_id)
        previous = None
        category = "new"
        if delegated._current_decision(latest, item, stale):
            previous = {
                "verdict": latest.get("verdict"), "disposition": latest.get("disposition"),
                "note": latest.get("note"), "decisionRevision": latest.get("decision_revision"),
            }
            same = (latest.get("verdict"), latest.get("disposition"), latest.get("note")) == (
                verdict, disposition, gm_note)
            category = "identical" if same else "differs"
        decision = delegated._decision(
            item, expected=delegated._active_revision(events, item_id), disposition=disposition,
            note=gm_note, verdict=verdict)
        out.append(ExpandedMember(item_id=item_id, category=category, decision=decision, previous=previous))
    return Expansion(members=tuple(out))


# =====================================================================================
# User Story 1: export a packet, plan a decisions file, write exactly the plan
# =====================================================================================

_NOISE_ACTION = "review_classified_noise"
_CLASS_CARD_NOTE = "One verdict here applies to every listed occurrence; each gets its own decision record."
_KIND_LABEL = {"review_claim_against_evidence": "claim vs evidence", "review_presentation": "presentation"}


def _refuse(code: str, text: str, *, detail: dict | None = None):
    from pipelines.summary_native.review.store import ReviewStoreError
    return ReviewStoreError(f"{code}: {text}", code, detail=detail)


def _draft_stem(item) -> str:
    return Path(item.locator.source_path or item.item_id).stem.casefold()


def _who(item) -> str:
    from pipelines.summary_native.review import custody
    return str(item.proposed_action.details.get("npc") or custody.npc_label(item) or item.item_id)


_CARD_NOTE_PREFIX = re.compile(r"^GM card verdict \[[^\]]*\](?:: )?")


def _previous_discuss(events, item, stale) -> str | None:
    """``Previously discussed by <reviewer>: <note>`` for an item whose current decision is a Discuss.

    Display only (spec 043 R2, GM ruling 2026-11-12): it reads the same latest-decision helpers decide
    uses and changes nothing decide records.
    """
    from pipelines.summary_native.review import delegated
    latest = delegated._latest(events, item.item_id)
    if not (delegated._current_decision(latest, item, stale) and latest.get("verdict") == "discuss"):
        return None
    note = _CARD_NOTE_PREFIX.sub("", str(latest.get("note") or "")).strip()
    return f"Previously discussed by {latest.get('reviewer')}" + (f": {note}" if note else "")


def _member(item, events) -> Member:
    from pipelines.summary_native.review import delegated
    return Member(
        item_id=item.item_id, action=item.proposed_action.action, item_revision=item.revision,
        review_digest=item.review_digest, expected_decision_revision=delegated._active_revision(events, item.item_id),
        line=item.locator.display_line)


def _noise_card(noise_class: str, members: list, events, stale=frozenset()) -> Card:
    from pipelines.summary_native.review import delegated
    rows = []
    for item in members:
        details = delegated._noise_details(item)
        line = details.get("line", item.locator.display_line)
        scenes = ", ".join(str(s) for s in details.get("cited_scenes", [])) or "none"
        sentence = details.get("sentence") or item.claim_text or ""
        rows.append(
            f"{_who(item)}{' L' + str(line) if line else ''} ({item.locator.source_path}): "
            f"token {details.get('token', '')}\n  {sentence}\n  cited: {scenes}; resolved by: {details.get('resolved_by', '')}"
            + (f"\n  {previous}" if (previous := _previous_discuss(events, item, stale)) else ""))
    n = len(members)
    plural = "s" if n != 1 else ""
    return Card(
        id=f"noise-class:{noise_class}", kind="noise_class", npc=None,
        title=f"Classified noise: {noise_class} ({n} occurrence{plural})",
        body=f"{_CLASS_CARD_NOTE}\n\n{n} occurrence{plural}:\n\n" + "\n\n".join(rows),
        approve_means="Keep as-is: every listed draft line stands as written (each records accept_no_change). "
                      "No edit to any draft.",
        reject_means="These occurrences are not noise: each listed line needs a fix in its own draft "
                     "(the draft is the origin). Say what to fix in a note.",
        evidence=(), members=tuple(_member(item, events) for item in members), draft_sha256=None)


def _finding_card(item, events, stale=frozenset()) -> Card:
    where = item.locator.source_path or ""
    line = item.locator.display_line
    action = item.proposed_action.action
    checker = sorted({d.message for d in item.diagnostics if d.message})
    body = f"Claim: {item.claim_text or ''}" + "".join(f"\nChecker: {m}" for m in checker)
    evidence = tuple(
        EvidenceRow(source=ev.source_path or "", anchor=ev.anchor, excerpt=ev.exact_excerpt,
                    missing_reason=ev.missing_reason)
        for ev in item.evidence if ev.exact_excerpt or ev.missing_reason)
    return Card(
        id=item.item_id, kind="finding", npc=_who(item),
        title=f"{_who(item)}{' L' + str(line) if line else ''} ({_KIND_LABEL.get(action, action or 'finding')}): "
              f"{item.rationale or ''}",
        body=body,
        approve_means=f"Keep as-is: the draft line stands as written (records accept_no_change). No edit to {where}.",
        reject_means=f"The line is wrong: no sign-off for this draft until it is corrected in {where} "
                     f"(the draft is the origin). Say the fix in a note.",
        evidence=evidence, members=(_member(item, events),), draft_sha256=None,
        previous_discussion=_previous_discuss(events, item, stale))


def _signoff_card(root: Path, item, events, stale=frozenset()) -> Card:
    from pipelines.summary_native.review.store import _reject_symlinks
    details = item.proposed_action.details
    draft_sha = str(details.get("draft_sha256"))
    text = _reject_symlinks(Path(root), Path(root) / str(details.get("draft_path"))).read_text(encoding="utf-8")
    who = _who(item)
    return Card(
        id=item.item_id, kind="signoff", npc=who, title=f"Sign off {who}'s draft for publication", body=text,
        approve_means=f"Record a GM sign-off for these exact bytes (sha256 {draft_sha[:16]}...); publish can then "
                      f"proceed. Mechanical verdict: {details.get('mechanical_verdict', '?')}.",
        reject_means="Keep the draft as it is, unsigned and unpublished. Say what to change in a note; "
                     "the fix goes in the draft and comes back for a new sign-off.",
        evidence=(), members=(_member(item, events),), draft_sha256=draft_sha,
        previous_discussion=_previous_discuss(events, item, stale))


def build_packet(root: Path, review_id: str, *, item_ids: list[str] | None = None,
                 actions: list[str] | None = None, snapshot: tuple | None = None) -> tuple[dict, list[dict]]:
    """The packet (camelCase dict, ``packetId`` included) and the sign-offs not offered (R2).

    Offers every item with no current approve or reject.  Decides nothing.
    """
    from pipelines.summary_native import noise
    from pipelines.summary_native.review import delegated
    from pipelines.summary_native.review.store import read_review_state

    root = Path(root).resolve()
    manifest, items, events, stale = snapshot if snapshot is not None else read_review_state(root, review_id)
    if manifest.kind.value != "npc_verification":
        raise _refuse("REVIEW_CARDS_KIND", f"cards are exported for npc_verification reviews only, not {manifest.kind.value}")
    known = {item.item_id for item in items}
    if item_ids:
        unknown = sorted(set(item_ids) - known)
        if unknown:
            raise _refuse("REVIEW_INVALID_SELECTION", f"not items of {manifest.review_id}: {', '.join(unknown)}")
    wanted = set(item_ids or ())
    candidates = []
    for item in items:
        if wanted and item.item_id not in wanted:
            continue
        if actions and item.proposed_action.action not in actions:
            continue
        latest = delegated._latest(events, item.item_id)
        if delegated._current_decision(latest, item, stale) and latest.get("verdict") in ("approve", "reject"):
            continue
        if (item.proposed_action.action, "approve") not in DISPOSITION_FOR:
            raise _refuse("REVIEW_CARDS_ACTION_UNKNOWN",
                          f"item {item.item_id} has action {item.proposed_action.action!r}, which has no card verdict mapping")
        candidates.append(item)

    def order(item):
        return (_draft_stem(item), item.proposed_action.action == SIGNOFF_ACTION, item.locator.display_line or 0, item.item_id)

    built: list[Card] = []
    used: set[str] = set()
    for noise_class in noise.CLASSES:
        members = sorted(delegated._noise_members(candidates, noise_class), key=order)
        if members:
            built.append(_noise_card(noise_class, members, events, stale))
            used.update(item.item_id for item in members)
    skipped: list[dict] = []
    for item in sorted((i for i in candidates if i.item_id not in used), key=order):
        if item.proposed_action.action == SIGNOFF_ACTION:
            blocker = delegated.npc_signoff_blocker(root, item)
            if blocker is not None:
                skipped.append({"itemId": item.item_id, "npc": _who(item), "code": blocker[0], "message": blocker[1]})
                continue
            built.append(_signoff_card(root, item, events, stale))
        else:
            built.append(_finding_card(item, events, stale))
    seen_members: dict[str, str] = {}
    seen_cards: set[str] = set()
    for card in built:
        if card.id in seen_cards:
            raise _refuse("REVIEW_CARDS_DUPLICATE_MEMBER", f"card id {card.id} appears twice",
                          detail={"itemId": card.id, "cards": [card.id]})
        seen_cards.add(card.id)
        for member in card.members:
            if member.item_id in seen_members:
                raise _refuse("REVIEW_CARDS_DUPLICATE_MEMBER", f"item {member.item_id} is in two cards",
                              detail={"itemId": member.item_id, "cards": [seen_members[member.item_id], card.id]})
            seen_members[member.item_id] = card.id
    if not built:
        raise _refuse("REVIEW_CARDS_NOTHING_TO_EXPORT", "no undecided items to offer", detail={"skippedSignoffs": skipped})
    body = {
        "schemaVersion": SCHEMA_VERSION, "reviewId": manifest.review_id, "reviewKind": manifest.kind.value,
        "generation": manifest.generation, "cards": [card.model_dump(by_alias=True, mode="json") for card in built],
    }
    packet = {**body, "packetId": packet_id_for(body)}
    CardPacket.model_validate(packet)
    return packet, skipped


def _packets_dir(root: Path, review_id: str) -> Path:
    from pipelines.summary_native.review.store import _review_dir
    return _review_dir(root, review_id) / "packets"


def export_packet(root: Path, review_id: str, *, item_ids: list[str] | None = None,
                  actions: list[str] | None = None, out: Path | None = None) -> dict:
    """Build, store (one journaled create under the exclusive lock) and report a packet."""
    from pipelines.summary_native.authority import sha256_bytes
    from pipelines.summary_native.authority_apply import (
        TransactionTarget, _prepare_transaction_locked, authority_lock, recover_transaction,
        require_no_pending_transaction)
    from pipelines.summary_native.review.store import _reject_symlinks, read_review_state

    root = Path(root).resolve()
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        snapshot = read_review_state(root, review_id, _already_locked=True)
        packet, skipped = build_packet(root, review_id, item_ids=item_ids, actions=actions, snapshot=snapshot)
        data = canonical_bytes(packet)
        path = _reject_symlinks(root, _packets_dir(root, review_id) / f"{packet['packetId']}.json")
        reused = path.exists()
        if reused:
            if path.read_bytes() != data:
                raise _refuse("REVIEW_CARDS_PACKET_CONFLICT",
                              f"a different packet is already stored as {packet['packetId']}")
        else:
            journal = _prepare_transaction_locked(
                root, proposal_id=f"review-cards-export-{packet['packetId']}", proposal_sha256=sha256_bytes(data),
                targets=[TransactionTarget.create(path, data)])
            recover_transaction(root, journal["id"], _already_locked=True)
    if out is not None:
        from campaignlib.util import atomic_write_bytes
        atomic_write_bytes(Path(out), data)
    by_kind = {"finding": 0, "noise_class": 0, "signoff": 0}
    for card in packet["cards"]:
        by_kind[card["kind"]] += 1
    return {
        "packetId": packet["packetId"], "reviewId": packet["reviewId"], "generation": packet["generation"],
        "path": path.relative_to(root).as_posix(), "cards": len(packet["cards"]),
        "members": sum(len(c["members"]) for c in packet["cards"]), "byKind": by_kind,
        "skippedSignoffs": skipped, "reused": reused,
    }


def load_packet(root: Path, review_id: str, packet_id: str) -> CardPacket:
    from pipelines.summary_native.review.models import ReviewModelError, parse_json_strict
    from pipelines.summary_native.review.store import _reject_symlinks
    import re as _re

    root = Path(root).resolve()
    if not _re.fullmatch(r"packet-[0-9a-f]{20}", str(packet_id)):
        raise _refuse("REVIEW_CARDS_PACKET_UNKNOWN", f"no packet {packet_id!r} in review {review_id}")
    path = _reject_symlinks(root, _packets_dir(root, review_id) / f"{packet_id}.json")
    if not path.is_file():
        raise _refuse("REVIEW_CARDS_PACKET_UNKNOWN", f"no packet {packet_id} in review {review_id}")
    try:
        raw = parse_json_strict(path.read_bytes())
        if not isinstance(raw, dict) or raw.get("packetId") != packet_id:
            raise ValueError("packetId differs from its file name")
        body = {k: v for k, v in raw.items() if k != "packetId"}
        if packet_id_for(body) != packet_id:
            raise ValueError("content no longer hashes to its id")
        packet = CardPacket.model_validate(raw)
    except (ValueError, ReviewModelError) as exc:
        raise _refuse("REVIEW_CARDS_PACKET_ALTERED", f"stored packet {packet_id} was altered: {exc}") from exc
    if packet.review_id != review_id:
        raise _refuse("REVIEW_CARDS_REVIEW_MISMATCH",
                      f"packet {packet_id} belongs to review {packet.review_id}, not {review_id}")
    return packet


def parse_decisions(raw: bytes, *, max_note_chars: int) -> CardDecisions:
    from pydantic import ValidationError
    from pipelines.summary_native.review.models import ReviewModelError, parse_json_strict

    try:
        value = parse_json_strict(raw)
    except (ValueError, ReviewModelError) as exc:
        raise _refuse("REVIEW_CARDS_INVALID", f"decisions file is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise _refuse("REVIEW_CARDS_INVALID", "decisions file must be a JSON object")
    version = value.get("schemaVersion")
    if isinstance(version, bool) or version not in ACCEPTED_SCHEMA_VERSIONS:
        accepted = ", ".join(str(v) for v in sorted(ACCEPTED_SCHEMA_VERSIONS))
        raise _refuse("REVIEW_CARDS_SCHEMA", f"schemaVersion {version!r} is not accepted; accepted: [{accepted}]")
    try:
        parsed = CardDecisions.model_validate(value)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first["loc"])
        raise _refuse("REVIEW_CARDS_INVALID", f"{field}: {first['msg']}") from exc
    for card_id, verdict in parsed.cards.items():
        if len(card_note(card_id, verdict.note)) > max_note_chars:
            raise _refuse("REVIEW_CARDS_NOTE_TOO_LONG",
                          f"the note on card {card_id} is too long once prefixed; the limit is {max_note_chars} characters")
    return parsed


def _offenders(code: str, text: str, cards_: list[str]):
    return _refuse(code, f"{text}: {', '.join(cards_)}", detail={"cards": cards_})


def pack_batches(card_decisions: list[list[dict]], cap: int) -> list[list[dict]]:
    """Greedy, card-aligned packing.  A card is split only when it alone exceeds ``cap``."""
    batches: list[list[dict]] = []
    current: list[dict] = []
    for group in card_decisions:
        if not group:
            continue
        if len(group) > cap:
            if current:
                batches.append(current)
                current = []
            batches.extend(group[start:start + cap] for start in range(0, len(group), cap))
            continue
        if len(current) + len(group) > cap:
            batches.append(current)
            current = []
        current.extend(group)
    if current:
        batches.append(current)
    return batches


def _refused_members(card: Card) -> list[dict]:
    """A refused card still names every item that was NOT recorded (the GM must see them)."""
    return [{"itemId": m.item_id, "category": "refused", "disposition": None, "previous": None, "decision": None}
            for m in card.members]


def plan_decide(root: Path, review_id: str, decisions: CardDecisions) -> dict:
    """Expand a decisions file from the STORED packet into a DecisionPlan (a dict, camelCase).  Writes nothing."""
    from pipelines.summary_native.review import custody, delegated
    from pipelines.summary_native.review.store import read_review_state, read_snapshot

    root = Path(root).resolve()
    snapshot = read_review_state(root, review_id)
    manifest, live_items, _events, _stale = snapshot
    packet = load_packet(root, review_id, decisions.packet_id)
    if decisions.review_id != packet.review_id:
        raise _refuse("REVIEW_CARDS_REVIEW_MISMATCH",
                      f"the decisions file names review {decisions.review_id}, the packet is for {packet.review_id}")
    if packet.generation != manifest.generation:
        raise _refuse("REVIEW_CARDS_PACKET_STALE",
                      f"packet {packet.packet_id} is for generation {packet.generation}, the review is at "
                      f"{manifest.generation}; export a new packet: summary_native review cards export {review_id}")
    by_card = {card.id: card for card in packet.cards}
    unknown = sorted(set(decisions.cards) - set(by_card))
    if unknown:
        raise _offenders("REVIEW_CARDS_UNKNOWN_CARD", "cards that are not in the packet", unknown)
    bad_members = sorted(
        cid for cid, verdict in decisions.cards.items()
        if sorted(verdict.members) != sorted(m.item_id for m in by_card[cid].members))
    if bad_members:
        raise _offenders("REVIEW_CARDS_MEMBER_MISMATCH", "the echoed members differ from the packet's", bad_members)
    bad_prints = sorted(cid for cid, verdict in decisions.cards.items()
                        if verdict.draft_sha256 != by_card[cid].draft_sha256)
    if bad_prints:
        raise _offenders("REVIEW_CARDS_FINGERPRINT_MISMATCH",
                         "the echoed draft fingerprint differs from the packet's", bad_prints)

    live = {item.item_id: item for item in live_items}
    planned: dict[str, dict] = {}
    for card in packet.cards:
        entry = {"cardId": card.id, "verdict": None, "state": "unmarked", "refusal": None, "members": []}
        planned[card.id] = entry
        verdict_entry = decisions.cards.get(card.id)
        if verdict_entry is None:
            continue
        verdict = verdict_entry.verdict
        entry["verdict"] = verdict

        def refuse(code, message, data=None):
            entry.update(state="refused", refusal={"code": code, "message": message, "data": data},
                         members=_refused_members(card))

        moved = [m.item_id for m in card.members
                 if m.item_id not in live or live[m.item_id].revision != m.item_revision
                 or live[m.item_id].review_digest != m.review_digest]
        if moved:
            refuse("REVIEW_CARDS_MEMBER_STALE", "an item changed since the packet was exported; export a new packet",
                   {"items": moved})
            continue
        if card.kind == "signoff" and verdict == "approve":
            signoff_item = live[card.members[0].item_id]
            blocker = delegated.npc_signoff_blocker(root, signoff_item)
            if blocker is not None:
                draft_path = signoff_item.proposed_action.details.get("draft_path")
                refuse(blocker[0], f"{blocker[1]} ({draft_path})" if draft_path else blocker[1],
                       {"items": [signoff_item.item_id], "draftPath": draft_path})
                continue
        expansion = expand(
            snapshot, member_ids=[m.item_id for m in card.members], verdict=verdict,
            disposition_for=lambda item, v=verdict: DISPOSITION_FOR[(item.proposed_action.action, v)],
            gm_note=card_note(card.id, verdict_entry.note))
        entry["state"] = "applied"
        for member in expansion.members:
            category = {"new": "record", "identical": "noop", "differs": "supersede"}[member.category]
            entry["members"].append({
                "itemId": member.item_id, "category": category, "disposition": member.decision["disposition"],
                "previous": member.previous, "decision": None if category == "noop" else member.decision})

    # Spec 042: a card with a stale source never reaches the store; the rest of the file proceeds.
    writing = [m["itemId"] for e in planned.values() if e["state"] == "applied"
               for m in e["members"] if m["category"] != "noop"]
    if writing:
        _manifest, custody_gen, snap_items = read_snapshot(root, review_id)
        probe = custody.disk_probe(root)
        report = custody.stale_report(manifest.kind, custody_gen, snap_items, writing, probe)
        if report.stale:
            for entry in planned.values():
                ids = [m["itemId"] for m in entry["members"] if m["category"] != "noop"]
                if entry["state"] != "applied" or not any(i in report.stale for i in ids):
                    continue
                own = custody.stale_report(manifest.kind, custody_gen, snap_items, ids, probe)
                entry.update(
                    state="refused", members=_refused_members(by_card[entry["cardId"]]),
                    refusal={"code": "REVIEW_STALE_CUSTODY", "message": custody.refusal_message(own, "decide"),
                             "data": custody.refusal_detail(
                                 own, review_id=review_id, generation=manifest.generation, operation="decide",
                                 items=snap_items)})
    counts = {"record": 0, "supersede": 0, "noop": 0, "unmarked": 0, "refused": 0}
    cards_out = []
    for card in packet.cards:
        entry = planned[card.id]
        if entry["state"] == "unmarked":
            counts["unmarked"] += 1
        elif entry["state"] == "refused":
            counts["refused"] += len(card.members)
        else:
            for member in entry["members"]:
                counts[member["category"]] += 1
        cards_out.append(entry)
    plan_sha = hashlib.sha256(canonical_bytes(cards_out)).hexdigest()
    return {"reviewId": review_id, "packetId": packet.packet_id, "generation": packet.generation,
            "planSha256": plan_sha, "cards": cards_out, "counts": counts}


def apply_decide(root: Path, review_id: str, decisions: CardDecisions, *, reviewer: str, plan_sha256: str) -> dict:
    """Rebuild the plan, require it to be the one the GM saw, and record exactly that."""
    from campaignlib.review_config import load_campaign_review_config
    from pipelines.summary_native.review import delegated

    root = Path(root).resolve()
    plan = plan_decide(root, review_id, decisions)
    if plan["planSha256"] != plan_sha256:
        raise _refuse("REVIEW_CARDS_PLAN_CHANGED",
                      "the plan differs from the one confirmed (the review changed after the dry run); "
                      "run the dry run again and confirm the new plan", detail=plan)
    groups = [[m["decision"] for m in card["members"] if m["category"] != "noop"]
              for card in plan["cards"] if card["state"] == "applied"]
    groups = [g for g in groups if g]
    if not groups:
        return {**plan, "saved": []}
    cap = load_campaign_review_config(root).max_batch_decisions
    batches = pack_batches(groups, cap)
    saved = delegated.submit_decisions(
        root, review_id, generation=plan["generation"], reviewer=reviewer,
        decisions=[d for batch in batches for d in batch], prefix=f"cards-{plan['packetId']}", batches=batches)
    return {**plan, "saved": saved}
