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
                        "{rendering_instruction}",
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
            "scene_events_line", "rendering_instruction",
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
        "scene_events_line", "rendering_instruction",
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
    assert combined.count(narrate._gm_attribution_brief(False).strip()) == 1
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


# #399 — the first-person rule was kept in the bundle template and dropped from
# the single-scene one, so `sd_narrate` without `--bundle` rendered with a
# materially weaker POV constraint and nothing caught it. The rule now lives in
# the writing brief, which BOTH paths interpolate, so the two cannot drift
# again. These two tests are a pair on purpose: one copy per path is what
# created the defect, so each path asserts the rule arrives, and the bundle
# asserts it arrives exactly once.


def test_first_person_rule_reaches_single_scene_prompts():
    for scene_anchored in (False, True):
        system = narrate.build_narrate_system(
            None, scene="The Wave Echo Chamber", narrator="Brewbarry",
            scene_anchored=scene_anchored)
        assert "The narrator is always “I”" in system, scene_anchored
        assert "first-person point of view" in system, scene_anchored
    # `scene_anchored` appends its own softer perspective line. The hard rule
    # must not depend on it — that dependency is what #399 actually was.
    unanchored = narrate.build_narrate_system(None, scene="S", narrator="B")
    assert "close first-person perspective" not in unanchored
    assert "The narrator is always “I”" in unanchored


def test_first_person_rule_reaches_bundle_prompts_exactly_once():
    system, user = narrate.build_bundled_narrate_prompts(
        [_bundle_scene(1, "Arrival", "Alice"), _bundle_scene(2, "Departure", "Bob")])
    combined = system + "\n" + user
    assert combined.count("The narrator is always “I”") == 1


# #400 — `examples_block.md` kept a list item, "- Style reference examples
# showing the voice, structure, and tone to aim for", from when `base.md`
# interpolated the block inside its "You will be given:" list. `base.md` now
# places `{examples_block}` last, after `{genre_directive}`, so the item
# rendered as a bullet attached to no list, directly under a `GENRE:` line.
# It hit BOTH paths, not just the single-scene one the report named: the bundle
# uses the same file as `{shared_examples_block}` (`bundle_base.md:19`) and has
# no inputs list at all. That sharing is also why the item could not simply move
# back into a list, and why it is not in `base.md`'s list either — the block is
# conditional on `examples_text`, so a static bullet would promise examples that
# an empty block never delivers. The block carries its own header instead.


def test_shared_examples_template_is_self_contained():
    """No part of the block may depend on a list a host template supplies."""
    lines = [ln for ln in narrate.EXAMPLES_BLOCK.strip().splitlines() if ln.strip()]
    assert lines[0].startswith("STYLE REFERENCE"), lines[0]
    assert [ln for ln in lines if ln.lstrip().startswith("- ")] == []


def test_examples_block_strands_no_list_item_on_either_path():
    single = narrate.build_narrate_system(
        "Example prose.", scene="The Wave Echo Chamber", genre="Grim, tactile.")
    system, user = narrate.build_bundled_narrate_prompts(
        [_bundle_scene(1, "Arrival", "Alice")], shared_examples="Example prose.")
    for rendered in (single, system + "\n" + user):
        assert "STYLE REFERENCE — HANDCRAFTED EXAMPLES:" in rendered
        assert "- Style reference examples" not in rendered


# #400, second half — the same commit deleted `base.md`'s reconciling pair
# ("ALLOW: Non-linear structure for the narrator's inner life" / "The actual
# events of the session must appear in the order they occur ... only the
# narrator's internal thoughts and memories may be non-linear") but left the
# examples block telling the model the examples show "the non-linear structure"
# with no bound. Unqualified, that contradicts the brief's "Preserve the order
# of events and the timing of discoveries" and the model cannot obey both.
# The allowance is scoped to the inner life again. The event-order rule is NOT
# restated here: it stays in the brief alone, because one copy per template is
# exactly what produced #399.


