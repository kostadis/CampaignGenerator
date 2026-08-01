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


def test_planning_emerging_section_layers_pending_proposals(tmp_path):
    camp = _campaign(tmp_path)
    (camp / "docs/ensemble/thread_proposals.yaml").write_text(yaml.safe_dump({
        "proposals": [
            {"norm": "a", "title": "Carver's dark influence", "status": "pending",
             "matches": "carver-march", "chapters": [35],
             "evidence": [{"chapter": 35, "fact": "Something dark threads in."}]},
            {"norm": "b", "title": "The drowned gate", "status": "pending",
             "matches": None, "chapters": [21, 44],
             "evidence": [{"chapter": 21, "fact": "A gate lies drowned."}]},
            {"norm": "c", "title": "Old ruling", "status": "rejected",
             "matches": None, "chapters": [3], "evidence": []},
        ]}))
    r = run_cli(camp, "build", "--doc", "planning")
    assert r.returncode == 0, r.stderr
    draft = (camp / "docs/planning_draft.md").read_text()
    assert "Emerging Threads" in draft
    assert "Continuations of ratified threads" in draft
    assert "`carver-march`" in draft
    assert "The drowned gate" in draft
    assert "Old ruling" not in draft       # ruled proposals never resurface
    assert "not yet ruled on" in draft


def test_npc_outlook_selection_and_guards(tmp_path):
    camp = _campaign(tmp_path)
    # no salience list -> section skipped
    r = run_cli(camp, "build", "--doc", "planning")
    assert "npc_outlook (no GM salience list)" in r.stdout
    # salience list but no backend -> no-implicit-spend guard
    (camp / "docs/ensemble/narrative_importance.yaml").write_text(yaml.safe_dump(
        {"force_include": ["npc_adabra.md", "faction_kraken.md"]}))
    r2 = run_cli(camp, "build", "--doc", "planning")
    assert "npc_outlook (synthesis — pass --backend to render)" in r2.stdout


def test_npc_outlook_per_npc_freshness(tmp_path, monkeypatch):
    import importlib
    gs = importlib.import_module("pipelines.grounding.grounding_sections")
    camp = _campaign(tmp_path)
    (camp / "docs/ensemble/state_dossiers").mkdir(parents=True)
    (camp / "docs/ensemble/state_dossiers/npc_adabra.md").write_text("Adabra dossier.")
    calls = []
    monkeypatch.setattr(gs, "render_outlook_block",
                        lambda slug, inputs, args: calls.append(slug) or f"### {slug}\nBlock.")
    monkeypatch.chdir(camp)

    class A:
        npcs = "adabra"
        force = False
        model = None
        max_tokens = None
        backend = "dgx"

    sec = gs.Section("npc_outlook", "npc_outlook", optional=True)
    f = gs.SECTIONS_DIR / "planning" / "npc_outlook.md"
    rb, sk = gs.build_outlook_section(sec, A, f)
    assert rb == ["npc_outlook/adabra"] and calls == ["adabra"]
    # unchanged inputs -> fresh, renderer NOT called again
    rb2, sk2 = gs.build_outlook_section(sec, A, f)
    assert rb2 == [] and "npc_outlook/adabra (fresh)" in sk2
    assert calls == ["adabra"]
    # dossier edit -> re-render
    (camp / "docs/ensemble/state_dossiers/npc_adabra.md").write_text("Adabra dossier v2.")
    rb3, _ = gs.build_outlook_section(sec, A, f)
    assert rb3 == ["npc_outlook/adabra"] and calls == ["adabra", "adabra"]
    assert "### adabra" in f.read_text()


def test_tracking_section_guards(tmp_path):
    camp = _campaign(tmp_path)
    # no tracking lists -> clean skip
    r = run_cli(camp, "build", "--doc", "campaign_state")
    assert "tracking (no tracking lists)" in r.stdout
    # lists present but no backend -> no-implicit-spend guard
    (camp / "docs/tracking-storm-lords-wrath.txt").write_text(
        "# Main Quests\nAttack on the Wayside Inn\n")
    r2 = run_cli(camp, "build", "--doc", "campaign_state")
    assert "tracking (synthesis — pass --backend to render)" in r2.stdout


def test_synthesis_section_never_spends_without_backend(tmp_path):
    camp = _campaign(tmp_path)
    d = camp / "docs/ensemble/merged_dossiers"
    d.mkdir(parents=True)
    (d / "faction_kraken_society.md").write_text("---\nname: k\n---\nDossier.")
    r = run_cli(camp, "build", "--doc", "planning")
    assert r.returncode == 0, r.stderr
    assert "factions (synthesis — pass --backend to render)" in r.stdout


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
