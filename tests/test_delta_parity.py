"""spec 039 T076: every HTTP route is the CLI (Principle XI, SC-008).

1. For each route in contracts/http.md (plus review and transfer), the argv the route builds parses to
   the same arguments as the documented CLI invocation.
2. The same inputs give identical plan, decision and receipt records through the real CLI and through
   the real route (which spawns the console script), after timestamps are removed.
"""

from __future__ import annotations

import json

import pytest

from pipelines.summary_native import cli as sn_cli
from server.routers import summary_native_delta as router_mod
from server.subprocess_runner import console_script
from tests._delta_http_support import BASE, cli_json, client_for, init_identity, normalise
from tests._delta_us2 import copy_fixture

CD = "CAMPAIGN"


def _expected_cli(root) -> list[tuple[str, str, dict | None, list[str], bool]]:
    """(method, path, body, documented CLI args after `delta`, streamed?)."""
    c = ["--campaign-dir", str(root)]
    return [
        ("POST", "/plans", {"sources": ["a.md", "b.md"], "product": ["grounding", "npc"], "stop": "review"},
         ["plan", *c, "--product", "grounding", "--product", "npc", "--stop", "review",
          "--source", "a.md", "--source", "b.md", "--json"], False),
        ("POST", "/plans/p1/sources", {}, ["sources", *c, "--plan", "p1", "--json"], False),
        ("GET", "/plans/p1/baseline", None, ["baseline", "status", *c, "--plan", "p1", "--json"], False),
        ("POST", "/plans/p1/baseline/adopt", {"resolve": ["h1=accept", "h2=reject"]},
         ["baseline", "adopt", *c, "--plan", "p1", "--resolve", "h1=accept", "--resolve", "h2=reject", "--json"], False),
        ("POST", "/plans/p1/census", {}, ["census", *c, "--plan", "p1"], True),
        ("POST", "/plans/p1/associations/propose", {}, ["associate", "propose", *c, "--plan", "p1"], True),
        ("POST", "/associations/a1/decision", {"plan": "p1", "decision": "approve", "reason": "ok", "reviewer": "gm"},
         ["associate", "decide", "a1", *c, "--plan", "p1", "--decision", "approve", "--reason", "ok",
          "--reviewer", "gm", "--json"], False),
        ("POST", "/plans/p1/npc/draft", {}, ["npc", "draft", *c, "--plan", "p1"], True),
        ("POST", "/plans/p1/npc/verify", {}, ["npc", "verify", *c, "--plan", "p1"], True),
        ("POST", "/plans/p1/npc/Brannoc/attest", {"reason": "r", "publication": "abc"},
         ["npc", "attest", "Brannoc", *c, "--plan", "p1", "--reason", "r", "--publication", "abc", "--json"], False),
        ("POST", "/plans/p1/npc/publish", {"members": ["Brannoc", "Tobin"], "preview_sha": "s"},
         ["npc", "publish", *c, "--plan", "p1", "--member", "Brannoc", "--member", "Tobin", "--preview-sha", "s"], True),
        ("POST", "/plans/p1/grounding/propose", {}, ["grounding", "propose", *c, "--plan", "p1"], True),
        ("POST", "/grounding/proposals/g1/decision", {"decision": "reject", "reviewer": "gm"},
         ["grounding", "decide", "g1", *c, "--decision", "reject", "--reviewer", "gm", "--json"], False),
        ("POST", "/plans/p1/npc/publish/preview", {"members": ["Brannoc", "Tobin"]},
         ["npc", "publish", *c, "--plan", "p1", "--member", "Brannoc", "--member", "Tobin", "--json"], False),
        ("POST", "/plans/p1/grounding/check", {}, ["grounding", "check", *c, "--plan", "p1"], True),
        ("POST", "/plans/p1/grounding/preview", {"review": "r1", "claims_report": "cr", "request_id": "q"},
         ["grounding", "preview", *c, "--plan", "p1", "--review", "r1", "--claims-report", "cr",
          "--request-id", "q", "--json"], False),
        ("POST", "/plans/p1/grounding/apply", {"preview_sha": "s"},
         ["grounding", "apply", *c, "--plan", "p1", "--preview-sha", "s"], True),
        ("GET", "/plans/p1/status", None, ["run", "status", *c, "--plan", "p1", "--json"], False),
        ("POST", "/plans/p1/resume", {}, ["run", "resume", *c, "--plan", "p1"], True),
        ("GET", "/plans/p1/receipt", None, ["receipt", *c, "--plan", "p1", "--json"], False),
        ("GET", "/plans/p1/review", None, ["review", "show", *c, "--plan", "p1", "--json"], False),
        ("POST", "/plans/p1/review/handoff", {}, ["review", "handoff", *c, "--plan", "p1", "--json"], False),
        ("POST", "/transfer/verify", {"canonical": "/canon", "plan": "p1"},
         ["transfer", "verify", *c, "--plan", "p1", "--canonical", "/canon", "--json"], False),
        ("POST", "/transfer/bind", {"canonical": "/canon"},
         ["transfer", "bind", *c, "--canonical", "/canon", "--json"], False),
    ]