def test_non_linear_allowance_is_scoped_to_the_narrators_inner_life():
    single = narrate.build_narrate_system(
        "Example prose.", scene="The Wave Echo Chamber")
    system, user = narrate.build_bundled_narrate_prompts(
        [_bundle_scene(1, "Arrival", "Alice")], shared_examples="Example prose.")
    for rendered in (single, system + "\n" + user):
        assert "non-linear structure of the narrator's inner life" in rendered
        # The unqualified phrase is the defect itself.
        assert "the non-linear structure," not in rendered
        # The rule it contradicted must still arrive, from the brief.
        assert "Preserve the order of events and the timing of discoveries" in rendered


# #401 — `narrate.py` held a `length_instruction` Python literal whose second
# sentence was character-for-character `writing_brief.md`'s, so every prompt on
# the single-scene path stated the rule twice. The brief's copy is a strict
# superset ("Let its content determine its length **and the balance of dialogue
# and description**"), so the literal added nothing.
#
# It was a leftover, not a deliberate recency repeat. Before 26ec5b0 the value
# genuinely varied by branch — a long `if scene:` variant against a short
# "typically 4-8" `else` — and that commit collapsed both into one constant,
# outliving the reason the placeholder existed. The proof is the asymmetry these
# tests pin: `bundle_base.md` never had the placeholder, so only one of the two
# render paths repeated itself. The one repeat this module makes on purpose (the
# genre tail reminder) says so in a comment; this one said nothing.
#
# The rule now reaches the model from the brief alone, on both paths. Deleting
# the placeholder from `base.md` is itself guarded — `_load_template`'s two-way
# contract raises at import if it reappears there — but re-adding the literal
# *and* the placeholder together would satisfy that check, which is what the
# counts below are for.

_LENGTH_RULE = ("Complete every meaningful event and exchange without a fixed "
                "expansion formula or a dialogue quota.")


def test_the_length_rule_is_stated_once_on_every_single_scene_prompt():
    """Not the one combination the fix was written against — all 32.

    `length` was assigned unconditionally, so the duplication was invariant
    across the whole flag matrix and any single-combination test would have
    passed on the defect just as readily as on the fix.
    """
    assert _LENGTH_RULE in narrate.NARRATION_WRITING_BRIEF, "the brief must own it"
    for examples in (None, "Example prose."):
        for scene in (None, "The Wave Echo Chamber"):
            for prose_mode in (False, True):
                for has_events in (False, True):
                    for anchored in (False, True):
                        prompt = narrate.build_narrate_system(
                            examples, scene=scene, prose_mode=prose_mode,
                            has_scene_events=has_events, scene_anchored=anchored,
                            narrator="Alice")
                        combo = (f"ex={examples is not None} scene={scene is not None} "
                                 f"pm={prose_mode} se={has_events} sa={anchored}")
                        assert prompt.count(_LENGTH_RULE) == 1, combo


def test_the_length_rule_is_stated_once_on_the_bundle_prompt_too():
    """The path that was already correct, pinned so a "fix" cannot even it up
    by adding a second copy here instead of removing the one over there."""
    system, user = narrate.build_bundled_narrate_prompts(
        [_bundle_scene(1, "Arrival", "Alice"),
         _bundle_scene(2, "Departure", "Bob")])
    assert (system + "\n" + user).count(_LENGTH_RULE) == 1


def test_the_length_rule_reaches_the_model_from_the_brief_and_nowhere_else():
    """A second copy anywhere — a template or a Python literal — fails here.

    The brief is the only file allowed to carry it, so the walk covers the
    shipped narrate templates rather than just the one that regressed.
    """
    carriers = sorted(
        f.name for f in TEMPLATE_DIR.glob("*.md")
        if _LENGTH_RULE in f.read_text(encoding="utf-8"))
    assert carriers == ["writing_brief.md"], carriers

    source = (Path(narrate.__file__)).read_text(encoding="utf-8")
    # The literal is quoted here in halves so this test's own text, and the
    # comment above it, cannot be what the scan finds.
    needle = "expansion formula or a " + "dialogue quota"
    assert needle not in source, "the rule is back as a Python literal"


