"""Tests for sd_narrate.py's --batch path (spec 004-claude-api-batch, T020)
and the global-examples routing into scene mode.

sd_narrate's per-scene loop is order-dependent: each scene's ``handoff`` line
(the last line of its narration) feeds directly into the next scene's prompt,
and ``prev_voice_sample`` depends on plan position. So --batch must NEVER
group scenes into one multi-item batch — each scene's call becomes its own
sequential one-item batch via ``run_single_batch``, in the same loop order as
the live (stream_api) path.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session_doc  # noqa: E402
from session_doc import sd_narrate  # noqa: E402
from session_doc.voice import get_voice_note, load_voice_files  # noqa: E402


# ── Fixtures: a minimal 2-scene plan + scene-extraction pair ────────────────
#
# Scene 1 is narrated by Alice, Scene 2 by Bob — different narrators so the
# handoff line is the only thing threading them together (no dedup with
# prev-narrator == narrator).

PLAN_TEXT = """\
## Section 1
narrator: Alice
chunks: 1-1
scene: Scene One
focus: opening the scene

## Section 2
narrator: Bob
chunks: 2-2
scene: Scene Two
focus: closing the scene
"""

SCENE_ONE_BODY = "- Alice orders a drink at the bar.\n"
SCENE_TWO_BODY = "- Bob steps out into the rain.\n"

SCENE1_NARRATION = (
    'Alice leans on the bar and orders a drink.\n'
    '"See you at dawn."'
)
SCENE1_HANDOFF_TAIL = "See you at dawn."

SCENE2_NARRATION = (
    'Bob nods and steps out into the rain.\n'
    '"Until then."'
)


def _write_fixtures(tmp_path: Path) -> dict:
    recap = tmp_path / "recap.md"
    recap.write_text("# Recap\n\nNothing load-bearing here.\n", encoding="utf-8")

    plan = tmp_path / "plan.md"
    plan.write_text(PLAN_TEXT, encoding="utf-8")

    scenes_dir = tmp_path / "scenes"
    scenes_dir.mkdir()
    (scenes_dir / "01_scene_one.md").write_text(SCENE_ONE_BODY, encoding="utf-8")
    (scenes_dir / "02_scene_two.md").write_text(SCENE_TWO_BODY, encoding="utf-8")

    out_dir = tmp_path / "output"
    return {"recap": recap, "plan": plan, "scenes_dir": scenes_dir, "out_dir": out_dir}


def _base_argv(paths: dict, *extra: str) -> list:
    return [
        "sd_narrate", str(paths["recap"]),
        "--plan", str(paths["plan"]),
        "--scene-extractions", str(paths["scenes_dir"]),
        "--per-scene-output", str(paths["out_dir"]),
        *extra,
    ]


class FakeRunSingleBatch:
    """Records call kwargs in order; returns canned narration text per call."""

    def __init__(self, texts):
        self.calls = []
        self._texts = list(texts)

    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        idx = len(self.calls)
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens, "kwargs": kwargs})
        return self._texts[idx]


class FailingSecondCall:
    """Like FakeRunSingleBatch, but raises RuntimeError on the 2nd call."""

    def __init__(self):
        self.calls = []

    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens})
        if len(self.calls) == 2:
            raise RuntimeError(
                "batch item 'single' did not succeed: status=errored error='boom'"
            )
        return SCENE1_NARRATION


class FakeStreamAPI:
    """Live-path stand-in — records call args, returns canned narration text."""

    def __init__(self, texts):
        self.calls = []
        self._texts = list(texts)

    def __call__(self, client, system, user, model, *args, **kwargs):
        idx = len(self.calls)
        self.calls.append({"system": system, "user": user, "model": model,
                           "kwargs": kwargs})
        return self._texts[idx]


@pytest.fixture(autouse=True)
def _no_real_client(monkeypatch):
    # Avoid needing a real Anthropic client / API key for any test in this file.
    monkeypatch.setattr(sd_narrate, "client_from_args", lambda args: object())


@pytest.fixture(autouse=True)
def _chdir_tmp(monkeypatch, tmp_path):
    # No docs/entity_registry.yaml or dossiers in tmp_path — alias_map is {}.
    monkeypatch.chdir(tmp_path)


# ── --batch: sequential one-item batches, in order, with handoff threading ──

def test_batch_flag_routes_scenes_through_run_single_batch_in_order(monkeypatch, tmp_path):
    paths = _write_fixtures(tmp_path)
    fake_batch = FakeRunSingleBatch([SCENE1_NARRATION, SCENE2_NARRATION])
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "run_single_batch", fake_batch)
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)

    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--batch"))
    sd_narrate.main()

    # Batch path used exclusively — live streaming path never touched.
    assert len(fake_batch.calls) == 2
    assert fake_stream.calls == []

    # Order preserved: first call is Alice/Scene One, second is Bob/Scene Two.
    assert "## Narrator: Alice" in fake_batch.calls[0]["user"]
    assert "## Narrator: Bob" in fake_batch.calls[1]["user"]

    # Handoff threading intact: scene 2's user prompt carries scene 1's tail,
    # the same way build_narrate_prompt threads it on the live path.
    assert SCENE1_HANDOFF_TAIL in fake_batch.calls[1]["user"]
    assert "## Handoff from previous narrator" in fake_batch.calls[1]["user"]

    # Same system/model/max_tokens shape as the live call would have used.
    for call in fake_batch.calls:
        assert call["model"] == sd_narrate.DEFAULT_MODEL
        assert call["max_tokens"] == 16000  # default --narrate-tokens

    written = sorted(paths["out_dir"].glob("session_doc_scene_*.md"))
    assert [f.name for f in written] == [
        "session_doc_scene_01_scene_one.md",
        "session_doc_scene_02_scene_two.md",
    ]
    assert SCENE1_NARRATION in written[0].read_text(encoding="utf-8")
    assert SCENE2_NARRATION in written[1].read_text(encoding="utf-8")


def test_batch_failure_mid_loop_exits_nonzero_earlier_scenes_stay_on_disk(
    monkeypatch, tmp_path, capsys,
):
    paths = _write_fixtures(tmp_path)
    failing_batch = FailingSecondCall()
    monkeypatch.setattr(sd_narrate, "run_single_batch", failing_batch)

    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--batch"))
    with pytest.raises(SystemExit) as excinfo:
        sd_narrate.main()
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert "Error: batch item failed for scene Bob — Scene Two:" in err

    # Scene 1 (which succeeded before the 2nd call failed) is still on disk;
    # scene 2 (the failing item) was never written.
    written = sorted(paths["out_dir"].glob("session_doc_scene_*.md"))
    assert [f.name for f in written] == ["session_doc_scene_01_scene_one.md"]


# ── Default (non-batch) path: byte-identical, unaffected by --batch wiring ──

def test_default_path_uses_stream_api_not_run_single_batch(monkeypatch, tmp_path):
    paths = _write_fixtures(tmp_path)
    fake_batch = FakeRunSingleBatch([SCENE1_NARRATION, SCENE2_NARRATION])
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "run_single_batch", fake_batch)
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)

    monkeypatch.setattr(sys, "argv", _base_argv(paths))
    sd_narrate.main()

    assert len(fake_stream.calls) == 2
    assert fake_batch.calls == []

    # Handoff threading is identical on the live path too.
    assert SCENE1_HANDOFF_TAIL in fake_stream.calls[1]["user"]

    written = sorted(paths["out_dir"].glob("session_doc_scene_*.md"))
    assert [f.name for f in written] == [
        "session_doc_scene_01_scene_one.md",
        "session_doc_scene_02_scene_two.md",
    ]


# ── Global examples reach scene mode ────────────────────────────────────────

HOUSE_STYLE = "The deadpan lands in its own one-line paragraph. And he is correct."
ALICE_STYLE = "I do not explain the joke. I let it sit there."


def _write_examples(tmp_path: Path) -> Path:
    """A non-character file (global) plus a first-name-stemmed one (per-char)."""
    ex = tmp_path / "examples"
    ex.mkdir()
    (ex / "house_style.md").write_text(HOUSE_STYLE, encoding="utf-8")
    (ex / "alice.md").write_text(ALICE_STYLE, encoding="utf-8")
    return ex


def test_global_examples_reach_scene_mode_prompts(monkeypatch, tmp_path):
    """Every plan section carries a ``scene:`` line, so scene mode is the only
    mode the pipeline actually runs. The global block used to be suppressed
    there (``None if scene_name else examples_text``), which made a non-
    character example file silently inert. It must reach every scene now.
    """
    paths = _write_fixtures(tmp_path)
    ex_dir = _write_examples(tmp_path)
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)

    monkeypatch.setattr(sys, "argv", _base_argv(
        paths, "--examples", str(ex_dir), "--characters", "Alice, Bob"))
    sd_narrate.main()

    assert len(fake_stream.calls) == 2
    for call in fake_stream.calls:
        assert HOUSE_STYLE in call["system"]

    # Routing still holds: alice.md is per-character, so it reaches Alice's
    # scene only — and never leaks into the global block Bob also sees.
    assert ALICE_STYLE in fake_stream.calls[0]["system"]
    assert ALICE_STYLE not in fake_stream.calls[1]["system"]


def test_no_examples_dir_leaves_system_prompt_without_style_block(monkeypatch, tmp_path):
    """Guard the other direction: unrouted examples must not appear from nowhere."""
    paths = _write_fixtures(tmp_path)
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)

    monkeypatch.setattr(sys, "argv", _base_argv(paths))
    sd_narrate.main()

    for call in fake_stream.calls:
        assert "STYLE REFERENCE" not in call["system"]


# ── Alias normalisation must not reach verbatim dialogue (#223, defect A) ───
#
# The scene extraction below is the shape the bug actually took: a quote whose
# speaker used an alias, sitting next to prose using the same alias. Before the
# fix both were rewritten, so a line the player spoke came back as a sentence
# nobody said. The prose rewrite is the legitimate half and must survive.

REGISTRY_YAML = """\
version: 1
campaign: testcamp
entities:
  - name: Nezznar the Spider
    type: npc
    aliases: [Spider]
  - name: Dagult Neverember
    type: npc
    aliases: [Lord Neverember]
