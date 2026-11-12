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


def test_signoff_body_is_exact_draft_even_when_previously_discussed(tmp_path):
    fx = custody_fx.build(tmp_path)
    rc, env = _export(fx.root, fx.review_id, "--action", "signoff_npc_draft")
    packet = _load_packet(fx.root, fx.review_id, env["data"]["packetId"])
    by_npc = {c["npc"]: c for c in packet["cards"]}
    for npc in ("a", "c"):
        card = by_npc[npc.capitalize() + npc * 2]
        assert card["body"] == fx.draft(npc).read_text(encoding="utf-8")
        assert card["previousDiscussion"] is None
    card_c = by_npc["Ccc"]
    path = _decisions(fx.root, packet, {card_c["id"]: ("discuss", "check the quote")})
    _plan, (rc, _saved) = _plan_then_write(fx.root, fx.review_id, path)
    assert rc == 0
    rc, env = _export(fx.root, fx.review_id, "--action", "signoff_npc_draft")
    second = _load_packet(fx.root, fx.review_id, env["data"]["packetId"])
    again = {c["npc"]: c for c in second["cards"]}["Ccc"]
    assert again["body"].encode("utf-8") == fx.draft("c").read_bytes()  # verbatim: the draft, nothing prepended
    assert again["previousDiscussion"] == "Previously discussed by GM: check the quote"


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


# =====================================================================================
# User Story 2 (spec 043): nothing a page sends can record what CampaignGenerator cannot prove
# =====================================================================================

def _fx_packet(fx, *extra):
    rc, env = _export(fx.root, fx.review_id, *extra)
    assert rc == 0, env
    return _load_packet(fx.root, fx.review_id, env["data"]["packetId"])


def _refuses_whole_file(root, review, path, code, rc=2):
    """The dry run and the write both refuse with ``code`` and the review tree is byte-identical."""
    before = _tree(root, review)
    got, env = _decide_cmd(root, review, path)
    assert (got, env["code"]) == (rc, code), env
    got, env = _decide_cmd(root, review, path, "--write", "--plan-sha256", "0" * 64)
    assert (got, env["code"]) == (rc, code), env
    assert _tree(root, review) == before
    return env


def _by_card(plan):
    return {c["cardId"]: c for c in plan["data"]["cards"]}


def test_us2_s1_unknown_packet_refused(noise_cards):
    root, _ = noise_cards
    rc, env = _export(root, RID)
    packet = _load_packet(root, RID, env["data"]["packetId"])
    path = _decisions(root, packet, {"mixed": ("approve", "")}, packetId="packet-" + "0" * 20)
    _refuses_whole_file(root, RID, path, "REVIEW_CARDS_PACKET_UNKNOWN")


def test_us2_s2_review_id_mismatch_refused(noise_cards):
    root, _ = noise_cards
    rc, env = _export(root, RID)
    packet = _load_packet(root, RID, env["data"]["packetId"])
    path = _decisions(root, packet, {"mixed": ("approve", "")}, reviewId="some-other-review")
    _refuses_whole_file(root, RID, path, "REVIEW_CARDS_REVIEW_MISMATCH")


def test_us2_s3_unknown_card_named(noise_cards):
    root, _ = noise_cards
    rc, env = _export(root, RID)
    packet = _load_packet(root, RID, env["data"]["packetId"])
    path = _decisions(root, packet, {"mixed": ("approve", "")})
    body = json.loads(path.read_text(encoding="utf-8"))
    body["cards"]["ghost-2"] = {"verdict": "approve", "note": "", "members": ["x"]}
    body["cards"]["ghost-1"] = {"verdict": "reject", "note": "", "members": ["y"]}
    path.write_text(json.dumps(body), encoding="utf-8")
    env = _refuses_whole_file(root, RID, path, "REVIEW_CARDS_UNKNOWN_CARD")
    assert env["data"]["cards"] == ["ghost-1", "ghost-2"]
    assert "ghost-1" in env["message"] and "ghost-2" in env["message"]


