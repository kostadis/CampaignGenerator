"""summary_native routes (feature 031, US5).

Every run route must build its argv from ``console_script("summary_native")``,
resolve stored config the way ``tests/test_grounding_routes_config.py`` does
(explicit request value wins, else grounding.yaml), refuse with 400 before
spawning, and never pass the three CLI-only flags (contracts/http.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.grounding_config_service import GroundingConfigService  # noqa: E402
from server.main import app  # noqa: E402
from server.platform_config_service import (  # noqa: E402
    TRACKED_CONFIG_NAME,
    PlatformConfigService,
)
from server.subprocess_runner import console_script  # noqa: E402

client = TestClient(app)

BASE = "/api/grounding/summary-native"


@pytest.fixture
def campaign(monkeypatch, tmp_path):
    cfgdir = tmp_path / "config"
    cfgdir.mkdir()
    (cfgdir / TRACKED_CONFIG_NAME).write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(app.state, "platform", PlatformConfigService(tmp_path), raising=False)
    captured: dict = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        captured["cmd"] = cmd
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover - makes this an async generator

    # _sse_response lives in the grounding router; the seam is its global.
    monkeypatch.setattr("server.routers.grounding.stream_subprocess", fake_stream_subprocess)
    return tmp_path, GroundingConfigService(cfgdir), captured


def _run(path: str, params: dict | None = None) -> int:
    r = client.get(f"{BASE}{path}", params=params or {})
    _ = r.text  # drain the SSE generator so the fake subprocess runs
    return r.status_code


def _flag(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


RANGE = {"summaries_dir": "docs/summaries", "since": 3, "until": 9}


# ── argv construction ──────────────────────────────────────────────────────

@pytest.mark.parametrize("path,sub", [
    ("/run/validate", ["validate"]),
    ("/run/build", ["build"]),
    ("/run/synth/world_state", ["synth", "world_state"]),
    ("/run/compare/campaign_state", ["compare", "campaign_state"]),
    ("/run/annotate/world_state", ["annotate", "world_state"]),
])
def test_every_run_route_uses_the_console_script(campaign, path, sub):
    _, _, captured = campaign
    assert _run(path, RANGE) == 200
    cmd = captured["cmd"]
    assert cmd[0] == console_script("summary_native")
    assert cmd[1:1 + len(sub)] == sub
    assert _flag(cmd, "--summaries-dir") == "docs/summaries"
    assert _flag(cmd, "--since") == "3" and _flag(cmd, "--until") == "9"


def test_stored_config_reaches_the_command(campaign):
    _, svc, captured = campaign
    svc.update_config({"summary_native": {
        "summaries_dir": "docs/stored", "range_since": 1, "range_until": 5,
        "recent_chapters": 7, "recurring_min": 6, "parts": 3, "dup_threshold": 0.7,
    }})
    assert _run("/run/synth/party") == 200
    cmd = captured["cmd"]
    assert _flag(cmd, "--summaries-dir") == "docs/stored"
    assert (_flag(cmd, "--since"), _flag(cmd, "--until")) == ("1", "5")
    assert _flag(cmd, "--recent-chapters") == "7"
    assert _flag(cmd, "--recurring-min") == "6"
    assert _flag(cmd, "--parts") == "3"
    assert _run("/run/validate") == 200
    assert _flag(captured["cmd"], "--dup-threshold") == "0.7"


def test_explicit_request_beats_stored(campaign):
    _, svc, captured = campaign
    svc.update_config({"summary_native": {
        "summaries_dir": "docs/stored", "range_since": 1, "range_until": 5,
        "recent_chapters": 7, "parts": 3, "dup_threshold": 0.7,
    }})
    assert _run("/run/synth/party", {
        **RANGE, "recent_chapters": 2, "parts": 0,
    }) == 200
    cmd = captured["cmd"]
    assert _flag(cmd, "--summaries-dir") == "docs/summaries"
    assert (_flag(cmd, "--since"), _flag(cmd, "--until")) == ("3", "9")
    assert _flag(cmd, "--recent-chapters") == "2"
    # An explicit zero is an answer ("one call"), not "unset".
    assert _flag(cmd, "--parts") == "0"
    assert _run("/run/build", {**RANGE, "dup_threshold": 0.5, "force": True}) == 200
    cmd = captured["cmd"]
    assert _flag(cmd, "--dup-threshold") == "0.5"
    assert "--force" in cmd


def test_unconfigured_defaults_come_from_the_schema(campaign):
    from pipelines.summary_native import schema
    _, _, captured = campaign
    assert _run("/run/synth/party", RANGE) == 200
    cmd = captured["cmd"]
    assert _flag(cmd, "--recent-chapters") == str(schema.DEFAULT_RECENT_CHAPTERS)
    assert _flag(cmd, "--recurring-min") == str(schema.DEFAULT_RECURRING_MIN)
    assert _flag(cmd, "--parts") == str(schema.DEFAULT_PARTS)


def test_synth_carries_per_run_flags_and_never_the_cli_only_ones(campaign):
    _, svc, captured = campaign
    svc.update_config({"summary_native": {"out_root": "elsewhere"}})
    assert _run("/run/synth/party", {
        **RANGE,
        "name": ["Brewbarry", "Vukradin"],
        "dump_only": True,
        "max_tokens": 9000,
        "recent_chapters": 5,
        "recurring_min": 8,
        "world_state": "docs/ws.draft.md",
        "audit": ["notes/track.txt", "notes/other.txt"],
        "force": True,
    }) == 200
    cmd = captured["cmd"]
    i = cmd.index("--name")
    assert cmd[i + 1:i + 3] == ["Brewbarry", "Vukradin"]
    assert "--dump-only" in cmd and "--force" in cmd
    assert _flag(cmd, "--max-tokens") == "9000"
    assert _flag(cmd, "--recent-chapters") == "5"
    assert _flag(cmd, "--recurring-min") == "8"
    assert _flag(cmd, "--world-state") == "docs/ws.draft.md"
    j = cmd.index("--audit")
    assert cmd[j + 1:j + 3] == ["notes/track.txt", "notes/other.txt"]
    for banned in ("--registry", "--canon", "--out-root"):
        assert banned not in cmd


def test_audit_is_left_to_the_cli_unless_supplied(campaign):
    _, svc, captured = campaign
    svc.update_config({"campaign_state": {"track_files": ["notes/track.txt"]}})
    assert _run("/run/synth/campaign_state", RANGE) == 200
    assert "--audit" not in captured["cmd"]
    for flag in ("--max-tokens", "--dump-only", "--name", "--world-state"):
        assert flag not in captured["cmd"]


@pytest.mark.parametrize("path", ["/run/validate", "/run/build", "/run/synth/world_state"])
def test_no_cli_only_flag_on_any_run_route(campaign, path):
    _, _, captured = campaign
    assert _run(path, RANGE) == 200
    for banned in ("--registry", "--canon", "--out-root"):
        assert banned not in captured["cmd"]


def test_compare_passes_the_live_document(campaign):
    _, _, captured = campaign
    assert _run("/run/compare/world_state", RANGE) == 200
    assert _flag(captured["cmd"], "--live") == "docs/world_state.md"


def test_backend_and_model_come_from_the_selection_seam(campaign):
    _, svc, captured = campaign
    svc.update_config({"selection": {"backend": "anthropic", "model": "claude-test-model"}})
    assert _run("/run/synth/party", RANGE) == 200
    assert _flag(captured["cmd"], "--model") == "claude-test-model"
    assert _run("/run/synth/party", {**RANGE, "model": "claude-explicit"}) == 200
    assert _flag(captured["cmd"], "--model") == "claude-explicit"


# ── refusals (400, before spawning) ────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/run/validate", "/run/build", "/run/synth/world_state", "/run/compare/world_state",
])
def test_unset_range_is_400_and_never_spawns(campaign, path):
    _, _, captured = campaign
    r = client.get(f"{BASE}{path}", params={"summaries_dir": "docs/summaries"})
    assert r.status_code == 400
    assert "choose a chapter range" in r.json()["detail"]
    assert "cmd" not in captured


def test_half_a_range_is_still_400(campaign):
    _, _, captured = campaign
    r = client.get(f"{BASE}/run/validate",
                   params={"summaries_dir": "docs/summaries", "since": 1})
    assert r.status_code == 400 and "cmd" not in captured


def test_stored_range_satisfies_the_gate(campaign):
    _, svc, _ = campaign
    svc.update_config({"summary_native": {"range_since": 1, "range_until": 2}})
    assert _run("/run/validate", {"summaries_dir": "docs/summaries"}) == 200


@pytest.mark.parametrize("path", ["/run/validate", "/run/synth/world_state"])
def test_unset_summaries_dir_is_400(campaign, path):
    _, _, captured = campaign
    r = client.get(f"{BASE}{path}", params={"since": 1, "until": 2})
    assert r.status_code == 400
    assert "summaries directory" in r.json()["detail"]
    assert "cmd" not in captured


@pytest.mark.parametrize("path", ["/run/synth/bogus", "/run/compare/bogus"])
def test_unknown_doc_is_400(campaign, path):
    _, _, captured = campaign
    r = client.get(f"{BASE}{path}", params=RANGE)
    assert r.status_code == 400
    assert "cmd" not in captured


# ── read-only routes ───────────────────────────────────────────────────────

def test_chapters_lists_prefixes_and_duplicates_without_reading_content(campaign):
    root, _, _ = campaign
    d = root / "docs" / "summaries"
    d.mkdir(parents=True)
    # Unparseable content on purpose: a route that read it would choke.
    for name in ("001-a.md", "002-b.md", "002_b-again.md", "010.c.md", "notes.md"):
        (d / name).write_bytes(b"\xff\xfe not markdown at all")
    (d / "003-skip.txt").write_text("x")
    r = client.get(f"{BASE}/chapters", params={"summaries_dir": "docs/summaries"})
    assert r.status_code == 200
    body = r.json()
    assert body["present"] == [1, 2, 10]
    assert body["duplicate_chapters"] == [2]
    assert {f["path"] for f in body["files"]} == {"001-a.md", "002-b.md", "002_b-again.md", "010.c.md"}
    assert all(set(f) == {"chapter", "path"} for f in body["files"])


def test_chapters_uses_the_stored_directory_and_refuses_when_unset(campaign):
    root, svc, _ = campaign
    assert client.get(f"{BASE}/chapters").status_code == 400
    (root / "s").mkdir()
    (root / "s" / "004-x.md").write_text("x")
    svc.update_config({"summary_native": {"summaries_dir": "s"}})
    assert client.get(f"{BASE}/chapters").json()["present"] == [4]


def test_chapters_missing_directory_is_404(campaign):
    r = client.get(f"{BASE}/chapters", params={"summaries_dir": "nope"})
    assert r.status_code == 404


def test_report_reads_the_range_directory_json(campaign):
    root, _, _ = campaign
    rd = root / "docs" / "summary_native" / "ch003-009"
    rd.mkdir(parents=True)
    (rd / "validation_report.json").write_text(json.dumps({"blocking_count": 0}))
    r = client.get(f"{BASE}/report", params={"since": 3, "until": 9})
    assert r.status_code == 200 and r.json() == {"blocking_count": 0}


def test_report_absent_is_404_and_unset_range_is_400(campaign):
    assert client.get(f"{BASE}/report", params={"since": 3, "until": 9}).status_code == 404
    assert client.get(f"{BASE}/report").status_code == 400


def test_drafts_lists_draft_and_incomplete_files(campaign):
    root, _, _ = campaign
    rd = root / "docs" / "summary_native" / "ch003-009"
    # world_state and campaign_state build from the checked notes: their drafts live in state/drafts/
    dd = rd / "state" / "drafts"
    dd.mkdir(parents=True)
    (dd / "world_state.draft.md").write_text("abc")
    (dd / "campaign_state.incomplete.md").write_text("abcdef")
    (dd / "world_state.vs-live.diff").write_text("ignored")
    # party and planning keep the one-shot path and its drafts/ directory
    (rd / "drafts").mkdir()
    (rd / "drafts" / "party.draft.md").write_text("pp")
    r = client.get(f"{BASE}/drafts", params={"since": 3, "until": 9})
    assert r.status_code == 200
    rows = {(x["doc"], x["status"]): x for x in r.json()}
    assert set(rows) == {("world_state", "draft"), ("campaign_state", "incomplete"), ("party", "draft")}
    assert rows[("world_state", "draft")]["bytes"] == 3
    assert rows[("world_state", "draft")]["path"].endswith("state/drafts/world_state.draft.md")
    assert rows[("party", "draft")]["path"].endswith("drafts/party.draft.md")


def test_drafts_lists_the_timeline_reference_files_and_budget_report(campaign):
    root, _, _ = campaign
    dd = root / "docs" / "summary_native" / "ch003-009" / "state" / "drafts"
    (dd / "reference").mkdir(parents=True)
    (dd / "canon_events_timeline.md").write_text("t")
    (dd / "budget_report.json").write_text("{}")
    for kind in ("factions", "threads"):
        (dd / "reference" / f"{kind}.md").write_text("r")
    r = client.get(f"{BASE}/drafts", params={"since": 3, "until": 9})
    assert r.status_code == 200
    rows = {x["doc"]: x for x in r.json()}
    assert set(rows) == {"canon_events_timeline", "budget_report", "reference/factions", "reference/threads"}
    assert all(x["status"] == "report" for x in rows.values())
    assert rows["reference/factions"]["path"].endswith("state/drafts/reference/factions.md")


def test_state_carries_the_last_world_state_budget_report(campaign):
    root, _, _ = campaign
    assert client.get(f"{BASE}/state", params={"since": 3, "until": 9}).json()["world_budgets"] is None
    dd = root / "docs" / "summary_native" / "ch003-009" / "state" / "drafts"
    dd.mkdir(parents=True)
    rep = {"Locations": {"budget": 450, "words": 500, "over": True}}
    (dd / "budget_report.json").write_text(json.dumps(rep))
    assert client.get(f"{BASE}/state", params={"since": 3, "until": 9}).json()["world_budgets"] == rep


def test_drafts_absent_is_404_and_empty_dir_is_empty(campaign):
    root, _, _ = campaign
    assert client.get(f"{BASE}/drafts", params={"since": 3, "until": 9}).status_code == 404
    (root / "docs" / "summary_native" / "ch003-009").mkdir(parents=True)
    r = client.get(f"{BASE}/drafts", params={"since": 3, "until": 9})
    assert r.status_code == 200 and r.json() == []


# ── path resolution: one resolver shared with the CLI ──────────────────────

def test_tilde_out_root_is_expanded_for_report_and_drafts(campaign, monkeypatch, tmp_path_factory):
    _, svc, _ = campaign
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    rd = home / "sn" / "ch003-009"
    (rd / "state" / "drafts").mkdir(parents=True)
    (rd / "validation_report.json").write_text(json.dumps({"blocking_count": 0}))
    (rd / "state" / "drafts" / "world_state.draft.md").write_text("abc")
    svc.update_config({"summary_native": {"out_root": "~/sn"}})
    assert client.get(f"{BASE}/report", params={"since": 3, "until": 9}).json() == {"blocking_count": 0}
    r = client.get(f"{BASE}/drafts", params={"since": 3, "until": 9})
    assert r.status_code == 200 and len(r.json()) == 1


def test_absolute_out_root_outside_campaign_is_200_with_absolute_paths(campaign, tmp_path_factory):
    _, svc, _ = campaign
    out = tmp_path_factory.mktemp("elsewhere")
    dd = out / "ch003-009" / "state" / "drafts"
    dd.mkdir(parents=True)
    (dd / "world_state.draft.md").write_text("abc")
    svc.update_config({"summary_native": {"out_root": str(out)}})
    r = client.get(f"{BASE}/drafts", params={"since": 3, "until": 9})
    assert r.status_code == 200
    assert r.json()[0]["path"] == str(dd / "world_state.draft.md")


def test_tilde_summaries_dir_lists_chapters(campaign, monkeypatch, tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    (home / "summaries").mkdir()
    (home / "summaries" / "004-x.md").write_text("x")
    r = client.get(f"{BASE}/chapters", params={"summaries_dir": "~/summaries"})
    assert r.status_code == 200 and r.json()["present"] == [4]


def test_party_planning_config_paths_only_when_supplied(campaign):
    _, _, captured = campaign
    assert _run("/run/synth/party", RANGE) == 200
    assert "--party-config" not in captured["cmd"] and "--planning-config" not in captured["cmd"]
    assert _run("/run/synth/party", {**RANGE, "party_config": "config/alt_party.yaml"}) == 200
    assert _flag(captured["cmd"], "--party-config") == "config/alt_party.yaml"
    assert _run("/run/synth/planning", {**RANGE, "planning_config": " config/p.yaml "}) == 200
    assert _flag(captured["cmd"], "--planning-config") == "config/p.yaml"
    assert captured["cmd"][captured["cmd"].index("synth") + 1] == "planning"


# ── spec 033 US1: extract, and the chunked synth documents (T023) ──────────

from pipelines.summary_native import schema as _schema  # noqa: E402

STATE_DOCS = ["world_state", "campaign_state"]


def test_extract_argv(campaign):
    _, _, captured = campaign
    assert _run("/run/extract", RANGE) == 200
    cmd = captured["cmd"]
    assert cmd[0] == console_script("summary_native") and cmd[1] == "extract"
    assert _flag(cmd, "--summaries-dir") == "docs/summaries"
    assert (_flag(cmd, "--since"), _flag(cmd, "--until")) == ("3", "9")
    # the declared defaults reach the command line through the config, not through a literal in the router
    assert _flag(cmd, "--chunk-chars") == str(_schema.DEFAULT_CHUNK_CHARS)
    assert _flag(cmd, "--backend") == _schema.DEFAULT_DRAFT_BACKEND
    assert _flag(cmd, "--model") == _schema.DEFAULT_DRAFT_MODEL
    for absent in ("--dump-only", "--force", "--max-tokens", "--endpoints", "--parallel"):
        assert absent not in cmd
    for banned in ("--registry", "--canon", "--out-root"):
        assert banned not in cmd


def test_extract_carries_per_run_flags(campaign):
    _, _, captured = campaign
    assert _run("/run/extract", {**RANGE, "chunk_chars": 1234, "max_tokens": 9000, "dump_only": True,
                                 "force": True, "model": "other-model"}) == 200
    cmd = captured["cmd"]
    assert _flag(cmd, "--chunk-chars") == "1234" and _flag(cmd, "--max-tokens") == "9000"
    assert "--dump-only" in cmd and "--force" in cmd
    assert _flag(cmd, "--model") == "other-model"


def test_extract_stored_config_reaches_the_command(campaign):
    _, svc, captured = campaign
    svc.update_config({"summary_native": {
        "summaries_dir": "docs/stored", "range_since": 1, "range_until": 5,
        "extract": {"backend": "dgx", "model": "stored-model", "chunk_chars": 4321},
    }})
    assert _run("/run/extract") == 200
    cmd = captured["cmd"]
    assert _flag(cmd, "--summaries-dir") == "docs/stored"
    assert _flag(cmd, "--chunk-chars") == "4321" and _flag(cmd, "--model") == "stored-model"
    assert _run("/run/extract", {"chunk_chars": 99}) == 200
    assert _flag(captured["cmd"], "--chunk-chars") == "99"  # a request beats the stored value


def test_extract_unset_range_or_directory_is_400(campaign):
    _, _, captured = campaign
    r = client.get(f"{BASE}/run/extract", params={"summaries_dir": "docs/summaries"})
    assert r.status_code == 400 and "choose a chapter range" in r.json()["detail"]
    r = client.get(f"{BASE}/run/extract", params={"since": 1, "until": 2})
    assert r.status_code == 400 and "summaries directory" in r.json()["detail"]
    assert "cmd" not in captured


@pytest.mark.parametrize("doc", STATE_DOCS)
def test_chunked_synth_takes_the_prose_selection_and_no_parts(campaign, doc):
    _, _, captured = campaign
    assert _run(f"/run/synth/{doc}", RANGE) == 200
    cmd = captured["cmd"]
    assert cmd[1:3] == ["synth", doc]
    assert "--parts" not in cmd and "--audit" not in cmd
    assert _flag(cmd, "--backend") == _schema.DEFAULT_PROSE_BACKEND
    assert _flag(cmd, "--model") == _schema.DEFAULT_PROSE_MODEL
    assert _run(f"/run/synth/{doc}", {**RANGE, "model": "claude-opus-5-5"}) == 200
    assert _flag(captured["cmd"], "--model") == "claude-opus-5-5"


def test_chunked_synth_prose_block_in_config_reaches_the_command(campaign):
    _, svc, captured = campaign
    svc.update_config({"summary_native": {"prose": {"backend": "claude-code", "model": "claude-opus-5-5"}}})
    assert _run("/run/synth/world_state", RANGE) == 200
    assert _flag(captured["cmd"], "--model") == "claude-opus-5-5"


def test_a_stored_parts_value_is_not_sent_for_the_chunked_documents(campaign):
    _, svc, captured = campaign
    svc.update_config({"summary_native": {"parts": 3}})
    assert _run("/run/synth/world_state", RANGE) == 200
    assert "--parts" not in captured["cmd"]
    assert _run("/run/synth/party", RANGE) == 200  # the one-shot documents still get it
    assert _flag(captured["cmd"], "--parts") == "3"


@pytest.mark.parametrize("doc", STATE_DOCS)
def test_parts_is_a_400_for_the_chunked_documents_with_the_cli_message(campaign, doc):
    _, _, captured = campaign
    r = client.get(f"{BASE}/run/synth/{doc}", params={**RANGE, "parts": 2})
    assert r.status_code == 400
    assert r.json()["detail"] == _schema.STATE_PARTS_REFUSAL.format(doc=doc)
    assert "cmd" not in captured


def test_audit_is_a_400_for_campaign_state_naming_the_audit_step(campaign):
    _, _, captured = campaign
    r = client.get(f"{BASE}/run/synth/campaign_state", params={**RANGE, "audit": ["notes/track.txt"]})
    assert r.status_code == 400 and "summary_native audit" in r.json()["detail"]
    r = client.get(f"{BASE}/run/synth/world_state", params={**RANGE, "audit": ["notes/track.txt"]})
    assert r.status_code == 400 and "campaign_state only" in r.json()["detail"]
    assert "cmd" not in captured


def test_fallback_npc_lines_is_per_run_and_world_state_only(campaign):
    _, svc, captured = campaign
    assert _run("/run/synth/world_state", RANGE) == 200
    assert "--fallback-npc-lines" not in captured["cmd"]  # never remembered, never a config default
    assert _run("/run/synth/world_state", {**RANGE, "fallback_npc_lines": True}) == 200
    assert "--fallback-npc-lines" in captured["cmd"]
    captured.clear()
    for doc in ("campaign_state", "party"):
        r = client.get(f"{BASE}/run/synth/{doc}", params={**RANGE, "fallback_npc_lines": True})
        assert r.status_code == 400 and "world_state only" in r.json()["detail"]
    assert "cmd" not in captured


def test_the_key_npcs_selection_flags_go_to_world_state_but_not_campaign_state(campaign):
    _, _, captured = campaign
    assert _run("/run/synth/world_state", {**RANGE, "recent_chapters": 2, "name": ["Kalan"]}) == 200
    cmd = captured["cmd"]
    assert _flag(cmd, "--recent-chapters") == "2" and "--recurring-min" in cmd and "--name" in cmd
    assert _run("/run/synth/campaign_state", {**RANGE, "recent_chapters": 2}) == 200
    assert "--recent-chapters" not in captured["cmd"] and "--recurring-min" not in captured["cmd"]
    captured.clear()
    r = client.get(f"{BASE}/run/synth/campaign_state", params={**RANGE, "name": ["Kalan"]})
    assert r.status_code == 400 and "does not apply to campaign_state" in r.json()["detail"]
    assert "cmd" not in captured


def test_parts_zero_is_not_a_refusal(campaign):
    _, _, captured = campaign
    assert _run("/run/synth/world_state", {**RANGE, "parts": 0}) == 200


def _notes_manifest(root, **over):
    nd = root / "docs" / "summary_native" / "ch003-009" / "state" / "notes"
    nd.mkdir(parents=True)
    m = {
        "kind": "state_notes", "complete": True, "backend": "dgx", "model": "m", "chunk_chars": 10,
        "corpus_manifest_sha256": None, "registry_sha256": None, "players_sha256": None,
        "chunks": [
            {"index": 1, "chapters": "003-004", "status": "checked", "kept": 40, "dropped": 1},
            {"index": 2, "chapters": "005-006", "status": "checked", "kept": 50, "dropped": 2},
            {"index": 3, "chapters": "007-008", "status": "checked", "kept": 10, "dropped": 60},
            {"index": 4, "chapters": "009-009", "status": "failed", "kept": 0, "dropped": 0},
        ],
        **over,
    }
    (nd / "manifest.json").write_text(json.dumps(m))
    (nd / "drops.md").write_text("# Extraction drops\n")
    return nd


def test_state_reports_the_extract_block_from_files(campaign):
    root, _, _ = campaign
    _notes_manifest(root, complete=False)
    r = client.get(f"{BASE}/state", params={"since": 3, "until": 9})
    assert r.status_code == 200
    ex = r.json()["extract"]
    assert ex["present"] is True and ex["complete"] is False and ex["stale"] is False
    assert [c["chapters"] for c in ex["chunks"]] == ["003-004", "005-006", "007-008", "009-009"]
    assert [c["outlier"] for c in ex["chunks"]] == [False, False, True, False]
    assert ex["outliers"] == ["007-008"]
    assert ex["totals"] == {"chunks": 4, "checked": 3, "kept": 100, "dropped": 63}
    assert ex["drops_file"].endswith("state/notes/drops.md")


def test_state_marks_stale_notes_with_the_reason(campaign):
    root, _, _ = campaign
    _notes_manifest(root, registry_sha256="not-the-current-one")
    ex = client.get(f"{BASE}/state", params={"since": 3, "until": 9}).json()["extract"]
    assert ex["stale"] is True and "registry" in ex["stale_reason"] and "summary_native extract" in ex["stale_reason"]


def test_state_with_nothing_extracted_is_not_present(campaign):
    ex = client.get(f"{BASE}/state", params={"since": 3, "until": 9}).json()["extract"]
    assert ex["present"] is False and ex["chunks"] == [] and ex["drops_file"] is None


def test_state_unset_range_is_400(campaign):
    assert client.get(f"{BASE}/state").status_code == 400


def test_drafts_lists_the_drops_and_status_reports(campaign):
    root, _, _ = campaign
    rd = root / "docs" / "summary_native" / "ch003-009"
    _notes_manifest(root)
    (rd / "state" / "drafts").mkdir()
    (rd / "state" / "drafts" / "npc_status_report.md").write_text("# NPC table identity report\n")
    rows = {(x["doc"], x["status"]) for x in client.get(f"{BASE}/drafts", params={"since": 3, "until": 9}).json()}
    assert rows == {("drops", "report"), ("npc_status_report", "report")}


# ── spec 033 US4: annotate, annotations and missing_dossiers ───────────────────

@pytest.mark.parametrize("doc", ["world_state", "campaign_state"])
def test_annotate_argv_and_dry_run(campaign, doc):
    _, _, captured = campaign
    assert _run(f"/run/annotate/{doc}", RANGE) == 200
    cmd = captured["cmd"]
    assert cmd[:3] == [console_script("summary_native"), "annotate", doc]
    assert _flag(cmd, "--summaries-dir") == "docs/summaries" and _flag(cmd, "--since") == "3" and _flag(cmd, "--until") == "9"
    assert "--dry-run" not in cmd
    assert _run(f"/run/annotate/{doc}", {**RANGE, "dry_run": True}) == 200
    assert "--dry-run" in captured["cmd"]


@pytest.mark.parametrize("doc", ["party", "planning"])
def test_annotate_is_a_400_for_the_one_shot_documents(campaign, doc):
    _, _, captured = campaign
    assert _run(f"/run/annotate/{doc}", RANGE) == 400
    assert "cmd" not in captured


def test_annotate_unset_range_or_directory_is_400(campaign):
    assert _run("/run/annotate/world_state", {"summaries_dir": "docs/summaries"}) == 400
    assert _run("/run/annotate/world_state", {"since": 3, "until": 9}) == 400


def test_state_carries_each_documents_annotation_counts(campaign):
    root, _, _ = campaign
    assert client.get(f"{BASE}/state", params={"since": 3, "until": 9}).json()["annotations"] == {}
    dd = root / "docs" / "summary_native" / "ch003-009" / "state" / "drafts"
    dd.mkdir(parents=True)
    counts = {"later": 8, "since": 7, "unverified": 2, "removed": 0, "lines": 14}
    (dd / "annotations.json").write_text(json.dumps({"world_state": {"counts": counts, "annotated": [], "removed": []}}))
    assert client.get(f"{BASE}/state", params={"since": 3, "until": 9}).json()["annotations"] == {"world_state": counts}


def test_state_missing_dossiers_is_null_before_a_build_then_the_latest_attempts_list(campaign):
    root, _, _ = campaign
    body = client.get(f"{BASE}/state", params={"since": 3, "until": 9}).json()
    assert body["missing_dossiers"] is None and body["missing_dossiers_refused"] is False
    sd = root / "docs" / "summary_native" / "ch003-009" / "state"
    sd.mkdir(parents=True)
    npcs = [{"name": "Kalan", "state": "not drafted"}, {"name": "Sarith", "state": "failed verification (not-found 2)"}]
    (sd / "missing_dossiers.json").write_text(json.dumps({"range": {"since": 3, "until": 9}, "refused": True, "npcs": npcs}))
    body = client.get(f"{BASE}/state", params={"since": 3, "until": 9}).json()
    assert body["missing_dossiers"] == npcs and body["missing_dossiers_refused"] is True
    (sd / "missing_dossiers.json").write_text(json.dumps({"range": {"since": 3, "until": 9}, "refused": False, "npcs": []}))
    body = client.get(f"{BASE}/state", params={"since": 3, "until": 9}).json()
    assert body["missing_dossiers"] == [] and body["missing_dossiers_refused"] is False


def test_drafts_lists_the_annotations_and_key_npcs_reports(campaign):
    root, _, _ = campaign
    dd = root / "docs" / "summary_native" / "ch003-009" / "state" / "drafts"
    dd.mkdir(parents=True)
    (dd / "annotations.md").write_text("# Annotations\n")
    (dd / "annotations.json").write_text("{}")  # the machine copy is not a listed report
    (dd / "key_npcs_report.md").write_text("# Key NPCs\n")
    rows = {x["doc"]: x for x in client.get(f"{BASE}/drafts", params={"since": 3, "until": 9}).json()}
    assert set(rows) == {"annotations", "key_npcs_report"}
    assert rows["annotations"]["status"] == "report" and rows["annotations"]["path"].endswith("state/drafts/annotations.md")
    assert rows["key_npcs_report"]["path"].endswith("state/drafts/key_npcs_report.md")


# ── spec 033 US5: endpoints, parallel and the prose selection (T045) ───────


def test_extract_endpoints_are_one_multi_value_flag(campaign):
    _, _, captured = campaign
    eps = ["http://spark:8001/v1", "http://spark2:8001/v1"]
    assert _run("/run/extract", {**RANGE, "endpoints": eps, "parallel": 4}) == 200
    cmd = captured["cmd"]
    i = cmd.index("--endpoints")
    assert cmd[i + 1:i + 3] == eps
    assert _flag(cmd, "--parallel") == "4"
    assert "--endpoint" not in cmd  # one spelling: the singular never rides along
    assert _flag(cmd, "--backend") == "dgx"


def test_extract_blank_endpoints_are_ignored_and_parallel_alone_is_carried(campaign):
    _, _, captured = campaign
    assert _run("/run/extract", {**RANGE, "endpoints": ["  ", ""], "parallel": 2}) == 200
    cmd = captured["cmd"]
    assert "--endpoints" not in cmd and _flag(cmd, "--parallel") == "2"


def test_extract_endpoints_with_a_non_dgx_backend_is_400_before_spawning(campaign):
    _, svc, captured = campaign
    svc.update_config({"summary_native": {"extract": {"backend": "openrouter", "model": "vendor/model"}}})
    r = client.get(f"{BASE}/run/extract", params={**RANGE, "endpoints": ["http://spark:8001/v1"]})
    assert r.status_code == 400 and "--endpoints" in r.json()["detail"] and "dgx" in r.json()["detail"]
    assert "cmd" not in captured


def test_extract_parallel_below_one_is_400(campaign):
    _, _, captured = campaign
    r = client.get(f"{BASE}/run/extract", params={**RANGE, "parallel": 0})
    assert r.status_code == 400 and "cmd" not in captured


def test_endpoints_never_come_from_stored_config(campaign):
    _, svc, captured = campaign
    with pytest.raises(Exception):
        svc.update_config({"summary_native": {"extract": {"endpoints": ["http://x/v1"]}}})
    assert _run("/run/extract", RANGE) == 200
    assert "--endpoints" not in captured["cmd"]


@pytest.mark.parametrize("doc", STATE_DOCS)
def test_chunked_synth_carries_the_prose_effort(campaign, doc):
    _, _, captured = campaign
    assert _run(f"/run/synth/{doc}", {**RANGE, "model": "claude-opus-5-5", "claude_code_effort": "high"}) == 200
    cmd = captured["cmd"]
    assert _flag(cmd, "--backend") == "claude-code" and _flag(cmd, "--model") == "claude-opus-5-5"
    assert _flag(cmd, "--claude-code-effort") == "high"
    assert "--endpoints" not in cmd and "--parallel" not in cmd


def test_synth_without_an_effort_request_sends_none(campaign):
    _, _, captured = campaign
    assert _run("/run/synth/world_state", RANGE) == 200
    assert "--claude-code-effort" not in captured["cmd"]
