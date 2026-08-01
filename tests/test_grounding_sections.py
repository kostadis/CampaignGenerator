"""Per-section grounding projections (#213 Phase 4).

The incremental contract under test: a section re-renders when and only
when the bytes of its input store changed (content-derived freshness, not
mtime — the #137 principle), and the assembled draft is built from section
files each carrying an inputs-sha stamp.
"""

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

CLI = REPO / "pipelines/grounding/grounding_sections.py"


def run_cli(cwd, *argv):
    return subprocess.run([sys.executable, str(CLI), *argv],
                          capture_output=True, text=True, cwd=cwd)


def _campaign(tmp_path: Path) -> Path:
    camp = tmp_path
    (camp / "docs/ensemble").mkdir(parents=True)
    rows = [
        {"chapter": 40, "scene": 1, "seq": 5, "event": "Orc nine dies."},
        {"chapter": 41, "scene": 1, "seq": 2, "event": "The boar dies."},
        {"chapter": 45, "scene": None, "seq": None, "event": "Victory lap."},
    ]
    (camp / "docs/ensemble/events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n")
    (camp / "docs/thread_registry.yaml").write_text(yaml.safe_dump({
        "version": 1, "threads": [
            {"id": "carver-march", "title": "The Carver's march",
             "status": "open", "opened": 4, "tracker": "Carver threat",
             "log": [{"chapter": 40, "change": "advanced", "summary": "Closer."}]},
        ]}))
    (camp / "docs/party.md").write_text("# Party\n\nVukradin and friends.\n")
    return camp


def test_campaign_state_builds_deterministically_and_skips_when_fresh(tmp_path):
    camp = _campaign(tmp_path)
    r = run_cli(camp, "build", "--doc", "campaign_state")
    assert r.returncode == 0, r.stderr
    assert "rebuilt: recent_events, party" in r.stdout
    draft = (camp / "docs/campaign_state_draft.md").read_text()
    assert "Orc nine dies." in draft and "Vukradin and friends." in draft
    assert "inputs-sha" in draft

    # second run: nothing changed -> nothing re-rendered
    r2 = run_cli(camp, "build", "--doc", "campaign_state")
    assert r2.returncode == 0, r2.stderr
    assert "rebuilt: nothing" in r2.stdout
    assert "recent_events (fresh)" in r2.stdout


def test_changed_store_re_renders_only_that_section(tmp_path):
    camp = _campaign(tmp_path)
    assert run_cli(camp, "build", "--doc", "campaign_state").returncode == 0
    events = camp / "docs/ensemble/events.jsonl"
    events.write_text(events.read_text() +
                      json.dumps({"chapter": 46, "scene": 1, "seq": 1,
                                  "event": "UBT begins."}) + "\n")
    r = run_cli(camp, "build", "--doc", "campaign_state")
    assert "rebuilt: recent_events" in r.stdout
    assert "party (fresh)" in r.stdout
    assert "UBT begins." in (camp / "docs/campaign_state_draft.md").read_text()


def test_touch_without_content_change_stays_fresh(tmp_path):
    camp = _campaign(tmp_path)
    assert run_cli(camp, "build", "--doc", "campaign_state").returncode == 0
    p = camp / "docs/party.md"
    p.write_text(p.read_text())          # rewrite identical bytes (mtime bumps)
    r = run_cli(camp, "build", "--doc", "campaign_state")
    assert "rebuilt: nothing" in r.stdout


def test_planning_threads_section_renders_registry(tmp_path):
    camp = _campaign(tmp_path)
    r = run_cli(camp, "build", "--doc", "planning")
    assert r.returncode == 0, r.stderr
    draft = (camp / "docs/planning_draft.md").read_text()
    assert "The Carver's march" in draft
    assert "[ch40] (advanced) Closer." in draft
    assert "notes (optional, no input)" in r.stdout   # optional section skipped


def test_spine_window_flag_scopes_recent_section(tmp_path):
    camp = _campaign(tmp_path)
    r = run_cli(camp, "build", "--doc", "campaign_state", "--window", "1")
    assert r.returncode == 0, r.stderr
    draft = (camp / "docs/campaign_state_draft.md").read_text()
    assert "Victory lap." in draft and "Orc nine dies." not in draft


def test_list_reports_staleness_states(tmp_path):
    camp = _campaign(tmp_path)
    r = run_cli(camp, "list", "--doc", "campaign_state")
    assert "unbuilt" in r.stdout
    run_cli(camp, "build", "--doc", "campaign_state")
    r2 = run_cli(camp, "list", "--doc", "campaign_state")
    assert r2.stdout.count("fresh") == 2


def test_missing_required_input_fails_loudly(tmp_path):
    camp = _campaign(tmp_path)
    (camp / "docs/party.md").unlink()
    r = run_cli(camp, "build", "--doc", "campaign_state")
    assert r.returncode != 0
    assert "party" in r.stderr and "input missing" in r.stderr