def test_us2_s4_stale_generation_refused_with_export_remedy(tmp_path):
    fx = custody_fx.build(tmp_path)
    packet = _fx_packet(fx, "--action", "review_presentation")
    path = _decisions(fx.root, packet, {packet["cards"][0]["id"]: ("approve", "")})
    rc, env = fx.cli("review", "refresh", fx.review_id, "--expected-generation", str(fx.generation))
    assert rc == 0, env
    assert fx.snapshot()[0].generation != packet["generation"]
    env = _refuses_whole_file(fx.root, fx.review_id, path, "REVIEW_CARDS_PACKET_STALE", rc=3)
    assert "review cards export" in env["message"]


def test_us2_s5_signoff_draft_changed_refuses_that_card_only(tmp_path):
    fx = custody_fx.build(tmp_path)
    packet = _fx_packet(fx)
    sign_c, sign_d, find_b = fx.signoff("c").item_id, fx.signoff("d").item_id, fx.findings("b")[0].item_id
    path = _decisions(fx.root, packet, {sign_c: ("approve", ""), sign_d: ("approve", ""), find_b: ("approve", "")})
    fx.touch(fx.draft("c"))
    rc, plan = _decide_cmd(fx.root, fx.review_id, path)
    assert rc == 0, plan
    cards_ = _by_card(plan)
    refused = cards_[sign_c]
    assert refused["state"] == "refused" and refused["refusal"]["code"] == "REVIEW_NPC_SIGNOFF_STALE"
    assert "npc_c.md" in refused["refusal"]["message"]
    assert refused["members"] == [{"itemId": sign_c, "category": "refused", "disposition": None,
                                   "previous": None, "decision": None}]
    assert cards_[sign_d]["state"] == "applied" and cards_[find_b]["state"] == "applied"
    assert plan["data"]["counts"]["refused"] == 1 and plan["data"]["counts"]["record"] == 2
    n_before = len(_events(fx.root, fx.review_id))
    rc, saved = _decide_cmd(fx.root, fx.review_id, path, "--write", "--plan-sha256", plan["data"]["planSha256"])
    assert rc == 0, saved
    recorded = {e["item_id"] for e in _events(fx.root, fx.review_id)[n_before:]}
    assert recorded == {sign_d, find_b}


def test_us2_s5_signoff_echo_missing_or_different_refused(tmp_path):
    fx = custody_fx.build(tmp_path)
    packet = _fx_packet(fx, "--action", "signoff_npc_draft")
    sign = fx.signoff("c").item_id
    for bad in (None, "0" * 64):
        path = _decisions(fx.root, packet, {sign: ("approve", "")})
        body = json.loads(path.read_text(encoding="utf-8"))
        if bad is None:
            del body["cards"][sign]["draftSha256"]
        else:
            body["cards"][sign]["draftSha256"] = bad
        path.write_text(json.dumps(body), encoding="utf-8")
        env = _refuses_whole_file(fx.root, fx.review_id, path, "REVIEW_CARDS_FINGERPRINT_MISMATCH")
        assert env["data"]["cards"] == [sign]


def test_us2_s6_packet_has_no_verdict_and_unmarked_records_nothing(tmp_path):
    fx = custody_fx.build(tmp_path)
    packet = _fx_packet(fx)
    forbidden = {"verdict", "guess", "decision", "recommendation"}

    def keys(value):
        if isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from keys(v)
        elif isinstance(value, list):
            for v in value:
                yield from keys(v)

    assert not forbidden & set(keys(packet))
    path = _decisions(fx.root, packet, {})
    before = _tree(fx.root, fx.review_id)
    n_before = len(_events(fx.root, fx.review_id))
    rc, plan = _decide_cmd(fx.root, fx.review_id, path)
    assert rc == 0 and plan["data"]["counts"]["unmarked"] == len(packet["cards"])
    assert all(c["state"] == "unmarked" and c["verdict"] is None for c in plan["data"]["cards"])
    rc, saved = _decide_cmd(fx.root, fx.review_id, path, "--write", "--plan-sha256", plan["data"]["planSha256"])
    assert rc == 0 and saved["data"]["saved"] == []
    assert _tree(fx.root, fx.review_id) == before and len(_events(fx.root, fx.review_id)) == n_before


