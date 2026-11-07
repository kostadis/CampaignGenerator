"""T036: digest-bound grounding preview/apply (spec 039 FR-016, FR-020, FR-021)."""

from __future__ import annotations

import json

import pytest

from pipelines.summary_native import cli as sn_cli
from pipelines.summary_native.delta import grounding_publish as gp
from pipelines.summary_native.delta.errors import EXIT_REFUSAL, EXIT_STALE, DeltaRefusal
from pipelines.summary_native.delta.lineage import (
    BaselineRef, CustodyRef, DeltaLineageRecord, LineageMember, save_lineage)
from pipelines.summary_native.delta.plan import create_plan, plans_dir, save_plan
import hashlib

MODELS = {"generation": {"backend": "anthropic", "model": "m"},
          "consistency": {"backend": "dgx", "model": "q", "effort": "low"}}
SHA = "b" * 64


@pytest.fixture
def world(tmp_path):
    src = tmp_path / "docs/summaries/003-x.md"
    src.parent.mkdir(parents=True)
    src.write_text("c3")
    plan = create_plan(campaign_identity="camp", products=["grounding"], stopping_point="apply",
                       source_paths=[src], models=MODELS)
    save_plan(plan, plans_dir(tmp_path))
    base = gp.grounding_dir(tmp_path, plan.plan_id)
    (base / "candidates").mkdir(parents=True)
    (base / "candidates/world_state.md").write_text("world v2\n")
    old = tmp_path / "docs/summaries/ch001-002/party.md"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"party v1\n")
    d = hashlib.sha256(b"party v1\n").hexdigest()
    ws = hashlib.sha256(b"world v2\n").hexdigest()
    (tmp_path / "c.json").write_text(json.dumps({"candidate_sha256": {"world_state": ws}}))
    lineage = DeltaLineageRecord(plan_ref=plan.plan_id, baseline=BaselineRef(generation_id="g1", manifest_sha256=SHA), members=[
        LineageMember(name="party", mode="inherited", sha256=d, custody_ref=CustodyRef(path="docs/summaries/ch001-002/party.md", sha256=d)),
        LineageMember(name="world_state", mode="produced", sha256=ws, check_ref="c.json", check_status="passed")])
    save_lineage(lineage, base / gp.LINEAGE_FILE)
    return tmp_path, plan, base


def _bind(root, plan):
    """The review record `apply` requires (FR-020): an explicit approval bound to the current hashes."""
    from pipelines.summary_native.delta import review_binding as rb
    rb.save_binding(root, rb.make_binding(root, plan, "grounding", "publication", decisions=[
        rb.BoundDecision(id="doc", level="document", decision="approve", reviewer="GM")]))


def _preview(tmp_path, plan):
    c, l, r = gp.load_inputs(tmp_path, plan.plan_id)
    return gp.preview(plan, c, l, r, campaign_dir=tmp_path)


def test_preview_is_deterministic_and_complete(world):
    root, plan, _ = world
    a, b = _preview(root, plan), _preview(root, plan)
    assert a.preview_sha256 == b.preview_sha256 and a.complete and not a.problems


def test_apply_delegates_and_writes_no_synth_record(world):
    root, plan, base = world
    seen = []
    _bind(root, plan)
    result = gp.apply(plan, _preview(root, plan).preview_sha256, campaign_dir=root,
                      publisher=lambda c, p, r: seen.append((c, p.plan_id, r)) or {"generation": "g2"})
    assert result == {"generation": "g2"} and seen[0][1] == plan.plan_id
    names = [p.name for p in root.rglob("*") if p.is_file()]
    assert not any("synth" in n for n in names)


@pytest.mark.parametrize("mutate", ["candidate", "lineage", "request"])
def test_apply_refuses_stale_preview_exit_3(world, mutate):
    root, plan, base = world
    sha = _preview(root, plan).preview_sha256
    if mutate == "candidate":
        (base / "candidates/world_state.md").write_text("world v2 edited\n")
    elif mutate == "lineage":
        rec = json.loads((base / gp.LINEAGE_FILE).read_text())
        rec["plan_ref"] = "other"
        (base / gp.LINEAGE_FILE).write_text(json.dumps(rec))
    else:
        (base / gp.PUBLISH_REQUEST_FILE).write_text('{"since": 3}')
    _bind(root, plan)  # a review of the CURRENT inputs, so only the confirmed preview digest is stale
    called = []
    with pytest.raises(DeltaRefusal) as err:
        gp.apply(plan, sha, campaign_dir=root, publisher=lambda *a: called.append(1) or {})
    assert err.value.exit_code == EXIT_STALE == 3 and not called


def test_layout_is_the_one_plan_scoped_directory(world):
    root, plan, base = world
    assert base == root / "docs/summaries/delta/grounding" / plan.plan_id