"""

SCENE_WITH_QUOTE = (
    "- Alice asks about Spider, who runs the docks.\n"
    '- Alice: "Tell me about Spider and Lord Neverember."\n'
)


def _write_registry(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    reg = docs / "entity_registry.yaml"
    reg.write_text(REGISTRY_YAML, encoding="utf-8")
    return reg


def _run_with_registry(monkeypatch, tmp_path, *extra: str) -> FakeStreamAPI:
    paths = _write_fixtures(tmp_path)
    (paths["scenes_dir"] / "01_scene_one.md").write_text(
        SCENE_WITH_QUOTE, encoding="utf-8")
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.setattr(sys, "argv", _base_argv(paths, *extra))
    sd_narrate.main()
    return fake_stream


def test_alias_normalisation_skips_quoted_dialogue_but_rewrites_prose(
    monkeypatch, tmp_path,
):
    _write_registry(tmp_path)
    fake_stream = _run_with_registry(monkeypatch, tmp_path)

    prompt = fake_stream.calls[0]["user"]
    # The quote is a record of what Alice said — byte-identical, aliases and all.
    assert '"Tell me about Spider and Lord Neverember."' in prompt
    # ...while the surrounding prose bullet still gets the canonical names.
    assert "Alice asks about Nezznar the Spider, who runs the docks." in prompt


def test_no_alias_normalize_disables_the_rewrite_but_keeps_the_roster(
    monkeypatch, tmp_path,
):
    _write_registry(tmp_path)
    fake_stream = _run_with_registry(monkeypatch, tmp_path, "--no-alias-normalize")

    prompt = fake_stream.calls[0]["user"]
    assert "Alice asks about Spider, who runs the docks." in prompt
    assert "Nezznar the Spider" not in prompt.split("## Known NPCs")[0]
    # Canonical names still reach the model — as knowledge, not as a rewrite.
    assert "## Known NPCs" in prompt
    assert "Nezznar the Spider (also: Spider)" in prompt


def test_known_npc_roster_reaches_the_prompt_even_when_party_is_given(
    monkeypatch, tmp_path,
):
    """The roster used to be passed as ``roster or npc_roster``, so supplying
    a party roster silently dropped the NPC one — leaving the destructive
    rewrite as the only channel carrying canonical names."""
    _write_registry(tmp_path)
    cfg = _write_party_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    fake_stream = _run_with_registry(monkeypatch, tmp_path, "--party-config", str(cfg))

    prompt = fake_stream.calls[0]["user"]
    assert "## Character Classes" in prompt          # party roster still there
    assert "## Known NPCs" in prompt                 # and so is the NPC roster
    assert "Never apply them inside quotation marks" in prompt


def test_alias_registry_flag_overrides_autodiscovery(monkeypatch, tmp_path):
    """No docs/entity_registry.yaml under CWD — the flag is the only source."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    reg = elsewhere / "registry.yaml"
    reg.write_text(REGISTRY_YAML, encoding="utf-8")

    fake_stream = _run_with_registry(
        monkeypatch, tmp_path, "--alias-registry", str(reg))

    prompt = fake_stream.calls[0]["user"]
    assert "Alice asks about Nezznar the Spider" in prompt
    assert '"Tell me about Spider and Lord Neverember."' in prompt