# ---------------------------------------------------------------------------
# #402 — every style-reference block must state its own bound.
#
# 26ec5b0 scoped base/bundle_base/voice_spec/scene_anchored/bundle_scene and both
# dialogue templates ("these govern style only"), and missed the two example
# blocks, which stayed at 4e22e6c. The design it chose is that each appended
# block declares its own boundary — a block glued on *after* base.md's scoping
# paragraph is outside that paragraph's reach, so a shared statement upstream
# does not cover it. These tests pin the pattern to every block that carries it.
#
# Two live conflicts made the gap concrete, and neither is a tense-vs-tense
# argument between two rules — both are a reference file disagreeing with the
# brief about grammatical person or tense while the prompt says to match it:
#
#   out-of-the-abyss  examples/daz.md is third person ("Daz and his crew collect
#                     the chamber pots", "he arrives at the winch") against
#                     voice/_genre.md:12 "First-person past is the spine"
#   stormgiants       examples/*.md are first-person past; the campaign has no
#   obelisk           voice/_genre.md at all, so the brief's stated default
#                     (present) applies and nothing broke the tie — voice_spec's
#                     carve-out resolved tense to a file these campaigns lack.
# ---------------------------------------------------------------------------

# The blocks that are appended after base.md's scoping paragraph, and so cannot
# rely on it. `examples_block.md` is deliberately absent: it is interpolated
# *inside* base.md directly beneath that paragraph, which governs it by position.
_APPENDED_STYLE_BLOCKS = (
    "per_char_examples.md",
    "prev_voice_contrast.md",
    "voice_spec.md",
)


@pytest.mark.parametrize("template", _APPENDED_STYLE_BLOCKS)
def test_every_appended_style_block_bounds_itself_to_style(template):
    """A block that outranks something must say what it does not outrank."""
    text = (TEMPLATE_DIR / template).read_text(encoding="utf-8")
    # Case-folded: the bound is the same whether it opens a sentence or not.
    flat = " ".join(text.split()).lower()
    assert "style only" in flat, template
    assert "point of view" in flat, template
    # Naming the brief is what makes the bound actionable rather than decorative.
    assert "writing brief" in flat, template


def test_point_of_view_is_the_briefs_and_no_reference_supplies_it():
    """#395 recorded the decision ("Person stays in the brief"); base.md never
    got the matching edit and kept `perspective` in the *supply* list, which is
    what licensed a third-person example file to set the person."""
    for text in (f.read_text(encoding="utf-8") for f in TEMPLATE_DIR.glob("*.md")):
        flat = " ".join(text.split())
        # The old supply-list wording, in either template's phrasing.
        assert "register, perspective, and tense" not in flat
    for mode, prompt in (("single", narrate.build_narrate_system(
                             "Global.", narrator="Daz", char_examples="Daz collects.",
                             voice_note="Dry.", genre="First-person past is the spine.")),
                         ("bundle", "\n".join(narrate.build_bundled_narrate_prompts(
                             [_bundle_scene(1, "Arrival", "Daz")],
                             genre="First-person past is the spine.")))):
        flat = " ".join(prompt.split())
        assert "governs point of view" in flat, mode
        assert "not the grammatical person, which the brief owns" in flat, mode


def test_a_style_reference_cannot_set_person_or_tense_on_either_render_path():
    """The sentence that resolves out-of-the-abyss and stormgiants.

    A voice sample in the wrong person or tense must be readable as diction to
    borrow, not as an instruction to follow — on the bundle path too, where the
    block moves into the per-scene user packet.
    """
    licence = "voice sample, not a licence"
    single = narrate.build_narrate_system(
        "Global.", narrator="Daz", char_examples="Daz and his crew collect the pots.")
    assert single.count(licence) == 1

    system, user = narrate.build_bundled_narrate_prompts(
        [_bundle_scene(1, "Arrival", "Alice"), _bundle_scene(2, "Departure", "Bob")])
    # One per scene packet: the block is per-scene on this path, not shared.
    assert (system + "\n" + user).count(licence) == 2

    # No character examples => no claim to bound, and so no orphaned sentence.
    assert licence not in narrate.build_narrate_system("Global.", narrator="Daz")


