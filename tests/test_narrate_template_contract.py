"""The narrate templates and the code that fills them must agree (#302).

`campaignlib.config.load_agent_prompt` documents a two-way strict check —
"every `{key}` in the template must appear in `placeholders`, and every key in
`placeholders` must appear in the template [...] so prompt drift surfaces
loudly instead of silently producing a malformed prompt" — but it only runs
when a `placeholders` dict is passed. `session_doc/narrate.py` cannot pass one
(its values are computed per call, conditionally, while the templates are
constants loaded at import), so it declined the check and hand-rolled
`str.replace`, which is a no-op on an absent needle.

The consequence, and the reason this file exists: renaming `{genre_directive}`
in `base.md` deleted the genre rulebook from every system prompt with no error,
no warning, and a green suite — in the pipeline that had just lost that
rulebook for months (#295).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doc import narrate  # noqa: E402

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "config" / "agents" / "session_doc" / "narrate"


def test_every_shipped_template_satisfies_its_declared_contract():
    """Importing `narrate` is the check; this states it as an assertion.

    If a template on disk drifts from what the code substitutes, the import at
    the top of this module has already raised.
    """
    assert narrate.NARRATE_SYSTEM_BASE
    for placeholder in ("{genre_directive}", "{examples_block}",
                        "{scene_scope_line}", "{scene_events_line}",
                        "{rendering_instruction}", "{length_instruction}",
                        "{dialogue_instruction}"):
        assert placeholder in narrate.NARRATE_SYSTEM_BASE, placeholder


def test_a_template_missing_a_placeholder_fails_loudly(tmp_path, monkeypatch):
    """The #295-shaped regression: `{genre_directive}` renamed in base.md.

    Before #302 this produced a prompt with no genre block and no complaint.
    """
    override = tmp_path / "config" / "agents" / "session_doc" / "narrate"
    override.mkdir(parents=True)
    text = (TEMPLATE_DIR / "base.md").read_text(encoding="utf-8")
    (override / "base.md").write_text(
        text.replace("{genre_directive}", "{genre_block}"), encoding="utf-8")
    # `load_agent_prompt` caches per ABSOLUTE path, and the override lives
    # under tmp_path, so it is a distinct key from the repo's copy — no cache
    # clearing needed, and none available.
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError) as exc:
        narrate._load_template(
            "session_doc/narrate/base",
            "genre_directive", "examples_block", "scene_scope_line",
            "scene_events_line", "rendering_instruction", "length_instruction",
            "dialogue_instruction",
        )

    msg = str(exc.value)
    assert "placeholder drift" in msg
    assert "genre_directive" in msg          # what the code substitutes
    assert "genre_block" in msg              # what the template now says
    assert "silently never appear" in msg


def test_an_unsubstituted_placeholder_fails_too(tmp_path, monkeypatch):
    """The other direction: a template asking for something nothing supplies,
    which would otherwise reach the model as the literal text `{tone}`."""
    override = tmp_path / "config" / "agents" / "session_doc" / "narrate"
    override.mkdir(parents=True)
    (override / "voice_spec.md").write_text(
        "Voice for {narrator}: {voice_note}\nTone: {tone}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError) as exc:
        narrate._load_template(
            "session_doc/narrate/voice_spec", "narrator", "voice_note")

    msg = str(exc.value)
    assert "['tone']" in msg
    assert "literal text" in msg


def test_a_template_with_no_placeholders_is_valid(tmp_path, monkeypatch):
    """`prose_mode.md`, `dialogue_full.md` and `dialogue_conditional.md` are
    plain prose — declaring no placeholders must not be mistaken for drift."""
    override = tmp_path / "config" / "agents" / "session_doc" / "narrate"
    override.mkdir(parents=True)
    (override / "prose_mode.md").write_text("No placeholders here.\n",
                                            encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert narrate._load_template(
        "session_doc/narrate/prose_mode").strip() == "No placeholders here."


def test_a_campaign_override_is_checked_too(tmp_path, monkeypatch):
    """`load_agent_prompt` resolves a CWD override ahead of the repo's copy, so
    a GM's hand-edited prompt is exactly the case worth failing on — it is the
    one nobody reviews."""
    override = tmp_path / "config" / "agents" / "session_doc" / "narrate"
    override.mkdir(parents=True)
    (override / "examples_block.md").write_text("Style: (nothing)\n",
                                                encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError) as exc:
        narrate._load_template("session_doc/narrate/examples_block", "examples")

    assert "examples" in str(exc.value)