def test_alias_registry_flag_errors_when_the_path_is_missing(monkeypatch, tmp_path):
    paths = _write_fixtures(tmp_path)
    monkeypatch.setattr(sys, "argv", _base_argv(
        paths, "--alias-registry", str(tmp_path / "nope.yaml")))
    with pytest.raises(SystemExit) as excinfo:
        sd_narrate.main()
    assert excinfo.value.code == 1


# ── Smoothed-sibling guard (#223, defect C) ────────────────────────────────

def test_warns_when_a_smoothed_sibling_exists_but_was_not_selected(
    monkeypatch, tmp_path, capsys,
):
    paths = _write_fixtures(tmp_path)
    smoothed = tmp_path / "scenes_smoothed"
    smoothed.mkdir()
    (smoothed / "01_scene_one.md").write_text(SCENE_ONE_BODY, encoding="utf-8")
    monkeypatch.setattr(sd_narrate, "stream_api",
                        FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION]))

    monkeypatch.setattr(sys, "argv", _base_argv(paths))
    sd_narrate.main()

    err = capsys.readouterr().err
    assert "scenes_smoothed/ exists alongside scenes/" in err
    assert "will NOT reach narration" in err


# ── Unknown-name warning (#223, defect A.3) ────────────────────────────────

def test_known_lore_warns_about_a_name_absent_from_bible_and_source(
    monkeypatch, tmp_path, capsys,
):
    paths = _write_fixtures(tmp_path)
    bible = tmp_path / "bible.md"
    bible.write_text("Alice drinks at the bar in Neverwinter.\n", encoding="utf-8")

    leaked = "Kazneporium had been watching.\n\nAlice ordered another.\n"
    monkeypatch.setattr(sd_narrate, "stream_api",
                        FakeStreamAPI([leaked, SCENE2_NARRATION]))
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--known-lore", str(bible)))
    sd_narrate.main()

    err = capsys.readouterr().err
    assert "Kazneporium" in err
    assert "#223 A.3" in err
    # A warning only — the narration file is written exactly as generated.
    written = paths["out_dir"] / "session_doc_scene_01_scene_one.md"
    assert "Kazneporium had been watching." in written.read_text(encoding="utf-8")