def test_us2_s7_disallowed_pair_refused_on_every_path(tmp_path, monkeypatch):
    fx = custody_fx.build(tmp_path)
    finding, signoff = fx.findings("a")[0], fx.signoff("a")
    # review decide: a finding cannot take document_signoff, and a sign-off cannot take accept_no_change.
    before = fx.review_tree_sha()
    rc, env = fx.decide([finding], verdict="approve", disposition="document_signoff")
    assert rc != 0 and env["code"] == "REVIEW_ACTION_MISMATCH", env
    rc, env = fx.decide([signoff], verdict="approve", disposition="accept_no_change")
    assert rc != 0 and env["code"] == "REVIEW_ACTION_MISMATCH", env
    assert fx.review_tree_sha() == before
    # review npc sign: signing a finding item is not a sign-off.
    digest = hashlib.sha256(fx.draft("a").read_bytes()).hexdigest()
    rc, env = fx.cli("review", "npc", "sign", fx.review_id, "--item", finding.item_id, "--draft-sha256", digest,
                     "--expected-decision-revision", "0", "--reviewer", "GM")
    assert rc != 0 and not env["ok"], env
    assert fx.review_tree_sha() == before
    # cards decide: a wrong pair out of DISPOSITION_FOR is refused by the store's table, not trusted.
    packet = _fx_packet(fx, "--action", finding.proposed_action.action)
    card_id = next(c["id"] for c in packet["cards"] if finding.item_id in [m["itemId"] for m in c["members"]])
    path = _decisions(fx.root, packet, {card_id: ("approve", "")})
    monkeypatch.setitem(cards.DISPOSITION_FOR, (finding.proposed_action.action, "approve"), "document_signoff")
    _refuses_whole_file(fx.root, fx.review_id, path, "REVIEW_ACTION_MISMATCH")


def test_us2_member_echo_mismatch_refused(noise_cards):
    root, _ = noise_cards
    rc, env = _export(root, RID)
    packet = _load_packet(root, RID, env["data"]["packetId"])
    path = _decisions(root, packet, {"noise-class:label": ("approve", ""), "mixed": ("approve", "")})
    body = json.loads(path.read_text(encoding="utf-8"))
    body["cards"]["noise-class:label"]["members"] = ["label-1", "label-2"]
    path.write_text(json.dumps(body), encoding="utf-8")
    env = _refuses_whole_file(root, RID, path, "REVIEW_CARDS_MEMBER_MISMATCH")
    assert env["data"]["cards"] == ["noise-class:label"]
    body["cards"]["noise-class:label"]["members"] = ["label-1", "label-2", "label-3", "mixed"]
    path.write_text(json.dumps(body), encoding="utf-8")
    _refuses_whole_file(root, RID, path, "REVIEW_CARDS_MEMBER_MISMATCH")


def test_us2_altered_packet_refused(noise_cards):
    root, _ = noise_cards
    rc, env = _export(root, RID)
    pid = env["data"]["packetId"]
    packet = _load_packet(root, RID, pid)
    path = _decisions(root, packet, {"mixed": ("approve", "")})
    stored = root / "docs/reviews" / RID / "packets" / f"{pid}.json"
    stored.write_bytes(stored.read_bytes().replace(b"Classified noise", b"Classified n0ise"))
    _refuses_whole_file(root, RID, path, "REVIEW_CARDS_PACKET_ALTERED")


def test_us2_member_item_moved_refused_per_card(tmp_path, monkeypatch):
    fx = custody_fx.build(tmp_path)
    packet = _fx_packet(fx, "--action", "review_presentation")
    a_item, b_item = fx.findings("a")[0], fx.findings("b")[0]
    path = _decisions(fx.root, packet, {a_item.item_id: ("approve", ""), b_item.item_id: ("approve", "")})
    # An item staged at a new revision without a generation move cannot be made through the store
    # (a stage bumps the generation, which refuses the whole packet first), so present the moved item
    # to the planner exactly as read_review_state would return it after such a revision.
    from pipelines.summary_native.review import store
    real = store.read_review_state

    def moved(root, review_id, **kw):
        manifest, items, events, stale = real(root, review_id, **kw)
        return manifest, tuple(i.model_copy(update={"revision": i.revision + 1}) if i.item_id == a_item.item_id else i
                               for i in items), events, stale

    monkeypatch.setattr(store, "read_review_state", moved)
    before = _tree(fx.root, fx.review_id)
    rc, plan = _decide_cmd(fx.root, fx.review_id, path)
    assert rc == 0, plan
    cards_ = _by_card(plan)
    assert cards_[a_item.item_id]["state"] == "refused"
    assert cards_[a_item.item_id]["refusal"]["code"] == "REVIEW_CARDS_MEMBER_STALE"
    assert cards_[a_item.item_id]["refusal"]["data"] == {"items": [a_item.item_id]}
    assert [(m["itemId"], m["category"]) for m in cards_[a_item.item_id]["members"]] == [(a_item.item_id, "refused")]
    assert cards_[b_item.item_id]["state"] == "applied"
    assert plan["data"]["counts"]["refused"] == 1 and plan["data"]["counts"]["record"] == 1
    assert _tree(fx.root, fx.review_id) == before


