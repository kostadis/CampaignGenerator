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
    draft = (camp / "docs/projections/campaign_state_draft.md").read_text()
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
    assert "UBT begins." in (camp / "docs/projections/campaign_state_draft.md").read_text()


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
    draft = (camp / "docs/projections/planning_draft.md").read_text()
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
    draft = (camp / "docs/projections/planning_draft.md").read_text()
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
    from campaignlib.projection_config import ProjectionConfig
    camp = _campaign(tmp_path)
    (camp / "docs/ensemble/state_dossiers").mkdir(parents=True)
    (camp / "docs/ensemble/state_dossiers/npc_adabra.md").write_text("Adabra dossier.")
    calls = []
    monkeypatch.setattr(gs, "render_outlook_block",
                        lambda slug, inputs, args, sections_dir: calls.append(slug) or f"### {slug}\nBlock.")
    monkeypatch.chdir(camp)

    class A:
        npcs = "adabra"
        force = False
        model = None
        max_tokens = None
        backend = "dgx"

    cfg = ProjectionConfig()
    sec = gs.Section("npc_outlook", "npc_outlook", optional=True)
    # No config/projections.yaml in this fixture, so this is the same default
    # sections_dir main() would resolve — see ProjectionOutput.sections_dir.
    sections_dir = Path("docs/grounding_sections")
    f = sections_dir / "planning" / "npc_outlook.md"
    rb, sk = gs.build_outlook_section(sec, A, f, sections_dir, cfg)
    # Only state_dossiers/ (the fallback set) has this NPC — the choice is
    # now named rather than absorbed silently (research D4, FR-024a).
    assert rb == ["npc_outlook/adabra (fallback)"] and calls == ["adabra"]
    # unchanged inputs -> fresh, renderer NOT called again
    rb2, sk2 = gs.build_outlook_section(sec, A, f, sections_dir, cfg)
    assert rb2 == [] and "npc_outlook/adabra (fresh, fallback dossier)" in sk2
    assert calls == ["adabra"]
    # dossier edit -> re-render
    (camp / "docs/ensemble/state_dossiers/npc_adabra.md").write_text("Adabra dossier v2.")
    rb3, _ = gs.build_outlook_section(sec, A, f, sections_dir, cfg)
    assert rb3 == ["npc_outlook/adabra (fallback)"] and calls == ["adabra", "adabra"]
    assert "### adabra" in f.read_text()
    assert "_Dossier: fallback._" in f.read_text()


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
    draft = (camp / "docs/projections/campaign_state_draft.md").read_text()
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


def test_dossiers_entirely_absent_skips_synthesis_and_exits_zero(tmp_path):
    """Neither a curated nor a fallback dossier directory exists on disk at
    all — the live-campaign case this closes (research D4: Phandalin has no
    merged_dossiers/, and until now nothing said the fallback was even
    attempted, let alone that BOTH could be absent). All four world_state
    sections must skip with a stated reason and the build must still exit
    zero: a campaign with no dossiers extracted yet is an expected early
    state, not an error. ``--backend`` is passed to prove the skip is about
    missing dossiers and not the separate no-implicit-spend guard.

    ALL FOUR of world_state's sections are omittable here (none is a
    non-degradable "anchor" the way campaign_state's party/recent_events or
    planning's threads are) — so this is also the SC-007 total-degrade
    case; see test_total_degrade_writes_no_draft_and_says_so below for the
    dedicated assertions on the no-draft-written behavior itself.
    """
    camp = _campaign(tmp_path)
    r = run_cli(camp, "build", "--doc", "world_state", "--backend", "anthropic")
    assert r.returncode == 0, r.stderr
    for name in ("npcs", "factions", "locations", "world"):
        assert f"{name} (no dossiers matched)" in r.stdout
    assert "rebuilt: nothing" in r.stdout
    assert "dossiers: docs/ensemble/state_dossiers (fallback)" in r.stdout


def test_total_degrade_writes_no_draft_and_says_so(tmp_path):
    """SC-007's other half, spelled out on its own: when EVERY section is
    omitted, no draft is written at all — an empty-but-titled document is
    worse than none, because there's nothing to review and the file's mere
    existence implies otherwise. stdout must plainly say no draft was
    written and list why, since there is no file left to say it in.
    """
    camp = _campaign(tmp_path)
    r = run_cli(camp, "build", "--doc", "world_state", "--backend", "anthropic")
    assert r.returncode == 0, r.stderr
    assert not (camp / "docs/projections/world_state_draft.md").exists()
    assert not (camp / "docs/projections").exists() or not any(
        (camp / "docs/projections").iterdir())
    assert "no draft written for world_state: nothing to assemble" in r.stdout
    assert "every section was omitted" in r.stdout
    for name in ("npcs", "factions", "locations", "world"):
        assert f"{name}: no dossiers matched under" in r.stdout


