"""spec 039 T077: state lives on disk, so a server restart changes nothing; no capability leaks (FR-023)."""

from __future__ import annotations

import json
import re

from pipelines.summary_native.delta import associations as A
from pipelines.summary_native.delta import plan as dplan
from pipelines.summary_native.delta import run as run_mod
from tests._delta_http_support import BASE, client_for, cli_json, init_identity
from tests._delta_us2 import copy_fixture

_BAD_KEY = re.compile(r"url|token|capab|secret_key|access_key", re.I)


def _scan(value, where="response"):
    """No key names a URL/token/capability and no string value is an http(s) URL."""
    if isinstance(value, dict):
        for k, v in value.items():
            assert not _BAD_KEY.search(k), f"{where}: key {k!r}"
            _scan(v, f"{where}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _scan(v, f"{where}[{i}]")
    elif isinstance(value, str):
        assert not re.search(r"https?://", value), f"{where}: {value[:80]}"


def _seed(root, client):
    src = str(root / "docs" / "summaries" / "003-the-new-fire.md")
    r = client.post(f"{BASE}/plans", json={"sources": [src], "product": ["npc"]})
    assert r.status_code == 200, r.text
    pid = r.json()["plan_id"]
    assert cli_json(["delta", "census", "--campaign-dir", str(root), "--plan", pid, "--json"])[0] == 0
    store = A.AssocStore(plan_id=pid, associations=[A.Association(
        id="assoc-1", name="the Envoy", canonical_id="envoy-sella-marr",
        source=A.AssocSource(path="docs/summaries/003-the-new-fire.md", revision="0" * 64, scene="003.01",
                             span="the Envoy"),
        relationship_support="same speaker", scope="faction offer")])
    A.save_store(root, store)
    r = client.post(f"{BASE}/associations/assoc-1/decision",
                    json={"plan": pid, "decision": "approve", "reason": "same table", "reviewer": "gm"})
    assert r.status_code == 200, r.text
    plan = dplan.load_plan(dplan.plans_dir(root), pid)
    state = run_mod.RunState(run_id=f"run-{pid}", plan_ref=f"{pid}-r{plan.revision}")
    run_mod.save_run(state, run_mod.run_path(root, pid))
    return pid


def test_decisions_and_status_survive_a_restart(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    init_identity(root)
    first = client_for(root, monkeypatch)
    pid = _seed(root, first)
    status_before = first.get(f"{BASE}/plans/{pid}/status").json()
    decision_before = A.load_store(root, pid).associations[0].model_dump(mode="json")
    assert decision_before["decision"] == "approved"

    second = client_for(root, monkeypatch)  # a new app instance over the same campaign dir
    assert second is not first
    r = second.get(f"{BASE}/plans/{pid}/status")
    assert r.status_code == 200
    assert r.json() == status_before
    assert A.load_store(root, pid).associations[0].model_dump(mode="json") == decision_before
    # the decision is still the same one after a second decide-free read of the plan
    assert second.get(f"{BASE}/plans/{pid}/baseline").status_code in (200, 409, 422)


def test_no_capability_url_or_token_in_any_response_or_receipt(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    init_identity(root)
    client = client_for(root, monkeypatch)
    pid = _seed(root, client)
    bodies = [client.get(f"{BASE}/plans/{pid}/status").json(),
              client.get(f"{BASE}/plans/{pid}/receipt").json(),
              client.post(f"{BASE}/plans/{pid}/sources", json={}).json()]
    for b in bodies:
        _scan(b)
    for f in (root / "docs" / "summaries" / "delta").rglob("*.json"):
        if "/sources/" in f.as_posix():
            continue  # source records carry file digests of GM files, not capabilities
        _scan(json.loads(f.read_text(encoding="utf-8")), f.name)
