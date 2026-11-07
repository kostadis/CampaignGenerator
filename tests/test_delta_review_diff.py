"""T058 + T061/T062/T063: the review document, the combined handoff, and the binding gate at publish/apply.

NPC half: the quickstart fixture drafted with a fake model, signed through the real review CLI.
Grounding half: a real propose/decide/check/preview over the managed-generation fixture.
"""

from __future__ import annotations

import json

import pytest

from _delta_npc_support import (CANARY, census_for, copy_fixture, install_fake, make_plan, sign_drafts)
from pipelines.summary_native import cli as sn_cli
from pipelines.summary_native.delta import diff_view, review_binding as rb
from pipelines.summary_native.delta.plan import load_plan, plans_dir

RD = "docs/npcs/summary_native/ch001-003"
STEMS = {"npc_brannoc_ironvein": "Brannoc Ironvein", "npc_tobin_fenwick": "Tobin Fenwick"}


def run(argv, capsys):
    rc = sn_cli.main(argv)
    out = capsys.readouterr()
    return rc, out.out, out.err


def d(root, plan, *leaf, extra=()):
    return ["delta", *leaf, "--campaign-dir", str(root), "--plan", plan.plan_id, *extra]


@pytest.fixture
def drafted(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_for(root, plan)
    install_fake(monkeypatch)
    rc, _o, err = run(d(root, plan, "npc", "draft", extra=["--backend", "claude-code", "--model", "m", "--json"]), capsys)
    assert rc == 0, err
    return root, plan


def publish(root, plan, capsys, *members):
    base = d(root, plan, "npc", "publish", extra=["--json"])
    for m in members:
        base += ["--member", m]
    rc, out, err = run(base, capsys)
    assert rc == 0, err
    return run([*base, "--preview-sha", json.loads(out)["preview_sha256"]], capsys)


def show(root, plan, capsys):
    rc, out, err = run(d(root, plan, "review", "show"), capsys)
    assert rc == 0, err
    return out


# ── the document ────────────────────────────────────────────────────────────


def test_document_renders_diff_new_prose_evidence_hashes_coverage_and_findings(drafted, capsys):
    root, plan = drafted
    text = show(root, plan, capsys)
    assert "### Brannoc Ironvein (changed)" in text and "### Tobin Fenwick (new)" in text
    assert "--- baseline/brannoc-ironvein.md" in text and "+++ candidate/brannoc-ironvein.md" in text
    assert "+- Restarts the forge and swears to forge for the town again." in text  # a diff line
    assert "Full prose (new dossier):" in text and "A young fletcher in Emberfall." in text
    assert "Evidence spans:" in text and "(new)" in text and "docs/summaries/003-the-new-fire.md" in text
    assert "baseline horizon: 2" in text and "baseline horizon: none (new)" in text
    import re
    assert re.search(r"draft sha256: `[0-9a-f]{64}`", text) and re.search(r"plan sha256: `[0-9a-f]{64}`", text)
    assert "Inherited findings:" in text and "Outstanding findings:" in text
    assert CANARY not in text  # Secrets are not part of the review document


def test_document_is_deterministic_and_the_json_carries_the_same_bytes(drafted, capsys):
    root, plan = drafted
    a, b = show(root, plan, capsys), show(root, plan, capsys)
    assert a == b
    rc, out, _ = run(d(root, plan, "review", "show", extra=["--json"]), capsys)
    rec = json.loads(out)
    assert rc == 0 and rec["document"] == a and rec["call_counts"] == {"model": 0}
    assert rec["document_path"].endswith("/review/review.md")
    assert diff_view.render(root, load_plan(plans_dir(root), plan.plan_id)) == a  # the page's entry point


def test_without_a_handoff_nothing_is_authorised(drafted, capsys):
    root, plan = drafted
    assert "No review binding recorded" in show(root, plan, capsys)


# ── handoff: one combined review, prior sign-offs reused ────────────────────


def test_handoff_creates_one_review_and_everything_needs_review_when_nothing_was_signed(drafted, capsys):
    root, plan = drafted
    initialize(root, capsys)
    rc, out, err = run(d(root, plan, "review", "handoff", extra=["--json"]), capsys)
    assert rc == 0, err
    h = json.loads(out)["handoff"]["npc"]
    assert h["carried"] == [] and len(h["needs_review"]) == 2
    text = show(root, plan, capsys)
    assert text.count("BLOCKING") >= 2 and "no saved decision" in text


def initialize(root, capsys):
    from pipelines.summary_native.authority import AuthorityLedger
    from pipelines.summary_native.authority_apply import initialize_ledger
    initialize_ledger(root, AuthorityLedger(version=2, campaign="delta-fixture", revision=1), actor="test")
    assert sn_cli.main(["review", "init", "--campaign-dir", str(root), "--json"]) == 0
    capsys.readouterr()


def test_handoff_reuses_valid_prior_signoffs_and_asks_only_for_the_changed_draft(drafted, capsys):
    root, plan = drafted
    rdir = root / RD
    first = sign_drafts(root, rdir, STEMS, capsys)
    # one draft changes after the first sign-off: only that one needs a fresh look
    tobin = rdir / "draft/npc_tobin_fenwick.md"
    tobin.write_text(tobin.read_text(encoding="utf-8").replace("Willing to help.", "Willing to help, mostly."),
                     encoding="utf-8")
    rc, out, err = run(d(root, plan, "review", "handoff", extra=["--json"]), capsys)
    assert rc == 0, err
    h = json.loads(out)["handoff"]["npc"]
    assert len(h["carried"]) == 1 and len(h["needs_review"]) == 1
    assert set(h["carried_from"].values()) == {first["npc_brannoc_ironvein"]["review_id"]}
    binding = rb.load_binding(root, plan.plan_id, "npc", "publication")
    assert {x.member: x.decision for x in binding.decisions} == {"brannoc-ironvein": "approve", "tobin-fenwick": "unset"}


def test_a_discuss_or_unsaved_decision_blocks_publish_of_that_member_only(drafted, capsys):
    root, plan = drafted
    sign_drafts(root, root / RD, {"npc_brannoc_ironvein": "Brannoc Ironvein"}, capsys)
    assert run(d(root, plan, "review", "handoff"), capsys)[0] == 0
    rc, out, _ = publish(root, plan, capsys, "Tobin Fenwick")  # covered by the binding, but unsigned
    assert rc == 1  # blocked (exit 1), nothing written
    assert not (root / "docs/npcs/tobin-fenwick.md").exists()
    rc, out, err = publish(root, plan, capsys, "Brannoc Ironvein")
    assert rc == 0, err
    assert json.loads(out)["members"][0]["outcome"] == "published"


# ── SC-005: change a bound input after sign-off ─────────────────────────────


@pytest.mark.parametrize("what", ["rules", "evidence", "draft"])
def test_npc_publish_refuses_exit_3_when_a_bound_input_moved_after_signoff(drafted, capsys, what):
    root, plan = drafted
    sign_drafts(root, root / RD, STEMS, capsys)
    assert run(d(root, plan, "review", "handoff"), capsys)[0] == 0
    if what == "rules":
        reg = root / "docs/entity_registry.yaml"
        reg.write_text(reg.read_text(encoding="utf-8") + "\n# a ruling changed\n", encoding="utf-8")
    elif what == "evidence":
        p = root / RD / "evidence/npc_brannoc_ironvein.md"
        p.write_text(p.read_text(encoding="utf-8") + "\nextra\n", encoding="utf-8")
    else:
        p = root / RD / "draft/npc_brannoc_ironvein.md"
        p.write_text(p.read_text(encoding="utf-8") + "\nedit\n", encoding="utf-8")
    rc, out, err = publish(root, plan, capsys, "Brannoc Ironvein", "Tobin Fenwick")
    assert rc == 3, (out, err)
    assert {"rules": "rules", "evidence": "evidence", "draft": "candidate"}[what] in err
    assert not (root / "docs/npcs/tobin-fenwick.md").exists()


def test_publish_after_a_clean_handoff_still_works(drafted, capsys):
    root, plan = drafted
    sign_drafts(root, root / RD, STEMS, capsys)
    assert run(d(root, plan, "review", "handoff"), capsys)[0] == 0
    rc, out, err = publish(root, plan, capsys, "Brannoc Ironvein", "Tobin Fenwick")
    assert rc == 0, err
    assert [m["outcome"] for m in json.loads(out)["members"]] == ["published", "published"]


def test_a_member_outside_the_binding_is_refused_exit_3(drafted, capsys):
    root, plan = drafted
    sign_drafts(root, root / RD, STEMS, capsys)
    assert run(d(root, plan, "review", "handoff"), capsys)[0] == 0
    path = rb.binding_path(root, plan.plan_id, "npc", "publication")
    b = json.loads(path.read_text())
    b["members"] = ["brannoc-ironvein"]
    path.write_text(json.dumps(b))
    rc, _o, err = publish(root, plan, capsys, "Tobin Fenwick")
    assert rc == 3 and "not covered" in err


# ── grounding ───────────────────────────────────────────────────────────────


def test_grounding_document_diff_and_apply_gate(tmp_path, capsys, monkeypatch):
    from test_delta_grounding_e2e import NEW_LINE, prepare
    from pipelines.summary_native.delta import grounding_publish as gp
    from tests.support.delta_grounding_fixture import add_new_chapter, make_grounding_campaign

    root = make_grounding_campaign(tmp_path)
    source = add_new_chapter(root)
    pid, _line = prepare(capsys, root, source, monkeypatch, "{line}\n" + NEW_LINE)
    for leaf in (["grounding", "check"], ["grounding", "preview"]):
        assert sn_cli.main(["delta", *leaf, "--plan", pid, "--campaign-dir", str(root), "--json"]) == 0
    capsys.readouterr()
    rc, text, err = run(["delta", "review", "show", "--plan", pid, "--campaign-dir", str(root)], capsys)
    assert rc == 0, err
    assert "### world_state.md (changed)" in text and "--- baseline/world_state.md" in text
    assert "+" + NEW_LINE in text
    assert "### campaign_state.md (unchanged)" in text
    assert "### Coverage" in text and "### Lineage" in text and "Outstanding findings:" in text
    assert "No review binding recorded" in text

    # handoff needs the document review the promotion names
    rc, _o, err = run(["delta", "review", "handoff", "--plan", pid, "--campaign-dir", str(root)], capsys)
    assert rc == 2 and "names no document review" in err

    # a binding is recorded, approved explicitly, then a bound rule moves before apply
    plan = load_plan(plans_dir(root), pid)
    b = rb.make_binding(root, plan, "grounding", "publication")
    rb.save_binding(root, b)
    assert "BLOCKING" in run(["delta", "review", "show", "--plan", pid, "--campaign-dir", str(root)], capsys)[1]
    b = rb.record_decision(root, b, "world_state", "approve", reviewer="GM", level="document")
    monkeypatch.setattr(gp, "default_publisher", lambda *a: {"published": True})
    sha = json.loads(run(["delta", "grounding", "preview", "--plan", pid, "--campaign-dir", str(root), "--json"], capsys)[1])["preview_sha256"]
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs/entity_registry.yaml").write_text("entities: []\n")
    rc, _o, err = run(["delta", "grounding", "apply", "--plan", pid, "--preview-sha", sha,
                       "--campaign-dir", str(root)], capsys)
    assert rc == 3 and "rules" in err
