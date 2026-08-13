"""End-to-end delivery of Pass 5's style inputs: session_doc.yaml → prompt (#299).

Every stage of this chain was already unit-tested when #295 was found, and the
chain was still broken on all three live campaigns:

    session_doc.yaml            tests/test_session_editor_config_service.py
      -> resolved config        tests/test_narrate_genre_file.py
      -> argv                   (nothing)
      -> sd_narrate loaders     tests/test_narrate_genre_file.py, test_sd_narrate.py
      -> system prompt          tests/test_narrate_genre.py

The untested link was argv, and the failure it hid was total: no genre directive
reached the narrator for months. A per-stage suite cannot catch that, because
every stage was individually correct — so this module asserts the composition
instead, and does it the way the server does (real config file, real path
resolution, real command builder, real loaders).

It deliberately stops short of the API call. What is being verified is that the
text a GM put in a file arrives in the system prompt, which is exactly the
property #295 lost.
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
    Roster,
    SessionEditorConfig,
    save_session_editor_config,
)
from session_doc.examples import get_char_examples  # noqa: E402
from session_doc.narrate import build_narrate_system  # noqa: E402
from session_doc.sd_narrate import _load_examples, _load_genre_file  # noqa: E402
from session_doc.voice import get_voice_note, load_voice_files  # noqa: E402

GENRE_TEXT = """# Register

First person, past tense, one POV per section.

## Banned tics
- "the shape of X"
"""

VOICE_TEXT = """# Vukradin

Principled volleys. Says "fair-trade, conflict-free gold" without irony.
"""

EXAMPLES_TEXT = """# Vukradin — style reference