def test_tense_falls_back_to_the_brief_when_a_campaign_has_no_genre_file():
    """stormgiants and obelisk ship no voice/_genre.md, so a carve-out that
    resolves tense to "the campaign genre reference" and stops there points at
    a document that does not exist and leaves past-tense examples unopposed."""
    prompt = narrate.build_narrate_system(
        "Global.", narrator="Thistle", char_examples="The desert had changed.",
        voice_note="Performer-light.")
    flat = " ".join(prompt.split())
    assert "where the campaign supplies no genre reference" in flat
    assert "the tense the brief states" in flat


def test_the_contrast_block_cannot_differentiate_on_person_or_tense():
    """It is the last block in every bundle scene packet (bundle_scene.md:22),
    so it holds the recency the original #402 attributed to per_char_examples.
    "Sound clearly different" must not reach person, tense, or the brief's rules.
    """
    user_msg = narrate.build_narrate_prompt(
        narrator="Daz", focus="f", char_moments="- m", party="p", handoff="",
        roster="r", prev_narrator="Zalthir", prev_voice_sample="A prior line.")
    flat = " ".join(user_msg.split())
    assert "Differentiate style only" in flat
    assert "never what makes two sections sound different" in flat


# ---------------------------------------------------------------------------
# #416 — one substitution mechanism, so a template rename cannot go one way
#
# `build_narrate_system` built the style-reference block with a raw
# `.replace("{examples}", ...)` — the module's last one — while the bundle path
# used `_fill` for the same template. `.replace()` is a no-op on an absent
# needle, so a rename in `examples_block.md` raised on one render path and
# shipped a literal placeholder plus none of the campaign's examples on the
# other.
#
# The two-way load check does not cover this: it compares the template's
# placeholders against the list declared in `_load_template_deferred`, so
# renaming BOTH in one edit passes the check while the `.replace()` quietly
# stops substituting. That is why the guard here is behavioural rather than a
# second reading of the declaration.
# ---------------------------------------------------------------------------

_DRIFTED_EXAMPLES_BLOCK = "STYLE REFERENCE:\n{style_examples}\nEND OF STYLE REFERENCE"


def test_a_renamed_examples_placeholder_raises_on_the_single_scene_path(monkeypatch):
    monkeypatch.setattr(narrate, "EXAMPLES_BLOCK", _DRIFTED_EXAMPLES_BLOCK)
    with pytest.raises(ValueError) as excinfo:
        narrate.build_narrate_system("Handcrafted prose.", narrator="Alice")
    assert "style_examples" in str(excinfo.value)


def test_the_bundle_path_already_raised_and_still_does(monkeypatch):
    """The behaviour the single-scene path was missing, pinned so a later
    "simplification" cannot even the two up by removing this one instead."""
    monkeypatch.setattr(narrate, "EXAMPLES_BLOCK", _DRIFTED_EXAMPLES_BLOCK)
    with pytest.raises(ValueError) as excinfo:
        narrate.build_bundled_narrate_prompts(
            [_bundle_scene(1, "Arrival", "Alice")],
            shared_examples="Handcrafted prose.")
    assert "style_examples" in str(excinfo.value)


def test_the_module_has_no_raw_placeholder_replace_left():
    """`_fill`'s docstring is the argument: "a chain is a list of intentions
    that nothing checks". A new `.replace("{...")` is a new unchecked link."""
    source = Path(narrate.__file__).read_text(encoding="utf-8")
    # Assembled so this test's own text cannot be what the scan finds.
    needle = '.replace("' + "{"
    assert needle not in source, "a raw placeholder .replace() is back"


