"""End-to-end delivery of Pass 5's style inputs: session_doc.yaml → prompt (#299).

Every stage of this chain was already unit-tested when #295 was found, and the
chain was still broken on all three live campaigns:

    session_doc.yaml            tests/test_session_editor_config_service.py
      -> resolved config        tests/test_narrate_genre_file.py
      -> argv                   (nothing)
      -> sd_narrate's parser    (nothing)
      -> sd_narrate's wiring    (nothing — no test passed --narration-genre-file)
      -> system prompt          tests/test_narrate_genre.py

The untested links were argv and everything downstream of it, and the failure
they hid was total: no genre directive reached the narrator for months. A
per-stage suite cannot catch that, because every stage was individually
correct — so this module asserts the composition instead.

**It runs the real `sd_narrate.main()` on the argv the real router built**,
with only the API call stubbed. That matters more than it looks: an earlier
version of this file imported sd_narrate's loaders and re-assembled them by
hand, which left `sd_narrate.main`'s own wiring — the `_load_genre_file` call
at :268 and the `genre=narration_genre` argument at :420 — executed by nothing.
Deleting that argument reproduced #295 exactly and kept the whole suite green.
It also left the flag NAMES unverified in the direction that matters: the
router emitting `--narration-genre-file` proves nothing if sd_narrate's parser
has stopped accepting it, which surfaces to the GM only as "Stream error —
check terminal."

Two narrators, because one cannot detect a leak: a bleed only shows up as one
narrator's material appearing in the other's prompt. Feature 009 replaced the
routing rule with declarations, so the leak the fall-through produced is gone
by construction — these tests now assert that each narrator receives exactly
what its roster entry names, and nothing else.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.platform_config_service import PlatformConfigService  # noqa: E402
from server.routers import scene_editor  # noqa: E402
from server.session_editor_config_service import (  # noqa: E402
    SessionEditorConfigService,
)
from server.session_editor_config_shared import (  # noqa: E402
    EditorPaths,
    SessionEditorConfig,
    save_session_editor_config,
)
from session_doc import sd_narrate  # noqa: E402
from session_doc.narrate import NarrationScene, build_bundled_narrate_prompts  # noqa: E402

GENRE_TEXT = """# Register

First person, past tense, one POV per section.

## Banned tics
- "the shape of X"
"""

VUKRADIN_VOICE = """# Vukradin

Principled volleys. Says "fair-trade, conflict-free gold" without irony.
"""

SOMA_VOICE = """# Soma

Tortle-patient asides. Calls the party "my bale".
"""

VUKRADIN_EXAMPLES = """# Vukradin — style reference

I set the halberd down before I answered him.
"""

SOMA_EXAMPLES = """# Soma — style reference

The shell remembers what the mouth forgets.
"""

SKIPPED_EXAMPLES = """# Shared campaign notes

Underscore files are shared material and must never reach a prompt.
"""


class _FakeStream:
    """Records every (system, user) pair sd_narrate builds; returns canned prose."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user})
        return "Narration body.\n\nHandoff line."


