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
                           "max_tokens": max_tokens})
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
        self.calls.append({"system": system, "user": user, "model": model})
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
    --party silently dropped it — leaving the destructive rewrite as the only
    channel carrying canonical names."""
    _write_registry(tmp_path)
    party = tmp_path / "party.md"
    party.write_text("## Alice\n**Human Bard 5, Player: Ann**\n", encoding="utf-8")

    fake_stream = _run_with_registry(monkeypatch, tmp_path, "--party", str(party))

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


def test_no_warning_when_the_smoothed_dir_is_the_one_selected(
    monkeypatch, tmp_path, capsys,
):
    paths = _write_fixtures(tmp_path)
    monkeypatch.setattr(sd_narrate, "stream_api",
                        FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION]))
    monkeypatch.setattr(sys, "argv", _base_argv(paths))
    sd_narrate.main()

    assert "exists alongside" not in capsys.readouterr().err
