"""The four US2 verbs through the public CLI: census, associate propose/decide, npc attest."""

from __future__ import annotations

import json

import pytest

from _delta_us2 import copy_fixture, make_plan
from pipelines.summary_native import cli as sn_cli
from pipelines.summary_native.delta import associations as asc
from pipelines.summary_native.delta import npc_baseline as nb

QUOTE = "the Lantern Guild would buy every blade the forge could make"


@pytest.fixture
def env(tmp_path):
    root = copy_fixture(tmp_path)
    return root, make_plan(root)


def _run(argv, capsys):
    rc = sn_cli.main(argv)
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_census_json(env, capsys):
    root, plan = env
    rc, out, _ = _run(["delta", "census", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json"], capsys)
    assert rc == 0
    d = json.loads(out)["dispositions"]
    assert d["Brannoc Ironvein"] == "changed" and d["Old Marrow Pike"] == "unresolved"
    assert (root / "docs/summaries/delta/census" / f"{plan.plan_id}.json").is_file()


def test_census_requires_plan(env, capsys):
    root, _ = env
    rc, _, err = _run(["delta", "census", "--campaign-dir", str(root)], capsys)
    assert rc == 2 and "--plan" in err


def test_associate_propose_then_decide(env, capsys, monkeypatch):
    root, plan = env
    import campaignlib
    items = [{"name": "Old Marrow Pike", "canonical_id": "The Lantern Guild", "scene": "003.02",
              "relationship_support": QUOTE, "scope": "faction offer"}]
    monkeypatch.setattr(campaignlib, "make_client", lambda **k: object())
    monkeypatch.setattr(campaignlib, "call_api", lambda c, s, u, m, *a, **k: json.dumps(items))
    rc, out, _ = _run(["delta", "associate", "propose", "--campaign-dir", str(root), "--plan", plan.plan_id,
                       "--backend", "claude-code", "--model", "m", "--json"], capsys)
    assert rc == 0
    aid = json.loads(out)["associations"][0]["id"]
    rc, out, _ = _run(["delta", "associate", "decide", aid, "--campaign-dir", str(root), "--plan", plan.plan_id,
                       "--decision", "approve", "--reviewer", "gm", "--json"], capsys)
    assert rc == 0 and json.loads(out)["decision"] == "approved"
    assert [a.id for a in asc.approved_associations(root, plan.plan_id)] == [aid]


def test_attest_cli(env, capsys):
    root, plan = env
    sha = nb.baseline_for(root, "envoy-sella-marr").publication["published_sha256"]
    base = ["delta", "npc", "attest", "Envoy Sella Marr", "--campaign-dir", str(root), "--plan", plan.plan_id]
    rc, out, _ = _run(base + ["--reason", "passing mention", "--publication", sha, "--json"], capsys)
    assert rc == 0 and json.loads(out)["publication_sha256"] == sha
    rc, _, err = _run(base + ["--reason", "  ", "--publication", sha], capsys)
    assert rc == 2
    rc, _, _ = _run(base + ["--reason", "x", "--publication", "b" * 64], capsys)
    assert rc == 3


def test_associate_decide_requires_an_explicit_reviewer(env, capsys):
    """No getpass default: a decision without --reviewer is a usage error (exit 2)."""
    root, plan = env
    rc, _o, err = _run(["delta", "associate", "decide", "a1", "--campaign-dir", str(root), "--plan", plan.plan_id,
                        "--decision", "approve", "--json"], capsys)
    assert rc == 2 and "--reviewer" in err