def test_known_lore_is_quiet_when_every_name_is_accounted_for(
    monkeypatch, tmp_path, capsys,
):
    paths = _write_fixtures(tmp_path)
    bible = tmp_path / "bible.md"
    bible.write_text("Alice drinks at the bar in Neverwinter.\n", encoding="utf-8")

    monkeypatch.setattr(sd_narrate, "stream_api",
                        FakeStreamAPI(["Alice went back to Neverwinter.", SCENE2_NARRATION]))
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--known-lore", str(bible)))
    sd_narrate.main()

    assert "#223 A.3" not in capsys.readouterr().err


def test_no_known_lore_flag_means_no_check_at_all(monkeypatch, tmp_path, capsys):
    """Without an allowlist every name would be 'unknown' — so the check is
    strictly opt-in."""
    paths = _write_fixtures(tmp_path)
    monkeypatch.setattr(sd_narrate, "stream_api",
                        FakeStreamAPI(["Kazneporium was here.", SCENE2_NARRATION]))
    monkeypatch.setattr(sys, "argv", _base_argv(paths))
    sd_narrate.main()

    assert "#223 A.3" not in capsys.readouterr().err


def test_known_lore_checks_the_PRE_normalisation_source(monkeypatch, tmp_path, capsys):
    """The session's own extractions are snapshotted BEFORE alias expansion.
    Otherwise a surname the normaliser just introduced would appear in the
    'known' set and vouch for itself — which is exactly the ch47 defect."""
    paths = _write_fixtures(tmp_path)
    (paths["scenes_dir"] / "01_scene_one.md").write_text(
        "- Aldus counts the coins.\n", encoding="utf-8")
    _write_registry(tmp_path)
    (tmp_path / "docs" / "entity_registry.yaml").write_text(
        "version: 1\ncampaign: testcamp\nentities:\n"
        "  - name: Aldus Hern\n    type: npc\n    aliases: [Aldus]\n",
        encoding="utf-8")
    bible = tmp_path / "bible.md"
    bible.write_text("Alice drinks at the bar.\n", encoding="utf-8")

    monkeypatch.setattr(sd_narrate, "stream_api",
                        FakeStreamAPI(["I watched Aldus Hern count.", SCENE2_NARRATION]))
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--known-lore", str(bible)))
    sd_narrate.main()

    err = capsys.readouterr().err
    assert "Aldus Hern" in err, "alias expansion vouched for itself"


def test_no_warning_when_the_smoothed_dir_is_the_one_selected(
    monkeypatch, tmp_path, capsys,
):
    paths = _write_fixtures(tmp_path)
    monkeypatch.setattr(sd_narrate, "stream_api",
                        FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION]))
    monkeypatch.setattr(sys, "argv", _base_argv(paths))
    sd_narrate.main()

    assert "exists alongside" not in capsys.readouterr().err


