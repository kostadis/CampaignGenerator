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


# =====================================================================================
# User Story 1 (spec 043): export a packet, plan a decisions file, write exactly the plan
# =====================================================================================

import hashlib  # noqa: E402

from pipelines.summary_native.review.models import canonical_bytes  # noqa: E402
from tests import _custody_fixture as custody_fx  # noqa: E402
from tests.conftest_npc import run_cli, sha_tree  # noqa: E402
from tests.test_summary_native_review_delegated import _events  # noqa: E402,F401
from tests.test_summary_native_review_noise_cli import RID, _noise_item  # noqa: E402


@pytest.fixture
def noise_cards(campaign):
    """label x3 (one class), idiom x1 (another class), one plain finding."""
    root, cid, summary_sha, _d, sources = campaign
    items = {
        "label-1": _noise_item(cid, "label-1", "label", summary_sha=summary_sha),
        "label-2": _noise_item(cid, "label-2", "label", summary_sha=summary_sha, npc=None),
        "label-3": _noise_item(cid, "label-3", "label", summary_sha=summary_sha),
        "idiom-1": _noise_item(cid, "idiom-1", "idiom", summary_sha=summary_sha),
        "mixed": _noise_item(cid, "mixed", "label", summary_sha=summary_sha, extra_code="number-inconsistency"),
    }
    _create(root, cid, RID, list(items.values()), sources)
    return root, items


def _cli(root, *args):
    rc, out, err = run_cli([*args, "--campaign-dir", str(root), "--json"])
    try:
        return rc, json.loads(out)
    except json.JSONDecodeError:
        raise AssertionError(f"not JSON ({rc}): {out!r} {err!r}")


def _export(root, review, *extra):
    return _cli(root, "review", "cards", "export", review, *extra)


def _load_packet(root, review, packet_id):
    return json.loads((root / "docs/reviews" / review / "packets" / f"{packet_id}.json").read_text(encoding="utf-8"))


def _decisions(root, packet, marks, *, name="decisions.json", **overrides):
    """A page-shaped decisions file from ``{card_id: (verdict, note)}``, echoing the packet's members."""
    by_id = {c["id"]: c for c in packet["cards"]}
    body = {"schemaVersion": 1, "packetId": packet["packetId"], "reviewId": packet["reviewId"],
            "savedAt": "2026-11-12T21:04:00Z", "cards": {}}
    for card_id, (verdict, note) in marks.items():
        entry = {"verdict": verdict, "note": note, "members": [m["itemId"] for m in by_id[card_id]["members"]]}
        if by_id[card_id]["draftSha256"]:
            entry["draftSha256"] = by_id[card_id]["draftSha256"]
        body["cards"][card_id] = entry
    body.update(overrides)
    path = root / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _decide_cmd(root, review, path, *extra, reviewer="GM"):
    return _cli(root, "review", "cards", "decide", review, "--decisions", str(path), "--reviewer", reviewer, *extra)


def _plan_then_write(root, review, path):
    rc, plan = _decide_cmd(root, review, path)
    assert rc == 0 and plan["code"] == "REVIEW_CARDS_PLAN", plan
    return plan, _decide_cmd(root, review, path, "--write", "--plan-sha256", plan["data"]["planSha256"])


def _tree(root, review):
    return sha_tree(root / "docs" / "reviews" / review)


def test_us1_s1_export_stores_packet_with_members_excluding_decided(tmp_path):
    fx = custody_fx.build(tmp_path)
    decided = fx.findings("a")[0]
    rc, _ = fx.decide([decided])
    assert rc == 0
    rc, env = _export(fx.root, fx.review_id)
    assert rc == 0 and env["code"] == "REVIEW_CARDS_EXPORTED", env
    data = env["data"]
    assert data["reused"] is False
    packet = _load_packet(fx.root, fx.review_id, data["packetId"])
    assert data["path"].endswith(f"packets/{data['packetId']}.json") and not data["path"].startswith("/")
    body = {k: v for k, v in packet.items() if k != "packetId"}
    assert packet["packetId"] == cards.packet_id_for(body)
    assert packet["generation"] == fx.generation and packet["reviewId"] == fx.review_id
    assert all(card["members"] for card in packet["cards"])
    member_ids = {m["itemId"] for card in packet["cards"] for m in card["members"]}
    assert decided.item_id not in member_ids
    assert fx.findings("b")[0].item_id in member_ids
    signoffs = [c for c in packet["cards"] if c["kind"] == "signoff"]
    assert len(signoffs) == 4 and all(len(c["draftSha256"]) == 64 for c in signoffs)
    # FR-004: no verdict, guess or recommendation anywhere in the packet.
    forbidden = {"verdict", "guess", "recommendation", "recommended", "suggestion"}
    def keys(value):
        if isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from keys(v)
        elif isinstance(value, list):
            for v in value:
                yield from keys(v)
    assert not forbidden & set(keys(packet))
    # No absolute machine path and no HTML escaping by CampaignGenerator.
    text = json.dumps(packet)
    assert str(fx.root) not in text
    assert "&amp;" not in text and "&lt;" not in text
    # Re-export of identical content is a reuse.
    rc, again = _export(fx.root, fx.review_id)
    assert again["data"]["packetId"] == data["packetId"] and again["data"]["reused"] is True