I set the halberd down before I answered him.
"""


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
    # `_genre.md` sits INSIDE voice/, and the `_` prefix is what keeps it from
    # being read as a per-character spec — the arrangement every live campaign
    # uses, so the test would catch a regression in either skip rule.
    (voice / "_genre.md").write_text(GENRE_TEXT, encoding="utf-8")
    # The real Phandalin filename shape (#247): neither `vukradin.md` nor
    # `vukradin_voice.md`, so resolution rule (c) has to fire for this to pass.
    (voice / "vukradin_new_pipeline.md").write_text(VOICE_TEXT, encoding="utf-8")

    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "vukradin.md").write_text(EXAMPLES_TEXT, encoding="utf-8")

    session = tmp_path / "20260801"
    session.mkdir()
    (session / "session-summary.md").write_text(
        "# Recap\n\n## Scenes\n\n### Scene One\n- bullet\n", encoding="utf-8"
    )
    sx = session / "scene_extractions"
    sx.mkdir()
    (sx / "01_scene_one.md").write_text(
        "---\nscene: Scene One\n---\n\n## Verbatim moments\n\nVukradin: \"No.\"\n",
        encoding="utf-8",
    )
    nd = session / "narration"
    nd.mkdir()
    (nd / "plan.md").write_text(
        "## Section 1\nnarrator: Vukradin\nscene: Scene One\nchunks: 1-1\nfocus: f\n",
        encoding="utf-8",
    )
    return tmp_path, session


def _write_config(campaign: Path, session: Path, *, genre_file: str | None) -> None:
    cfg = SessionEditorConfig(
        paths=EditorPaths(
            session_summary=str(session / "session-summary.md"),
            scene_extractions_dir=str(session / "scene_extractions"),
            narration_dir=str(session / "narration"),
            voice_dir="voice",
            examples_dir="examples",
            genre_file=genre_file,
        ),
        roster=Roster(characters="Vukradin"),
    )
    # Written through the module-level saver, not the service, so the stored
    # shape is exactly what a GM's hand-edited session_doc.yaml looks like.
    save_session_editor_config(campaign / "config" / "session_doc.yaml", cfg)


def _argv(campaign: Path) -> list[str]:
    platform = PlatformConfigService(str(campaign))
    resolved = SessionEditorConfigService(platform).resolved_editor_config()
    cmd = scene_editor._build_narrate_cmd(None, resolved, 1)
    assert isinstance(cmd, list), cmd
    return cmd


def _flag(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else None


def _system_prompt_from(argv: list[str], narrator: str = "Vukradin") -> str:
    """Drive sd_narrate's own loaders from argv and build the system prompt.

    This mirrors `sd_narrate.main`'s input handling rather than re-implementing
    it — the point is to catch a flag that stops being emitted, so the readers
    on the far side have to be the real ones.
    """
    characters = [c.strip() for c in (_flag(argv, "--characters") or "").split(",") if c.strip()]
    voice_dir = _flag(argv, "--voice-dir")
    examples_dir = _flag(argv, "--examples")

    genre = _load_genre_file(_flag(argv, "--narration-genre-file"))
    voices = load_voice_files(Path(voice_dir)) if voice_dir else {}
    examples_text, per_char = _load_examples(
        Path(examples_dir) if examples_dir else None, characters
    )
    return build_narrate_system(
        examples_text,
        scene="Scene One",
        narrator=narrator,
        char_examples=get_char_examples(per_char, narrator) if per_char else None,
        voice_note=get_voice_note(voices, narrator) if voices else None,
        genre=genre,
    )


# ── the whole chain, configured ──────────────────────────────────────────────


def test_configured_inputs_all_reach_the_system_prompt(tmp_path):
    campaign, session = _campaign(tmp_path)
    _write_config(campaign, session, genre_file="voice/_genre.md")

    prompt = _system_prompt_from(_argv(campaign))

    assert "First person, past tense" in prompt          # genre rulebook
    assert '"the shape of X"' in prompt                  # ...including its tail
    assert "fair-trade, conflict-free gold" in prompt    # voice spec
    assert "I set the halberd down" in prompt            # per-character examples


def test_campaign_relative_style_paths_resolve_against_the_campaign(tmp_path):
    """`voice`/`examples`/`voice/_genre.md` are stored relative on every live
    campaign; argv must carry them absolute or the subprocess resolves them
    against its own cwd."""
    campaign, session = _campaign(tmp_path)
    _write_config(campaign, session, genre_file="voice/_genre.md")

    argv = _argv(campaign)

    assert _flag(argv, "--voice-dir") == str(campaign / "voice")
    assert _flag(argv, "--examples") == str(campaign / "examples")
    assert _flag(argv, "--narration-genre-file") == str(campaign / "voice" / "_genre.md")


def test_genre_arrives_as_a_delimited_block_not_an_inline_label(tmp_path):
    """#276: a multi-line rulebook must not be wedged in as `GENRE: ...`."""
    campaign, session = _campaign(tmp_path)
    _write_config(campaign, session, genre_file="voice/_genre.md")

    prompt = _system_prompt_from(_argv(campaign))

    assert "GENRE & REGISTER (campaign-specific) — BEGIN" in prompt
    assert "GENRE: # Register" not in prompt


# ── the whole chain, with the rulebook unset (the #295 state) ────────────────


def test_unset_genre_file_costs_the_prompt_its_whole_rulebook(tmp_path):
    """The regression #299 exists to make visible.

    Every other input still arrives, which is why this went unnoticed: the
    renders kept working and kept sounding like the characters. Only the
    register rules, the banned-tic list and the caps were gone.
    """
    campaign, session = _campaign(tmp_path)
    _write_config(campaign, session, genre_file=None)

    argv = _argv(campaign)
    prompt = _system_prompt_from(argv)

    assert "--narration-genre-file" not in argv
    assert "First person, past tense" not in prompt
    assert "GENRE" not in prompt
    # ...and the loss is silent from here on: voice and examples are unaffected,
    # so nothing downstream looks wrong.
    assert "fair-trade, conflict-free gold" in prompt
    assert "I set the halberd down" in prompt
