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
    body: str
    approve_means: str
    reject_means: str
    evidence: tuple[EvidenceRow, ...] = ()
    members: tuple[Member, ...] = Field(min_length=1)
    draft_sha256: str | None = None


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
    category: Literal["record", "supersede", "noop"]
    disposition: str
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