def test_us1_export_out_copy_is_byte_identical_and_filters_narrow(tmp_path):
    fx = custody_fx.build(tmp_path)
    out = tmp_path / "kit-packet.json"
    rc, env = _export(fx.root, fx.review_id, "--action", "signoff_npc_draft", "--out", str(out))
    assert rc == 0, env
    stored = fx.root / env["data"]["path"]
    assert out.read_bytes() == stored.read_bytes()
    assert env["data"]["byKind"] == {"finding": 0, "noise_class": 0, "signoff": 4}
    assert str(out) in env["artifacts"]
    rc, env = _export(fx.root, fx.review_id, "--item", "no-such-item")
    assert rc == 2 and not env["ok"]


def test_us1_export_nothing_and_wrong_kind_refuse(tmp_path):
    fx = custody_fx.build(tmp_path)
    rc, env = _export(fx.root, fx.review_id, "--action", "review_supersession")
    assert rc == 2 and env["code"] == "REVIEW_CARDS_NOTHING_TO_EXPORT"
    assert not (fx.root / "docs/reviews" / fx.review_id / "packets").exists()


def test_us1_s2_plan_lists_four_records_one_unmarked_writes_nothing(noise_cards):
    root, _items = noise_cards
    rc, env = _export(root, RID)
    packet = _load_packet(root, RID, env["data"]["packetId"])
    ids = [c["id"] for c in packet["cards"]]
    assert ids == ["noise-class:label", "noise-class:idiom", "mixed"]
    path = _decisions(root, packet, {"noise-class:label": ("approve", "all fine"), "mixed": ("reject", "wrong")})
    before = _tree(root, RID)
    rc, plan = _decide_cmd(root, RID, path)
    assert rc == 0 and plan["code"] == "REVIEW_CARDS_PLAN"
    assert plan["data"]["counts"] == {"record": 4, "supersede": 0, "noop": 0, "unmarked": 1, "refused": 0}
    by_card = {c["cardId"]: c for c in plan["data"]["cards"]}
    assert by_card["noise-class:idiom"]["state"] == "unmarked" and by_card["noise-class:idiom"]["verdict"] is None
    assert _tree(root, RID) == before


def test_us1_s3_write_records_exactly_the_plan(noise_cards):
    root, items = noise_cards
    rc, env = _export(root, RID)
    pid = env["data"]["packetId"]
    packet = _load_packet(root, RID, pid)
    path = _decisions(root, packet, {"noise-class:label": ("approve", "all fine"), "mixed": ("reject", "wrong")})
    n_before = len(_events(root, RID))
    plan, (rc, saved) = _plan_then_write(root, RID, path)
    assert rc == 0 and saved["code"] == "REVIEW_CARDS_SAVED", saved
    new = _events(root, RID)
    assert len(new) == n_before + 4
    recorded = {e["item_id"]: e for e in new}
    assert set(recorded) == {"label-1", "label-2", "label-3", "mixed"}
    for item_id in ("label-1", "label-2", "label-3"):
        event = recorded[item_id]
        assert event["verdict"] == "approve"
        assert event["disposition"] == cards.DISPOSITION_FOR[("review_classified_noise", "approve")]
        assert event["note"] == cards.card_note("noise-class:label", "all fine")
        assert event["request_id"].startswith(f"cards-{pid}-")
        assert event["reviewer"] == "GM"
    assert recorded["mixed"]["verdict"] == "reject" and recorded["mixed"]["disposition"] == "reject_action"
    assert recorded["mixed"]["note"] == cards.card_note("mixed", "wrong")
    assert "idiom-1" not in recorded
    assert saved["data"]["planSha256"] == plan["data"]["planSha256"] and saved["data"]["saved"]
    # SC-003: re-applying the same file records nothing and is not an error.
    n_after = len(_events(root, RID))
    plan2, (rc, saved2) = _plan_then_write(root, RID, path)
    assert plan2["data"]["counts"]["noop"] == 4 and plan2["data"]["counts"]["record"] == 0
    assert rc == 0 and saved2["data"]["saved"] == [] and len(_events(root, RID)) == n_after