def test_us2_custody_stale_refused_per_card(tmp_path):
    fx = custody_fx.build(tmp_path)
    packet = _fx_packet(fx, "--action", "review_presentation")
    a_item, b_item = fx.findings("a")[0], fx.findings("b")[0]
    path = _decisions(fx.root, packet, {a_item.item_id: ("approve", ""), b_item.item_id: ("approve", "")})
    fx.touch(fx.evidence("a"))
    rc, plan = _decide_cmd(fx.root, fx.review_id, path)
    assert rc == 0, plan
    cards_ = _by_card(plan)
    assert cards_[a_item.item_id]["state"] == "refused"
    assert cards_[a_item.item_id]["refusal"]["code"] == "REVIEW_STALE_CUSTODY"
    assert cards_[a_item.item_id]["refusal"]["data"]["stale_items"][0]["item_id"] == a_item.item_id
    assert [(m["itemId"], m["category"]) for m in cards_[a_item.item_id]["members"]] == [(a_item.item_id, "refused")]
    assert cards_[b_item.item_id]["state"] == "applied"
    assert plan["data"]["counts"]["refused"] == 1 and plan["data"]["counts"]["record"] == 1
    n_before = len(_events(fx.root, fx.review_id))
    rc, saved = _decide_cmd(fx.root, fx.review_id, path, "--write", "--plan-sha256", plan["data"]["planSha256"])
    assert rc == 0, saved
    assert [e["item_id"] for e in _events(fx.root, fx.review_id)[n_before:]] == [b_item.item_id]


def test_us2_schema_version_refused(noise_cards):
    root, _ = noise_cards
    rc, env = _export(root, RID)
    packet = _load_packet(root, RID, env["data"]["packetId"])
    path = _decisions(root, packet, {"mixed": ("approve", "")}, schemaVersion=2)
    env = _refuses_whole_file(root, RID, path, "REVIEW_CARDS_SCHEMA")
    assert "[1]" in env["message"]


def test_us2_extra_key_refused(noise_cards):
    root, _ = noise_cards
    rc, env = _export(root, RID)
    packet = _load_packet(root, RID, env["data"]["packetId"])
    path = _decisions(root, packet, {"mixed": ("approve", "")}, reviewer="GM")
    _refuses_whole_file(root, RID, path, "REVIEW_CARDS_INVALID")
    path = _decisions(root, packet, {"mixed": ("approve", "")})
    body = json.loads(path.read_text(encoding="utf-8"))
    body["cards"]["mixed"]["disposition"] = "accept_no_change"
    path.write_text(json.dumps(body), encoding="utf-8")
    _refuses_whole_file(root, RID, path, "REVIEW_CARDS_INVALID")


def test_us2_unsaved_page_refused(noise_cards):
    root, _ = noise_cards
    rc, env = _export(root, RID)
    packet = _load_packet(root, RID, env["data"]["packetId"])
    path = _decisions(root, packet, {"mixed": ("approve", "")}, savedAt="")
    _refuses_whole_file(root, RID, path, "REVIEW_CARDS_INVALID")


# =====================================================================================
# User Story 3 (spec 043): re-saving keeps every mark and shows every change
# =====================================================================================

