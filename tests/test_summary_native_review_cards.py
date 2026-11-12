"""Review card contract (spec 043): the shared expansion rule, ids, notes and published schemas."""

from __future__ import annotations

import json

import pytest

from pipelines.summary_native.review import cards, delegated
from pipelines.summary_native.review.store import ReviewStoreError, read_review_state
from tests.test_summary_native_review_delegated import (  # noqa: F401  (campaign is a fixture)
    _create, _decide, _item, campaign)


def _snapshot(root, review_id):
    return read_review_state(root, review_id)


def _setup(campaign):
    root, cid, summary_sha, _draft_sha, sources = campaign
    items = [_item(cid, "cards-review", f"m-{n}", summary_sha=summary_sha) for n in range(4)]
    _create(root, cid, "cards-review", items, sources)
    return root, items


def test_expand_classifies_new_identical_and_differs(campaign):
    root, items = _setup(campaign)
    note = cards.card_note("c1", "fine")
    # m-1: identical fresh decision; m-2: fresh but different; m-0 and m-3: none.
    _decide_with_note(root, items[1], "approve", "accept_no_change", note, "r1")
    _decide_with_note(root, items[2], "reject", "reject_action", "other", "r2")
    result = cards.expand(
        _snapshot(root, "cards-review"), member_ids=[i.item_id for i in items], verdict="approve",
        disposition_for=lambda item: cards.DISPOSITION_FOR[(item.proposed_action.action, "approve")],
        gm_note=note)
    categories = {m.item_id: m.category for m in result.members}
    assert categories == {"m-0": "new", "m-1": "identical", "m-2": "differs", "m-3": "new"}
    by_id = {m.item_id: m for m in result.members}
    assert by_id["m-2"].previous["verdict"] == "reject"
    assert by_id["m-0"].previous is None
    events = _snapshot(root, "cards-review")[2]
    for member in result.members:
        assert member.decision["expected_decision_revision"] == delegated._active_revision(events, member.item_id)
    assert by_id["m-2"].decision["expected_decision_revision"] == 1


def test_expand_refuses_a_disallowed_pair(campaign):
    root, items = _setup(campaign)
    with pytest.raises(ReviewStoreError) as caught:
        cards.expand(_snapshot(root, "cards-review"), member_ids=["m-0"], verdict="approve",
                     disposition_for=lambda item: "reject_action", gm_note="x")
    assert caught.value.code == "REVIEW_ACTION_MISMATCH"


def _decide_with_note(root, item, verdict, disposition, note, request):
    from pipelines.summary_native.review.store import save_decisions
    save_decisions(root, "cards-review", {
        "version": 1, "request_id": request, "review_generation": 1, "reviewer": "GM",
        "decisions": [{"item_id": item.item_id, "item_revision": item.revision,
                       "review_digest": item.review_digest, "expected_decision_revision": 0,
                       "verdict": verdict, "disposition": disposition, "note": note}]})


def test_card_note_and_packet_id_are_stable():
    assert cards.card_note("c1", "") == "GM card verdict [c1]"
    assert cards.card_note("c1", " hi ") == "GM card verdict [c1]: hi"
    body = {"packetId": "ignored", "reviewId": "r", "cards": []}
    assert cards.packet_id_for(body) == cards.packet_id_for({**body, "packetId": "other"})
    assert cards.packet_id_for(body).startswith("packet-") and len(cards.packet_id_for(body)) == 27


def test_disposition_map_matches_r4():
    assert cards.DISPOSITION_FOR[("signoff_npc_draft", "approve")] == "document_signoff"
    assert cards.DISPOSITION_FOR[("review_claim_against_evidence", "approve")] == "accept_no_change"
    assert cards.DISPOSITION_FOR[("review_classified_noise", "reject")] == "reject_action"
    assert cards.DISPOSITION_FOR[("signoff_npc_draft", "discuss")] == "defer"


def test_models_are_strict_and_camel_cased():
    with pytest.raises(Exception):
        cards.CardVerdict.model_validate({"verdict": "approve", "members": [], "extra": 1})
    parsed = cards.CardVerdict.model_validate({"verdict": "approve", "members": ["a"], "draftSha256": "x"})
    assert parsed.draft_sha256 == "x"
    assert "draftSha256" in parsed.model_dump(by_alias=True)


def test_checked_in_schemas_match_the_models():
    for name, text in cards.schema_files().items():
        assert (cards.schemas_dir() / name).read_text(encoding="utf-8") == text, name
        json.loads(text)