# ── Silent-failure warning when --party can't be parsed (#245, defect 4) ────
#
# The Phandalin ch46 regression: `## Character Classes` was silently ABSENT
# from the prompt because the roster parser produced junk from a party.md
# layout it didn't understand, with nothing telling the GM. The parser now
# reads all six hand-authored campaign layouts (issue #248; see
# tests/test_roster.py) — this pair guards the failure mode for whatever's
# left over: a party.md with no class-shaped line the parser recognises at
# all, synthetic on purpose so it isn't tied to any one campaign's (movable)
# current file content.

UNPARSEABLE_PARTY = (
    "## Characters\n\n### Akritas\n**Notes:** Not a class line at all.\n"
)

# Verbatim excerpt from /home/kroussos/src/campaigns/Phandalin/docs/party.md — kept
# as a local copy rather than importing from tests/test_roster.py: tests/ has no
# __init__.py, so a cross-file `from tests.test_roster import ...` makes Python
# import that module twice under two different names ("test_roster" via pytest's
# own rootdir-relative collection, "tests.test_roster" via the explicit import),
# re-executing its module body a second time. That duplicate execution was
# observed to produce flaky session_doc.roster resolution in this suite —
# harmless on its own terms, but not worth the risk. See tests/test_roster.py
# for the parser-level coverage of this fixture; this copy only needs enough to
# exercise the --party wiring end to end.
PHANDALIN_PARTY = (
    "# Party Reference — Icespire Peak / Phandalin Campaign\n"
    "\n"
    "## Characters\n"
    "\n"
    "### Brewbarry\n"
    "\n"
    "**Barbarian 6 (Path of the Giant) | Goliath | Stephane Boudreau \n"
    "\n"
    "### Valphine Sotorra\n"
    "\n"
    "**Cleric 6 (Peace Domain) | Drow Elf | Player: Gary Young**\n"
    "\n"
    "### Soma\n"
    "\n"
    "**Druid 6 (Circle of the Moon) | Tortle | Player: Wade Brown**\n"
    "\n"
    "### Vukradin\n"
    "\n"
    "**Bard 6 (College of Eloquence) | Aasimar | Player: David Mendenhall (Dave)**\n"
    "\n"
)


def _write_party_config(tmp_path) -> Path:
    """A campaign roster: party.yaml plus one migrated sheet (#265)."""
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "brewbarry.md").write_text(
        "---\n"
        "name: Brewbarry\n"
        "player: Stéphane Bourdeaud\n"
        "species: Goliath\n"
        "class_level: Barbarian 6\n"
        "subclass: Path of the Giant\n"
        "---\n"
        "# Brewbarry\n", encoding="utf-8")
    cfg = tmp_path / "party.yaml"
    cfg.write_text(
        "characters:\n- name: Brewbarry\n  sheet: docs/brewbarry.md\n",
        encoding="utf-8")
    return cfg


def test_party_md_alone_is_now_a_hard_error(monkeypatch, tmp_path, capsys):
    """#245 defect 4 was that `## Character Classes` went silently ABSENT when
    party.md's layout defeated the roster parser. That is structurally
    impossible now: party.md is not a roster source, and asking for a roster
    without a usable config exits non-zero instead of rendering without one."""
    paths = _write_fixtures(tmp_path)
    party = tmp_path / "party.md"
    party.write_text(UNPARSEABLE_PARTY, encoding="utf-8")
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)

    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--party", str(party)))
    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "No --party-config was given" in err
    assert "sheet_frontmatter --apply" in err
    assert not fake_stream.calls          # nothing was sent to the model


def test_a_well_formed_party_md_does_not_rescue_it(monkeypatch, tmp_path, capsys):
    """Even a party.md the old parser handled perfectly is not consulted — the
    deletion is about the *source*, not about parse failures."""
    paths = _write_fixtures(tmp_path)
    party = tmp_path / "party.md"
    party.write_text(PHANDALIN_PARTY, encoding="utf-8")
    monkeypatch.setattr(sd_narrate, "stream_api",
                        FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION]))
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--party", str(party)))
    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()
    assert exc.value.code == 1


def test_roster_comes_from_the_sheet_frontmatter(monkeypatch, tmp_path, capsys):
    paths = _write_fixtures(tmp_path)
    cfg = _write_party_config(tmp_path)
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.chdir(tmp_path)          # party.yaml paths are campaign-root-relative

    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--party-config", str(cfg)))
    sd_narrate.main()

    prompt = fake_stream.calls[0]["user"]
    assert "## Character Classes" in prompt
    assert "Goliath Barbarian 6 (Path of the Giant)" in prompt