def _cli_decide(root, item_id, verdict, note, *, expected=0, request="cli-x"):
    """A CLI-path ``save_decisions`` for one live item of the noise_cards review."""
    from pipelines.summary_native.review.store import save_decisions
    manifest, items, _events_, _stale = read_review_state(root, RID)
    item = next(i for i in items if i.item_id == item_id)
    save_decisions(root, RID, {
        "version": 1, "request_id": request, "review_generation": manifest.generation, "reviewer": "CLI",
        "decisions": [{"item_id": item.item_id, "item_revision": item.revision, "review_digest": item.review_digest,
                       "expected_decision_revision": expected, "verdict": verdict,
                       "disposition": cards.DISPOSITION_FOR[(item.proposed_action.action, verdict)], "note": note}]})


def _fresh_packet(root):
    rc, env = _export(root, RID)
    assert rc == 0, env
    return _load_packet(root, RID, env["data"]["packetId"])


def test_us3_s1_reapply_is_noop(noise_cards):
    root, _items = noise_cards
    packet = _fresh_packet(root)
    path = _decisions(root, packet, {"noise-class:label": ("approve", "ok"), "mixed": ("reject", "no")})
    _plan, (rc, saved) = _plan_then_write(root, RID, path)
    assert rc == 0 and sum(len(b["events"]) for b in saved["data"]["saved"]) == 4
    n_events = len(_events(root, RID))
    plan2, (rc, saved2) = _plan_then_write(root, RID, path)
    assert plan2["data"]["counts"] == {"record": 0, "supersede": 0, "noop": 4, "unmarked": 1, "refused": 0}
    assert rc == 0 and saved2["data"]["saved"] == [] and len(_events(root, RID)) == n_events


def test_us3_s2_changed_verdict_supersedes_and_keeps_history(noise_cards):
    root, _items = noise_cards
    packet = _fresh_packet(root)
    ids = [m["itemId"] for c in packet["cards"] if c["id"] == "noise-class:label" for m in c["members"]]
    _plan, (rc, _saved) = _plan_then_write(root, RID, _decisions(root, packet, {"noise-class:label": ("approve", "ok")}))
    assert rc == 0
    first = {e["item_id"]: e for e in _events(root, RID) if e["item_id"] in ids}
    path = _decisions(root, packet, {"noise-class:label": ("reject", "not noise")}, name="d2.json")
    plan, (rc, saved) = _plan_then_write(root, RID, path)
    assert rc == 0, saved
    changed = [m for c in plan["data"]["cards"] for m in c["members"] if m["category"] == "supersede"]
    assert sorted(m["itemId"] for m in changed) == sorted(ids)
    assert all(m["previous"]["verdict"] == "approve" for m in changed)
    assert plan["data"]["counts"]["supersede"] == len(ids) and plan["data"]["counts"]["record"] == 0
    events = _events(root, RID)
    for item_id in ids:
        mine = sorted((e for e in events if e["item_id"] == item_id), key=lambda e: e["decision_revision"])
        assert [e["verdict"] for e in mine] == ["approve", "reject"]
        assert mine[1]["supersedes_event"] == first[item_id]["event_id"]
        assert mine[0] == first[item_id]


def test_us3_s3_cli_decision_after_export_is_diffed(noise_cards):
    root, _items = noise_cards
    packet = _fresh_packet(root)
    _cli_decide(root, "mixed", "approve", "my own words")
    path = _decisions(root, packet, {"mixed": ("approve", "gm")})
    rc, plan = _decide_cmd(root, RID, path)
    assert rc == 0, plan
    (member,) = _by_card(plan)["mixed"]["members"]
    assert member["category"] == "supersede" and member["previous"]["note"] == "my own words"
    assert member["decision"]["expected_decision_revision"] == 1
    # Same verdict, disposition and note text: noop.
    _cli_decide(root, "mixed", "approve", cards.card_note("mixed", "gm"), expected=1, request="cli-y")
    rc, plan = _decide_cmd(root, RID, path)
    assert rc == 0 and _by_card(plan)["mixed"]["members"][0]["category"] == "noop"
    assert plan["data"]["counts"]["supersede"] == 0