def test_partial_degrade_writes_draft_with_omission_block(tmp_path):
    """A REAL section renders (party.md is always present in _campaign),
    but a synthesis section with no matching dossiers is omitted — the
    draft must still be written (partial success, per spec's edge case),
    AND must carry an explicit, near-the-top block naming what's missing
    and why, because that file — not this run's stdout — is what a GM
    diffs, possibly days later.
    """
    camp = _campaign(tmp_path)
    # planning's "factions" section is optional + synthesis; with no
    # dossiers at all it degrades rather than erroring, while "threads"
    # (non-optional, backed by docs/thread_registry.yaml) still renders.
    r = run_cli(camp, "build", "--doc", "planning")
    assert r.returncode == 0, r.stderr
    draft_path = camp / "docs/projections/planning_draft.md"
    assert draft_path.exists()
    draft = draft_path.read_text()
    # The real content is still there...
    assert "The Carver's march" in draft
    # ...but the omission notice comes BEFORE it, near the top of the file,
    # and names every omitted section with its reason.
    header_end = draft.index("The Carver's march")
    notice_pos = draft.index("INCOMPLETE DRAFT")
    assert notice_pos < header_end
    assert "notes" in draft[:header_end] and "optional, no input" in draft[:header_end]
    assert draft.index("# Planning (draft)") < notice_pos


# ── Backend seam: --backend/--endpoint/--batch come from add_backend_args ───
#
# This CLI used to hand-roll --backend/--endpoint and so never grew --batch,
# leaving the 50%-cost Claude batch path unreachable for the only sections
# that actually spend tokens. Adopting the seam had to happen WITHOUT
# defaulting --backend to "anthropic", because the no-implicit-spend guard
# keys on the flag being falsy when omitted.


def test_build_exposes_the_uniform_batch_flag(tmp_path):
    """--batch is registered here like on every other registrar CLI."""
    camp = _campaign(tmp_path)
    r = run_cli(camp, "build", "--help")
    assert r.returncode == 0, r.stderr
    assert "--batch" in r.stdout
    assert "--endpoint" in r.stdout


def test_backend_still_has_no_default_so_spend_stays_opt_in(tmp_path):
    """The seam must not hand --backend a truthy default.

    `add_backend_args`' normal default is "anthropic"; taking it here would
    make `if not args.backend` always false and start rendering — and paying
    for — LLM sections on a plain deterministic build.
    """
    camp = _campaign(tmp_path)
    # a dossier must exist, or "no dossiers matched" short-circuits ahead of
    # the backend guard and the test proves nothing (cf.
    # test_synthesis_section_never_spends_without_backend)
    d = camp / "docs/ensemble/merged_dossiers"
    d.mkdir(parents=True)
    (d / "faction_kraken_society.md").write_text("---\nname: k\n---\nDossier.")
    r = run_cli(camp, "build", "--doc", "planning")
    assert r.returncode == 0, r.stderr
    assert "factions (synthesis — pass --backend to render)" in r.stdout
    # help must not advertise a default that would defeat the guard
    h = run_cli(camp, "build", "--help")
    assert "no default" in h.stdout


def test_batch_is_forwarded_to_the_synthesis_subprocess(monkeypatch):
    """A --batch that stopped at this process would be silently inert for
    exactly the sections that do the spending."""
    sys.path.insert(0, str(REPO))
    import importlib.util
    spec = importlib.util.spec_from_file_location("_gs", CLI)
    gs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gs)

    import types

    captured = {}

    def _fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(gs.subprocess, "run", _fake_run)

    class _Args:
        registry = None
        backend = "anthropic"
        endpoint = None
        model = None
        max_tokens = None
        batch = True

    sec = gs.Section(name="factions", mode="synthesis")
    gs.render_synthesis(sec, _Args(), [Path("d.md")], Path("out.md"))
    assert "--batch" in captured["cmd"]

    _Args.batch = False
    gs.render_synthesis(sec, _Args(), [Path("d.md")], Path("out.md"))
    assert "--batch" not in captured["cmd"]