def test_us1_s4_discuss_records_defer_with_note(noise_cards):
    root, _ = noise_cards
    rc, env = _export(root, RID)
    packet = _load_packet(root, RID, env["data"]["packetId"])
    path = _decisions(root, packet, {"mixed": ("discuss", "ask the GM")})
    _plan, (rc, saved) = _plan_then_write(root, RID, path)
    assert rc == 0
    (event,) = [e for e in _events(root, RID) if e["item_id"] == "mixed"]
    assert (event["verdict"], event["disposition"]) == ("discuss", "defer")
    assert event["note"] == cards.card_note("mixed", "ask the GM")


def test_us1_s5_partial_save_is_reported(noise_cards, monkeypatch):
    root, _ = noise_cards
    (root / "config" / "review.yaml").write_text("max_batch_decisions: 2\n", encoding="utf-8")
    rc, env = _export(root, RID)
    packet = _load_packet(root, RID, env["data"]["packetId"])
    path = _decisions(root, packet, {"noise-class:label": ("approve", ""), "mixed": ("reject", "")})
    rc, plan = _decide_cmd(root, RID, path)
    sha = plan["data"]["planSha256"]
    real = delegated.save_decisions
    calls = []

    def flaky(root_, review_, request, **kw):
        calls.append(request["request_id"])
        if len(calls) == 2:
            raise ReviewStoreError("REVIEW_STALE_DECISION: injected", "REVIEW_STALE_DECISION")
        return real(root_, review_, request, **kw)

    monkeypatch.setattr(delegated, "save_decisions", flaky)
    rc, env = _decide_cmd(root, RID, path, "--write", "--plan-sha256", sha)
    assert rc == 3 and env["code"] == "REVIEW_STALE_DECISION"
    on_disk = sorted(e["item_id"] for e in _events(root, RID))
    assert sorted(env["data"]["recorded"]) == on_disk and len(on_disk) == 2
    assert sorted(env["data"]["recorded"] + env["data"]["not_recorded"]) == ["label-1", "label-2", "label-3", "mixed"]
    monkeypatch.setattr(delegated, "save_decisions", real)
    rc, plan2 = _decide_cmd(root, RID, path)
    assert plan2["data"]["counts"]["noop"] == 2 and plan2["data"]["counts"]["record"] == 2
    rc, done = _decide_cmd(root, RID, path, "--write", "--plan-sha256", plan2["data"]["planSha256"])
    assert rc == 0
    assert sorted(e["item_id"] for e in _events(root, RID)) == ["label-1", "label-2", "label-3", "mixed"]


def test_us1_write_requires_plan_sha(noise_cards):
    root, _ = noise_cards
    rc, env = _export(root, RID)
    packet = _load_packet(root, RID, env["data"]["packetId"])
    path = _decisions(root, packet, {"mixed": ("approve", "")})
    before = _tree(root, RID)
    rc, env = _decide_cmd(root, RID, path, "--write")
    assert rc == 2 and env["code"] == "REVIEW_CARDS_PLAN_REQUIRED"
    rc, env = _decide_cmd(root, RID, path, reviewer="  ")
    assert rc == 2 and env["code"] == "REVIEW_INVALID_BATCH"
    assert _tree(root, RID) == before


def test_us1_plan_changed_refuses(noise_cards):
    root, items = noise_cards
    rc, env = _export(root, RID)
    packet = _load_packet(root, RID, env["data"]["packetId"])
    path = _decisions(root, packet, {"mixed": ("approve", "fine")})
    rc, plan = _decide_cmd(root, RID, path)
    sha = plan["data"]["planSha256"]
    from pipelines.summary_native.review.store import save_decisions
    item = items["mixed"]
    save_decisions(root, RID, {
        "version": 1, "request_id": "cli-between", "review_generation": 1, "reviewer": "Other",
        "decisions": [{"item_id": "mixed", "item_revision": item.revision, "review_digest": item.review_digest,
                       "expected_decision_revision": 0, "verdict": "reject", "disposition": "reject_action",
                       "note": "cli"}]})
    before = _tree(root, RID)
    rc, env = _decide_cmd(root, RID, path, "--write", "--plan-sha256", sha)
    assert rc == 5 and env["code"] == "REVIEW_CARDS_PLAN_CHANGED"
    assert env["data"]["planSha256"] != sha
    assert _tree(root, RID) == before
    # The new plan lists the CLI decision as a supersede, never silently overwritten.
    assert env["data"]["counts"]["supersede"] == 1


