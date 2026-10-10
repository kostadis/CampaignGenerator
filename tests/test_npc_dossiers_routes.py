"""NPC dossiers routes (spec 032 T047).

Every run route builds its argv from ``console_script("summary_native")`` in a
``_build_*_cmd`` function, refuses with 400 before spawning, reads stored config
at the route edge, and never writes. ``/state`` and ``/file`` read files only.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipelines.summary_native import npc_slug, schema  # noqa: E402
from pipelines.summary_native.freshness import manual_sha  # noqa: E402
from server.grounding_config_service import GroundingConfigService  # noqa: E402
from server.main import app  # noqa: E402
from server.npc_dossiers_config import NpcDossiersConfigService  # noqa: E402
from server.platform_config_service import PlatformConfigService  # noqa: E402
from server.routers import npc_dossiers as router_mod  # noqa: E402
from server.subprocess_runner import console_script  # noqa: E402
from tests.conftest_npc import SINCE, UNTIL, npc_campaign, run_cli  # noqa: E402

client = TestClient(app)
BASE = "/api/npc-dossiers"
RANGE = {"summaries_dir": "docs/summaries", "since": SINCE, "until": UNTIL}
ROUTER_SRC = Path(router_mod.__file__)


@pytest.fixture
def campaign(monkeypatch, tmp_path):
    root = npc_campaign(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(app.state, "platform", PlatformConfigService(root), raising=False)
    captured: dict = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        captured["cmd"] = cmd
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover

    monkeypatch.setattr("server.routers.grounding.stream_subprocess", fake_stream_subprocess)
    return root, captured


def _run(path: str, params: dict | None = None) -> int:
    r = client.get(f"{BASE}{path}", params=params or {})
    _ = r.text
    return r.status_code


def _flag(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


def _after(cmd: list[str], flag: str) -> list[str]:
    i = cmd.index(flag) + 1
    out = []
    while i < len(cmd) and not cmd[i].startswith("--"):
        out.append(cmd[i])
        i += 1
    return out


# ── argv builders: the exact argv of contracts/http.md ─────────────────────

def test_build_link_cmd():
    cmd = router_mod._build_link_cmd("docs/s", 2, 6)
    assert cmd == [console_script("summary_native"), "npc-link",
                   "--summaries-dir", "docs/s", "--since", "2", "--until", "6"]
    assert router_mod._build_link_cmd("docs/s", 2, 6, force=True)[-1] == "--force"


def test_build_draft_cmd_all_and_narrowed():
    common = dict(max_tokens=100, mode="chunked", chunk_chars=50, dump_only=False, force=False,
                  selection_args=["--backend", "dgx", "--model", "m"])
    cmd = router_mod._build_draft_cmd("d", 2, 6, select="all", names=[], recent_chapters=None,
                                      recurring_min=None, **common)
    assert cmd[:2] == [console_script("summary_native"), "npc-draft"]
    assert "--all" in cmd and "--name" not in cmd and "--recent-chapters" not in cmd
    assert cmd[-4:] == ["--backend", "dgx", "--model", "m"]
    assert _flag(cmd, "--mode") == "chunked" and _flag(cmd, "--chunk-chars") == "50"
    assert _flag(cmd, "--max-tokens") == "100"
    cmd = router_mod._build_draft_cmd("d", 2, 6, select="narrowed", names=["A", "B C"], recent_chapters=3,
                                      recurring_min=7, **{**common, "dump_only": True, "force": True})
    assert "--all" not in cmd
    assert _after(cmd, "--name") == ["A", "B C"]
    assert _flag(cmd, "--recent-chapters") == "3" and _flag(cmd, "--recurring-min") == "7"
    assert "--dump-only" in cmd and "--force" in cmd


def test_build_verify_compose_publish_cmds():
    assert router_mod._build_verify_cmd("d", 2, 6, names=[])[1] == "npc-verify"
    assert _after(router_mod._build_verify_cmd("d", 2, 6, names=["A", "B"]), "--name") == ["A", "B"]
    cmd = router_mod._build_compose_cmd("d", 2, 6, names=["A"], init=["B", "C"])
    assert cmd[1] == "npc-compose" and _after(cmd, "--name") == ["A"] and _after(cmd, "--init") == ["B", "C"]
    pub = lambda **k: router_mod._build_publish_cmd("d", 2, 6, source="", force=False, names=[], **k)  # noqa: E731
    assert "--all" in pub(select="all") and "--authored-all" not in pub(select="all")
    assert "--authored-all" in pub(select="authored_all")
    named = router_mod._build_publish_cmd("d", 2, 6, select="named", names=["A"], source="hand-built", force=True)
    assert named[1] == "npc-publish" and _after(named, "--name") == ["A"]
    assert _flag(named, "--source") == "hand-built" and "--force" in named and "--all" not in named


def test_scheduler_builders_carry_resume_parallel_and_endpoints():
    draft = router_mod._build_draft_cmd("d", 2, 6, select="all", names=[], recent_chapters=None,
                                        recurring_min=None, max_tokens=100, mode="one-shot", chunk_chars=50,
                                        dump_only=False, force=False, selection_args=["--backend", "dgx", "--model", "m"],
                                        endpoints=["http://spark-a/v1"], parallel=3, resume="run-17")
    assert _after(draft, "--endpoints") == ["http://spark-a/v1"]
    assert _flag(draft, "--parallel") == "3" and _flag(draft, "--resume") == "run-17"
    verify = router_mod._build_verify_cmd("d", 2, 6, names=["A"], parallel=2, resume="run-18")
    assert _flag(verify, "--parallel") == "2" and _flag(verify, "--resume") == "run-18"


def test_scheduler_routes_forward_draft_and_local_verify_controls(campaign, monkeypatch):
    _, captured = campaign
    from fastapi.responses import JSONResponse
    monkeypatch.setattr("server.routers.npc_dossiers._sse_response",
                        lambda cmd: (captured.update(cmd=cmd), JSONResponse({"ok": True}))[1])
    assert _run("/run/draft", {**RANGE, "select": "all", "backend": "dgx", "model": "qwen3.8-flash-next",
                                "endpoints": ["http://spark-a/v1", "http://spark-b/v1"], "parallel": 3,
                                "resume": "draft-17"}) == 200
    assert _after(captured["cmd"], "--endpoints") == ["http://spark-a/v1", "http://spark-b/v1"]
    assert _flag(captured["cmd"], "--parallel") == "3" and _flag(captured["cmd"], "--resume") == "draft-17"
    assert _run("/run/verify", {**RANGE, "name": ["Jimjar"], "parallel": 2, "resume": "verify-17"}) == 200
    assert "--endpoints" not in captured["cmd"]
    assert _flag(captured["cmd"], "--parallel") == "2" and _flag(captured["cmd"], "--resume") == "verify-17"


@pytest.mark.parametrize("params", [
    {"select": ""}, {"select": "all", "parallel": 0},
    {"select": "all", "resume": "draft-17", "force": True},
    {"select": "all", "resume": "draft-17", "dump_only": True},
])
def test_draft_scheduler_refuses_empty_selection_and_invalid_combinations(campaign, params):
    _, captured = campaign
    response = client.get(f"{BASE}/run/draft", params={**RANGE, **params})
    assert response.status_code == 400 and "cmd" not in captured


def test_draft_endpoints_refuse_a_non_dgx_backend(campaign):
    _, captured = campaign
    response = client.get(f"{BASE}/run/draft", params={**RANGE, "select": "all", "backend": "openrouter",
                                                         "model": "vendor/model", "endpoints": ["http://spark/v1"]})
    assert response.status_code == 400 and "--endpoints" in response.json()["detail"] and "cmd" not in captured


def test_npc_scheduler_status_reads_draft_and_verify_journals_after_reload(campaign):
    root, _ = campaign
    draft_record = root / schema.DEFAULT_NPC_ROOT / f"ch{SINCE:03d}-{UNTIL:03d}" / "runs" / "draft-17" / "record.json"
    draft_record.parent.mkdir(parents=True)
    draft_record.write_text(json.dumps({
        "schema": 2, "run_id": "draft-17", "status": "incomplete", "npcs": {"npc_jimjar": {"status": "cached"}, "npc_eldeth": {"status": "pending"}},
        "concurrency": {"value": 8, "source": "dgxlib", "model": "qwen3.8-flash-next"},
        "endpoints": [{"endpoint_id": "spark-a", "state": "quarantined", "active_count": 0, "limit": 8}],
        "failures": {"npc_eldeth": {"category": "transport", "code": "timeout"}},
    }), encoding="utf-8")
    response = client.get(f"{BASE}/status/draft", params={"since": SINCE, "until": UNTIL})
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "draft-17" and body["counts"] == {"total": 2, "cached": 1, "completed": 0, "unfinished": 1, "failed": 1}
    assert body["endpoints"] == [{"endpoint_id": "spark-a", "state": "quarantined", "active_count": 0, "limit": 8, "id": "spark-a", "active": 0}]
    # A page reload reconstructs this projection from the journal; no browser
    # state is needed to retain the explicit run identity or quarantine.
    assert client.get(f"{BASE}/status/draft", params={"since": SINCE, "until": UNTIL}).json() == body
    verify_record = root / schema.DEFAULT_NPC_ROOT / f"ch{SINCE:03d}-{UNTIL:03d}" / "verify_runs" / "verify-17" / "record.json"
    verify_record.parent.mkdir(parents=True)
    verify_record.write_text(json.dumps({"schema": 2, "run_id": "verify-17", "operation": "npc-verify", "status": "completed",
                                         "items": [{"id": "npc_jimjar", "key": "x"}], "results": {"npc_jimjar": {"result": {}}}}), encoding="utf-8")
    verified = client.get(f"{BASE}/status/verify", params={"since": SINCE, "until": UNTIL}).json()
    assert verified["run_id"] == "verify-17" and verified["counts"]["completed"] == 1


# ── run routes: argv through the live route ────────────────────────────────

@pytest.mark.parametrize("path,sub,extra", [
    ("/run/link", "npc-link", {}),
    ("/run/draft", "npc-draft", {"select": "all"}),
    ("/run/verify", "npc-verify", {}),
    ("/run/compose", "npc-compose", {}),
    ("/run/publish", "npc-publish", {"select": "all"}),
])
def test_every_run_route_uses_the_console_script(campaign, path, sub, extra):
    _, captured = campaign
    assert _run(path, {**RANGE, **extra}) == 200
    cmd = captured["cmd"]
    assert cmd[0] == console_script("summary_native") and cmd[1] == sub
    assert _flag(cmd, "--summaries-dir") == "docs/summaries"
    assert (_flag(cmd, "--since"), _flag(cmd, "--until")) == (str(SINCE), str(UNTIL))
    for banned in ("--registry", "--canon", "--out-root", "--npc-root"):
        assert banned not in cmd


def test_draft_all_carries_the_resolved_backend_model_and_defaults(campaign):
    _, captured = campaign
    assert _run("/run/draft", {**RANGE, "select": "all"}) == 200
    cmd = captured["cmd"]
    assert "--all" in cmd
    assert _flag(cmd, "--backend") == schema.DEFAULT_DRAFT_BACKEND
    assert _flag(cmd, "--model") == schema.DEFAULT_DRAFT_MODEL
    assert _flag(cmd, "--mode") == schema.DEFAULT_DRAFT_MODE
    assert _flag(cmd, "--chunk-chars") == str(schema.DEFAULT_CHUNK_CHARS)
    assert _flag(cmd, "--max-tokens") == str(schema.DEFAULT_MAX_TOKENS)
    assert cmd.count("--model") == 1 and cmd.count("--backend") == 1


def test_draft_stored_config_reaches_the_command_and_a_request_beats_it(campaign):
    root, captured = campaign
    NpcDossiersConfigService(root / "config").put_config(
        router_mod.NpcDossiersConfig.model_validate({
            "max_tokens": 9000, "draft": {"backend": "openrouter", "model": "or/model",
                                          "mode": "one-shot", "chunk_chars": 7}}))
    assert _run("/run/draft", {**RANGE, "select": "all"}) == 200
    cmd = captured["cmd"]
    assert (_flag(cmd, "--backend"), _flag(cmd, "--model")) == ("openrouter", "or/model")
    assert (_flag(cmd, "--mode"), _flag(cmd, "--chunk-chars"), _flag(cmd, "--max-tokens")) == ("one-shot", "7", "9000")
    assert _run("/run/draft", {**RANGE, "select": "all", "backend": "dgx", "model": "other",
                               "mode": "chunked", "chunk_chars": 11, "max_tokens": 5}) == 200
    cmd = captured["cmd"]
    assert (_flag(cmd, "--backend"), _flag(cmd, "--model")) == ("dgx", "other")
    assert (_flag(cmd, "--mode"), _flag(cmd, "--chunk-chars"), _flag(cmd, "--max-tokens")) == ("chunked", "11", "5")


def test_the_selection_override_beats_the_draft_block(campaign):
    root, captured = campaign
    svc = NpcDossiersConfigService(root / "config")
    svc.put_config(router_mod.NpcDossiersConfig.model_validate(
        {"selection": {"backend": "openrouter", "model": "sel/model"}}))
    assert _run("/run/draft", {**RANGE, "select": "all"}) == 200
    assert (_flag(captured["cmd"], "--backend"), _flag(captured["cmd"], "--model")) == ("openrouter", "sel/model")


def test_narrowed_by_name_sends_only_the_names(campaign):
    _, captured = campaign
    assert _run("/run/draft", {**RANGE, "select": "narrowed", "name": ["Jimjar", "Eldeth Feldrun"],
                               "dump_only": True, "force": True}) == 200
    cmd = captured["cmd"]
    assert _after(cmd, "--name") == ["Jimjar", "Eldeth Feldrun"]
    assert "--recent-chapters" not in cmd and "--recurring-min" not in cmd and "--all" not in cmd
    assert "--dump-only" in cmd and "--force" in cmd


def test_narrowed_with_nothing_to_narrow_by_uses_the_stored_thresholds_never_all(campaign):
    root, captured = campaign
    NpcDossiersConfigService(root / "config").put_config(
        router_mod.NpcDossiersConfig.model_validate({"recent_chapters": 2, "recurring_min": 3}))
    assert _run("/run/draft", {**RANGE, "select": "narrowed"}) == 200
    cmd = captured["cmd"]
    assert "--all" not in cmd
    assert (_flag(cmd, "--recent-chapters"), _flag(cmd, "--recurring-min")) == ("2", "3")
    # An explicit zero is an answer ("every chapter"), not "unset".
    assert _run("/run/draft", {**RANGE, "select": "narrowed", "recent_chapters": 0, "recurring_min": 5}) == 200
    assert (_flag(captured["cmd"], "--recent-chapters"), _flag(captured["cmd"], "--recurring-min")) == ("0", "5")


def test_compose_and_verify_names_and_init(campaign):
    _, captured = campaign
    assert _run("/run/verify", {**RANGE, "name": ["Jimjar"]}) == 200
    assert _after(captured["cmd"], "--name") == ["Jimjar"]
    assert _run("/run/compose", {**RANGE, "init": ["Jimjar", "Eldeth Feldrun"]}) == 200
    assert _after(captured["cmd"], "--init") == ["Jimjar", "Eldeth Feldrun"] and "--name" not in captured["cmd"]
    assert _run("/run/compose", {**RANGE, "name": ["Jimjar"]}) == 200
    assert _after(captured["cmd"], "--name") == ["Jimjar"] and "--init" not in captured["cmd"]


def test_publish_selection_source_and_force(campaign):
    _, captured = campaign
    assert _run("/run/publish", {**RANGE, "select": "named", "name": ["Jimjar"], "source": "hand-built",
                                 "force": True}) == 200
    cmd = captured["cmd"]
    assert _after(cmd, "--name") == ["Jimjar"] and _flag(cmd, "--source") == "hand-built" and "--force" in cmd
    assert _run("/run/publish", {**RANGE, "select": "authored_all"}) == 200
    assert "--authored-all" in captured["cmd"] and "--name" not in captured["cmd"]


def test_stored_range_and_dir_come_from_grounding_yaml(campaign):
    root, captured = campaign
    GroundingConfigService(root / "config").update_config({"summary_native": {
        "summaries_dir": "docs/stored", "range_since": 3, "range_until": 5}})
    assert _run("/run/link") == 200
    assert _flag(captured["cmd"], "--summaries-dir") == "docs/stored"
    assert (_flag(captured["cmd"], "--since"), _flag(captured["cmd"], "--until")) == ("3", "5")


# ── refusals: 400, and nothing is spawned ──────────────────────────────────

@pytest.mark.parametrize("path,extra", [
    ("/run/link", {}),
    ("/run/draft", {"select": "all"}),
    ("/run/verify", {}),
    ("/run/compose", {}),
    ("/run/publish", {"select": "all"}),
])
def test_missing_range_is_400_and_never_spawns(campaign, path, extra):
    _, captured = campaign
    r = client.get(f"{BASE}{path}", params={"summaries_dir": "docs/summaries", **extra})
    assert r.status_code == 400 and "choose a chapter range" in r.json()["detail"]
    assert "cmd" not in captured


@pytest.mark.parametrize("path", ["/run/link", "/run/draft", "/run/verify", "/run/compose", "/run/publish"])
def test_missing_summaries_dir_is_400(campaign, path):
    _, captured = campaign
    r = client.get(f"{BASE}{path}", params={"since": 2, "until": 6, "select": "all"})
    assert r.status_code == 400 and "cmd" not in captured


@pytest.mark.parametrize("select", [None, "", "everyone"])
def test_draft_without_a_valid_select_is_400(campaign, select):
    _, captured = campaign
    params = {**RANGE, **({"select": select} if select is not None else {})}
    r = client.get(f"{BASE}/run/draft", params=params)
    assert r.status_code == 400 and "select" in r.json()["detail"]
    assert "cmd" not in captured


@pytest.mark.parametrize("select", [None, "", "everyone"])
def test_publish_without_a_valid_select_is_400(campaign, select):
    _, captured = campaign
    params = {**RANGE, **({"select": select} if select is not None else {})}
    r = client.get(f"{BASE}/run/publish", params=params)
    assert r.status_code == 400 and "cmd" not in captured


def test_publish_named_without_names_and_bad_source_are_400(campaign):
    _, captured = campaign
    assert client.get(f"{BASE}/run/publish", params={**RANGE, "select": "named"}).status_code == 400
    assert client.get(f"{BASE}/run/publish", params={**RANGE, "select": "all", "source": "bogus"}).status_code == 400
    assert client.get(f"{BASE}/run/draft", params={**RANGE, "select": "all", "mode": "bogus"}).status_code == 400
    assert client.get(f"{BASE}/run/draft", params={**RANGE, "select": "all", "chunk_chars": -1}).status_code == 400
    assert "cmd" not in captured


# ── read-only: /chapters /state /report /file ──────────────────────────────

def _link(root):
    rc, _, err = run_cli(["npc-link", "--config", str(root / "config/config.yaml"),
                          "--summaries-dir", str(root / "docs/summaries"),
                          "--since", str(SINCE), "--until", str(UNTIL)])
    assert rc == 0, err


def _out(root):
    return root / schema.DEFAULT_NPC_ROOT / f"ch{SINCE:03d}-{UNTIL:03d}"


def test_chapters_shares_the_summary_native_listing(campaign):
    r = client.get(f"{BASE}/chapters", params={"summaries_dir": "docs/summaries"})
    same = client.get("/api/grounding/summary-native/chapters", params={"summaries_dir": "docs/summaries"})
    assert r.status_code == 200 and r.json() == same.json() and r.json()["present"]
    assert client.get(f"{BASE}/chapters").status_code == 400
    assert client.get(f"{BASE}/chapters", params={"summaries_dir": "nope"}).status_code == 404


def test_state_before_linking_is_empty_and_unlinked(campaign):
    r = client.get(f"{BASE}/state", params={"since": SINCE, "until": UNTIL})
    assert r.status_code == 200
    assert r.json() == {"range": f"{SINCE}-{UNTIL}", "linked": False, "link_stale": False,
                        "warnings": {"ambiguous": 0, "generic_unruled": 0}, "npcs": []}
    assert client.get(f"{BASE}/state").status_code == 400
    assert client.get(f"{BASE}/report/link", params={"since": SINCE, "until": UNTIL}).status_code == 404


def test_state_shape_after_linking_with_a_draft_a_verdict_and_a_dropped_edit(campaign):
    root, _ = campaign
    _link(root)
    body = client.get(f"{BASE}/state", params={"since": SINCE, "until": UNTIL}).json()
    assert body["linked"] is True and body["link_stale"] is False
    assert set(body["warnings"]) == {"ambiguous", "generic_unruled"}
    keys = {"stem", "subject", "global", "exclusion", "n_entries", "n_scenes", "n_moments", "first_seen",
            "last_seen", "draft", "published", "verify", "authored", "composed", "manual_dropped"}
    assert body["npcs"] and all(set(n) == keys for n in body["npcs"])
    assert {n["draft"] for n in body["npcs"]} == {"none"}
    assert {n["verify"] for n in body["npcs"]} == {"none"}
    jim = next(n for n in body["npcs"] if n["subject"] == "Jimjar")

    out = _out(root)
    (out / "draft").mkdir()
    (out / "draft" / f"{jim['stem']}.md").write_text("<!-- summary_native npc draft | npc: Jimjar -->\n## Identity\n")
    (out / "draft" / f"{jim['stem']}.verify.md").write_text(
        "# Verification: Jimjar\n\n**Verdict: fail**\n\n## Manual edits\n\n"
        "- [manual 1] used\n  - line 3: x\n- [manual 2] He has a bet.\n  - DROPPED: not cited anywhere in the draft\n")
    (out / "gm").mkdir()
    (out / "gm" / f"{jim['stem']}.md").write_text("gm")
    authored = root / schema.AUTHORED_DIR
    authored.mkdir(parents=True)
    (authored / f"{npc_slug.slug_for('Jimjar')}.authored.yaml").write_text("subject: Jimjar\n")
    jim = next(n for n in client.get(f"{BASE}/state", params={"since": SINCE, "until": UNTIL}).json()["npcs"]
               if n["subject"] == "Jimjar")
    assert (jim["draft"], jim["verify"], jim["authored"], jim["composed"], jim["published"]) == (
        "drafted", "fail", True, True, False)
    assert jim["manual_dropped"] == [{"n": 2, "text": "He has a bet."}]

    npcs = root / schema.NPCS_DIR
    (npcs / "jimjar.md").write_text(f"{schema.PUBLISH_HEADER_PREFIX} | x -->\nbody\n")
    assert next(n for n in client.get(f"{BASE}/state", params={"since": SINCE, "until": UNTIL}).json()["npcs"]
                if n["subject"] == "Jimjar")["published"] is True
    (out / "draft" / f"{jim['stem']}.md").unlink()
    (out / "draft" / f"{jim['stem']}.incomplete.md").write_text("x")
    assert next(n for n in client.get(f"{BASE}/state", params={"since": SINCE, "until": UNTIL}).json()["npcs"]
                if n["subject"] == "Jimjar")["draft"] == "incomplete"


def test_state_marks_a_draft_stale_when_the_manual_edits_changed(campaign):
    root, _ = campaign
    _link(root)
    out = _out(root)
    stem = next(n["stem"] for n in client.get(f"{BASE}/state", params={"since": SINCE, "until": UNTIL}).json()["npcs"]
                if n["subject"] == "Jimjar")
    (out / "draft").mkdir()
    sha = manual_sha([])
    (out / "draft" / f"{stem}.md").write_text(f"<!-- summary_native npc draft | manual sha256: {sha} -->\n")

    def status():
        return next(n["draft"] for n in client.get(f"{BASE}/state", params={"since": SINCE, "until": UNTIL}).json()["npcs"]
                    if n["stem"] == stem)

    assert status() == "drafted"
    authored = root / schema.AUTHORED_DIR
    authored.mkdir(parents=True)
    (authored / "jimjar.authored.yaml").write_text("subject: Jimjar\nmanual:\n  - a new edit\n")
    assert status() == "stale"


def _stale(root=None):
    return client.get(f"{BASE}/state", params={"since": SINCE, "until": UNTIL}).json()["link_stale"]


def test_state_link_stale_follows_the_clis_own_rule(campaign):
    root, _ = campaign
    _link(root)
    assert _stale() is False
    players = root / "config" / "players.yaml"
    original = players.read_text()
    players.write_text(original + "\n# changed\n")
    assert _stale() is True
    players.write_text(original)
    assert _stale() is False
    reg = root / "docs" / "entity_registry.yaml"
    reg_text = reg.read_text()
    reg.write_text(reg_text + "\n# changed\n")
    assert _stale() is True
    reg.write_text(reg_text)
    manifest = root / "docs/summary_native" / f"ch{SINCE:03d}-{UNTIL:03d}" / "manifest.json"
    manifest.write_text(manifest.read_text() + " ")
    assert _stale() is True


def test_link_and_verify_reports(campaign):
    root, _ = campaign
    _link(root)
    r = client.get(f"{BASE}/report/link", params={"since": SINCE, "until": UNTIL})
    assert r.status_code == 200 and r.json()["kind"] == "npc_link_report"
    assert client.get(f"{BASE}/report/verify/npc_jimjar", params={"since": SINCE, "until": UNTIL}).status_code == 404
    (_out(root) / "draft").mkdir()
    (_out(root) / "draft" / "npc_jimjar.verify.md").write_text("# Verification: Jimjar\n\n**Verdict: pass**\n")
    r = client.get(f"{BASE}/report/verify/npc_jimjar", params={"since": SINCE, "until": UNTIL})
    assert r.status_code == 200 and r.json()["verdict"] == "pass" and "Verification" in r.json()["markdown"]
    from fastapi import HTTPException
    for bad in ("../x", "a/b", "..", "", "x y"):
        with pytest.raises(HTTPException) as exc:
            router_mod._stem(bad)
        assert exc.value.status_code == 400


def test_file_serves_each_kind_read_only(campaign):
    root, _ = campaign
    _link(root)
    out = _out(root)
    stem = next(n["stem"] for n in client.get(f"{BASE}/state", params={"since": SINCE, "until": UNTIL}).json()["npcs"]
                if n["subject"] == "Jimjar")
    get = lambda kind, st=stem: client.get(f"{BASE}/file", params={"since": SINCE, "until": UNTIL,  # noqa: E731
                                                                   "kind": kind, "stem": st})
    r = get("evidence")
    assert r.status_code == 200 and "Jimjar" in r.json()["text"]
    assert get("draft").status_code == 404 and get("gm").status_code == 404 and get("published").status_code == 404
    (out / "draft").mkdir()
    (out / "draft" / f"{stem}.incomplete.md").write_text("INCOMPLETE")
    assert get("draft").json()["text"] == "INCOMPLETE"
    (out / "gm").mkdir()
    (out / "gm" / f"{stem}.md").write_text("GM")
    assert get("gm").json()["text"] == "GM"
    (root / schema.NPCS_DIR / "jimjar.md").write_text("PUB")
    assert get("published").json()["text"] == "PUB"
    assert get("bogus").status_code == 400
    assert get("evidence", "../../config/config").status_code == 400
    assert get("evidence", "npc_nobody").status_code == 404
    # No write verb exists on any of these routes.
    for verb in (client.post, client.put, client.delete, client.patch):
        for path in ("/file", "/state", "/report/link", "/run/draft", "/run/publish"):
            assert verb(f"{BASE}{path}").status_code in (404, 405, 422)


# ── nothing here writes the authored directory ─────────────────────────────

def test_the_router_has_no_mutating_call_and_never_names_the_authored_dir():
    tree = ast.parse(ROUTER_SRC.read_text(encoding="utf-8"))
    mutating = {"write_text", "write_bytes", "atomic_write_text", "replace", "rename", "unlink", "rmtree",
                "mkdir", "makedirs", "touch", "copy", "copyfile", "move", "init_authored"}
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if name in mutating or (name == "open" and any(
                    isinstance(a, ast.Constant) and isinstance(a.value, str) and set(a.value) & set("wax+")
                    for a in n.args[1:2])):
                bad.append((n.lineno, name))
        if isinstance(n, ast.Attribute) and n.attr == "AUTHORED_DIR":
            bad.append((n.lineno, "AUTHORED_DIR"))
    assert not bad, bad


def test_running_the_state_and_file_routes_leaves_the_authored_tree_byte_identical(campaign):
    from tests.conftest_npc import sha_tree
    root, _ = campaign
    authored = root / schema.AUTHORED_DIR
    authored.mkdir(parents=True)
    (authored / "jimjar.authored.yaml").write_text("subject: Jimjar\nsecrets: s\n")
    (authored / "x.md").write_text("hand built")
    _link(root)
    before = sha_tree(authored)
    client.get(f"{BASE}/state", params={"since": SINCE, "until": UNTIL})
    client.get(f"{BASE}/file", params={"since": SINCE, "until": UNTIL, "kind": "evidence", "stem": "npc_jimjar"})
    _run("/run/compose", {**RANGE, "init": ["Jimjar"]})  # fake spawn: the route itself must not write
    assert sha_tree(authored) == before


def test_the_migration_has_no_route():
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any("migrat" in p and "npc" in p for p in paths)
