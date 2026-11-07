"""Spec 039 review-fix round: one test per finding (numbers are the review's) plus T1 (require_fresh exercised
through the real `delta review handoff` + a real sign-off).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from _delta_npc_support import (census_for, handoff_and_sign, handoff_only, install_fake, make_plan)
from _delta_run_support import STEMS, copy_fixture, gm_prep, make_apply_plan, resume, sign_stems
from pipelines.summary_native import cli as sn_cli, npc_publish
from pipelines.summary_native.delta import (associations, attest as attest_mod, census as census_mod, npc_baseline,
                                            npc_update, review_binding as rb, run as run_mod)
from pipelines.summary_native.delta.errors import EXIT_REFUSAL, EXIT_STALE, DeltaRefusal
from pipelines.summary_native.delta.plan import load_plan, plans_dir

RD = "docs/npcs/summary_native/ch001-003"
A, B = "npc_brannoc_ironvein", "npc_tobin_fenwick"


def cli(capsys, *argv):
    rc = sn_cli.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


def publish(root, plan, capsys, *members):
    base = ["delta", "npc", "publish", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json"]
    for m in members:
        base += ["--member", m]
    rc, out, err = cli(capsys, *base)
    assert rc == 0, err
    return cli(capsys, *base, "--preview-sha", json.loads(out)["preview_sha256"])


@pytest.fixture
def drafted(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_for(root, plan)
    install_fake(monkeypatch)
    out = npc_update.draft(root, plan)
    assert out.exit_code == 0
    return root, plan


# ── 1: "unchanged" is an attestation, never an inference ──────────────────────────────────────


def test_1_a_mention_is_unchanged_only_with_a_current_covering_attestation(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_apply_plan(root)
    install_fake(monkeypatch)
    run_mod.advance(root, plan)
    state = run_mod.load_run(run_mod.run_path(root, plan.plan_id))
    envoy = next(m for m in state.members if m.subject == "Envoy Sella Marr")
    assert envoy.outcome is run_mod.MemberOutcome.held and "needs attestation" in envoy.reason

    sha = npc_baseline.baseline_for(root, "envoy-sella-marr").publication["published_sha256"]
    # an attestation that does not carry this plan's sources does not cover it
    attest_mod.attest(root, "Envoy Sella Marr", reason="ok", publication_sha256=sha, added_sources=[], plan_id=plan.plan_id)
    assert attest_mod.covering_attestation(root, "Envoy Sella Marr", plan) is None
    attest_mod.attest(root, "Envoy Sella Marr", reason="ok", publication_sha256=sha, plan_id=plan.plan_id,
                      added_sources=[{"path": s.path, "sha256": s.sha256} for s in plan.sources])
    assert attest_mod.covering_attestation(root, "Envoy Sella Marr", plan)["publication_sha256"] == sha
    run_mod.advance(root, plan)
    state = run_mod.load_run(run_mod.run_path(root, plan.plan_id))
    assert next(m for m in state.members if m.subject == "Envoy Sella Marr").outcome is run_mod.MemberOutcome.unchanged


# ── 2: the newest review that ruled on an item decides whether an older approval carries ───────


def test_2_an_older_approval_does_not_carry_past_a_newer_rejection(drafted, capsys):
    from pipelines.summary_native.review.delegated import _active_revision
    from pipelines.summary_native.review.store import read_review_state, read_snapshot, save_decisions

    root, plan = drafted
    first = handoff_and_sign(root, capsys)  # both approved in review 1
    second = handoff_only(root, capsys, plan)  # review 2 carries both
    _m, items, events, _s = read_review_state(root, second)
    tobin = next(i for i in items if i.proposed_action.details.get("draft_path", "").endswith(f"{B}.md"))
    assert any(e["item_id"] == tobin.item_id and e["verdict"] == "approve" for e in events)
    manifest, _c, snap = read_snapshot(root, second)
    save_decisions(root, second, {"version": 1, "request_id": "reject-tobin", "review_generation": manifest.generation,
                                  "reviewer": "GM", "decisions": [{
                                      "item_id": tobin.item_id, "item_revision": tobin.revision,
                                      "review_digest": tobin.review_digest,
                                      "expected_decision_revision": _active_revision(events, tobin.item_id),
                                      "verdict": "reject", "disposition": "reject_action", "note": "no"}]})
    from pipelines.summary_native.delta import cli_review
    third = cli_review._handoff_npc(root, plan)
    names = lambda ids: sorted(i for i in ids)  # noqa: E731
    brannoc_item = next(i.item_id for i in snap if i.proposed_action.details.get("draft_path", "").endswith(f"{A}.md"))
    assert brannoc_item in third["carried"]
    assert tobin.item_id not in third["carried"] and tobin.item_id in third["needs_review"], third
    assert first  # review 1's older approval of Tobin existed and was NOT resurrected


# ── 3 + T1: per-member freshness through the real handoff and a real sign-off ───────────────────


def test_3_redrafting_b_does_not_stale_a(drafted, capsys):
    root, plan = drafted
    handoff_and_sign(root, capsys)
    rb_ = rb.load_binding(root, plan.plan_id, "npc", "publication")
    assert set(rb_.member_hashes) == {"brannoc-ironvein", "tobin-fenwick"}
    p = root / RD / "draft" / f"{B}.md"
    p.write_text(p.read_text(encoding="utf-8") + "\nredrafted\n", encoding="utf-8")  # B only
    assert rb.require_fresh(root, plan, "npc", members=["brannoc-ironvein"], required=True)  # A is untouched
    with pytest.raises(DeltaRefusal) as e:
        rb.require_fresh(root, plan, "npc", members=["tobin-fenwick"], required=True)
    assert e.value.exit_code == EXIT_STALE and "tobin-fenwick" in e.value.message
    rc, out, err = publish(root, plan, capsys, "Brannoc Ironvein")
    assert rc == 0, err  # A publishes through the real gate while B waits for a fresh review
    assert not (root / "docs/npcs/tobin-fenwick.md").exists()


def test_t1_publish_without_a_handoff_binding_is_refused(drafted, capsys):
    root, plan = drafted
    from _delta_npc_support import sign_drafts  # noqa: F401  (signs through handoff now)
    pv = npc_update.publish_preview(root, plan, ["Brannoc Ironvein"])["preview_sha256"]
    with pytest.raises(DeltaRefusal) as e:
        npc_update.publish(root, plan, ["Brannoc Ironvein"], pv)
    assert e.value.exit_code == EXIT_REFUSAL and "delta review handoff" in e.value.message


def test_t1_a_post_signoff_authored_change_stales_only_the_affected_member(drafted, capsys):
    root, plan = drafted
    handoff_and_sign(root, capsys)
    authored = root / "docs/npcs/authored/brannoc-ironvein.authored.yaml"
    authored.write_text(authored.read_text(encoding="utf-8") + "\n# changed after sign-off\n", encoding="utf-8")
    npc_update.verify(root, plan)  # re-verifying must NOT launder the change into the graph
    rc, out, err = publish(root, plan, capsys, "Brannoc Ironvein", "Tobin Fenwick")
    outcomes = {m["subject"]: m["outcome"] for m in json.loads(out)["members"]}
    assert outcomes == {"Brannoc Ironvein": "held", "Tobin Fenwick": "published"}, (out, err)
    assert rc == 4


@pytest.mark.parametrize("rel", ["config/players.yaml", "docs/thread_registry.yaml", "docs/canon.yaml"])
def test_4_rule_files_are_dependencies_of_every_signoff(drafted, capsys, rel):
    root, plan = drafted
    handoff_and_sign(root, capsys)
    graph = npc_update.load_graph(root, plan.plan_id)
    assert any(n.kind == "rule" and n.key == rel for n in graph.dependencies(A))
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text((f.read_text(encoding="utf-8") if f.is_file() else "") + "\n# ruling changed\n", encoding="utf-8")
    assert graph.item_stale(A, npc_update.current_digests(root, plan.plan_id, graph))


def test_4_verify_never_records_the_graph(drafted):
    root, plan = drafted
    before = npc_update.graph_path(root, plan.plan_id).read_bytes()
    comp = root / RD / "gm" / f"{A}.md"
    comp.write_text(comp.read_text(encoding="utf-8") + "\nhand edit\n", encoding="utf-8")
    npc_update.verify(root, plan)
    assert npc_update.graph_path(root, plan.plan_id).read_bytes() == before


# ── 5: the handoff verifies against the member's own spans, parsing nothing ───────────────────────


def test_5_handoff_parses_no_summary_and_lists_no_other_chapter(drafted, monkeypatch, capsys):
    from pipelines.summary_native import parse
    from pipelines.summary_native.review.store import read_snapshot

    root, plan = drafted
    handoff_only(root, capsys, plan)  # initialises the ledger and review store

    def boom(*a, **k):
        raise AssertionError("the handoff must not parse a summary")

    monkeypatch.setattr(parse, "parse_file", boom)
    from pipelines.summary_native.delta import cli_review
    out = cli_review._handoff_npc(root, plan)
    assert out["read_counts"]["parsed_historical"] == 0
    _m, custody, _i = read_snapshot(root, out["review_id"])
    paths = {s.path for s in custody.sources}
    assert "docs/summaries/003-the-new-fire.md" in paths
    spans_sources = set()
    for stem in (A, B):
        rec = json.loads((npc_update.delta_dir(root, plan.plan_id) / f"{stem}.spans.json").read_text())
        spans_sources |= {s["source_path"] for s in rec["spans"]}
    assert paths - {f"{RD}/draft/{A}.md", f"{RD}/draft/{B}.md", f"{RD}/evidence/{A}.md", f"{RD}/evidence/{B}.md"} <= spans_sources


# ── 6: the run publishes only what the GM previewed ──────────────────────────────────────────────


def test_6_run_does_not_confirm_its_own_preview(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_apply_plan(root)
    install_fake(monkeypatch)
    run_mod.advance(root, plan)
    handoff_and_sign(root, capsys, plan=plan)
    gm_prep(root, plan)
    npc_update.preview_record_path(root, plan.plan_id).unlink()  # the GM never previewed
    report = run_mod.advance(root, plan)
    assert report.status is not run_mod.RunStatus.complete
    state = run_mod.load_run(run_mod.run_path(root, plan.plan_id))
    held = {m.subject: m.reason for m in state.members if m.outcome is run_mod.MemberOutcome.held}
    assert "GM-previewed" in held["Brannoc Ironvein"] and not (root / "docs/npcs/tobin-fenwick.md").exists()
    # an explicit member set: only Tobin previewed => only Tobin is published
    npc_update.store_preview(root, plan, ["Tobin Fenwick"])
    run_mod.advance(root, plan)
    assert (root / "docs/npcs/tobin-fenwick.md").exists()
    log = json.loads((root / "docs/npcs/summary_native/publish_log.json").read_text())
    assert log["brannoc-ironvein"]["range"] == "ch001-002"  # untouched


def test_6_a_moved_draft_after_the_preview_holds_that_member(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_apply_plan(root)
    install_fake(monkeypatch)
    resume(capsys, root, plan)
    sign_stems(root, capsys)
    gm_prep(root, plan)
    p = root / RD / "gm" / f"{B}.md"  # moves B's composition after the preview
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    run_mod.advance(root, plan)
    state = run_mod.load_run(run_mod.run_path(root, plan.plan_id))
    assert not (root / "docs/npcs/tobin-fenwick.md").exists()
    outcomes = {m.subject: m.outcome for m in state.members}
    assert outcomes["Tobin Fenwick"] is run_mod.MemberOutcome.held and "stale" in next(
        m.reason for m in state.members if m.subject == "Tobin Fenwick")


# ── 8: moment evidence uses word-bounded, non-withheld forms ─────────────────────────────────────


def test_8_forms_exclude_withheld_and_matching_is_word_bounded(tmp_path):
    root = copy_fixture(tmp_path)
    forms = npc_update._forms(root, "Brannoc Ironvein")
    assert "brannoc ironvein" in forms
    some_alias = next(f for f in forms if f != "brannoc ironvein") if len(forms) > 1 else None
    if some_alias:
        assert some_alias not in npc_update._forms(root, "Brannoc Ironvein", [some_alias])
    assert npc_update._mentions("Brannoc Ironvein lights it.", {"brannoc ironvein"})
    assert not npc_update._mentions("Ashen rose.", {"ash"})
    assert npc_update._mentions("He said Ash, quietly.", {"ash"})


# ── 9: bound inputs are hash-checked before the census / associations read them ───────────────────


def test_9_census_and_associations_refuse_an_edited_source(tmp_path):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    src = Path(plan.sources[0].path)
    src.write_text(src.read_text(encoding="utf-8") + "\nedited after planning\n", encoding="utf-8")
    with pytest.raises(DeltaRefusal) as e:
        census_mod.build_census(root, plan)
    assert e.value.exit_code == EXIT_STALE
    with pytest.raises(DeltaRefusal) as e2:
        associations.propose(root, plan, [], caller=lambda *a, **k: "[]")
    assert e2.value.exit_code == EXIT_STALE


# ── 13: a model never sets an audience, and the scene must contain the quote ────────────────────


def test_13_audience_is_forced_to_gm_and_the_scene_must_contain_the_quote(tmp_path):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    text = Path(plan.sources[0].path).read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if "Marrow" in ln and len(ln) > 30)
    quote = line.strip().lstrip("-* ").strip()[:60]
    import re
    scene = re.search(r"(\d{3}\.\d{2})", text).group(1)
    items = lambda sc: json.dumps([{"name": "Old Marrow Pike", "canonical_id": "Brannoc Ironvein", "scene": sc,  # noqa: E731
                                    "relationship_support": quote, "rationale": "r", "scope": "narrow",
                                    "audience": "player"}])
    store = associations.propose(root, plan, [], caller=lambda *a, **k: items("999.99"))
    assert [d["reason"] for d in store.dropped] == ["scene_does_not_contain_support"] and not store.associations
    scenes = [it.scene_id for it in __import__("pipelines.summary_native.npc_link", fromlist=["x"]).iter_items(
        __import__("pipelines.summary_native.parse", fromlist=["x"]).parse_file(Path(plan.sources[0].path), root))
        if it.kind == "scene" and quote in it.text]
    if scenes:
        store = associations.propose(root, plan, [], caller=lambda *a, **k: items(scenes[0]))
        assert store.associations and store.associations[0].audience == "gm"


# ── 15 / 16: full-mode publish is unchanged; receipts are revisioned ────────────────────────────


def test_15_full_mode_publish_does_not_swallow_errors(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    monkeypatch.setattr(npc_publish, "render_published", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        npc_publish.publish(root, root / "docs/npcs/summary_native/ch001-002", names=["Brannoc Ironvein"],
                            _signoff_checker=lambda *a: True)
    assert not list(root.rglob("*.intent.json")) and not list(root.rglob("receipts"))


def test_16_a_second_receipt_keeps_the_first(drafted, capsys):
    root, plan = drafted
    handoff_only(root, capsys, plan)
    rc, out, err = publish(root, plan, capsys, "Tobin Fenwick")  # unsigned: held receipt
    assert json.loads(out)["members"][0]["outcome"] == "held"
    handoff_and_sign(root, capsys, {B: "x"}, plan)
    rc, out, err = publish(root, plan, capsys, "Tobin Fenwick")
    assert rc == 0, err
    rdir = npc_update.receipts_dir(root, plan.plan_id)
    latest = json.loads((rdir / "tobin-fenwick.json").read_text())
    first = json.loads(next((rdir / "history").glob("tobin-fenwick.r*.json")).read_text())
    assert latest["outcome"] == "published" and first["outcome"] == "held"


# ── 17: an attestation records what the GM was shown ─────────────────────────────────────────────


def test_17_attestation_records_evidence_and_ruling_from_the_census(tmp_path):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_for(root, plan)
    sha = npc_baseline.baseline_for(root, "envoy-sella-marr").publication["published_sha256"]
    rec = attest_mod.attest(root, "Envoy Sella Marr", reason="fine", publication_sha256=sha, plan_id=plan.plan_id,
                            added_sources=[{"path": s.path, "sha256": s.sha256} for s in plan.sources])
    assert rec.added_evidence and rec.rulings.get("ruling")


# ── 18: a header with no draft digest proves nothing ─────────────────────────────────────────────


def test_18_a_publication_header_without_a_draft_digest_needs_repair(tmp_path):
    root = copy_fixture(tmp_path)
    log = json.loads((root / "docs/npcs/summary_native/publish_log.json").read_text())
    target = root / "docs/npcs/brannoc-ironvein.md"
    text = target.read_text(encoding="utf-8")
    import re
    assert re.search(r"draft sha256:\s*[0-9a-f]{64}", text.partition("\n")[0])
    target.write_text(re.sub(r"\|?\s*draft sha256:\s*[0-9a-f]{64}", "", text, count=1), encoding="utf-8")
    bl = npc_baseline.baseline_for(root, "brannoc-ironvein")
    assert bl.status in ("repair_required:draft_lineage_unproven", "repair_required:hand_edited_target"), bl.status
    assert log  # the log entry exists; only the header lost its lineage


# ── 20: historical chapters are not parsed unless the GM opted in ───────────────────────────────


def test_20_no_evidence_pack_means_refusal_unless_opted_in(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    (root / npc_update.HISTORICAL_PARSE_MARKER_REL).unlink()
    plan = make_plan(root)
    census_for(root, plan)
    install_fake(monkeypatch)
    with pytest.raises(DeltaRefusal) as e:
        npc_update.draft(root, plan)
    assert e.value.exit_code == EXIT_REFUSAL and "evidence pack" in e.value.message and "--allow-historical-parse" in e.value.message
    npc_update.allow_historical_parse(root)
    out = npc_update.draft(root, plan)
    assert out.exit_code == 0 and out.reads["parsed_historical"] > 0  # reported, never hidden