def test_us3_discuss_then_approve_supersedes(noise_cards):
    root, _items = noise_cards
    packet = _fresh_packet(root)
    _plan, (rc, _s) = _plan_then_write(root, RID, _decisions(root, packet, {"mixed": ("discuss", "later")}))
    assert rc == 0
    path = _decisions(root, packet, {"mixed": ("approve", "ok now")}, name="d2.json")
    plan, (rc, saved) = _plan_then_write(root, RID, path)
    assert rc == 0, saved
    (member,) = _by_card(plan)["mixed"]["members"]
    assert member["category"] == "supersede" and member["previous"]["verdict"] == "discuss"
    mine = sorted((e for e in _events(root, RID) if e["item_id"] == "mixed"), key=lambda e: e["decision_revision"])
    assert [e["verdict"] for e in mine] == ["discuss", "approve"]


def test_us3_later_packet_same_verdict_is_noop(noise_cards):
    root, _items = noise_cards
    first = _fresh_packet(root)
    _plan, (rc, _s) = _plan_then_write(root, RID, _decisions(root, first, {"mixed": ("discuss", "same")}))
    assert rc == 0
    # A Discuss is not a ruling, so a second packet after the decision offers the card again.
    second = _fresh_packet(root)
    assert second["packetId"] != first["packetId"]
    assert "mixed" in [c["id"] for c in second["cards"]]
    n_events = len(_events(root, RID))
    plan, (rc, saved) = _plan_then_write(root, RID, _decisions(root, second, {"mixed": ("discuss", "same")}, name="d2.json"))
    assert rc == 0 and saved["data"]["saved"] == []
    (member,) = _by_card(plan)["mixed"]["members"]
    assert member["category"] == "noop"
    assert plan["data"]["counts"]["supersede"] == 0 and len(_events(root, RID)) == n_events
    note = [e for e in _events(root, RID) if e["item_id"] == "mixed"][0]["note"]
    assert first["packetId"] not in note and second["packetId"] not in note


def test_reoffered_discuss_card_shows_previous_note(noise_cards):
    root, _items = noise_cards
    first = _fresh_packet(root)
    assert "Previously discussed" not in json.dumps(first)
    marks = {"mixed": ("discuss", "ask the GM"), "noise-class:label": ("discuss", "")}
    _plan, (rc, _s) = _plan_then_write(root, RID, _decisions(root, first, marks))
    assert rc == 0
    second = _fresh_packet(root)
    by_id = {c["id"]: c for c in second["cards"]}
    assert by_id["mixed"]["previousDiscussion"] == "Previously discussed by GM: ask the GM"
    assert "Previously discussed" not in by_id["mixed"]["body"]
    assert by_id["noise-class:label"]["previousDiscussion"] is None
    label = by_id["noise-class:label"]["body"]
    assert label.count("Previously discussed by GM") == 3  # one per affected occurrence
    assert "Previously discussed by GM:" not in label  # empty note: no colon
    assert "Previously discussed" not in by_id["noise-class:idiom"]["body"]
    # Display only: the packet still has no verdict-like KEYS, and decide records exactly what it did.
    def keys(v):
        if isinstance(v, dict):
            for k, x in v.items():
                yield k
                yield from keys(x)
        elif isinstance(v, list):
            for x in v:
                yield from keys(x)
    assert not {"verdict", "guess", "decision", "recommendation"} & set(keys(second))
    plan, (rc, saved) = _plan_then_write(root, RID, _decisions(root, second, marks, name="d2.json"))
    assert plan["data"]["counts"]["noop"] == 4 and saved["data"]["saved"] == []
    # An approve withdraws nothing, but a ruled card no longer shows the line.
    _plan, (rc, _s) = _plan_then_write(root, RID, _decisions(root, second, {"mixed": ("approve", "ok")}, name="d3.json"))
    third = _fresh_packet(root)
    assert "mixed" not in [c["id"] for c in third["cards"]]


def test_export_refuses_unknown_action(campaign):
    root, cid, summary_sha, _d, sources = campaign
    odd = _item(cid, "odd-review", "odd-1", summary_sha=summary_sha, action={"action": "made_up_action"})
    _create(root, cid, "odd-review", [odd], sources)
    before = _tree(root, "odd-review")
    rc, env = _export(root, "odd-review")
    assert rc == 2 and env["code"] == "REVIEW_CARDS_ACTION_UNKNOWN", env
    assert "odd-1" in env["message"] and "made_up_action" in env["message"]
    assert not (root / "docs/reviews/odd-review/packets").exists() or not list(
        (root / "docs/reviews/odd-review/packets").glob("*"))
    assert _tree(root, "odd-review") == before
