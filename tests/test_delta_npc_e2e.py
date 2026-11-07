"""T046: changed, new, mention and mixed-horizon NPC updates through public operations (SC-004).

Everything goes through the ``summary_native delta`` CLI. The only fake is the model call. The
sign-off is the real one: a review created and signed through the public ``review`` CLI and recorded
in the authority ledger. There is no sign-off override anywhere in this file.
"""

from __future__ import annotations

import json

import pytest

from _delta_npc_support import (handoff_only, BRANNOC_MODEL, CANARY, FakeModel, census_for, copy_fixture, install_fake, make_plan,
                                sign_drafts)
from pipelines.summary_native import cli as sn_cli
from pipelines.summary_native import npc_publish

SELLA_MODEL = """## Identity

A courteous envoy of the Lantern Guild. [ch 001 / entry]

## Personality and Motivations

She names a price for forgiving debts. [ch 002 / 002.01]

## History with the Party

- Shows the party the Guild ledger. [ch 002 / 002.01]
- Rides into Emberfall and asks who speaks for the town. [ch 001 / 001.02]

## Last Observed State

As of chapter 002 she has shown the ledger. [ch 002 / entry]

## Relationships

- Offers to forgive Emberfall's debts for a price. [ch 002 / entry]

## Notable Quotes

None in the evidence.

## Arc-Score Candidates

- Shows the Guild ledger. [ch 002 / 002.01]
"""


def run(argv, capsys):
    rc = sn_cli.main(argv)
    out = capsys.readouterr()
    return rc, out.out, out.err


def delta(root, plan, *tail):
    return ["delta", *tail[:2], "--campaign-dir", str(root), "--plan", plan.plan_id, *tail[2:]]


def published_body(root, slug):
    text = (root / "docs/npcs" / f"{slug}.md").read_text(encoding="utf-8")
    return text.partition("\n")[2]


