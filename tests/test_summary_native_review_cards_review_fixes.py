"""Spec 043 T046: code-review fixes -- approval is yes with the no, exact sign-off bytes, one snapshot, one table."""
from __future__ import annotations

import json

import pytest

from campaignlib.review_config import load_campaign_review_config
from pipelines.summary_native.review import cards, custody, delegated, store
from tests import _custody_fixture as custody_fx
from tests.conftest_npc import run_cli
from tests.test_summary_native_review_cards import (  # noqa: F401  (noise_cards, campaign are fixtures)
    RID, _by_card, _cli, _decide_cmd, _decisions, _events, _export, _fx_packet, _load_packet, noise_cards)
from tests.test_summary_native_review_delegated import campaign  # noqa: F401


def _text_plan(root, review, path, *extra, reviewer="GM"):
    return run_cli(["review", "cards", "decide", review, "--decisions", str(path), "--reviewer", reviewer, *extra,
                    "--campaign-dir", str(root)])


# ------------------------------------------------------------ 1. approval is yes with the no

def test_finding_reject_means_does_not_promise_to_block_signoff(tmp_path):
    packet = _fx_packet(custody_fx.build(tmp_path), "--action", "review_presentation")
    for card in packet["cards"]:
        assert "no sign-off" not in card["rejectMeans"]
        assert "travels with" in card["rejectMeans"] and "recorded" in card["rejectMeans"]


def test_signoff_approved_with_the_rejected_finding_in_the_same_file(tmp_path):
    fx = custody_fx.build(tmp_path)
    packet = _fx_packet(fx)
    finding, signoff = fx.findings("a")[0], fx.signoff("a")
    path = _decisions(fx.root, packet, {finding.item_id: ("reject", "the quote is wrong"),
                                         signoff.item_id: ("approve", "otherwise fine")})
    rc, plan = _decide_cmd(fx.root, fx.review_id, path)
    assert rc == 0, plan
    card = _by_card(plan)[signoff.item_id]
    assert card["state"] == "applied"  # NOT blocked
    assert card["withRejectedFindings"] == [{"itemId": finding.item_id, "line": 16, "note": "the quote is wrong"}]
    expected = (f"GM card verdict [{signoff.item_id}]: otherwise fine; with rejected finding(s): {finding.item_id} L16")
    assert card["members"][0]["decision"]["note"] == expected
    assert card["members"][0]["decision"]["disposition"] == "document_signoff"
    # text mode
    rc, out, _err = _text_plan(fx.root, fx.review_id, path)
    assert rc == 0 and f"  approved with 1 rejected finding(s): {finding.item_id} L16" in out
    # written exactly as planned, and the sign-off is a real sign-off
    rc, saved = _decide_cmd(fx.root, fx.review_id, path, "--write", "--plan-sha256", plan["data"]["planSha256"])
    assert rc == 0, saved
    events = {e["item_id"]: e for e in _events(fx.root, fx.review_id)}
    assert events[signoff.item_id]["note"] == expected and events[signoff.item_id]["disposition"] == "document_signoff"
    assert events[finding.item_id]["verdict"] == "reject"


def test_signoff_carries_a_reject_already_in_the_store_but_not_another_drafts(tmp_path):
    fx = custody_fx.build(tmp_path)
    rc, env = fx.decide([fx.findings("a")[0]], "reject", disposition="reject_action", note="stored no")
    assert rc == 0, env
    packet = _fx_packet(fx)  # the rejected finding is no longer offered
    assert fx.findings("a")[0].item_id not in {c["id"] for c in packet["cards"]}
    path = _decisions(fx.root, packet, {fx.signoff("a").item_id: ("approve", ""), fx.signoff("b").item_id: ("approve", "")})
    rc, plan = _decide_cmd(fx.root, fx.review_id, path)
    cards_ = _by_card(plan)
    a, b = cards_[fx.signoff("a").item_id], cards_[fx.signoff("b").item_id]
    assert a["withRejectedFindings"] == [{"itemId": fx.findings("a")[0].item_id, "line": 16, "note": "stored no"}]
    assert a["members"][0]["decision"]["note"].endswith(f"; with rejected finding(s): {fx.findings('a')[0].item_id} L16")
    assert "withRejectedFindings" not in b and "rejected finding" not in b["members"][0]["decision"]["note"]


