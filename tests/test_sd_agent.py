"""Tests for the stage-scoped orchestrator (spec 007, US3).

The properties that matter here are boundaries, not behaviour: the run must
stop at the human checkpoint, must not leak a secret into a printed command,
must continue when a check reports findings, and must stop when generation
fails. Each is asserted directly.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import campaignlib  # noqa: E402

# See tests/test_locate_quote_parity.py for why this guard exists.
_resolved = Path(campaignlib.__file__).resolve().parent.parent
if _resolved != _REPO_ROOT:
    pytest.skip(
        f"campaignlib resolved to {_resolved}, not this worktree ({_REPO_ROOT}) "
        f"— this run would be testing main's code. Run this file on its own.",
        allow_module_level=True,
    )

from session_doc import sd_agent  # noqa: E402
from session_doc.sd_agent import build_parser, build_steps, resolve_vtt  # noqa: E402


def _args(**over):
    argv = ["--stage", over.pop("stage", "summary"),
            "--session-dir", str(over.pop("session_dir"))]
    for k, v in over.items():
        flag = "--" + k.replace("_", "-")
        if v is True:
            argv.append(flag)
        elif isinstance(v, list):
            argv += [flag, *v]
        elif v is not None:
            argv += [flag, str(v)]
    return build_parser().parse_args(argv)


@pytest.fixture
def session(tmp_path):
    (tmp_path / "s.vtt").write_text("WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nA: hi.\n")
    (tmp_path / "gm-assist.md").write_text("# recap\n")
    (tmp_path / "session-summary.md").write_text("# summary\n")
    return tmp_path


# ── Step construction ────────────────────────────────────────────────────────

def test_summary_stage_has_three_steps_with_context(session):
    ctx = session / "campaign_state.md"
    ctx.write_text("# state\n")
    steps, notes = build_steps(_args(session_dir=session, context=[str(ctx)]))
    assert [s.key for s in steps] == ["generate", "verify", "consistency"]
    assert not notes


def test_summary_stage_skips_consistency_without_context_and_says_so(session):
    """A skipped check must be announced, not silently absent."""
    steps, notes = build_steps(_args(session_dir=session))
    assert [s.key for s in steps] == ["generate", "verify"]
    assert any("SKIPPED" in n for n in notes)


def test_scenes_stage_has_no_consistency_step(session):
    """sd_consistency compares a *recap* to grounding docs; per-scene
    extraction files are not a recap."""
    ctx = session / "campaign_state.md"
    ctx.write_text("# state\n")
    steps, _ = build_steps(_args(session_dir=session, stage="scenes", context=[str(ctx)]))
    assert [s.key for s in steps] == ["generate", "verify"]


def test_summary_stage_never_emits_scene_extract(session):
    """FR-018 — the Stage 1→2 human gate must survive orchestration."""
    steps, _ = build_steps(_args(session_dir=session))
    joined = " ".join(" ".join(s.cmd) for s in steps)
    assert "scene_extract" not in joined


def test_scenes_stage_never_emits_enhance_summary(session):
    steps, _ = build_steps(_args(session_dir=session, stage="scenes"))
    joined = " ".join(" ".join(s.cmd) for s in steps)
    assert "enhance_summary" not in joined


def test_skip_generate_drops_only_the_generation_step(session):
    steps, _ = build_steps(_args(session_dir=session, skip_generate=True))
    assert [s.key for s in steps] == ["verify"]


# ── The shared-transcript invariant ──────────────────────────────────────────

def test_same_vtt_reaches_generation_and_verification(session):
    """Verifying against a different .vtt than generation read would report
    edits that were never made."""
    steps, _ = build_steps(_args(session_dir=session))
    gen = next(s for s in steps if s.key == "generate")
    ver = next(s for s in steps if s.key == "verify")
    vtt = str(session / "s.vtt")
    assert vtt in gen.cmd
    assert ver.cmd[ver.cmd.index("--vtt") + 1] == vtt


def test_explicit_vtt_wins_over_the_glob(session):
    other = session / "other.vtt"
    other.write_text("WEBVTT\n")
    assert resolve_vtt(_args(session_dir=session, vtt=other)) == other


def test_missing_vtt_is_an_error_not_a_guess(tmp_path):
    (tmp_path / "gm-assist.md").write_text("x")
    with pytest.raises(ValueError, match="no .vtt found"):
        build_steps(_args(session_dir=tmp_path))


def test_missing_gmassist_is_an_error(session):
    (session / "gm-assist.md").unlink()
    with pytest.raises(ValueError, match="gm-assist not found"):
        build_steps(_args(session_dir=session))


def test_scenes_stage_requires_a_summary_first(session):
    (session / "session-summary.md").unlink()
    with pytest.raises(ValueError, match="run --stage summary first"):
        build_steps(_args(session_dir=session, stage="scenes"))


# ── Flag forwarding ──────────────────────────────────────────────────────────

def test_backend_flags_reach_generation_only(session):
    """Verification calls no model; giving it --model would imply a cost it
    cannot incur."""
    steps, _ = build_steps(_args(session_dir=session, backend="dgx",
                                 model="deepseek-x", endpoint="http://spark:8001/v1"))
    gen = next(s for s in steps if s.key == "generate")
    ver = next(s for s in steps if s.key == "verify")
    assert "--backend" in gen.cmd and "deepseek-x" in gen.cmd
    for flag in ("--backend", "--model", "--endpoint", "--fast", "--batch"):
        assert flag not in ver.cmd


def test_scene_grounding_flags_reach_scene_extract(session, tmp_path):
    """--dossier-dir/--party/--players-config must survive the hop. Since
    6e00f54 the roster is the ONLY channel for canonical NPC spellings (the VTT
    is deliberately never rewritten), so an orchestrator that drops it produces
    name-shaped quote findings that look like fabrication.

    ``--players-config`` replaced ``--gm-player`` in feature 009: one string
    could hold only one of a person's display names, and the game master has as
    many as anyone else."""
    dossiers = session / "npcs"
    dossiers.mkdir()
    party = session / "party.md"
    party.write_text("# party\n")
    players = tmp_path / "players.yaml"
    players.write_text("players: []\n", encoding="utf-8")
    steps, notes = build_steps(_args(
        session_dir=session, stage="scenes",
        dossier_dir=dossiers, party=party, players_config=players,
    ))
    gen = next(s for s in steps if s.key == "generate")
    assert "--dossier-dir" in gen.cmd and str(dossiers) in gen.cmd
    assert "--party" in gen.cmd and str(party) in gen.cmd
    assert "--players-config" in gen.cmd and str(players) in gen.cmd
    assert not any("dossier" in n for n in notes)


def test_missing_dossier_dir_with_no_registry_is_announced(session, monkeypatch):
    """Losing the roster degrades extraction invisibly — the run must say so
    rather than let the GM read the findings as fabrication (Principle VIII)."""
    monkeypatch.setattr(sd_agent, "_registry_visible", lambda: False)
    steps, notes = build_steps(_args(session_dir=session, stage="scenes"))
    gen = next(s for s in steps if s.key == "generate")
    assert "--dossier-dir" not in gen.cmd
    assert any("NO entity registry" in n for n in notes)


def test_missing_dossier_dir_with_a_registry_is_NOT_an_alarm(session, monkeypatch):
    """scene_extract auto-discovers docs/entity_registry.yaml from the CWD and a
    registry REPLACES the dossier scan, so the roster already reaches the model.
    Telling the GM to pass --dossier-dir here would be advice to add a flag the
    registry supersedes."""
    monkeypatch.setattr(sd_agent, "_registry_visible", lambda: True)
    _, notes = build_steps(_args(session_dir=session, stage="scenes"))
    assert not any("will not reach the model" in n for n in notes)
    assert any("supersedes" in n for n in notes)


def test_scene_grounding_flags_do_not_leak_into_the_summary_stage(session):
    """They configure scene extraction; enhance_summary has no such options,
    so forwarding them there would just crash the generation step."""
    dossiers = session / "npcs"
    dossiers.mkdir()
    steps, _ = build_steps(_args(session_dir=session, stage="summary",
                                 dossier_dir=dossiers,
                                 players_config=session / "players.yaml"))
    for s in steps:
        assert "--dossier-dir" not in s.cmd
        assert "--players-config" not in s.cmd


def test_scene_grounding_flags_never_reach_verification(session):
    dossiers = session / "npcs"
    dossiers.mkdir()
    steps, _ = build_steps(_args(session_dir=session, stage="scenes",
                                 dossier_dir=dossiers,
                                 players_config=session / "players.yaml"))
    ver = next(s for s in steps if s.key == "verify")
    for flag in ("--dossier-dir", "--party", "--players-config"):
        assert flag not in ver.cmd


def test_threshold_and_report_only_reach_verification_only(session):
    steps, _ = build_steps(_args(session_dir=session, threshold=0.9, report_only=True))
    ver = next(s for s in steps if s.key == "verify")
    gen = next(s for s in steps if s.key == "generate")
    assert "--threshold" in ver.cmd and "0.9" in ver.cmd
    assert "--report-only" in ver.cmd
    assert "--threshold" not in gen.cmd


def test_no_secret_appears_in_any_command(session, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET-VALUE")
    steps, _ = build_steps(_args(session_dir=session, backend="anthropic"))
    joined = " ".join(" ".join(s.cmd) for s in steps)
    assert "SECRET" not in joined and "sk-ant" not in joined


# ── Exit-code semantics ──────────────────────────────────────────────────────

def _run(*argv):
    return subprocess.run([sys.executable, "-m", "session_doc.sd_agent", *argv],
                          capture_output=True, text=True, cwd=str(_REPO_ROOT))


def test_dry_run_executes_nothing(session):
    r = _run("--stage", "summary", "--session-dir", str(session), "--dry-run")
    assert r.returncode == 0
    assert "Dry run" in r.stdout
    # generation would have overwritten this; it must be untouched
    assert (session / "session-summary.md").read_text() == "# summary\n"


def test_dry_run_prints_every_step(session):
    ctx = session / "campaign_state.md"
    ctx.write_text("# state\n")
    r = _run("--stage", "summary", "--session-dir", str(session),
             "--context", str(ctx), "--dry-run")
    assert "enhance_summary" in r.stdout
    assert "sd_verify_quotes" in r.stdout
    assert "sd_consistency" in r.stdout


def test_missing_session_dir_exits_2(tmp_path):
    r = _run("--stage", "summary", "--session-dir", str(tmp_path / "nope"))
    assert r.returncode == 2


def test_findings_do_not_abort_the_run(session):
    """FR-019: a check reporting findings is the tool working, not an error.

    Generation is skipped so the run is a pure check over a summary containing
    one fabricated quote; verification exits 1 and the agent must still finish
    and summarise rather than bail.
    """
    (session / "session-summary.md").write_text(
        '## Memorable Moments\n\n> "Words that were never spoken at this table."\n'
    )
    r = _run("--stage", "summary", "--session-dir", str(session),
             "--skip-generate", "--report-only")
    assert r.returncode == 1, r.stderr
    assert "findings" in r.stdout
    assert "Nothing was auto-corrected" in r.stdout


def test_clean_run_exits_0(session):
    (session / "session-summary.md").write_text('## Moments\n\n> "hi."\n')
    r = _run("--stage", "summary", "--session-dir", str(session),
             "--skip-generate", "--report-only")
    assert r.returncode == 0, r.stderr


def test_run_states_that_it_stopped_at_the_boundary(session):
    (session / "session-summary.md").write_text('## Moments\n\n> "hi."\n')
    r = _run("--stage", "summary", "--session-dir", str(session),
             "--skip-generate", "--report-only")
    assert "STOPPED at the stage boundary" in r.stdout


# ── Layering ─────────────────────────────────────────────────────────────────

def test_agent_makes_no_direct_api_call():
    """Principle VI — it orchestrates CLIs, it does not become one."""
    src = (_REPO_ROOT / "session_doc" / "sd_agent.py").read_text()
    for forbidden in ("stream_api(", "call_api(", "make_client(", "client_from_args("):
        assert forbidden not in src


# ── --party-config forwarding (#265) ─────────────────────────────────────────

def test_scenes_stage_forwards_party_config(session):
    """#265 deleted scene_extract's party.md roster fallback, so --party alone
    now exits 1 there. sd_agent must be able to supply the flag that fixes it —
    it had none, which made `sd_agent --stage scenes --party …` unsatisfiable:
    guaranteed failure with nothing the caller could add."""
    party = session / "party.md"
    party.write_text("## A\n**Human Bard 5, Player: Ann**\n", encoding="utf-8")
    cfg = session / "party.yaml"
    cfg.write_text("characters: []\n", encoding="utf-8")
    steps, _notes = build_steps(_args(
        stage="scenes", session_dir=session, party=party, party_config=cfg))
    generate = next(s for s in steps if s.key == "generate")
    assert "--party-config" in generate.cmd
    assert generate.cmd[generate.cmd.index("--party-config") + 1] == str(cfg)
    assert "--party" in generate.cmd


def test_scenes_stage_omits_party_config_when_not_given(session):
    steps, _notes = build_steps(_args(stage="scenes", session_dir=session))
    generate = next(s for s in steps if s.key == "generate")
    assert "--party-config" not in generate.cmd


# ── --batch-scenes forwarding (013-batched-scene-extraction) ─────────────────
#
# Before this, `sd_agent --stage scenes` could not reach batched extraction at
# all: `_selection_args` forwards an enumerated five flags and --batch-scenes
# was not among them, so a subscription run silently sent the transcript once
# per scene — the exact 8x cost the feature exists to remove — with nothing in
# the output saying so.

def _scene_cmd(session, **over):
    steps, _ = build_steps(_args(session_dir=session, stage="scenes", **over))
    gen = [s for s in steps if s.key == "generate"]
    assert gen, "scenes stage must have a generate step"
    return gen[0].cmd


def test_scenes_stage_defaults_batched_on_for_the_subscription_backend(session):
    """No prompt caching there, so per-scene re-sends the whole transcript."""
    cmd = _scene_cmd(session, backend="claude-code")
    assert "--batch-scenes" in cmd
    assert "--no-batch-scenes" not in cmd


def test_scenes_stage_defaults_batched_off_for_the_metered_backend(session):
    """anthropic caches the repeated transcript; batching buys nothing there."""
    cmd = _scene_cmd(session, backend="anthropic")
    assert "--no-batch-scenes" in cmd
    assert "--batch-scenes" not in cmd


def test_explicit_batch_scenes_overrides_the_backend_default_both_ways(session):
    on_metered = _scene_cmd(session, backend="anthropic", batch_scenes=True)
    assert "--batch-scenes" in on_metered

    off_subscription = _scene_cmd(session, backend="claude-code",
                                  no_batch_scenes=True)
    assert "--no-batch-scenes" in off_subscription
    assert "--batch-scenes" not in off_subscription


def test_the_flag_is_always_explicit_never_omitted(session):
    """sd_agent prints the resolved command; an omitted flag would hide the
    choice it made. Every scenes run states which mode it picked."""
    for backend in ("claude-code", "anthropic", None):
        cmd = _scene_cmd(session, backend=backend) if backend else _scene_cmd(session)
        assert ("--batch-scenes" in cmd) or ("--no-batch-scenes" in cmd), backend


def test_batch_scenes_never_reaches_the_summary_stage(session):
    """enhance_summary has no such flag — forwarding it there is an argparse
    error, which is why this lives outside _selection_args."""
    steps, _ = build_steps(_args(session_dir=session, stage="summary",
                                 backend="claude-code"))
    joined = " ".join(" ".join(s.cmd) for s in steps)
    assert "batch-scenes" not in joined


def test_batch_scenes_is_not_confused_with_batch(session):
    """--batch (Message Batches) and --batch-scenes are separate features."""
    cmd = _scene_cmd(session, backend="claude-code")
    assert "--batch-scenes" in cmd
    assert "--batch" not in cmd


def test_inferred_batch_scenes_stands_down_for_an_explicit_batch(session):
    """An INFERRED flag must never fight a flag the user actually typed.

    `--batch` (Message Batches) and `--batch-scenes` are mutually exclusive
    in scene_extract. Before this, `sd_agent --stage scenes --backend
    claude-code --batch` inferred --batch-scenes from the backend, built both,
    and died with "--batch-scenes cannot be combined with --batch" — naming a
    flag the user never wrote, for a choice they never made. The user's
    explicit --batch wins; the inference stands down.
    """
    cmd = _scene_cmd(session, backend="claude-code", batch=True)
    assert "--batch" in cmd
    assert "--no-batch-scenes" in cmd
    assert "--batch-scenes" not in cmd


def test_an_explicit_pair_still_conflicts_and_is_diagnosed_by_scene_extract(session):
    """Both flags typed by hand IS a real conflict — pass it through.

    scene_extract's own refusal names both flags correctly because the user
    wrote both. Duplicating that guard in sd_agent would give two places to
    keep in step, so this asserts the pass-through rather than a second
    refusal.
    """
    cmd = _scene_cmd(session, backend="claude-code", batch=True, batch_scenes=True)
    assert "--batch" in cmd
    assert "--batch-scenes" in cmd


def test_batch_does_not_suppress_an_explicit_no_batch_scenes(session):
    """--batch plus an explicit opt-out is not a conflict; both are honoured."""
    cmd = _scene_cmd(session, backend="claude-code", batch=True,
                     no_batch_scenes=True)
    assert "--batch" in cmd
    assert "--no-batch-scenes" in cmd