def test_us1_signoff_approve_records_document_signoff(tmp_path):
    fx = custody_fx.build(tmp_path)
    rc, env = _export(fx.root, fx.review_id, "--action", "signoff_npc_draft")
    packet = _load_packet(fx.root, fx.review_id, env["data"]["packetId"])
    by_npc = {c["npc"]: c["id"] for c in packet["cards"]}
    assert set(by_npc) == {"Aaa", "Bbb", "Ccc", "Ddd"}
    path = _decisions(fx.root, packet, {by_npc["Ccc"]: ("approve", "")})
    _plan, (rc, saved) = _plan_then_write(fx.root, fx.review_id, path)
    assert rc == 0, saved
    rc, signed = fx.sign("d")
    assert rc == 0
    events = {e["item_id"]: e for e in _events(fx.root, fx.review_id)}
    ours, theirs = events[fx.signoff("c").item_id], events[fx.signoff("d").item_id]
    skip = {"event_id", "item_id", "review_digest", "recorded_at", "note", "request_id", "authority_record_id"}
    assert {k: v for k, v in ours.items() if k not in skip} == {k: v for k, v in theirs.items() if k not in skip}
    assert ours["disposition"] == "document_signoff" and ours["request_id"].startswith("cards-")


def test_us1_cards_aligned_batches(noise_cards, monkeypatch):
    # Pure packing: a card is never split unless it alone exceeds the cap.
    two = [[{"i": 1}, {"i": 2}], [{"i": 3}, {"i": 4}]]
    assert cards.pack_batches(two, 3) == [two[0], two[1]]
    assert cards.pack_batches([[{"i": 1}], [{"i": 2}], [{"i": 3}]], 3) == [[{"i": 1}, {"i": 2}, {"i": 3}]]
    five = [[{"i": n} for n in range(5)]]
    assert [len(b) for b in cards.pack_batches(five, 3)] == [3, 2]
    assert cards.pack_batches([], 3) == []
    # End to end: cap 3, a 3-member card and a 1-member card, then 2 + 2.
    root, items = noise_cards
    (root / "config" / "review.yaml").write_text("max_batch_decisions: 3\n", encoding="utf-8")
    rc, env = _export(root, RID)
    packet = _load_packet(root, RID, env["data"]["packetId"])
    path = _decisions(root, packet, {"noise-class:label": ("approve", ""), "noise-class:idiom": ("approve", ""),
                                     "mixed": ("approve", "")})
    real = delegated.save_decisions
    sizes = []

    def counting(root_, review_, request, **kw):
        sizes.append([d["item_id"] for d in request["decisions"]])
        return real(root_, review_, request, **kw)

    monkeypatch.setattr(delegated, "save_decisions", counting)
    _plan, (rc, saved) = _plan_then_write(root, RID, path)
    assert rc == 0
    assert sorted(len(s) for s in sizes) == [2, 3]
    label = {"label-1", "label-2", "label-3"}
    assert any(set(s) == label for s in sizes)  # the 3-member card was not split


def test_us1_load_packet_refusals(noise_cards):
    root, _ = noise_cards
    rc, env = _export(root, RID)
    pid = env["data"]["packetId"]
    with pytest.raises(ReviewStoreError) as caught:
        cards.load_packet(root, RID, "packet-" + "0" * 20)
    assert caught.value.code == "REVIEW_CARDS_PACKET_UNKNOWN"
    path = root / "docs/reviews" / RID / "packets" / f"{pid}.json"
    path.write_bytes(path.read_bytes().replace(b"Classified noise", b"Classified n0ise"))
    with pytest.raises(ReviewStoreError) as caught:
        cards.load_packet(root, RID, pid)
    assert caught.value.code == "REVIEW_CARDS_PACKET_ALTERED"


def test_us1_parse_decisions_schema_and_note_limit():
    good = {"schemaVersion": 1, "packetId": "p", "reviewId": "r", "savedAt": "t", "cards": {}}
    assert cards.parse_decisions(json.dumps(good).encode(), max_note_chars=10).schema_version == 1
    with pytest.raises(ReviewStoreError) as caught:
        cards.parse_decisions(json.dumps({**good, "schemaVersion": 9}).encode(), max_note_chars=10)
    assert caught.value.code == "REVIEW_CARDS_SCHEMA" and "1" in str(caught.value)
    with pytest.raises(ReviewStoreError) as caught:
        cards.parse_decisions(json.dumps({**good, "reviewer": "x"}).encode(), max_note_chars=10)
    assert caught.value.code == "REVIEW_CARDS_INVALID"
    long_note = {**good, "cards": {"c": {"verdict": "approve", "note": "x" * 11, "members": ["a"]}}}
    with pytest.raises(ReviewStoreError) as caught:
        cards.parse_decisions(json.dumps(long_note).encode(), max_note_chars=10)
    assert caught.value.code == "REVIEW_CARDS_NOTE_TOO_LONG"