def test_file_approving_a_stored_reject_overrides_it_and_a_refused_reject_does_not_count(tmp_path):
    fx = custody_fx.build(tmp_path)
    packet = _fx_packet(fx)
    fa, fb = fx.findings("a")[0], fx.findings("b")[0]
    assert fx.decide([fa], "reject", disposition="reject_action")[0] == 0  # after export
    path = _decisions(fx.root, packet, {fa.item_id: ("approve", ""), fx.signoff("a").item_id: ("approve", ""),
                                         fb.item_id: ("reject", ""), fx.signoff("b").item_id: ("approve", "")})
    fx.touch(fx.evidence("b"))  # the b finding's reject is refused for stale custody, so it is not recorded
    rc, plan = _decide_cmd(fx.root, fx.review_id, path)
    cards_ = _by_card(plan)
    assert cards_[fb.item_id]["state"] == "refused"
    assert "withRejectedFindings" not in cards_[fx.signoff("a").item_id]
    assert "withRejectedFindings" not in cards_[fx.signoff("b").item_id]
    fx.restore(fx.evidence("b"))  # control: with the reject recordable, the b sign-off does carry it
    rc, plan = _decide_cmd(fx.root, fx.review_id, path)
    assert [f["itemId"] for f in _by_card(plan)[fx.signoff("b").item_id]["withRejectedFindings"]] == [fb.item_id]
    assert "withRejectedFindings" not in _by_card(plan)[fx.signoff("a").item_id]


def test_finding_with_no_determinable_draft_is_not_linked(tmp_path, monkeypatch):
    fx = custody_fx.build(tmp_path)
    packet = _fx_packet(fx)
    finding, signoff = fx.findings("a")[0], fx.signoff("a")
    path = _decisions(fx.root, packet, {finding.item_id: ("reject", ""), signoff.item_id: ("approve", "")})
    monkeypatch.setattr(cards, "_draft_of", lambda item: None if item.item_id == finding.item_id else
                        cards.PurePosixPath(item.proposed_action.details.get("draft_path") or item.locator.source_path))
    rc, plan = _decide_cmd(fx.root, fx.review_id, path)
    assert rc == 0 and "withRejectedFindings" not in _by_card(plan)[signoff.item_id]


def test_signoff_note_too_long_once_findings_named_refuses_that_card_only(tmp_path):
    fx = custody_fx.build(tmp_path)
    packet = _fx_packet(fx)
    limit = load_campaign_review_config(fx.root).max_note_chars
    signoff, finding, other = fx.signoff("a"), fx.findings("a")[0], fx.signoff("c")
    head = len(cards.card_note(signoff.item_id, "x"))
    note = "x" * (limit - head + 1)  # exactly at the limit before the suffix
    path = _decisions(fx.root, packet, {finding.item_id: ("reject", ""), signoff.item_id: ("approve", note),
                                         other.item_id: ("approve", "")})
    rc, plan = _decide_cmd(fx.root, fx.review_id, path)
    assert rc == 0, plan
    cards_ = _by_card(plan)
    assert cards_[signoff.item_id]["state"] == "refused"
    assert cards_[signoff.item_id]["refusal"]["code"] == "REVIEW_CARDS_NOTE_TOO_LONG"
    assert cards_[other.item_id]["state"] == "applied" and cards_[finding.item_id]["state"] == "applied"
    assert cards_[signoff.item_id]["members"][0]["category"] == "refused"


# ------------------------------------------------------------ 2 and 3. sign-off body bytes, unreadable drafts

def test_signoff_body_keeps_crlf_and_hash_is_of_the_shown_bytes(tmp_path, monkeypatch):
    original = custody_fx._draft
    monkeypatch.setattr(custody_fx, "_draft", lambda *a, **k: original(*a, **k).replace("\n", "\r\n"))
    fx = custody_fx.build(tmp_path)
    raw = fx.draft("c").read_bytes()
    assert b"\r\n" in raw
    packet = _fx_packet(fx, "--action", "signoff_npc_draft")
    card = next(c for c in packet["cards"] if c["npc"] == "Ccc")
    assert card["body"].encode("utf-8") == raw
    import hashlib
    assert card["draftSha256"] == hashlib.sha256(card["body"].encode("utf-8")).hexdigest()