def census_cli(root, plan, capsys):
    rc, _o, err = run(["delta", "census", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json"], capsys)
    assert rc == 0, err


def draft_cli(root, plan, capsys):
    return run(["delta", "npc", "draft", "--campaign-dir", str(root), "--plan", plan.plan_id,
                "--backend", "claude-code", "--model", "m", "--json"], capsys)


def publish_cli(root, plan, members, capsys):
    base = ["delta", "npc", "publish", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json"]
    for m in members:
        base += ["--member", m]
    rc, out, err = run(base, capsys)  # no --preview-sha: a preview only, nothing is written
    assert rc == 0, err
    pv = json.loads(out)
    assert pv["published"] is False
    return run([*base, "--preview-sha", pv["preview_sha256"]], capsys)


def test_changed_and_new_complete_with_a_real_signoff(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    before_sella = (root / "docs/npcs/envoy-sella-marr.md").read_bytes()
    old_brannoc = (root / "docs/npcs/brannoc-ironvein.md").read_text(encoding="utf-8")
    census_cli(root, plan, capsys)
    fake = install_fake(monkeypatch)

    rc, out, err = draft_cli(root, plan, capsys)
    assert rc == 0, err
    d = json.loads(out)
    assert d["range"] == "ch001-003" and sorted(d["members"]) == ["Brannoc Ironvein", "Tobin Fenwick"]
    assert {v["verdict"] for v in d["verify"].values()} == {"pass"}
    assert len(fake.prompts) == 2  # one model call per drafted member, none for the mention
    rd = root / "docs/npcs/summary_native/ch001-003"

    rc, out, err = run(["delta", "npc", "verify", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json"], capsys)
    assert rc == 0, err
    assert json.loads(out)["verify"]["Brannoc Ironvein"]["evidence_kind"] == "sparse"

    handoff_only(root, capsys, plan)  # setup: the review binding publication requires; nothing is approved
    # without a sign-off nothing is published: no override exists
    rc, out, _ = publish_cli(root, plan, ["Brannoc Ironvein"], capsys)
    assert rc == 1
    assert json.loads(out)["members"][0]["outcome"] == "held"
    assert "NPC_DRAFT_SIGNOFF_REQUIRED" in json.loads(out)["members"][0]["reason"]
    assert not (root / "docs/npcs/tobin-fenwick.md").exists()

    sign_drafts(root, rd, {"npc_brannoc_ironvein": "Brannoc Ironvein", "npc_tobin_fenwick": "Tobin Fenwick"}, capsys)
    rc, out, err = publish_cli(root, plan, ["Brannoc Ironvein", "Tobin Fenwick"], capsys)
    assert rc == 0, err
    got = json.loads(out)["members"]
    assert [m["outcome"] for m in got] == ["published", "published"]
    assert all(m["receipt"]["body_sha256"] and m["receipt"]["target_sha256"] for m in got)

    # changed: the old history bytes survive, the new event is appended
    body = published_body(root, "brannoc-ironvein")
    old_history = old_brannoc.split("## History with the Party\n", 1)[1].split("\n## ", 1)[0].rstrip("\n")
    assert old_history in body
    assert "Restarts the forge and swears to forge for the town again. [ch 003 / 003.01]" in body
    assert body.index("Gives the party his apprentice's hammer") < body.index("Restarts the forge")
    assert CANARY in body  # the published dossier is GM-only and carries Secrets
    # new
    assert "haul coal" in published_body(root, "tobin-fenwick")
    log = json.loads((root / "docs/npcs/summary_native/publish_log.json").read_text())
    assert log["brannoc-ironvein"]["range"] == "ch001-003" and log["tobin-fenwick"]["range"] == "ch001-003"
    # mention: untouched
    assert (root / "docs/npcs/envoy-sella-marr.md").read_bytes() == before_sella
    assert log["envoy-sella-marr"]["range"] == "ch001-001"


def test_mention_is_attested_and_its_dossier_is_byte_identical(tmp_path, capsys):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_cli(root, plan, capsys)
    sella = root / "docs/npcs/envoy-sella-marr.md"
    before = sella.read_bytes()
    sha = json.loads((root / "docs/npcs/summary_native/publish_log.json").read_text())["envoy-sella-marr"]["published_sha256"]
    rc, out, err = run(["delta", "npc", "attest", "Envoy Sella Marr", "--campaign-dir", str(root), "--plan",
                        plan.plan_id, "--reason", "passing mention only", "--publication", sha, "--json"], capsys)
    assert rc == 0, err
    assert sella.read_bytes() == before
    # the mention is never drafted
    rc, _o, _e = run(["delta", "npc", "publish", "--campaign-dir", str(root), "--plan", plan.plan_id,
                      "--member", "Envoy Sella Marr"], capsys)
    assert rc == 2  # not drafted in this plan


def test_mixed_horizons_keep_each_subjects_own_history(tmp_path, monkeypatch, capsys):
    """Brannoc is published through ch002, Sella only through ch001; the plan is ch002 + ch003."""
    root = copy_fixture(tmp_path)
    plan = make_plan(root, ("002-the-ledger.md", "003-the-new-fire.md"))
    census_cli(root, plan, capsys)
    census = json.loads(next((root / "docs/summaries/delta/census").glob("*.json")).read_text())
    disp = {e["subject"]: e["disposition"] for e in census["entries"]}
    assert disp["Brannoc Ironvein"] == disp["Envoy Sella Marr"] == "changed"
    old_sella = (root / "docs/npcs/envoy-sella-marr.md").read_text(encoding="utf-8")
    fake = install_fake(monkeypatch, FakeModel({"Brannoc Ironvein": BRANNOC_MODEL, "Envoy Sella Marr": SELLA_MODEL,
                                                "Tobin Fenwick": __import__("_delta_npc_support").TOBIN_MODEL}))

    rc, out, err = draft_cli(root, plan, capsys)
    assert rc == 0, err
    assert {v["verdict"] for v in json.loads(out)["verify"].values()} == {"pass"}
    nd = root / "docs/summaries/delta" / plan.plan_id / "npc"
    spans = lambda stem, origin: {  # noqa: E731
        (s["chapter"], s["id"]) for s in json.loads((nd / f"{stem}.spans.json").read_text())["spans"] if s["origin"] == origin}
    # Brannoc (horizon 2): his ch002 material is already published, so only ch003 is new
    assert {c for c, _ in spans("npc_brannoc_ironvein", "new")} == {3}
    # Sella (horizon 1): ch002 is new for her
    assert {c for c, _ in spans("npc_envoy_sella_marr", "new")} == {2}
    assert (1, "entry") in spans("npc_envoy_sella_marr", "inherited")

    rd = root / "docs/npcs/summary_native/ch001-003"
    sign_drafts(root, rd, {"npc_brannoc_ironvein": "Brannoc Ironvein", "npc_envoy_sella_marr": "Envoy Sella Marr",
                           "npc_tobin_fenwick": "Tobin Fenwick"}, capsys)
    rc, out, err = publish_cli(root, plan, ["Brannoc Ironvein", "Envoy Sella Marr", "Tobin Fenwick"], capsys)
    assert rc == 0, err
    sella = published_body(root, "envoy-sella-marr")
    old_hist = old_sella.split("## History with the Party\n", 1)[1].split("\n## ", 1)[0].rstrip("\n")
    assert old_hist in sella and "Shows the party the Guild ledger. [ch 002 / 002.01]" in sella
    assert "swears to forge" not in sella  # her dossier does not take Brannoc's ch003 events
    log = json.loads((root / "docs/npcs/summary_native/publish_log.json").read_text())
    assert {log[s]["range"] for s in ("brannoc-ironvein", "envoy-sella-marr", "tobin-fenwick")} == {"ch001-003"}


def test_a_member_without_a_current_signoff_is_held_and_the_run_is_partial(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_cli(root, plan, capsys)
    install_fake(monkeypatch)
    assert draft_cli(root, plan, capsys)[0] == 0
    rd = root / "docs/npcs/summary_native/ch001-003"
    sign_drafts(root, rd, {"npc_brannoc_ironvein": "Brannoc Ironvein"}, capsys)  # Tobin is never signed
    rc, out, _ = publish_cli(root, plan, ["Brannoc Ironvein", "Tobin Fenwick"], capsys)
    assert rc == 4
    outcomes = {m["subject"]: m["outcome"] for m in json.loads(out)["members"]}
    assert outcomes == {"Brannoc Ironvein": "published", "Tobin Fenwick": "held"}
    assert not (root / "docs/npcs/tobin-fenwick.md").exists()


def test_publish_refuses_no_members_and_a_stale_preview(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_cli(root, plan, capsys)
    install_fake(monkeypatch)
    assert draft_cli(root, plan, capsys)[0] == 0
    handoff_only(root, capsys, plan)  # setup: the review binding publication requires
    rc, _o, err = run(["delta", "npc", "publish", "--campaign-dir", str(root), "--plan", plan.plan_id], capsys)
    assert rc == 2 and "no 'all'" in err
    rc, _o, err = run(["delta", "npc", "publish", "--campaign-dir", str(root), "--plan", plan.plan_id,
                       "--member", "Tobin Fenwick", "--preview-sha", "0" * 64], capsys)
    assert rc == 3 and "stale" in err
    assert not (root / "docs/npcs/tobin-fenwick.md").exists()