def test_no_party_flags_at_all_still_runs(monkeypatch, tmp_path):
    """Running with no roster predates #265 and stays legitimate — the class
    block is simply absent. Deleting the fallback must not turn "no roster
    wanted" into an error."""
    paths = _write_fixtures(tmp_path)
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.setattr(sys, "argv", _base_argv(paths))
    sd_narrate.main()
    assert "## Character Classes" not in fake_stream.calls[0]["user"]


# ── Underscore-prefixed shared campaign files are skipped (#245, item E) ────
#
# session_doc/io.py already treats a leading `_` as "shared sibling artifact,
# not a per-item file" (`_genre.md` sitting next to per-scene/per-character
# files). voice.py and sd_narrate.py's `_load_examples` glob the same `*.md`
# directories and must mirror that skip.

GENRE_SENTINEL = "SENTINEL_GENRE_TEXT — this is shared campaign material."


def test_underscore_file_is_not_loaded_as_a_voice(tmp_path):
    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()
    (voice_dir / "_genre.md").write_text(GENRE_SENTINEL, encoding="utf-8")
    (voice_dir / "alice_voice.md").write_text("Alice speaks in short sentences.",
                                               encoding="utf-8")

    voices = load_voice_files(voice_dir)

    assert set(voices.keys()) == {"alice"}
    assert not any("genre" in key for key in voices)

    # Behaviour check: a voice/ dir with ONLY an underscore file yields {},
    # and looking up a narrator against it returns None rather than crashing.
    only_underscore_dir = tmp_path / "voice_only_underscore"
    only_underscore_dir.mkdir()
    (only_underscore_dir / "_genre.md").write_text(GENRE_SENTINEL, encoding="utf-8")
    empty_voices = load_voice_files(only_underscore_dir)
    assert empty_voices == {}
    assert get_voice_note(empty_voices, "Brewbarry") is None


def test_underscore_file_does_not_join_global_examples(tmp_path):
    examples_dir = tmp_path / "examples"
    examples_dir.mkdir()
    (examples_dir / "_genre.md").write_text(GENRE_SENTINEL, encoding="utf-8")
    (examples_dir / "alice.md").write_text("Alice's per-character style sample.",
                                            encoding="utf-8")
    (examples_dir / "general_style.md").write_text("The house style sample.",
                                                     encoding="utf-8")

    global_text, per_char = sd_narrate._load_examples(examples_dir, ["Alice", "Bob"])

    # Sentinel from the underscore file reaches neither the global block...
    assert GENRE_SENTINEL not in (global_text or "")
    # ...nor any per-character entry.
    for text in per_char.values():
        assert GENRE_SENTINEL not in text
    # A normal shared file (no leading underscore) still joins the global block.
    assert "The house style sample." in (global_text or "")


# ── Voice-file lookup resolution (#247) ──────────────────────────────────────
#
# load_voice_files only strips a trailing "_voice" suffix, so real Phandalin
# filenames like "brewbarry_new_pipeline.md" key as "brewbarry_new_pipeline"
# — a lookup on "Brewbarry" (full name or first name) used to miss entirely
# and all four Phandalin narrators silently got no VOICE SPEC block. These
# cover every real filename shape plus the ambiguity and skip cases.

def test_get_voice_note_resolves_new_pipeline_filename(tmp_path):
    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()
    (voice_dir / "brewbarry_new_pipeline.md").write_text(
        "Blustery halfling merchant voice.", encoding="utf-8")

    voices = load_voice_files(voice_dir)

    assert get_voice_note(voices, "Brewbarry") == "Blustery halfling merchant voice."


def test_get_voice_note_resolves_legacy_voice_suffix(tmp_path):
    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()
    (voice_dir / "brewbarry_voice.md").write_text(
        "Legacy spec.", encoding="utf-8")

    voices = load_voice_files(voice_dir)

    assert get_voice_note(voices, "Brewbarry") == "Legacy spec."


def test_get_voice_note_resolves_bare_filename(tmp_path):
    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()
    (voice_dir / "brewbarry.md").write_text("Bare spec.", encoding="utf-8")

    voices = load_voice_files(voice_dir)

    assert get_voice_note(voices, "Brewbarry") == "Bare spec."


def test_get_voice_note_ambiguous_prefix_returns_none_and_warns(tmp_path, capsys):
    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()
    # Two files whose keys both start with "brewbarry" + separator — the
    # resolver must refuse to guess between them rather than picking one.
    (voice_dir / "brewbarry_new_pipeline.md").write_text("New spec.", encoding="utf-8")
    (voice_dir / "brewbarry-alt-take.md").write_text("Alt spec.", encoding="utf-8")

    voices = load_voice_files(voice_dir)

    result = get_voice_note(voices, "Brewbarry")

    assert result is None
    err = capsys.readouterr().err
    assert "ambiguous" in err
    assert "Brewbarry" in err
    assert "brewbarry_new_pipeline" in err
    assert "brewbarry-alt-take" in err