def test_non_utf8_draft_is_a_skipped_signoff_not_a_failed_export(tmp_path, monkeypatch):
    fx = custody_fx.build(tmp_path)
    fx.draft("c").write_bytes(b"\xff\xfe not utf-8 \x80")
    monkeypatch.setattr(delegated, "npc_signoff_blocker", lambda root, item: None)
    rc, env = _export(fx.root, fx.review_id, "--action", "signoff_npc_draft")
    assert rc == 0, env
    skipped = {s["itemId"]: s for s in env["data"]["skippedSignoffs"]}
    assert skipped[fx.signoff("c").item_id]["code"] == "REVIEW_CARDS_DRAFT_NOT_UTF8"
    assert fx.signoff("c").item_id not in {c["id"] for c in _load_packet(fx.root, fx.review_id, env["data"]["packetId"])["cards"]}


def test_symlinked_draft_is_a_skipped_signoff_not_a_failed_export(tmp_path):
    fx = custody_fx.build(tmp_path)
    draft = fx.draft("c")
    real = draft.with_name("real_npc_c.md")
    real.write_bytes(draft.read_bytes())
    draft.unlink()
    draft.symlink_to(real)
    rc, env = _export(fx.root, fx.review_id, "--action", "signoff_npc_draft")
    assert rc == 0, env
    skipped = {s["itemId"]: s for s in env["data"]["skippedSignoffs"]}
    assert skipped[fx.signoff("c").item_id]["code"] == "REVIEW_PATH"
    assert env["data"]["cards"] == 3


# ------------------------------------------------------------ 4. the reviewer is in the plan hash

def test_write_with_a_different_reviewer_than_planned_is_plan_changed(tmp_path):
    fx = custody_fx.build(tmp_path)
    packet = _fx_packet(fx, "--action", "review_presentation")
    path = _decisions(fx.root, packet, {fx.findings("a")[0].item_id: ("approve", "")})
    rc, plan = _decide_cmd(fx.root, fx.review_id, path, reviewer="GM")
    sha = plan["data"]["planSha256"]
    _rc, other = _decide_cmd(fx.root, fx.review_id, path, reviewer="Somebody Else")
    assert other["data"]["planSha256"] != sha
    n_before = len(_events(fx.root, fx.review_id))
    rc, env = _decide_cmd(fx.root, fx.review_id, path, "--write", "--plan-sha256", sha, reviewer="Somebody Else")
    assert rc == 5 and env["code"] == "REVIEW_CARDS_PLAN_CHANGED"
    assert len(_events(fx.root, fx.review_id)) == n_before
    rc, env = _decide_cmd(fx.root, fx.review_id, path, "--write", "--plan-sha256", sha, reviewer="GM")
    assert rc == 0 and env["code"] == "REVIEW_CARDS_SAVED"


# ------------------------------------------------------------ 5. one snapshot, one stale report

def test_plan_decide_reads_one_snapshot_and_computes_stale_report_once(tmp_path, monkeypatch):
    fx = custody_fx.build(tmp_path)
    packet = _fx_packet(fx, "--action", "review_presentation")
    a, b = fx.findings("a")[0], fx.findings("b")[0]
    path = _decisions(fx.root, packet, {a.item_id: ("approve", ""), b.item_id: ("approve", "")})
    fx.touch(fx.evidence("a"))
    fx.touch(fx.evidence("b"))
    calls = {"snapshot": 0, "stale": 0}
    real_snapshot, real_stale = store.read_snapshot, custody.stale_report

    def snapshot(*args, **kw):
        calls["snapshot"] += 1
        return real_snapshot(*args, **kw)

    def stale(*args, **kw):
        calls["stale"] += 1
        return real_stale(*args, **kw)

    monkeypatch.setattr(store, "read_snapshot", snapshot)
    monkeypatch.setattr(custody, "stale_report", stale)
    decisions = cards.parse_decisions(path.read_bytes(), max_note_chars=10_000)
    plan = cards.plan_decide(fx.root, fx.review_id, decisions, reviewer="GM")
    assert [c["state"] for c in plan["cards"]] == ["refused", "refused"]
    assert all(c["refusal"]["code"] == "REVIEW_STALE_CUSTODY" for c in plan["cards"])
    assert calls == {"snapshot": 1, "stale": 1}