def _parse(argv: list[str]):
    ns = sn_cli.build_parser().parse_args(argv)
    d = {k: v for k, v in vars(ns).items() if not callable(v)}
    return d


def test_every_route_builds_the_documented_cli_argv(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    client = client_for(root, monkeypatch)
    seen: list[list[str]] = []

    async def fake_json(argv, *, cwd=None, timeout_seconds=30.0):
        seen.append(argv)
        return {"ok": True}

    def fake_stream(argv):
        seen.append(argv)
        return {"streamed": True}

    monkeypatch.setattr(router_mod, "_run_json", fake_json)
    monkeypatch.setattr(router_mod, "_stream", fake_stream)
    # model flags are resolved from config at the route edge; compare them separately
    for method, path, body, cli, streamed in _expected_cli(root):
        seen.clear()
        r = client.request(method, BASE + path, json=body) if body is not None else client.request(method, BASE + path)
        assert r.status_code == 200, (path, r.text)
        (argv,) = seen
        assert argv[:2] == [console_script("summary_native"), "delta"]
        got = _parse([a for a in argv[1:]])
        want = _parse(["delta", *cli])
        if "backend" in got:  # config-resolved, not in the documented invocation
            got["backend"], got["model"] = want.get("backend"), want.get("model")
        assert got == want, (method, path)
        assert ("--json" in argv) is (not streamed), path


def test_empty_sources_and_missing_plan_refuse_before_spawn(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    client = client_for(root, monkeypatch)
    r = client.post(f"{BASE}/plans", json={"sources": [], "product": ["npc"]})
    assert r.status_code == 400 and "does not default to all chapters" in r.text
    r = client.post(f"{BASE}/associations/a1/decision", json={"decision": "approve"})
    assert r.status_code == 400 and "--plan" in r.text
    r = client.post(f"{BASE}/plans/p1/npc/publish", json={"members": []})
    assert r.status_code == 400 and "explicit member list" in r.text


def _sequence(root, face):
    """plan -> census -> decision -> receipt through one face, from a clean delta tree."""
    import shutil
    shutil.rmtree(root / "docs" / "summaries" / "delta", ignore_errors=True)
    source = str(root / "docs" / "summaries" / "003-the-new-fire.md")
    plan = face("POST", "/plans", {"sources": [source], "product": ["npc"]},
                ["plan", "--product", "npc", "--source", source])
    pid = plan["plan_id"]
    cli_json(["delta", "census", "--campaign-dir", str(root), "--plan", pid, "--json"])
    store = root / "docs" / "summaries" / "delta" / "associations" / f"{pid}.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(_association_store(pid)), encoding="utf-8")
    decision = face("POST", "/associations/assoc-1/decision",
                    {"plan": pid, "decision": "approve", "reason": "same table", "reviewer": "gm"},
                    ["associate", "decide", "assoc-1", "--plan", pid, "--decision", "approve",
                     "--reason", "same table", "--reviewer", "gm"])
    from pipelines.summary_native.delta import run as run_mod
    plan_rec = _load(root, pid)
    run_mod.save_run(run_mod.RunState(run_id=f"run-{pid}", plan_ref=f"{pid}-r{plan_rec.revision}"),
                     run_mod.run_path(root, pid))
    receipt = face("GET", f"/plans/{pid}/receipt", None, ["receipt", "--plan", pid])
    return plan, decision, receipt


def test_plan_decision_and_receipt_records_match_cli(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    init_identity(root)
    client = client_for(root, monkeypatch)

    def via_cli(method, path, body, cli):
        code, rec = cli_json(_cli_argv(cli, root))
        assert code == 0, rec
        return rec

    def via_http(method, path, body, cli):
        r = client.request(method, BASE + path, json=body) if body is not None else client.request(method, BASE + path)
        assert r.status_code == 200, r.text
        return r.json()

    cli_records = _sequence(root, via_cli)
    http_records = _sequence(root, via_http)
    for c, h in zip(cli_records, http_records):
        assert normalise(c, (root,)) == normalise(h, (root,))
    assert cli_records[0]["plan_id"] == http_records[0]["plan_id"]


def _cli_argv(cli, root):
    head = 2 if cli[0] == "associate" else 1
    return ["delta", *cli[:head], "--campaign-dir", str(root), *cli[head:], "--json"]


def _load(root, pid):
    from pipelines.summary_native.delta import plan as dplan
    return dplan.load_plan(dplan.plans_dir(root), pid)


def _association_store(pid):
    from pipelines.summary_native.delta import associations as A
    store = A.AssocStore(plan_id=pid, associations=[A.Association(
        id="assoc-1", name="the Envoy", canonical_id="envoy-sella-marr",
        source=A.AssocSource(path="docs/summaries/003-the-new-fire.md", revision="0" * 64, scene="003.01",
                             span="the Envoy"),
        relationship_support="same speaker", scope="faction offer")])
    return store.model_dump(mode="json")
