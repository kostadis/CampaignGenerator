"""The authority HTTP adapter invokes the installed CLI; it has no policy copy."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.main import app  # noqa: E402
from server.platform_config_service import TRACKED_CONFIG_NAME, PlatformConfigService  # noqa: E402
from pipelines.summary_native.authority import AuthorityLedger, NoteRecord, ledger_bytes, write_ledger  # noqa: E402
from pipelines.summary_native.authority_apply import write_ledger_tip  # noqa: E402


BASE = "/api/grounding/summary-native/authority"


@pytest.fixture
def client(monkeypatch, tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / TRACKED_CONFIG_NAME).write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(app.state, "platform", PlatformConfigService(tmp_path), raising=False)
    return TestClient(app), tmp_path


def _envelope_from_sse(body: str) -> dict:
    chunks: list[str] = []
    for frame in body.split("\n\n"):
        if frame.startswith("event: done") or frame.startswith("event: command"):
            continue
        for line in frame.splitlines():
            if line.startswith("data: "):
                value = json.loads(line[6:])
                if isinstance(value, str) and not value.startswith("$"):
                    chunks.append(value)
    text = "".join(chunks)
    return json.loads(text)


def test_init_then_status_uses_the_authority_cli_subprocess(client):
    http, campaign = client
    before = http.get(f"{BASE}/status")
    assert before.status_code == 200
    assert before.json()["data"]["state"] == "absent"

    initialized = http.post(f"{BASE}/init", json={"campaign_dir": str(campaign)})
    assert initialized.status_code == 200
    init = _envelope_from_sse(initialized.text)
    assert init["ok"] and init["code"] == "OK"

    after = http.get(f"{BASE}/status")
    assert after.status_code == 200
    payload = after.json()
    assert payload["ok"] and payload["data"]["state"] == "initialized"
    assert payload["data"]["revision"] == 1


def test_note_preview_forwards_authored_selectors_to_the_authority_cli(client):
    http, campaign = client
    notes = campaign / "notes" / "gm"
    notes.mkdir(parents=True)
    note = notes / "plot.md"
    section = b"<!-- anchor: plot -->\n# A GM planning note\n"
    note.write_bytes(section)

    assert http.post(f"{BASE}/init", json={"campaign_dir": str(campaign)}).status_code == 200
    record_file = campaign / "docs" / "authority" / "preview-note.json"
    record_file.parent.mkdir(parents=True, exist_ok=True)
    record_file.write_text(json.dumps({
        "id": "note-a",
        "kind": "note",
        "revision": 1,
        "classification": "PREP",
        "subject": {"kind": "topic", "id": "plot"},
        "effective": {"horizon": "future"},
        "audience": {"grants": ["gm"]},
        "projections": ["planning"],
        "recorded_at": "2026-10-09T00:00:00Z",
        "recorded_by": "GM",
        "status": "active",
        "source": {"path": "notes/gm/plot.md", "anchor": "plot"},
        "content_digest": hashlib.sha256(section).hexdigest(),
        "planning_date": "chapter-1",
        "selection_label": "GM plot",
    }), encoding="utf-8")
    staged = _envelope_from_sse(http.post(
        f"{BASE}/records/stage", json={"record_file": str(record_file)},
    ).text)["data"]
    ledger_sha = http.get(f"{BASE}/status").json()["data"]["sha256"]
    applied = http.post(
        f"{BASE}/records/stages/{staged['id']}/apply",
        json={"stage_sha256": staged["sha256"], "expected_ledger_sha256": ledger_sha},
    )
    assert _envelope_from_sse(applied.text)["ok"]

    configured = {"id": "gm-notes", "path": "notes/gm/*.md", "record_ids": ["note-a"]}
    assert http.post("/api/planning/notes", json=configured).status_code == 201
    result = http.post(f"{BASE}/notes/preview", json={"audience": "gm"})

    assert result.status_code == 200
    payload = result.json()
    assert payload["ok"] and payload["data"]["selection_digest"]
    assert payload["data"]["membership_digest"]
    assert payload["data"]["members"] == [{
        "selector_id": "gm-notes", "path": "notes/gm/*.md", "resolved_path": str(note),
        "external": False, "record_ids": ["note-a"], "reason": "selector:gm-notes",
        "sha256": hashlib.sha256(note.read_bytes()).hexdigest(),
        "records": [{
            "id": "note-a", "classification": "PREP", "audience": ["gm"],
            "effective": {"horizon": "future"}, "status": "active", "anchor": "plot",
            "section_sha256": hashlib.sha256(section).hexdigest(),
        }],
    }]


def test_status_exposes_safe_structured_stale_projection_metadata(client):
    http, campaign = client
    assert http.post(f"{BASE}/init", json={"campaign_dir": str(campaign)}).status_code == 200
    run = campaign / "state" / "ch001-001" / "runs" / "planning-run"
    run.mkdir(parents=True)
    (run / "record.json").write_text(json.dumps({
        "doc": "planning", "inputs": {"authority_manifest": {"ledger_sha256": "superseded-ledger"}},
    }), encoding="utf-8")

    status = http.get(f"{BASE}/status")

    assert status.status_code == 200
    stale = status.json()["data"]["stale_projections"]
    assert stale == [{
        "doc": "planning", "draft": str(run.parent / "drafts" / "planning.draft.md"),
        "reason": "authority inputs changed since this output",
    }]


def test_stage_then_apply_uses_the_cli_stage_id_and_sha256_envelope(client):
    """The stage response is forwarded intact into the guarded apply call."""
    http, campaign = client
    initialized = http.post(f"{BASE}/init", json={"campaign_dir": str(campaign)})
    assert initialized.status_code == 200

    note_source = campaign / "notes" / "stage.md"
    note_source.parent.mkdir(parents=True, exist_ok=True)
    section = b"<!-- anchor: stage-note -->\nReviewed planning note.\n"
    note_source.write_bytes(section)
    record_file = campaign / "docs" / "authority" / "stage-note.json"
    record_file.parent.mkdir(parents=True, exist_ok=True)
    record_file.write_text(json.dumps({
        "id": "stage-note",
        "kind": "note",
        "revision": 1,
        "classification": "CANON",
        "subject": {"kind": "topic", "id": "stage-topic"},
        "effective": {"from_chapter": 1, "through_chapter": 1},
        "audience": {"grants": ["gm"]},
        "projections": ["planning"],
        "recorded_at": "2026-10-09T00:00:00Z",
        "recorded_by": "GM",
        "status": "active",
        "source": {"path": "notes/stage.md", "anchor": "stage-note"},
        "content_digest": hashlib.sha256(section).hexdigest(),
        "selection_label": "Staged planning note",
    }), encoding="utf-8")

    staged_response = http.post(
        f"{BASE}/records/stage", json={"record_file": "docs/authority/stage-note.json"},
    )
    assert staged_response.status_code == 200
    staged = _envelope_from_sse(staged_response.text)
    assert staged["ok"]
    assert set(staged["data"]) == {"id", "record", "sha256"}
    assert staged["data"]["record"]["id"] == "stage-note"

    ledger = http.get(f"{BASE}/status").json()["data"]["sha256"]
    applied_response = http.post(
        f"{BASE}/records/stages/{staged['data']['id']}/apply",
        json={
            "stage_sha256": staged["data"]["sha256"],
            "expected_ledger_sha256": ledger,
        },
    )
    assert applied_response.status_code == 200
    applied = _envelope_from_sse(applied_response.text)
    assert applied["ok"]

    status = http.get(f"{BASE}/status").json()["data"]
    assert status["revision"] == 2
    assert status["records"] == 1


def test_planning_synth_forwards_one_reviewed_selection_and_audience(client, monkeypatch):
    http, campaign = client
    summaries = campaign / "docs" / "summaries"
    summaries.mkdir(parents=True)
    (campaign / "config" / "grounding.yaml").write_text(
        "summary_native:\n  summaries_dir: docs/summaries\n  range_since: 1\n  range_until: 1\n",
        encoding="utf-8",
    )
    captured: dict[str, list[str]] = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        captured["cmd"] = cmd
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover

    monkeypatch.setattr("server.routers.grounding.stream_subprocess", fake_stream_subprocess)
    result = http.get(
        "/api/grounding/summary-native/run/synth/planning",
        params={"summaries_dir": "docs/summaries", "since": 1, "until": 1,
                "authority_selection": "player-reviewed-sha", "audience": "players"},
    )

    assert result.status_code == 200
    command = captured["cmd"]
    assert command[command.index("--authority-selection") + 1] == "player-reviewed-sha"
    assert command[command.index("--audience") + 1] == "players"


def test_conflict_routes_run_the_real_cli_lifecycle(client):
    http, campaign = client
    assert http.post(f"{BASE}/init", json={"campaign_dir": str(campaign)}).status_code == 200
    def record(identifier: str) -> NoteRecord:
        return NoteRecord.model_validate({
            "id": identifier, "kind": "note", "revision": 1, "classification": "CANON",
            "subject": {"kind": "topic", "id": "gate"}, "effective": {"from_chapter": 1},
            "audience": {"grants": ["gm"]}, "projections": ["planning"], "status": "active",
            "recorded_at": "2026-10-09T00:00:00Z", "recorded_by": "GM",
            "source": {"path": f"notes/{identifier}.md", "anchor": identifier},
            "content_digest": "0" * 64, "selection_label": identifier,
        })
    ledger = AuthorityLedger(version=1, campaign=campaign.name, revision=2, records=[record("gate-left"), record("gate-right")])
    write_ledger(campaign, ledger); write_ledger_tip(campaign, event_id="route-seed", after=ledger_bytes(ledger))
    assert http.get(f"{BASE}/conflicts").json()["data"]["conflicts"] == []
    digest = http.get(f"{BASE}/status").json()["data"]["sha256"]
    identified = http.post(f"{BASE}/conflicts/identify", json={"id": "gm-gate-tension", "record_ids": ["gate-left", "gate-right"], "basis": "human_identified", "reason": "GM comparison", "expected_ledger_sha256": digest})
    assert _envelope_from_sse(identified.text)["data"]["conflict"]["status"] == "open"
    history = http.get(f"{BASE}/conflicts/gm-gate-tension/history").json()["data"]
    assert history["events"][0]["conflict_id"] == "gm-gate-tension"
    digest = http.get(f"{BASE}/status").json()["data"]["sha256"]
    dismissed = http.post(f"{BASE}/conflicts/gm-gate-tension/dismiss", json={"reason": "not contradictory", "expected_ledger_sha256": digest})
    assert _envelope_from_sse(dismissed.text)["data"]["conflict"]["status"] == "dismissed"