def test_slice_report_equals_a_report_computed_for_just_those_items(tmp_path):
    fx = custody_fx.build(tmp_path)
    fx.touch(fx.evidence("a"))
    manifest, gen, items = store.read_snapshot(fx.root, fx.review_id)
    probe = custody.disk_probe(fx.root)
    ids = [i.item_id for npc in ("a", "b") for i in fx.items[npc]]
    whole = custody.stale_report(manifest.kind, gen, items, ids, probe)
    for npc in ("a", "b"):
        own_ids = [i.item_id for i in fx.items[npc]]
        want = custody.stale_report(manifest.kind, gen, items, own_ids, probe)
        got = custody.slice_report(whole, own_ids)
        assert (got.stale, got.changed_files, got.dependency_sets, got.no_dependency) == (
            want.stale, want.changed_files, want.dependency_sets, want.no_dependency)


# ------------------------------------------------------------ 6. event index

class _CountingList(list):
    iterations = 0

    def __iter__(self):
        type(self).iterations += 1
        return super().__iter__()


def test_event_index_matches_the_scan_it_replaced():
    events = [
        {"item_id": "a", "decision_revision": 1}, {"item_id": "b", "kind": "stage"},
        {"item_id": "a", "kind": "withdrawal"}, {"kind": "rebind"}, {"item_id": "b", "decision_revision": 3},
        {"item_id": "a", "decision_revision": 2, "verdict": "approve"}, {"item_id": "c", "kind": "withdrawal"},
    ]

    def latest(item_id):
        matches = [e for e in events if e.get("item_id") == item_id]
        return matches[-1] if matches else None

    def revision(item_id):
        out = 0
        for e in events:
            if e.get("item_id") == item_id and "decision_revision" in e:
                out = int(e["decision_revision"])
        return out

    index = delegated.index_events(events)
    for item_id in ("a", "b", "c", "zzz"):
        assert delegated._latest(events, item_id, index) == latest(item_id) == delegated._latest(events, item_id)
        assert delegated._active_revision(events, item_id, index) == revision(item_id) == delegated._active_revision(events, item_id)


def test_build_packet_scans_events_once_not_once_per_item(tmp_path):
    fx = custody_fx.build(tmp_path, extra_npcs=40)
    manifest, items, events, stale = store.read_review_state(fx.root, fx.review_id)
    counting = _CountingList(events)
    _CountingList.iterations = 0
    packet, _skipped = cards.build_packet(fx.root, fx.review_id, snapshot=(manifest, items, counting, stale))
    assert len(packet["cards"]) > 40
    assert _CountingList.iterations <= 2, _CountingList.iterations


# ------------------------------------------------------------ 7. one action table

def test_cards_derive_their_dispositions_from_the_stores_action_table():
    assert cards.SIGNOFF_ACTION is custody.SIGNOFF_ACTION
    assert cards._FINDING_ACTIONS is store.FINDING_ACTIONS
    for (action, verdict), disposition in cards.DISPOSITION_FOR.items():
        assert (verdict, disposition) in store.ACTION_DECISIONS[action]
    assert set(cards.DISPOSITION_FOR) == {
        (action, verdict) for action in (*store.FINDING_ACTIONS, custody.SIGNOFF_ACTION)
        for verdict, _d in store.ACTION_DECISIONS[action]}


def test_validate_action_decision_reads_the_exposed_table(tmp_path, monkeypatch):
    fx = custody_fx.build(tmp_path)
    item = fx.findings("a")[0]
    with pytest.raises(store.ReviewStoreError):
        store._validate_action_decision(item, verdict="approve", disposition="merge")
    table = dict(store.ACTION_DECISIONS)
    table[item.proposed_action.action] = frozenset({("approve", "merge")})
    monkeypatch.setattr(store, "ACTION_DECISIONS", table)
    store._validate_action_decision(item, verdict="approve", disposition="merge")


# ------------------------------------------------------------ 8. plan_noise_class goes through expand

def test_plan_noise_class_builds_its_decisions_through_expand_with_the_final_note(noise_cards, monkeypatch):
    root, _items = noise_cards
    seen = []
    real = cards.expand

    def spy(snapshot, **kw):
        out = real(snapshot, **kw)
        seen.append((kw["gm_note"], out))
        return out

    monkeypatch.setattr(cards, "expand", spy)
    plan = delegated.plan_noise_class(root, RID, noise_class="label", verdict="approve", note="fine")
    final_note, final = seen[-1]
    assert final_note.startswith("GM class verdict on batch card") and "(3 occurrences)" in final_note
    assert plan["decisions"] == [m.decision for m in final.members]
    assert {d["note"] for d in plan["decisions"]} == {final_note}