# ---------------------------------------------------------------------------
# #417 — the same-narrator contrast rule has one home
#
# PREV_VOICE_CONTRAST_BLOCK says "{narrator}'s voice should sound clearly
# different from {prev_narrator}'s", under a heading reading "for contrast — do
# NOT imitate". Emitting it when they are the same person instructs a narrator
# to sound unlike themselves.
#
# `build_narrate_prompt` treated that as the builder's invariant. The bundle
# builder checked only that a previous narrator and a sample existed, leaving
# the identity half to its one caller in `sd_narrate` — correct today, and
# wrong for anything else that builds a NarrationScene. Both now call
# `_voice_contrast_applies`, so the rule cannot be half-applied.
# ---------------------------------------------------------------------------

_CONTRAST_MARKER = "do NOT imitate"


def _bundle_has_contrast(narrator: str, prev: str | None) -> bool:
    scene = narrate.NarrationScene(
        index=1, scene_name="Arrival", narrator=narrator, focus="focus",
        source_path=Path("01.md"), source_kind="base",
        scene_events="events", moments="moments",
        voice_note="", character_examples="",
        previous_narrator=prev,
        previous_voice_sample="A prior line." if prev else None,
        estimated_output_tokens=500, output_path=Path("out.md"),
        output_existed=False,
    )
    system, user = narrate.build_bundled_narrate_prompts([scene])
    return _CONTRAST_MARKER in (system + "\n" + user)


def _single_has_contrast(narrator: str, prev: str | None) -> bool:
    prompt = narrate.build_narrate_prompt(
        narrator=narrator, focus="focus", char_moments="- moment",
        party="party", handoff="", roster="roster",
        prev_narrator=prev,
        prev_voice_sample="A prior line." if prev else None,
    )
    return _CONTRAST_MARKER in prompt


# Same person under four spellings, a different person, and nobody. The case
# variants are the point: the single-scene builder always folded case and the
# bundle builder had no comparison at all to fold.
_CONTRAST_CASES = [
    ("Daz", "Zalthir", True),
    ("Daz", "Daz", False),
    ("Daz", "daz", False),
    ("Daz", "DAZ", False),
    ("Daz", None, False),
]


@pytest.mark.parametrize("narrator,prev,expected", _CONTRAST_CASES)
def test_the_bundle_builder_owns_the_same_narrator_rule(narrator, prev, expected):
    assert _bundle_has_contrast(narrator, prev) is expected


@pytest.mark.parametrize("narrator,prev,expected", _CONTRAST_CASES)
def test_the_single_scene_builder_still_owns_it(narrator, prev, expected):
    assert _single_has_contrast(narrator, prev) is expected


@pytest.mark.parametrize("narrator,prev,_expected", _CONTRAST_CASES)
def test_both_render_paths_decide_the_contrast_block_identically(
        narrator, prev, _expected):
    """Stated as agreement rather than as two independent expectations: the
    defect was the two paths disagreeing, so the assertion that matters is that
    they cannot, whatever the shared answer turns out to be."""
    assert _bundle_has_contrast(narrator, prev) == _single_has_contrast(narrator, prev)


# ---------------------------------------------------------------------------
# #435 / #438 — one copy per rule, and where the POV rule's teeth live
# ---------------------------------------------------------------------------

_SPEECH_RULE = ("preserving attribution, conversational purpose, and the order "
                "of events and the timing of discoveries.")


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_speech_selection_rule_is_stated_once_per_render_path():
    """#435. `scene_anchored.md` and `bundle_scene.md` each restated three rules
    the brief owns, and the two restatements had already drifted — "retain their
    attribution" vs "preserving attribution", "Select exchanges" vs "Select and
    shape speech". Neither matched the brief either: "discovery order" dropped
    the event-order half of "the order of events and the timing of discoveries".

    Kept rather than deleted (the reinforcement may be earning its tokens on
    small local models) but sourced from one file, so it cannot become two
    rules again.
    """
    single = narrate.build_narrate_system(None, narrator="Daz", scene_anchored=True)
    assert _flat(single).count(_SPEECH_RULE) == 1

    system, user = narrate.build_bundled_narrate_prompts(
        [_bundle_scene(1, "Arrival", "Alice")])
    assert _flat(system + " " + user).count(_SPEECH_RULE) == 1


