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
    assert _run("/run/synth/world_state") == 200
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
    assert _run("/run/synth/world_state", {
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
    assert _run("/run/synth/world_state", RANGE) == 200
    cmd = captured["cmd"]
    assert _flag(cmd, "--recent-chapters") == str(schema.DEFAULT_RECENT_CHAPTERS)
    assert _flag(cmd, "--recurring-min") == str(schema.DEFAULT_RECURRING_MIN)
    assert _flag(cmd, "--parts") == str(schema.DEFAULT_PARTS)


def test_synth_carries_per_run_flags_and_never_the_cli_only_ones(campaign):
    _, svc, captured = campaign
    svc.update_config({"summary_native": {"out_root": "elsewhere"}})
    assert _run("/run/synth/campaign_state", {
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
    assert _run("/run/synth/world_state", RANGE) == 200
    assert _flag(captured["cmd"], "--model") == "claude-test-model"
    assert _run("/run/synth/world_state", {**RANGE, "model": "claude-explicit"}) == 200
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
    dd = root / "docs" / "summary_native" / "ch003-009" / "drafts"
    dd.mkdir(parents=True)
    (dd / "world_state.draft.md").write_text("abc")
    (dd / "campaign_state.incomplete.md").write_text("abcdef")
    (dd / "world_state.vs-live.diff").write_text("ignored")
    r = client.get(f"{BASE}/drafts", params={"since": 3, "until": 9})
    assert r.status_code == 200
    rows = {(x["doc"], x["status"]): x for x in r.json()}
    assert set(rows) == {("world_state", "draft"), ("campaign_state", "incomplete")}
    assert rows[("world_state", "draft")]["bytes"] == 3
    assert rows[("world_state", "draft")]["path"].endswith("drafts/world_state.draft.md")


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
    (rd / "drafts").mkdir(parents=True)
    (rd / "validation_report.json").write_text(json.dumps({"blocking_count": 0}))
    (rd / "drafts" / "world_state.draft.md").write_text("abc")
    svc.update_config({"summary_native": {"out_root": "~/sn"}})
    assert client.get(f"{BASE}/report", params={"since": 3, "until": 9}).json() == {"blocking_count": 0}
    r = client.get(f"{BASE}/drafts", params={"since": 3, "until": 9})
    assert r.status_code == 200 and len(r.json()) == 1


def test_absolute_out_root_outside_campaign_is_200_with_absolute_paths(campaign, tmp_path_factory):
    _, svc, _ = campaign
    out = tmp_path_factory.mktemp("elsewhere")
    dd = out / "ch003-009" / "drafts"
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
