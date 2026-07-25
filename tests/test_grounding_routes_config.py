"""The grounding run routes must build commands from grounding.yaml.

Phase 8 of ``docs/config/grounding-isolation.md``. Before this, every default
was a literal in a route signature (``chunk_size: int = 60000``, five copies)
and the routes read no configuration at all — so any config document would
have been decorative.

Precedence under test: explicit request param → the doc's stored value → the
shared ``summaries`` pointer (for inputs) → refuse.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.grounding_config_service import GroundingConfigService  # noqa: E402
from server.main import app  # noqa: E402
from server.platform_config_service import (  # noqa: E402
    PlatformConfigService,
    TRACKED_CONFIG_NAME,
)

client = TestClient(app)


@pytest.fixture
def campaign(monkeypatch, tmp_path):
    """A booted platform in tmp_path, with subprocess spawning stubbed out."""
    cfgdir = tmp_path / "config"
    cfgdir.mkdir(parents=True, exist_ok=True)
    (cfgdir / TRACKED_CONFIG_NAME).write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(app.state, "platform", PlatformConfigService(tmp_path),
                        raising=False)

    captured: dict = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        captured["cmd"] = cmd
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("server.routers.grounding.stream_subprocess",
                        fake_stream_subprocess)
    return GroundingConfigService(cfgdir), captured


def _run(path: str, params: dict | None = None) -> int:
    r = client.get(path, params=params or {})
    _ = r.text  # drain the SSE generator so the fake subprocess runs
    return r.status_code


def _flag(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


# ── Config endpoints ───────────────────────────────────────────────────────

def test_get_config_returns_defaults(campaign):
    _, _c = campaign
    r = client.get("/api/grounding/config")
    assert r.status_code == 200
    assert r.json()["campaign_state"]["split_chapters"] == "# Chapter"


def test_put_config_takes_a_bare_partial(campaign):
    """No {"values": ...} envelope — matches PUT /api/ensemble/config."""
    svc, _ = campaign
    r = client.put("/api/grounding/config",
                   json={"summaries": "docs/summaries.md"})
    assert r.status_code == 200
    assert svc.resolved().summaries == "docs/summaries.md"


def test_put_config_rejects_unknown_key(campaign):
    r = client.put("/api/grounding/config", json={"campaign_state": {"nope": 1}})
    assert r.status_code == 400


# ── Stored config reaches the command ──────────────────────────────────────

def test_stored_values_reach_the_command(campaign):
    svc, captured = campaign
    svc.update_config({
        "summaries": "docs/summaries.md",
        "distill": {"output": "docs/world_state.md",
                    "extract_dir": "docs/distill_extractions"},
    })
    assert _run("/api/grounding/run/distill") == 200
    cmd = captured["cmd"]
    assert "docs/summaries.md" in cmd                       # positional input
    assert _flag(cmd, "--output") == "docs/world_state.md"
    assert _flag(cmd, "--extract-dir") == "docs/distill_extractions"


def test_explicit_param_beats_stored(campaign):
    svc, captured = campaign
    svc.update_config({"summaries": "docs/summaries.md",
                       "distill": {"output": "docs/stored.md"}})
    assert _run("/api/grounding/run/distill",
                {"output": "docs/explicit.md"}) == 200
    assert _flag(captured["cmd"], "--output") == "docs/explicit.md"


def test_per_doc_input_beats_shared_summaries(campaign):
    svc, captured = campaign
    svc.update_config({"summaries": "docs/summaries.md",
                       "campaign_state": {"input": "docs/other.md"}})
    assert _run("/api/grounding/run/campaign-state") == 200
    assert "docs/other.md" in captured["cmd"]
    assert "docs/summaries.md" not in captured["cmd"]


def test_missing_input_is_400_not_a_silent_run(campaign):
    """No silent 'all' — the ensemble chapters_selected precedent."""
    assert _run("/api/grounding/run/distill") == 400


def test_synthesize_only_needs_no_input(campaign):
    """--synthesize-only reads cached extracts, so the input is irrelevant."""
    assert _run("/api/grounding/run/distill", {"synthesize_only": True}) == 200


# ── Chunking, and the split_chapters default that disagreed ────────────────

def test_split_chapters_default_reaches_command(campaign):
    """Python's route signature defaulted to "" while all four Vue pages
    defaulted to '# Chapter'. The Vue value is the shipped one."""
    svc, captured = campaign
    svc.update_config({"summaries": "docs/s.md"})
    assert _run("/api/grounding/run/distill") == 200
    assert _flag(captured["cmd"], "--split-chapters") == "# Chapter"


def test_chunk_size_only_emitted_when_non_default(campaign):
    svc, captured = campaign
    svc.update_config({"summaries": "docs/s.md",
                       "distill": {"split_chapters": "", "chunk_size": 60000}})
    assert _run("/api/grounding/run/distill") == 200
    assert "--chunk-size" not in captured["cmd"]

    svc.update_config({"distill": {"chunk_size": 30000}})
    assert _run("/api/grounding/run/distill") == 200
    assert _flag(captured["cmd"], "--chunk-size") == "30000"


def test_split_chapters_wins_over_chunk_size(campaign):
    svc, captured = campaign
    svc.update_config({"summaries": "docs/s.md",
                       "distill": {"split_chapters": "# Session",
                                   "chunk_size": 30000}})
    assert _run("/api/grounding/run/distill") == 200
    assert _flag(captured["cmd"], "--split-chapters") == "# Session"
    assert "--chunk-size" not in captured["cmd"]


# ── campaign_state's three collapsed track fields ──────────────────────────

def test_track_files_and_items_from_config(campaign):
    svc, captured = campaign
    svc.update_config({
        "summaries": "docs/s.md",
        "campaign_state": {"track_files": ["notes/a.txt", "notes/b.txt"],
                           "track_items": ["Freed the sovereign"]},
    })
    assert _run("/api/grounding/run/campaign-state") == 200
    cmd = captured["cmd"]
    assert cmd.count("--track-file") == 2
    assert "notes/a.txt" in cmd and "notes/b.txt" in cmd
    assert _flag(cmd, "--track") == "Freed the sovereign"


def test_explicit_track_file_params_beat_stored(campaign):
    svc, captured = campaign
    svc.update_config({"summaries": "docs/s.md",
                       "campaign_state": {"track_files": ["notes/stored.txt"]}})
    assert _run("/api/grounding/run/campaign-state",
                {"track_file": "notes/explicit.txt"}) == 200
    cmd = captured["cmd"]
    assert "notes/explicit.txt" in cmd
    assert "notes/stored.txt" not in cmd


# ── party / planning mode selection ────────────────────────────────────────

def test_party_config_mode_uses_stored_roster_path(campaign):
    svc, captured = campaign
    svc.update_config({"summaries": "docs/s.md",
                       "party": {"mode": "config",
                                 "config_path": "config/party.yaml"}})
    assert _run("/api/grounding/run/party") == 200
    assert _flag(captured["cmd"], "--party-config") == "config/party.yaml"


def test_party_flat_mode_uses_stored_file_lists(campaign):
    svc, captured = campaign
    svc.update_config({"summaries": "docs/s.md",
                       "party": {"mode": "flat",
                                 "characters": ["docs/party/a.md"],
                                 "arc_scores": ["docs/tracking/a.md"]}})
    assert _run("/api/grounding/run/party") == 200
    cmd = captured["cmd"]
    assert "--party-config" not in cmd
    assert _flag(cmd, "--character") == "docs/party/a.md"
    assert _flag(cmd, "--arc-scores") == "docs/tracking/a.md"


def test_party_runs_without_summaries(campaign):
    """Characters-only mode is legitimate — party must not 400 like the others."""
    svc, captured = campaign
    svc.update_config({"party": {"mode": "flat",
                                 "characters": ["docs/party/a.md"]}})
    assert _run("/api/grounding/run/party") == 200
    assert "--summaries" not in captured["cmd"]


def test_planning_config_mode_uses_stored_path(campaign):
    svc, captured = campaign
    svc.update_config({"summaries": "docs/s.md",
                       "planning": {"synth_mode": "config",
                                    "config_path": "config/planning.yaml"}})
    assert _run("/api/grounding/run/planning") == 200
    assert _flag(captured["cmd"], "--planning-config") == "config/planning.yaml"


def test_build_dossiers_reads_its_nested_group(campaign):
    svc, captured = campaign
    svc.update_config({
        "summaries": "docs/s.md",
        "planning": {"dossiers": {"dossier_dir": "docs/npcs/", "since": 4}},
    })
    assert _run("/api/grounding/run/build-dossiers") == 200
    cmd = captured["cmd"]
    assert "--build-dossiers" in cmd
    assert _flag(cmd, "--dossier-dir") == "docs/npcs/"
    assert _flag(cmd, "--since") == "4"
    assert _flag(cmd, "--summaries") == "docs/s.md"  # inherits the root pointer
