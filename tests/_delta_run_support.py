"""Shared helpers for the US4 run/resume tests (not collected: no ``test_`` prefix)."""

from __future__ import annotations

import json
from pathlib import Path

from _delta_npc_support import FakeModel, install_fake, sign_drafts  # noqa: F401
from _delta_us2 import copy_fixture, M  # noqa: F401
from pipelines.summary_native import cli as sn_cli
from pipelines.summary_native.delta import plan as dplan

STEMS = {"npc_brannoc_ironvein": "Brannoc Ironvein", "npc_tobin_fenwick": "Tobin Fenwick"}
RANGE = "docs/npcs/summary_native/ch001-003"


def make_apply_plan(root: Path, chapters=("003-the-new-fire.md",), stop="apply", products=("npc",)):
    p = dplan.create_plan(campaign_identity="delta-fixture", products=list(products), stopping_point=stop,
                          source_paths=[root / "docs" / "summaries" / c for c in chapters], models=M)
    dplan.save_plan(p, dplan.plans_dir(root))
    return p


def cli(capsys, *argv):
    rc = sn_cli.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


def resume(capsys, root, plan, *extra):
    gm_prep(root, plan)
    rc, out, err = cli(capsys, "delta", "run", "resume", "--campaign-dir", str(root), "--plan", plan.plan_id,
                       "--json", *extra)
    try:
        return rc, json.loads(out), err
    except ValueError:
        return rc, {"raw": out}, err


def status(capsys, root, plan):
    rc, out, err = cli(capsys, "delta", "run", "status", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json")
    assert rc == 0, err
    return json.loads(out)


def sign_all(root, capsys):
    return sign_drafts(root, root / RANGE, STEMS, capsys)


def census_for_plan(root, plan, capsys):
    rc, _o, err = cli(capsys, "delta", "census", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json")
    assert rc == 0, err


def sign_stems(root: Path, capsys, stems: dict[str, str] | None = None) -> dict[str, dict]:
    """Sign through the real handoff + review CLI; safe to call again after an interrupted attempt."""
    from _delta_npc_support import handoff_and_sign

    return handoff_and_sign(root, capsys, STEMS if stems is None else stems)


def gm_prep(root: Path, plan) -> None:
    """What the GM does before a publish stage can run: preview the drafted members (the preview record names
    the member set), and attest each mentioned-unchanged NPC (the census never infers it). Idempotent."""
    from pipelines.summary_native.delta import attest as attest_mod, census as census_mod, npc_baseline, npc_update

    if census_mod.census_path(root, plan.plan_id).is_file():
        for e in census_mod.load_census(root, plan.plan_id).entries:
            if e.disposition != "mentioned_unchanged" or attest_mod.covering_attestation(root, e.subject, plan):
                continue
            bl = npc_baseline.baseline_for(root, e.slug)
            attest_mod.attest(root, e.subject, reason="still correct after the new chapter",
                              publication_sha256=bl.publication["published_sha256"],
                              added_sources=[{"path": s.path, "sha256": s.sha256} for s in plan.sources],
                              plan_id=plan.plan_id)
    if npc_update._state_path(root, plan.plan_id).is_file() and npc_update.load_stored_preview(root, plan.plan_id) is None:
        subjects = [m["subject"] for m in npc_update.load_state(root, plan.plan_id)["members"]]
        npc_update.store_preview(root, plan, subjects)
