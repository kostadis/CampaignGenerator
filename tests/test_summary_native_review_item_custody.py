"""Per-item source custody through the real store (spec 042, user stories 1-4).

Every test builds a REAL multi-NPC verified review with ``tests/_custody_fixture.py`` and
drives it through the public CLI, so the refusal an NPC sees is the one production writes.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from pipelines.summary_native.authority import load_ledger, sha256_bytes
from pipelines.summary_native.review import delegated
from pipelines.summary_native.review.store import CampaignReviewIdentity, load_campaign_identity
from pipelines.summary_native.review.models import canonical_bytes
from tests import _custody_fixture as fixture
from tests.conftest_npc import run_cli, sha_tree

STALE = "REVIEW_STALE_CUSTODY"


def _state(fx):
    """Everything a refused batch must leave alone: review dir (events, requests) + ledger."""
    ledger = load_ledger(fx.root)
    return fx.review_tree_sha(), ledger.revision, len(ledger.records)


def _ids(*items):
    return sorted(i.item_id for i in items)


def _refused(rc, out):
    assert rc == 3, out
    assert out["ok"] is False and out["code"] == STALE


def _saved(rc, out):
    assert rc == 0, out
    assert out["ok"] is True


# ── T012 ───────────────────────────────────────────────────────────────────

def test_us1_s1_other_npc_signoff_saves_after_draft_edit(tmp_path):
    fx = fixture.build(tmp_path)
    fx.touch(fx.draft("a"))
    rc, out = fx.sign("b")
    _saved(rc, out)
    assert len(list((fx.root / "docs/reviews" / fx.review_id / "events").glob("*.json"))) == 1


# ── T013 ───────────────────────────────────────────────────────────────────

def test_us1_s2_edited_npc_items_refused_nothing_written(tmp_path):
    fx = fixture.build(tmp_path)
    fx.touch(fx.draft("a"))
    before = _state(fx)
    kinds = fx.findings("a") + [fx.signoff("a")]
    assert {i.proposed_action.action for i in kinds} >= {"review_presentation", "signoff_npc_draft"}
    for item in kinds:
        rc, out = fx.decide([item])
        _refused(rc, out)
        assert _state(fx) == before
    # `review npc sign` hashes the touched draft and is refused earlier by its own digest check
    rc, out = fx.sign("a")
    assert rc == 3 and out["code"] == "REVIEW_NPC_SIGNOFF_STALE"
    assert _state(fx) == before


# ── T014 ───────────────────────────────────────────────────────────────────

def test_us1_s3_summary_change_stales_only_naming_npcs(tmp_path):
    fx = fixture.build(tmp_path / "x")
    fx.touch(fx.summary(2))
    for npc in ("b",):
        rc, out = fx.decide([fx.signoff(npc)])
        _refused(rc, out)
        rc, out = fx.decide(fx.findings(npc))
        _refused(rc, out)
    _saved(*fx.sign("a"))
    _saved(*fx.sign("c"))

    fy = fixture.build(tmp_path / "y")
    fy.touch(fy.summary(3))
    _refused(*fy.decide([fy.signoff("c")]))
    _saved(*fy.sign("a"))
    _saved(*fy.sign("b"))


# ── T015 ───────────────────────────────────────────────────────────────────

def test_us1_s4_mixed_batch_refused_whole_and_lists_every_stale(tmp_path):
    fx = fixture.build(tmp_path)
    fx.touch(fx.draft("a"))
    before = _state(fx)
    batch = [fx.signoff("b"), *fx.findings("a"), fx.signoff("a")]
    assert len(fx.findings("a")) + 1 == 2
    rc, out = fx.decide(batch)
    _refused(rc, out)
    assert out["data"]["stale_items"] and \
        sorted(e["item_id"] for e in out["data"]["stale_items"]) == _ids(*fx.findings("a"), fx.signoff("a"))
    assert _state(fx) == before


# ── T016 ───────────────────────────────────────────────────────────────────

def test_deleted_dependency_is_missing_and_refuses(tmp_path):
    fx = fixture.build(tmp_path)
    fx.delete(fx.summary(2))
    before = _state(fx)
    rc, out = fx.decide([fx.signoff("b")])
    _refused(rc, out)
    states = {f["path"]: f["state"] for f in out["data"]["changed_files"]}
    assert states[fx.rel(fx.summary(2))] == "missing"
    assert _state(fx) == before


def test_change_and_change_back_is_current(tmp_path):
    fx = fixture.build(tmp_path)
    fx.touch(fx.draft("a"))
    _refused(*fx.decide([fx.signoff("a")]))
    fx.restore(fx.draft("a"))
    _saved(*fx.sign("a"))


def test_signoff_depends_on_evidence(tmp_path):
    fx = fixture.build(tmp_path)
    fx.touch(fx.evidence("c"))
    _refused(*fx.decide([fx.signoff("c")]))
    _saved(*fx.sign("a"))


def test_unparseable_evidence_falls_back_to_all_summaries(tmp_path):
    fx = fixture.build(tmp_path)
    fx.touch(fx.summary(3))
    _refused(*fx.decide([fx.signoff("d")]))
    _saved(*fx.sign("a"))


def test_noise_class_card_batch_refused_whole(tmp_path):
    """A class card is one batch through ``delegated.submit_decisions`` (what ``review noise decide
    --write`` calls); the fixture review has no classified-noise items, so the batch is built by hand
    over A and B items with the same call."""
    fx = fixture.build(tmp_path)
    fx.touch(fx.draft("a"))
    before = _state(fx)
    decisions = [{
        "item_id": i.item_id, "item_revision": i.revision, "review_digest": i.review_digest,
        "expected_decision_revision": 0, "verdict": "approve", "disposition": "document_signoff",
        "note": "class card",
    } for i in (fx.signoff("a"), fx.signoff("b"))]
    try:
        delegated.submit_decisions(fx.root, fx.review_id, generation=fx.generation, reviewer="GM",
                                   decisions=decisions, prefix="noise")
    except Exception as exc:  # noqa: BLE001
        assert getattr(exc, "code", None) == STALE
    else:
        raise AssertionError("expected a refusal")
    assert _state(fx) == before


def test_n_npc_review_other_npcs_unaffected(tmp_path):
    fx = fixture.build(tmp_path, extra_npcs=8)
    assert len(fx.items) == 12
    fx.touch(fx.draft("a"))
    refusals = 0
    for npc in fx.items:
        if npc == "a":
            continue
        rc, out = fx.sign(npc)
        refusals += rc != 0
    assert refusals == 0


# ── T017 ───────────────────────────────────────────────────────────────────

def test_withdrawal_allowed_on_stale_item(tmp_path):
    fx = fixture.build(tmp_path)
    item = fx.signoff("a")
    rc, out = fx.sign("a")
    _saved(rc, out)
    event_id = out["data"]["events"][0]["event_id"]
    fx.touch(fx.draft("a"))
    rc, out = fx.cli("review", "retract", fx.review_id, "--event", event_id,
                     "--expected-decision-revision", "1", "--reason", "redo", "--reviewer", "GM Two")
    _saved(rc, out)
    rc, hist = fx.cli("review", "history", fx.review_id, "--item", item.item_id)
    assert rc == 0
    withdrawal = [e for e in hist["data"]["events"] if e.get("kind") == "withdrawal"]
    assert len(withdrawal) == 1
    assert withdrawal[0]["reviewer"] == "GM Two" and withdrawal[0]["recorded_at"]


# ── T018: import ───────────────────────────────────────────────────────────

def _replica(fx, tmp_path):
    replica = tmp_path / "replica"
    shutil.copytree(fx.root, replica)
    identity = load_campaign_identity(fx.root)
    (replica / "docs" / "reviews" / "campaign.json").write_bytes(
        CampaignReviewIdentity(1, identity.campaign_id, str(replica.resolve())).bytes())
    return replica


def _export(fx, replica, items):
    selection = fx.root / "export-selection.json"
    selection.write_text(json.dumps({"items": [i.item_id for i in items]}), encoding="utf-8")
    rc, out = fx.cli("review", "export", fx.review_id, "--selection", str(selection))
    assert rc == 0, out
    target = replica / "bundle.json"
    target.write_bytes((fx.root / out["data"]["path"]).read_bytes())
    return target


def _import(replica, bundle):
    rc, out, _err = run_cli(["review", "import", "--bundle", str(bundle), "--expected-generation", "1",
                             "--campaign-dir", str(replica), "--json"])
    return rc, json.loads(out)


def _touch(path):
    path.write_bytes(path.read_bytes() + b"\nedited.\n")


def test_import_checks_bundle_items_only(tmp_path):
    fx = fixture.build(tmp_path / "src")
    replica = _replica(fx, tmp_path)
    _saved(*fx.sign("b"))
    bundle = _export(fx, replica, [fx.signoff("b")])
    _touch(replica / fx.rel(fx.draft("a")))
    rc, out = _import(replica, bundle)
    assert rc == 0, out
    assert out["data"]["imported_events"] == 1


def test_import_refuses_stale_bundle_item_with_detail(tmp_path):
    fx = fixture.build(tmp_path / "src")
    replica = _replica(fx, tmp_path)
    _saved(*fx.sign("a"))
    bundle = _export(fx, replica, [fx.signoff("a")])
    _touch(replica / fx.rel(fx.draft("a")))
    before = sha_tree(replica / "docs" / "reviews")
    rc, out = _import(replica, bundle)
    _refused(rc, out)
    assert out["data"]["operation"] == "import"
    assert [e["item_id"] for e in out["data"]["stale_items"]] == [fx.signoff("a").item_id]
    assert sha_tree(replica / "docs" / "reviews") == before


def test_import_withdrawal_only_bundle_on_stale_item(tmp_path):
    fx = fixture.build(tmp_path / "src")
    # a reject writes no authority record, so the bundle's withdrawal is the only new fact
    rc, out = fx.decide([fx.signoff("a")], verdict="reject", disposition="reject_action")
    _saved(rc, out)
    event_id = out["data"]["events"][0]["event_id"]
    replica = _replica(fx, tmp_path)  # already holds the decision
    _saved(*fx.cli("review", "retract", fx.review_id, "--event", event_id,
                   "--expected-decision-revision", "1", "--reason", "redo", "--reviewer", "GM"))
    bundle = _export(fx, replica, [fx.signoff("a")])
    _touch(replica / fx.rel(fx.draft("a")))
    rc, out = _import(replica, bundle)
    assert rc == 0, out
    assert out["data"]["imported_events"] == 1


def test_import_custody_digest_mismatch_still_refuses(tmp_path):
    fx = fixture.build(tmp_path / "src")
    replica = _replica(fx, tmp_path)
    _saved(*fx.sign("b"))
    bundle = _export(fx, replica, [fx.signoff("b")])
    raw = json.loads(bundle.read_text(encoding="utf-8"))
    raw.pop("bundle_sha256")
    raw["custody_digest"] = "0" * 64
    raw["bundle_sha256"] = sha256_bytes(canonical_bytes(raw))
    bundle.write_text(json.dumps(raw), encoding="utf-8")
    rc, out = _import(replica, bundle)
    _refused(rc, out)
    assert "import custody changed" in out["message"]
