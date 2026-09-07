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

    If a shipped template drifts from what the code substitutes,
    `_TEMPLATE_ERROR` is set at import and every prompt build raises.
    """
    assert narrate._TEMPLATE_ERROR is None
    assert narrate.NARRATE_SYSTEM_BASE
    for placeholder in ("{writing_brief}", "{audit_hatch}", "{genre_directive}",
                        "{examples_block}",
                        "{scene_scope_line}", "{scene_events_line}",
                        "{rendering_instruction}", "{length_instruction}",
                        "{dialogue_instruction}", "{name_fidelity}", "{real_names}"):
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
            "writing_brief", "audit_hatch",
            "genre_directive", "examples_block", "scene_scope_line",
            "scene_events_line", "rendering_instruction", "length_instruction",
            "dialogue_instruction", "name_fidelity", "real_names",
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


# ── The other direction: every placeholder the template HAS gets a value ─────
#
# Found reviewing #302 itself. The import-time check binds template <-> declared
# list, but nothing bound either to the `.replace()` chain that did the work.
# Deleting one `.replace()` line left the name in the declaration and in the
# template, passed the new check cleanly, and shipped the literal string
# `{rendering_instruction}` to the model — #302's failure, reversed, still
# silent. `_fill` makes that structurally impossible: the walk is driven by the
# template, so a value that is not supplied raises instead of being skipped.


def test_fill_substitutes_every_placeholder():
    assert narrate._fill("a {x} b {y}", x="1", y="2") == "a 1 b 2"


def test_fill_refuses_when_a_value_is_not_supplied():
    """The deleted-`.replace()`-line scenario."""
    with pytest.raises(ValueError) as exc:
        narrate._fill("a {x} b {rendering_instruction}", x="1")

    msg = str(exc.value)
    assert "{rendering_instruction}" in msg
    assert "literal text" in msg


def test_fill_does_not_rescan_substituted_values():
    """A rulebook or voice spec containing `{narrator}` is content, not a
    placeholder — it must pass through untouched rather than trip the check.

    This is why the guarantee is a template-driven walk and not a scan of the
    finished prompt: the finished prompt contains GM prose.
    """
    out = narrate._fill("Spec: {voice_note}", voice_note="uses {narrator} oddly")
    assert out == "Spec: uses {narrator} oddly"


def test_unused_values_are_allowed():
    """`build_narrate_system` passes the same names on every path; the template
    decides which appear. Extra values are not drift."""
    assert narrate._fill("only {x}", x="1", y="unused") == "only 1"


# ── A drifted template must not take down the whole package ─────────────────


def test_drift_does_not_break_importing_session_doc(tmp_path, monkeypatch):
    """`session_doc/__init__.py` re-exports these constants, so raising at
    import made a bad narrate template break `parse_plan` too — and with it the
    editor's scene list, sd_consistency, sd_plan and assemble, none of which
    build a narrate prompt.

    The error is held and raised where a prompt is actually assembled.

    Exercised without `importlib.reload`, deliberately: reloading rebinds
    `narrate.build_narrate_system` to a new function object while
    `session_doc/__init__.py` still holds the original, and no second reload
    restores that identity — which broke `test_sd_split.py`'s re-export
    identity check for the rest of the session. The two halves are tested
    separately instead.
    """
    override = tmp_path / "config" / "agents" / "session_doc" / "narrate"
    override.mkdir(parents=True)
    text = (TEMPLATE_DIR / "base.md").read_text(encoding="utf-8")
    (override / "base.md").write_text(
        text.replace("{genre_directive}", "{genre_block}"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    # Half 1: loading a drifted template records the error instead of raising,
    # so the module-level constants still bind and `import session_doc` works.
    monkeypatch.setattr(narrate, "_TEMPLATE_ERROR", None)
    assert narrate._load_template_deferred(
        "session_doc/narrate/base",
        "writing_brief", "audit_hatch",
        "genre_directive", "examples_block", "scene_scope_line",
        "scene_events_line", "rendering_instruction", "length_instruction",
        "dialogue_instruction", "name_fidelity", "real_names",
    ) == ""
    assert narrate._TEMPLATE_ERROR is not None

    # Half 2: the prompt builders — and only they — surface it.
    with pytest.raises(ValueError) as exc:
        narrate.build_narrate_system(None, narrator="Alice")
    assert "placeholder drift" in str(exc.value)

    with pytest.raises(ValueError):
        narrate.build_narrate_prompt("Alice", "focus", "moments", None, "")


def test_the_drift_error_names_both_candidate_paths(tmp_path, monkeypatch):
    """The campaign override wins, so reporting only the repo's copy sends a GM
    to a file that is correct, with no hint another was loaded."""
    override = tmp_path / "config" / "agents" / "session_doc" / "narrate"
    override.mkdir(parents=True)
    (override / "voice_spec.md").write_text("{narrator} only\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError) as exc:
        narrate._load_template(
            "session_doc/narrate/voice_spec", "narrator", "voice_note")

    msg = str(exc.value)
    assert str(tmp_path / "config" / "agents") in msg      # the override, first
    assert "loaded from the first of" in msg


def _bundle_scene(index: int, name: str, narrator_name: str) -> narrate.NarrationScene:
    return narrate.NarrationScene(
        index=index, scene_name=name, narrator=narrator_name, focus="focus",
        source_path=Path(f"{index:02d}.md"), source_kind="base",
        scene_events="events", moments='Someone: "Exact quote."',
        voice_note=f"PRIVATE_VOICE_{index}",
        character_examples=f"PRIVATE_EXAMPLE_{index}",
        previous_narrator=("Other" if index > 1 else None),
        previous_voice_sample=("PRIOR_SAMPLE" if index > 1 else None),
        estimated_output_tokens=500, output_path=Path(f"out-{index}.md"),
        output_existed=False,
    )


def test_bundle_templates_satisfy_placeholder_and_load_bearing_rule_contracts():
    assert narrate.BUNDLE_SYSTEM_BASE
    assert narrate.BUNDLE_SCENE_TEMPLATE
    system, user = narrate.build_bundled_narrate_prompts(
        [_bundle_scene(1, "Arrival", "Alice"),
         _bundle_scene(2, "Departure", "Bob")],
        prose_mode=True,
    )
    combined = system + "\n" + user

    assert "first-person" in combined
    assert "The narrator is always “I”" in combined
    assert combined.count(narrate.NARRATION_WRITING_BRIEF.strip()) == 1
    # #408/#410 — Version B licenses adaptation instead of requiring "actual
    # wording"; pin the new paragraph's own language.
    assert "Dialogue is editable dramatic material, not a verbatim transcription requirement" in combined
    assert "without a fixed expansion formula or a dialogue quota" in combined
    assert "legitimate in-world quantities, evidence, money, and spell names" in combined
    assert "A player speaking at the table does not by itself place their character in the room" in combined
    assert "USE DIALOGUE IF PRESENT" in combined
    assert "DO NOT invent dialogue" in " ".join(combined.split())
    assert "Render only that scene" in combined
    assert "Never carry one narrator's private guidance" in " ".join(combined.split())
    assert "<<<CG-SCENE NN BEGIN: Exact Scene Name>>>" in combined
    assert "<<<CG-SCENE NN END>>>" in combined
    assert "Emit the scenes in packet order" in combined
    assert "final prose line of the section you just emitted" in combined
    assert "Every eligible verbatim quote belongs" not in combined
    # #395 — the bundle wrapper carried its own copy of the precedence block,
    # so a fix applied only to `base.md` would leave every bundled render
    # still overriding the campaign's tense.
    assert "present-tense voice" not in combined
    assert "knowledge boundaries, tense" not in combined
    assert "the authority on tense" in combined
    # #396 — the reclassification judgment reaches the bundle through the
    # shared brief, so the audit hatch has to reach it too. `26ec5b0` kept the
    # judgment and deleted the record; this pin is the reverse of the one it
    # left behind.
    assert "table-speech reclassified" in combined
    assert "not a claim of completeness" in " ".join(combined.split())
    # Transport: `split_batched_response` discards anything outside a
    # BEGIN/END pair *silently*, and still reports the section complete — so a
    # hatch emitted after the END marker is a false clean with no signal.
    assert "as the last line before its END marker" in combined
    assert "not a prose line" in combined
    # #410/#411 — the anti-normalization rule reaches the bundle through
    # `bundle_base.md`'s own `{name_fidelity}` placeholder, same as `base.md`,
    # so it is unconditional on this render path too and does not depend on
    # a non-empty NPC roster to appear.
    assert "NAMES INSIDE QUOTED SPEECH" in combined
    assert "characterization, not a spelling error" in combined
    assert "Never normalize a name inside a quoted line" in " ".join(combined.split())
    # #398 — the real-people ban (deleted wholesale by 26ec5b0, replaced by
    # nothing) reaches the bundle through `bundle_base.md`'s own {real_names}
    # placeholder, same as {name_fidelity}, so it is unconditional here too.
    flat_combined = " ".join(combined.split())
    assert "THE PEOPLE AT THE TABLE" in combined
    assert "their real names never appear in the prose" in flat_combined
    assert "Only the characters exist in the fiction" in flat_combined
    assert "The narrator does not receive information from a person at the table" in flat_combined


# ── #411 regression: the rule must not depend on having a roster ────────────
#
# Before #411, the anti-normalization caveat lived only inside the
# `if npc_roster:` block in each build function, so a scene with an empty NPC
# roster — a new campaign, or a scene where nothing in docs/npcs/ matched —
# got no protection at all. The rule is about characterization — the name a
# speaker chose is part of what the line reveals about them — so it must not
# depend on having a canonical spellings list to normalize *toward*.


def test_name_fidelity_rule_reaches_single_scene_prompts_without_a_roster():
    system = narrate.build_narrate_system(None, scene="The Wave Echo Chamber")
    assert "NAMES INSIDE QUOTED SPEECH" in system

    user_without_roster = narrate.build_narrate_prompt(
        "Brewbarry", "focus", "moments", None, "", npc_roster="")
    assert "## Known NPCs" not in user_without_roster

    user_with_roster = narrate.build_narrate_prompt(
        "Brewbarry", "focus", "moments", None, "",
        npc_roster="Nezznar the Spider (also: Spider)")
    assert "## Known NPCs" in user_with_roster
    # The rule reaches the model once, from the system prompt. Supplying a
    # roster must not re-introduce a second copy in the user prompt — that
    # duplication is how the two hand-written caveats drifted apart (#410).
    assert "NAMES INSIDE QUOTED SPEECH" not in user_without_roster
    assert "NAMES INSIDE QUOTED SPEECH" not in user_with_roster


def test_name_fidelity_rule_reaches_bundle_prompts_without_a_roster():
    system_without_roster, _ = narrate.build_bundled_narrate_prompts(
        [_bundle_scene(1, "Arrival", "Alice")], npc_roster="")
    assert "NAMES INSIDE QUOTED SPEECH" in system_without_roster
    assert "## Known NPCs" not in system_without_roster

    system_with_roster, _ = narrate.build_bundled_narrate_prompts(
        [_bundle_scene(1, "Arrival", "Alice")],
        npc_roster="Nezznar the Spider (also: Spider)")
    assert "NAMES INSIDE QUOTED SPEECH" in system_with_roster
    assert "## Known NPCs" in system_with_roster