def test_get_voice_note_genre_file_is_skipped_not_a_candidate(tmp_path):
    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()
    (voice_dir / "_genre.md").write_text(GENRE_SENTINEL, encoding="utf-8")
    (voice_dir / "brewbarry_new_pipeline.md").write_text(
        "Blustery halfling merchant voice.", encoding="utf-8")

    voices = load_voice_files(voice_dir)

    assert "genre" not in voices
    assert get_voice_note(voices, "Brewbarry") == "Blustery halfling merchant voice."


def test_get_voice_note_real_phandalin_shape_all_four_narrators_found(tmp_path):
    # Mirrors the actual ~/src/campaigns/Phandalin/voice/ layout: four
    # "_new_pipeline" files plus a shared "_genre.md".
    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()
    (voice_dir / "_genre.md").write_text(GENRE_SENTINEL, encoding="utf-8")
    for name in ("brewbarry", "soma", "valphine", "vukradin"):
        (voice_dir / f"{name}_new_pipeline.md").write_text(
            f"{name} voice spec.", encoding="utf-8")

    voices = load_voice_files(voice_dir)

    for name in ("Brewbarry", "Soma", "Valphine", "Vukradin"):
        assert get_voice_note(voices, name) == f"{name.lower()} voice spec."


def test_get_voice_note_warns_on_miss_with_nonempty_voices(capsys):
    voices = {"vukradin": "Gruff."}

    result = get_voice_note(voices, "Brewbarry")

    assert result is None
    err = capsys.readouterr().err
    assert "Brewbarry" in err
    assert "vukradin" in err


def test_get_voice_note_does_not_warn_on_empty_voices(capsys):
    result = get_voice_note({}, "Brewbarry")

    assert result is None
    err = capsys.readouterr().err
    assert err == ""


# ── System-prompt caching on the live narrate call (#245, item E) ───────────
#
# The system prompt (base + prose_mode + examples + voice spec + genre doc)
# is identical across every scene in the per-scene loop, so caching it is
# free money for API-billed runs. --batch is a different code path/semantics
# and must NOT pick up cache_system.