def test_only_one_file_carries_the_speech_selection_rule():
    carriers = sorted(f.name for f in TEMPLATE_DIR.glob("*.md")
                      if _SPEECH_RULE in _flat(f.read_text(encoding="utf-8")))
    assert carriers == ["speech_selection.md"], carriers


def test_the_drifted_restatements_do_not_come_back():
    """The exact wordings that had diverged, so a revert is visible."""
    for stale in ("retain their attribution", "and discovery order"):
        offenders = sorted(f.name for f in TEMPLATE_DIR.glob("*.md")
                           if stale in f.read_text(encoding="utf-8"))
        assert not offenders, (stale, offenders)


# ── #438: the POV rule keeps the mild variant, on purpose ───────────────────
#
# `26ec5b0` had two POV rules, one per render path: a four-component one in
# base.md (assertion + pronoun ban + self-check/repair + "Third person is a hard
# failure") and a one-line one in bundle_base.md. #399 correctly moved the rule
# into the shared brief and, in doing so, applied the BUNDLE's milder wording to
# both paths.
#
# Decided to keep it that way, because the prohibitive half is already in every
# live campaign's genre file, written in that campaign's own terms:
#
#   Phandalin  "Never drift into third person ("he", "she", "Brewbarry felt")
#              — even close third with the character's vocabulary is wrong here."
#   oota       "convert third-person observations to first-person
#              ("Daz noticed X" -> "I noticed X")"
#   toee       "When adapting from third-person scene notes, convert directly:
#              "Calmer struck" -> "I struck.""
#
# Restoring it to the brief would put a second copy of a rule beside a better,
# campaign-specific one — the multi-copy drift #399, #400 and #401 each removed.
# These pin the decision so the next reader of 26ec5b0 does not re-add the
# strong variant as an oversight.

_POV_ASSERTION = "Stay in the named narrator's first-person point of view."
#: Prohibitive POV wording. `audit_hatch.md` is exempt below: it says "third
#: person" for an unrelated job — flagging stage direction and table speech —
#: not to govern narration POV.
_POV_PROHIBITIONS = ("hard failure", "Never use \"he\"", "not even in passing")


def test_the_brief_states_the_pov_rule_positively_and_owns_it():
    assert _POV_ASSERTION in narrate.NARRATION_WRITING_BRIEF
    carriers = sorted(f.name for f in TEMPLATE_DIR.glob("*.md")
                      if _POV_ASSERTION in f.read_text(encoding="utf-8"))
    assert carriers == ["writing_brief.md"], carriers


@pytest.mark.parametrize("phrase", _POV_PROHIBITIONS)
def test_no_shipped_template_re_adds_the_prohibitive_pov_half(phrase):
    """Not an assertion that the strong variant is wrong — an assertion that
    dropping it was a decision. If it is ever restored, this failing is the
    prompt to record why, in the brief and nowhere else."""
    offenders = sorted(f.name for f in TEMPLATE_DIR.glob("*.md")
                       if phrase in f.read_text(encoding="utf-8")
                       and f.name != "audit_hatch.md")
    assert not offenders, (phrase, offenders)


def test_the_live_campaigns_still_carry_the_prohibition(live_workspace):
    """The evidence the decision rests on, checked rather than remembered.

    Skipped, not failed, on a checkout with no campaigns — per this repo's rule
    that a suite going red on a fresh clone trains everyone to ignore it. If a
    campaign ever drops this from its genre file, the brief's mild wording
    becomes the only POV guidance that campaign gets, and reopening #438 is the
    right response.
    """
    campaigns = {"Phandalin": "Never drift into third person",
                 "out-of-the-abyss": "convert third-person observations",
                 "toee": "convert directly"}
    missing = []
    for name, phrase in campaigns.items():
        genre = live_workspace / name / "voice" / "_genre.md"
        if not genre.is_file():
            continue          # a campaign may legitimately not exist here
        if phrase not in genre.read_text(encoding="utf-8"):
            missing.append(name)
    assert not missing, missing