def test_preview_refuses_check_report_that_does_not_match_candidate_bytes(world, capsys, monkeypatch):
    root, plan, base = world
    from pipelines.summary_native.delta import cli_grounding_publish as cgp
    monkeypatch.setattr(cgp, "stage_for_promotion", lambda *a, **k: {})
    (base / "candidates/world_state.md").write_text("world v2 EDITED AFTER CHECK\n")
    code = sn_cli.main(["delta", "grounding", "preview", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json"])
    assert code == 3 and "check" in capsys.readouterr().err


def test_apply_refuses_incomplete_lineage(world):
    root, plan, base = world
    rec = json.loads((base / gp.LINEAGE_FILE).read_text())
    rec["members"][1]["check_status"] = "failed"
    (base / gp.LINEAGE_FILE).write_text(json.dumps(rec))
    _bind(root, plan)
    with pytest.raises(DeltaRefusal) as err:
        gp.apply(plan, _preview(root, plan).preview_sha256, campaign_dir=root, publisher=lambda *a: {})
    assert err.value.exit_code == EXIT_REFUSAL


def test_default_publisher_goes_through_promotion_cli(world, monkeypatch):
    root, plan, base = world
    (base / gp.PUBLISH_REQUEST_FILE).write_text(json.dumps(
        {"since": 1, "until": 3, "review": "r", "check_report": "cr.json", "request_id": "rq1"}))
    calls = []
    from pipelines.summary_native.promotion import cli as pcli

    def fake_run(ns):
        calls.append(ns)
        print(json.dumps({"data": {"preview": {"preview_sha256": SHA}, "committed": not ns.dry_run}}))
        return 0

    monkeypatch.setattr(pcli, "run", fake_run)
    _bind(root, plan)
    out = gp.apply(plan, _preview(root, plan).preview_sha256, campaign_dir=root)
    assert [c.dry_run for c in calls] == [True, False]
    assert calls[1].preview_sha256 == SHA and calls[1].request_id == "rq1"
    assert out["committed"] is True


def test_cli_preview_then_apply_stale(world, capsys, monkeypatch):
    root, plan, base = world
    # this synthetic world has no campaign config to stage a promotion range into; staging has its own
    # coverage in test_delta_grounding_e2e.py
    from pipelines.summary_native.delta import cli_grounding_publish as cgp
    monkeypatch.setattr(cgp, "stage_for_promotion", lambda *a, **k: {})
    assert sn_cli.main(["delta", "grounding", "preview", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json"]) == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["complete"] and (base / gp.PREVIEW_FILE).is_file()
    (base / "candidates/world_state.md").write_text("changed\n")
    _bind(root, plan)
    code = sn_cli.main(["delta", "grounding", "apply", "--campaign-dir", str(root), "--plan", plan.plan_id,
                        "--preview-sha", rec["preview_sha256"], "--json"])
    assert code == 3
    assert sn_cli.main(["delta", "grounding", "apply", "--campaign-dir", str(root), "--plan", plan.plan_id]) == 2


def test_apply_without_a_review_binding_is_refused_and_publishes_nothing(world):
    """FR-020/#585: the 'no binding' escape hatch is closed for apply, so the refusal is reachable."""
    root, plan, _ = world
    called = []
    with pytest.raises(DeltaRefusal) as err:
        gp.apply(plan, _preview(root, plan).preview_sha256, campaign_dir=root,
                 publisher=lambda *a: called.append(1) or {})
    assert err.value.exit_code == EXIT_REFUSAL and "review handoff" in err.value.message and not called


def _stage_tree(root, plan, *, out_root="docs/summary_native", since=3, until=3):
    base = gp.grounding_dir(root, plan.plan_id)
    (base / gp.PUBLISH_REQUEST_FILE).write_text(json.dumps({"out_root": out_root, "since": since, "until": until}))
    drafts = root / out_root / f"ch{since:03d}-{until:03d}" / "state/drafts"
    drafts.mkdir(parents=True)
    (drafts / "world_state.draft.md").write_text("staged v1\n")
    (drafts.parent.parent / "manifest.json").write_text("{}")
    return drafts


def test_preview_binds_the_staged_promotion_tree_not_only_the_candidates(world):
    """A staged draft edited after the preview is what the publisher would read; apply refuses exit 3."""
    root, plan, _ = world
    drafts = _stage_tree(root, plan)
    sha = _preview(root, plan)
    assert sha.staged_sha256 not in ("unstaged", "absent")
    (drafts / "world_state.draft.md").write_text("staged v2 (hand edit)\n")
    _bind(root, plan)
    called = []
    with pytest.raises(DeltaRefusal) as err:
        gp.apply(plan, sha.preview_sha256, campaign_dir=root, publisher=lambda *a: called.append(1) or {})
    assert err.value.exit_code == EXIT_STALE and not called


@pytest.mark.parametrize("what", ["manifest", "reference"])
def test_staged_digest_covers_manifest_and_copied_reference(world, what):
    root, plan, _ = world
    drafts = _stage_tree(root, plan)
    before = _preview(root, plan).staged_sha256
    if what == "manifest":
        (drafts.parent.parent / "manifest.json").write_text('{"files": []}')
    else:
        (drafts / "reference").mkdir()
        (drafts / "reference/party.md").write_text("copied\n")
    assert _preview(root, plan).staged_sha256 != before


def test_stage_refuses_to_write_into_an_existing_full_build_directory(world, monkeypatch):
    """A range directory this delta did not stage (a full build's) is never overwritten (exit 1)."""
    from pipelines.summary_native.delta import grounding_candidates as gc
    root, plan, _base = world
    (root / "config").mkdir()
    (root / "config/config.yaml").write_text("{}\n")
    monkeypatch.setattr("pipelines.summary_native.promotion.settings.resolve_out_root", lambda *a, **k: "docs/sn")
    monkeypatch.setattr("pipelines.summary_native.promotion.settings.load_settings", lambda *a, **k: object())
    monkeypatch.setattr(gc, "require_check_binding", lambda *a, **k: None)
    existing = root / "docs/sn/ch003-003"
    existing.mkdir(parents=True)
    (existing / "manifest.json").write_text('{"full": "build"}')
    with pytest.raises(DeltaRefusal) as err:
        gc.stage_for_promotion(root, plan)
    assert err.value.exit_code == EXIT_REFUSAL and "not staged by a delta" in err.value.message
    assert (existing / "manifest.json").read_text() == '{"full": "build"}'
    # restaging a directory the stager itself created (marker present) is exercised by the e2e preview steps