def test_narrate_requests_system_prompt_caching(monkeypatch, tmp_path):
    paths = _write_fixtures(tmp_path)
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)

    monkeypatch.setattr(sys, "argv", _base_argv(paths))
    sd_narrate.main()

    assert len(fake_stream.calls) == 2
    for call in fake_stream.calls:
        assert call["kwargs"].get("cache_system") is True

    # --batch path is untouched: no cache_system kwarg reaches run_single_batch.
    fake_batch = FakeRunSingleBatch([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "run_single_batch", fake_batch)
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--batch"))
    sd_narrate.main()

    assert len(fake_batch.calls) == 2
    for call in fake_batch.calls:
        assert "cache_system" not in call["kwargs"]


# ── #300: a configured --voice-dir that cannot deliver stops the run ─────────
#
# `Path.glob` over a missing directory yields nothing rather than raising, so a
# typo'd voice_dir produced the same `{}` as no flag at all — and
# `get_voice_note`'s #247 warning opens with `if not voices: return None`, so
# the warning built to stop a spec from silently missing the prompt was mute in
# the one case where EVERY spec was lost. These pin the refusal that replaces
# that silence.


def test_voice_dir_not_given_is_still_a_legitimate_mode(tmp_path):
    """Rendering without voice specs is a real mode and must not be broken."""
    assert sd_narrate._load_voice_dir(None) == {}
    assert sd_narrate._load_voice_dir("") == {}


def test_voice_dir_that_does_not_exist_refuses(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        sd_narrate._load_voice_dir(str(tmp_path / "nope"))
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "is not a directory" in err
    assert "NO voice specs" in err


def test_voice_dir_holding_only_shared_material_is_no_voice_mode(tmp_path, capsys):
    """`_genre.md` is campaign material, not a spec — but a dir with only that
    in it means "nobody has written specs yet", not "the path is wrong".

    Deliberately NOT fatal: `new_workspace` creates `voice/` empty and
    `PlatformConfigService.derive` fills `voice_dir` in from its mere
    existence, so refusing here would break Narrate on every fresh campaign
    over a path the tool chose rather than the GM.
    """
    vd = tmp_path / "voice"
    vd.mkdir()
    (vd / "_genre.md").write_text("# Register\n", encoding="utf-8")

    assert sd_narrate._load_voice_dir(str(vd)) == {}
    assert "holds no per-character voice files" in capsys.readouterr().err


def test_empty_voice_dir_is_no_voice_mode_not_a_refusal(tmp_path, capsys):
    """The fresh-workspace shape, exactly."""
    vd = tmp_path / "voice"
    vd.mkdir()

    assert sd_narrate._load_voice_dir(str(vd)) == {}
    assert "holds no per-character voice files" in capsys.readouterr().err


def test_a_fresh_workspace_still_renders(monkeypatch, tmp_path):
    """End-to-end version of the above: empty voice/ must not block a render."""
    paths = _write_fixtures(tmp_path)
    vd = tmp_path / "voice"
    vd.mkdir()
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--voice-dir", str(vd)))

    sd_narrate.main()

    assert len(fake_stream.calls) == 2


def test_usable_voice_dir_loads(tmp_path):
    vd = tmp_path / "voice"
    vd.mkdir()
    (vd / "alice_new_pipeline.md").write_text("Alice speaks flatly.", encoding="utf-8")
    assert sd_narrate._load_voice_dir(str(vd)) == {
        "alice_new_pipeline": "Alice speaks flatly."
    }


# ── #300: every narrator in the render must resolve, before the first call ───


def _voice_dir(tmp_path: Path, *names: str) -> Path:
    vd = tmp_path / "voice"
    vd.mkdir()
    for n in names:
        (vd / n).write_text(f"# {n}\n\nspec body\n", encoding="utf-8")
    return vd


def test_narrator_without_a_voice_file_stops_the_run_before_any_api_call(
        monkeypatch, tmp_path, capsys):
    """The plan needs Alice and Bob; only Alice has a spec.

    Nothing may be rendered: the old behaviour warned for Bob and produced a
    full session document in which one narrator had silently lost their voice.
    """
    paths = _write_fixtures(tmp_path)
    vd = _voice_dir(tmp_path, "alice.md")
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--voice-dir", str(vd)))

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()

    assert exc.value.code == 1
    assert fake_stream.calls == []                       # nothing was paid for
    # The output dir itself is created earlier in main() (as it is on every
    # other refusal path); what must not exist is narration.
    assert list(paths["out_dir"].glob("*.md")) == []
    err = capsys.readouterr().err
    assert "narrator 'Bob': no voice file" in err
    assert "available keys: ['alice']" in err


def test_ambiguous_voice_file_stops_the_run_rather_than_guessing(
        monkeypatch, tmp_path, capsys):
    """#247 refuses to guess between two candidates; #300 makes that refusal
    stop the render instead of dropping one narrator's spec."""
    paths = _write_fixtures(tmp_path)
    vd = _voice_dir(tmp_path, "alice_v1.md", "alice_v2.md", "bob.md")
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--voice-dir", str(vd)))

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()

    assert exc.value.code == 1
    assert fake_stream.calls == []
    err = capsys.readouterr().err
    assert "ambiguous" in err
    assert "alice_v1" in err and "alice_v2" in err


def test_a_narrator_filtered_out_of_this_render_is_not_required(
        monkeypatch, tmp_path):
    """`--narrator Alice` renders only Alice's sections, so Bob's missing spec
    is irrelevant to THIS run. The check follows the filters, not the plan."""
    paths = _write_fixtures(tmp_path)
    vd = _voice_dir(tmp_path, "alice.md")
    fake_stream = FakeStreamAPI([SCENE1_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.setattr(sys, "argv", _base_argv(
        paths, "--voice-dir", str(vd), "--narrator", "Alice"))

    sd_narrate.main()

    assert len(fake_stream.calls) == 1
    assert "spec body" in fake_stream.calls[0]["system"]


def test_full_coverage_renders_normally(monkeypatch, tmp_path):
    paths = _write_fixtures(tmp_path)
    vd = _voice_dir(tmp_path, "alice_new_pipeline.md", "bob.md")
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--voice-dir", str(vd)))

    sd_narrate.main()

    assert len(fake_stream.calls) == 2


# ── voice_resolution_problems in isolation ──────────────────────────────────


def test_resolution_problems_empty_when_everyone_resolves():
    voices = {"alice_new_pipeline": "a", "bob": "b"}
    assert session_doc.voice_resolution_problems(voices, ["Alice", "Bob"]) == []


def test_resolution_problems_reports_each_narrator_once():
    """A plan giving one character four scenes is one problem, not four."""
    problems = session_doc.voice_resolution_problems({"bob": "b"},
                                                     ["Alice", "Alice", "Alice"])
    assert len(problems) == 1
    assert "Alice" in problems[0]


def test_resolution_problems_ignores_blank_narrators():
    assert session_doc.voice_resolution_problems({"bob": "b"}, ["", "  "]) == []