def _campaign(tmp_path: Path) -> tuple[Path, Path]:
    """A campaign laid out the way the live ones are: style inputs addressed by
    CAMPAIGN-relative paths, session artifacts by absolute ones."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )

    voice = tmp_path / "voice"
    voice.mkdir()
    # `_genre.md` sits INSIDE voice/ — the arrangement every live campaign uses.
    (voice / "_genre.md").write_text(GENRE_TEXT, encoding="utf-8")
    # The real Phandalin filename shape (#247): neither `vukradin.md` nor
    # `vukradin_voice.md`, so resolution rule (c) has to fire for this to pass.
    # Phandalin's real filename shape: neither `vukradin.md` nor
    # `vukradin_voice.md`. Under the rule feature 009 deleted this resolved only
    # through a first-name-prefix step; now the roster names the file outright,
    # so the shape of the filename stops mattering at all.
    (voice / "vukradin_new_pipeline.md").write_text(VUKRADIN_VOICE, encoding="utf-8")
    (voice / "soma_new_pipeline.md").write_text(SOMA_VOICE, encoding="utf-8")

    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "vukradin.md").write_text(VUKRADIN_EXAMPLES, encoding="utf-8")
    (examples / "soma.md").write_text(SOMA_EXAMPLES, encoding="utf-8")
    # Declared by nobody. Under the old rule it joined a GLOBAL block that
    # reached every narrator; now it reaches none, which is the point.
    (examples / "_shared.md").write_text(SKIPPED_EXAMPLES, encoding="utf-8")

    # The roster: sheets, and the voice/example DECLARATIONS that replaced the
    # first-name-prefix rule.
    for name in ("Vukradin", "Soma"):
        (tmp_path / "docs").mkdir(exist_ok=True)
        (tmp_path / "docs" / f"{name}.md").write_text(
            f"---\nplayer: someone\nspecies: Human\nclass_level: Fighter 5\n"
            f"---\n\n# {name}\n",
            encoding="utf-8",
        )
    (tmp_path / "config" / "party.yaml").write_text(
        "characters:\n"
        "- name: Vukradin\n"
        "  sheet: docs/Vukradin.md\n"
        "  voice: voice/vukradin_new_pipeline.md\n"
        "  examples: examples/vukradin.md\n"
        "- name: Soma\n"
        "  sheet: docs/Soma.md\n"
        "  voice: voice/soma_new_pipeline.md\n"
        "  examples: examples/soma.md\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "players.yaml").write_text(
        "players:\n"
        "- id: dave\n"
        "  name: Dave Mendenhall\n"
        "  display_names: [Dave]\n"
        "  plays: [Vukradin]\n"
        "- id: wade\n"
        "  name: Wade Brown\n"
        "  display_names: [Wade]\n"
        "  plays: [Soma]\n",
        encoding="utf-8",
    )

    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "party.md").write_text(
        "## Vukradin\n**Human Fighter 5**\n\n## Soma\n**Tortle Druid 6**\n",
        encoding="utf-8",
    )

    session = tmp_path / "20260801"
    session.mkdir()
    (session / "session-summary.md").write_text(
        "# Recap\n\n## Scenes\n\n### Scene One\n- bullet\n\n### Scene Two\n- bullet\n",
        encoding="utf-8",
    )
    sx = session / "scene_extractions"
    sx.mkdir()
    (sx / "01_scene_one.md").write_text(
        "---\nscene: Scene One\n---\n\n## Verbatim moments\n\nVukradin: \"No.\"\n",
        encoding="utf-8",
    )
    (sx / "02_scene_two.md").write_text(
        "---\nscene: Scene Two\n---\n\n## Verbatim moments\n\nSoma: \"Slowly.\"\n",
        encoding="utf-8",
    )
    nd = session / "narration"
    nd.mkdir()
    (nd / "plan.md").write_text(
        "## Section 1\nnarrator: Vukradin\nscene: Scene One\nchunks: 1-1\nfocus: f\n\n"
        "## Section 2\nnarrator: Soma\nscene: Scene Two\nchunks: 2-2\nfocus: g\n",
        encoding="utf-8",
    )
    return tmp_path, session


def _write_config(campaign: Path, session: Path, *, genre_file: str | None,
                  characters: str | None = None) -> None:
    """``characters`` is accepted and ignored — feature 009 deleted the roster
    group; the cast comes from ``party.yaml``."""
    cfg = SessionEditorConfig(
        paths=EditorPaths(
            session_summary=str(session / "session-summary.md"),
            scene_extractions_dir=str(session / "scene_extractions"),
            narration_dir=str(session / "narration"),
            voice_dir="voice",
            examples_dir="examples",
            genre_file=genre_file,
            party="docs/party.md",
        ),
    )
    # Written through the module-level saver, not the service, so the stored
    # shape is exactly what a GM's hand-edited session_doc.yaml looks like.
    save_session_editor_config(campaign / "config" / "session_doc.yaml", cfg)


def _argv(campaign: Path, scene: int) -> list[str]:
    platform = PlatformConfigService(str(campaign))
    resolved = SessionEditorConfigService(platform).resolved_editor_config()
    cmd = scene_editor._build_narrate_cmd(None, resolved, scene)
    assert isinstance(cmd, list), cmd
    return cmd


def _flag(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else None


def _system_prompt(monkeypatch, tmp_path: Path, campaign: Path, scene: int) -> str:
    """Run the REAL sd_narrate.main() on the REAL router argv; return its system prompt.

    Only the API call and the client are stubbed. Everything else — argparse,
    `_load_genre_file`, `load_voice_files`, `_load_examples`, the
    `build_narrate_system` call and its arguments — is the production path.
    """
    fake = _FakeStream()
    monkeypatch.setattr(sd_narrate, "stream_api", fake)
    monkeypatch.setattr(sd_narrate, "client_from_args", lambda args: object())
    # No docs/entity_registry.yaml under tmp_path, so alias_map stays empty and
    # the repo's own registry is not picked up from the real cwd.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", _argv(campaign, scene))

    sd_narrate.main()

    assert len(fake.calls) == 1, fake.calls
    return fake.calls[0]["system"]


# ── the whole chain, configured ──────────────────────────────────────────────


def test_configured_inputs_all_reach_the_system_prompt(monkeypatch, tmp_path):
    campaign, session = _campaign(tmp_path)
    _write_config(campaign, session, genre_file="voice/_genre.md")

    prompt = _system_prompt(monkeypatch, tmp_path, campaign, scene=1)

    assert "First person, past tense" in prompt          # genre rulebook
    assert '"the shape of X"' in prompt                  # ...including its tail
    assert "fair-trade, conflict-free gold" in prompt    # voice spec
    assert "I set the halberd down" in prompt            # per-character examples


def test_per_character_examples_do_not_leak_across_narrators(monkeypatch, tmp_path):
    """The assertion a single-narrator test cannot make.

    Drop `--characters` and `_load_examples` routes BOTH example files into the
    global block, so every narrator reads every other narrator's examples while
    a substring check on their own still passes (#301). Only a second narrator
    can see that.
    """
    campaign, session = _campaign(tmp_path)
    _write_config(campaign, session, genre_file="voice/_genre.md")

    soma = _system_prompt(monkeypatch, tmp_path, campaign, scene=2)

    assert "The shell remembers" in soma                 # her own examples
    assert "my bale" in soma                             # her own voice spec
    assert "I set the halberd down" not in soma          # NOT Vukradin's
    assert "fair-trade, conflict-free gold" not in soma  # NOT Vukradin's spec


def test_underscore_examples_file_reaches_nobody(monkeypatch, tmp_path):
    campaign, session = _campaign(tmp_path)
    _write_config(campaign, session, genre_file="voice/_genre.md")

    for scene in (1, 2):
        prompt = _system_prompt(monkeypatch, tmp_path, campaign, scene)
        assert "Underscore files are shared material" not in prompt


def test_campaign_relative_style_paths_resolve_against_the_campaign(tmp_path):
    """`voice`/`examples`/`voice/_genre.md` are stored relative on every live
    campaign; argv must carry them absolute or the subprocess resolves them
    against its own cwd."""
    campaign, session = _campaign(tmp_path)
    _write_config(campaign, session, genre_file="voice/_genre.md")

    argv = _argv(campaign, 1)

    assert _flag(argv, "--voice-dir") == str(campaign / "voice")
    assert _flag(argv, "--examples") == str(campaign / "examples")
    assert _flag(argv, "--narration-genre-file") == str(campaign / "voice" / "_genre.md")


def test_genre_arrives_as_a_delimited_block_not_an_inline_label(monkeypatch, tmp_path):
    """#276: a multi-line rulebook must not be wedged in as `GENRE: ...`."""
    campaign, session = _campaign(tmp_path)
    _write_config(campaign, session, genre_file="voice/_genre.md")

    prompt = _system_prompt(monkeypatch, tmp_path, campaign, scene=1)

    assert "GENRE & REGISTER (campaign-specific) — BEGIN" in prompt
    assert "GENRE: # Register" not in prompt


# ── the whole chain, with the rulebook unset (the #295 state) ────────────────


def test_unset_genre_file_costs_the_prompt_its_whole_rulebook(monkeypatch, tmp_path):
    """The regression #299 exists to make visible.

    Every other input still arrives, which is why this went unnoticed: the
    renders kept working and kept sounding like the characters. Only the
    register rules, the banned-tic list and the caps were gone.
    """
    campaign, session = _campaign(tmp_path)
    _write_config(campaign, session, genre_file=None)

    argv = _argv(campaign, 1)
    prompt = _system_prompt(monkeypatch, tmp_path, campaign, scene=1)

    assert "--narration-genre-file" not in argv
    assert "First person, past tense" not in prompt
    assert "GENRE" not in prompt
    # ...and the loss is silent from here on: voice and examples are unaffected,
    # so nothing downstream looks wrong.
    assert "fair-trade, conflict-free gold" in prompt
    assert "I set the halberd down" in prompt


def _bundle_scene(index: int, narrator: str, *, previous: str | None = None):
    return NarrationScene(
        index=index, scene_name=f"Scene {index}", narrator=narrator,
        focus=f"FOCUS_{index}", source_path=Path(f"{index:02d}.md"),
        source_kind="base", scene_events=f"EVENTS_{index}",
        moments=f"MOMENTS_{index}", voice_note=f"VOICE_{index}",
        character_examples=f"EXAMPLES_{index}", previous_narrator=previous,
        previous_voice_sample=(f"PREVIOUS_{index}" if previous else None),
        estimated_output_tokens=500, output_path=Path(f"out-{index}.md"),
        output_existed=False,
    )


def test_bundle_shared_inputs_are_delivered_once_and_private_inputs_stay_scoped():
    system, user = build_bundled_narrate_prompts(
        [_bundle_scene(1, "Alice"), _bundle_scene(2, "Bob", previous="Alice")],
        shared_examples="SHARED_STYLE", party="PARTY_DOCUMENT",
        roster="CLASS_ROSTER", npc_roster="NPC_ROSTER",
        context_docs=["HISTORY_ONE", "HISTORY_TWO"],
        genre="GENRE_RULE", prose_mode=True,
    )
    combined = system + "\n" + user

    for shared in (
        "SHARED_STYLE", "PARTY_DOCUMENT", "CLASS_ROSTER", "NPC_ROSTER",
        "HISTORY_ONE", "HISTORY_TWO", "GENRE_RULE",
    ):
        assert combined.count(shared) == 1, shared
    for private in (
        "EVENTS_1", "MOMENTS_1", "VOICE_1", "EXAMPLES_1",
        "EVENTS_2", "MOMENTS_2", "VOICE_2", "EXAMPLES_2", "PREVIOUS_2",
    ):
        assert combined.count(private) == 1, private

    first, second = user.split("## Scene packet 02", 1)
    assert "VOICE_1" in first and "VOICE_2" not in first
    assert "EXAMPLES_1" in first and "EXAMPLES_2" not in first
    assert "VOICE_2" in second and "VOICE_1" not in second
    assert "EXAMPLES_2" in second and "EXAMPLES_1" not in second
