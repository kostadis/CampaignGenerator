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

SCENE_THREE_SECTION = """\
## Section 3
narrator: Alice
chunks: 3-3
scene: Scene Three
focus: checking the partial smoothed layer
"""


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


def _assert_exact_scene_input_refused_before_model(
    monkeypatch, tmp_path, capsys, *extra: str, expected: tuple[str, ...],
) -> None:
    paths = _write_fixtures(tmp_path)
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    fake_batch = FakeRunSingleBatch([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.setattr(sd_narrate, "run_single_batch", fake_batch)

    monkeypatch.setattr(sys, "argv", _base_argv(paths, *extra))
    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()
    assert exc.value.code != 0
    assert not fake_stream.calls
    assert not fake_batch.calls

    err = capsys.readouterr().err
    for text in expected:
        assert text in err


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


# ── --scene-extraction-file: parser and pre-model validation ───────────────

def test_exact_scene_input_help_documents_the_sole_spelling(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["sd_narrate", "--help"])

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--scene-extraction-file FILE" in out
    assert "single-scene input override" in out
    assert "exactly one --scene N" in out
    assert "--scene-file" not in out
    assert "--extraction-file" not in out


def test_exact_scene_input_requires_one_scene_before_model_call(
    monkeypatch, tmp_path, capsys,
):
    exact = tmp_path / "scenes" / "01_scene_one.md"

    _assert_exact_scene_input_refused_before_model(
        monkeypatch, tmp_path, capsys,
        "--scene-extraction-file", str(exact),
        expected=("--scene-extraction-file", "exactly one --scene N"),
    )


def test_exact_scene_input_rejects_multiple_scenes_before_model_call(
    monkeypatch, tmp_path, capsys,
):
    exact = tmp_path / "scenes" / "01_scene_one.md"

    _assert_exact_scene_input_refused_before_model(
        monkeypatch, tmp_path, capsys,
        "--scene", "1", "2",
        "--scene-extraction-file", str(exact),
        expected=("--scene-extraction-file", "exactly one --scene N"),
    )


@pytest.mark.parametrize(
    ("filename", "writer", "expected_rule"),
    [
        pytest.param("missing.md", None, "does not exist", id="nonexistent"),
        pytest.param(
            "01_scene_one.md",
            "directory",
            "not a regular file",
            id="non-file",
        ),
        pytest.param(
            "not_a_scene.md",
            "text",
            "eligible NN_*.md scene extraction",
            id="ineligible",
        ),
        pytest.param(
            "01_invalid_utf8.md",
            "bytes",
            "readable UTF-8",
            id="invalid-utf8",
        ),
    ],
)
def test_exact_scene_input_requires_eligible_readable_utf8_before_model_call(
    monkeypatch, tmp_path, capsys, filename, writer, expected_rule,
):
    exact = tmp_path / filename
    if writer == "text":
        exact.write_text("not an eligible scene extraction\n", encoding="utf-8")
    elif writer == "directory":
        exact.mkdir()
    elif writer == "bytes":
        exact.write_bytes(b"\xff\xfe\x00")

    _assert_exact_scene_input_refused_before_model(
        monkeypatch, tmp_path, capsys,
        "--scene", "1",
        "--scene-extraction-file", str(exact),
        expected=("--scene-extraction-file", str(exact), expected_rule),
    )


def test_exact_scene_input_must_associate_with_selected_scene_before_model_call(
    monkeypatch, tmp_path, capsys,
):
    exact = tmp_path / "01_wrong_scene.md"
    exact.write_text(
        "---\nscene: A Different Scene\n---\n\nnot scene two\n",
        encoding="utf-8",
    )

    _assert_exact_scene_input_refused_before_model(
        monkeypatch, tmp_path, capsys,
        "--scene", "2",
        "--scene-extraction-file", str(exact),
        expected=("--scene-extraction-file", "scene 2", "A Different Scene"),
    )


def test_exact_scene_input_reaches_selected_prompt_once_without_rewriting_inputs(
    monkeypatch, tmp_path,
):
    paths = _write_fixtures(tmp_path)
    raw_scene = paths["scenes_dir"] / "01_scene_one.md"
    raw_scene.write_text(
        "- RAW_ONLY_BEAT must not be narrated from the selected prompt.\n",
        encoding="utf-8",
    )
    smoothed_dir = tmp_path / "scenes_smoothed"
    smoothed_dir.mkdir()
    exact = smoothed_dir / "01_scene_one_smoothed_exact.md"
    exact.write_text(
        "---\nscene: Scene One\nsource: voice-smoothed\n---\n\n"
        "- EXACT_SMOOTHED_BEAT reaches the prompt once.\n",
        encoding="utf-8",
    )
    bible = tmp_path / "known_lore.md"
    bible.write_text("Alice knows the tavern.\n", encoding="utf-8")

    raw_before = raw_scene.read_bytes()
    raw_mtime_before = raw_scene.stat().st_mtime_ns
    exact_before = exact.read_bytes()
    exact_mtime_before = exact.stat().st_mtime_ns

    fake_stream = FakeStreamAPI([SCENE1_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.setattr(sd_narrate, "run_single_batch", FakeRunSingleBatch([]))
    captured_sources: list[list[str]] = []

    def fake_find_unknown_names(_narration, sources):
        captured_sources.append(list(sources))
        return []

    monkeypatch.setattr(sd_narrate, "find_unknown_names", fake_find_unknown_names)
    monkeypatch.setattr(sys, "argv", _base_argv(
        paths,
        "--scene", "1",
        "--scene-extraction-file", str(exact),
        "--known-lore", str(bible),
    ))

    sd_narrate.main()

    assert len(fake_stream.calls) == 1
    prompt = fake_stream.calls[0]["user"]
    assert prompt.count("EXACT_SMOOTHED_BEAT") == 1
    assert "RAW_ONLY_BEAT" not in prompt

    assert len(captured_sources) == 1
    assert sum(
        "EXACT_SMOOTHED_BEAT" in source
        for source in captured_sources[0]
    ) == 1

    assert raw_scene.read_bytes() == raw_before
    assert raw_scene.stat().st_mtime_ns == raw_mtime_before
    assert exact.read_bytes() == exact_before
    assert exact.stat().st_mtime_ns == exact_mtime_before


def test_exact_scene_input_selects_requested_scene_from_partial_directory(
    monkeypatch, tmp_path,
):
    paths = _write_fixtures(tmp_path)
    paths["plan"].write_text(PLAN_TEXT + "\n" + SCENE_THREE_SECTION, encoding="utf-8")
    raw_scene_three = paths["scenes_dir"] / "03_scene_three_raw.md"
    raw_scene_three.write_text(
        "---\nscene: Scene Three\n---\n\n"
        "- RAW_SCENE_THREE_BEAT must not reach the prompt.\n",
        encoding="utf-8",
    )

    smoothed_dir = tmp_path / "scenes_smoothed"
    smoothed_dir.mkdir()
    smoothed_scene_one = smoothed_dir / "01_scene_one_smoothed.md"
    smoothed_scene_one.write_text(
        "---\nscene: Scene One\nsource: voice-smoothed\n---\n\n"
        "- WRONG_PARTIAL_SCENE_BEAT must not be substituted.\n",
        encoding="utf-8",
    )
    exact = smoothed_dir / "03_different_voice_slug.md"
    exact.write_text(
        "---\nscene: Scene Three\nsource: voice-smoothed\n---\n\n"
        "- EXACT_PARTIAL_SCENE_THREE_BEAT is the selected input.\n",
        encoding="utf-8",
    )

    fake_stream = FakeStreamAPI([SCENE1_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.setattr(sd_narrate, "run_single_batch", FakeRunSingleBatch([]))
    monkeypatch.setattr(sys, "argv", _base_argv(
        paths,
        "--scene", "3",
        "--scene-extraction-file", str(exact),
    ))

    sd_narrate.main()

    assert len(fake_stream.calls) == 1
    prompt = fake_stream.calls[0]["user"]
    assert prompt.count("EXACT_PARTIAL_SCENE_THREE_BEAT") == 1
    assert "RAW_SCENE_THREE_BEAT" not in prompt
    assert "WRONG_PARTIAL_SCENE_BEAT" not in prompt


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


def test_sequential_single_scene_rerun_replaces_only_that_scene(monkeypatch, tmp_path):
    paths = _write_fixtures(tmp_path)
    paths["out_dir"].mkdir()
    untouched = paths["out_dir"] / "session_doc_scene_02_scene_two.md"
    untouched.write_text("reviewed scene two\n", encoding="utf-8")
    fake_stream = FakeStreamAPI([SCENE1_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.setattr(sd_narrate, "run_single_batch", FakeRunSingleBatch([]))
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--scene", "1"))

    sd_narrate.main()

    assert len(fake_stream.calls) == 1
    assert untouched.read_text(encoding="utf-8") == "reviewed scene two\n"
    rerun = paths["out_dir"] / "session_doc_scene_01_scene_one.md"
    text = rerun.read_text(encoding="utf-8")
    assert "scene: 01\nslug: scene_one\nnarrator: Alice\n" in text
    assert SCENE1_NARRATION in text


def test_explicit_no_batch_scenes_keeps_sequential_calls_and_ignores_bundle_ceiling(
    monkeypatch, tmp_path, capsys,
):
    paths = _write_fixtures(tmp_path)
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.setattr(sd_narrate, "run_single_batch", FakeRunSingleBatch([]))
    monkeypatch.setattr(sys, "argv", _base_argv(
        paths, "--no-batch-scenes", "--batch-max-tokens", "900",
    ))

    sd_narrate.main()

    assert len(fake_stream.calls) == 2
    assert "--batch-max-tokens is ignored without --batch-scenes" in capsys.readouterr().err

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


def test_shared_examples_reach_scene_mode_prompts(monkeypatch, tmp_path):
    """Every plan section carries a ``scene:`` line, so scene mode is the only
    mode the pipeline actually runs. The campaign-wide block used to be
    suppressed there (``None if scene_name else examples_text``), which made a
    shared example file silently inert. It must reach every scene.

    The block's *source* changed with feature 009 — it is the roster's
    ``shared_examples:`` list rather than whatever failed to match a name — but
    what it must reach did not.
    """
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "examples").mkdir(exist_ok=True)
    for who in ("Alice", "Bob"):
        (tmp_path / "docs" / f"{who}.md").write_text(
            f"---\nname: {who}\nspecies: Human\nclass_level: Rogue 4\n"
            f"subclass: ''\n---\n# {who}\n", encoding="utf-8")
    (tmp_path / "examples" / "house_style.md").write_text(HOUSE_STYLE, encoding="utf-8")
    (tmp_path / "examples" / "alice.md").write_text(ALICE_STYLE, encoding="utf-8")
    cfg = tmp_path / "party.yaml"
    cfg.write_text(
        "characters:\n"
        "- name: Alice\n  sheet: docs/Alice.md\n  examples: examples/alice.md\n"
        "- name: Bob\n  sheet: docs/Bob.md\n"
        "shared_examples:\n- examples/house_style.md\n",
        encoding="utf-8")

    paths = _write_fixtures(tmp_path)
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--party-config", str(cfg)))
    sd_narrate.main()

    assert len(fake_stream.calls) == 2
    for call in fake_stream.calls:
        assert HOUSE_STYLE in call["system"]

    # Alice's own file is named by Alice's entry and by nothing else, so it
    # reaches her scene and never joins the block Bob also sees.
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


def test_an_undeclared_file_joins_nothing(tmp_path):
    """The `_`-prefix convention used to be the only thing keeping `_genre.md`
    out of the block every narrator sees. Declarations make it moot: a file
    reaches a prompt because something named it, and `_genre.md` names itself
    to nobody. `general_style.md` is the case that used to slip through — a
    perfectly ordinary filename that matched no character and therefore went to
    everyone."""
    from campaignlib.party_config import PartyConfig, PartyCharacter, resolve_party_config
    from session_doc.examples import load_declared_examples, load_shared_examples

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "Alice.md").write_text("x", encoding="utf-8")
    examples_dir = tmp_path / "examples"
    examples_dir.mkdir()
    (examples_dir / "_genre.md").write_text(GENRE_SENTINEL, encoding="utf-8")
    (examples_dir / "alice.md").write_text("Alice's per-character style sample.",
                                            encoding="utf-8")
    (examples_dir / "general_style.md").write_text("The house style sample.",
                                                     encoding="utf-8")

    cfg = resolve_party_config(PartyConfig(characters=[
        PartyCharacter(name="Alice", sheet="docs/Alice.md",
                       examples="examples/alice.md"),
    ]), tmp_path)

    per_char = load_declared_examples(cfg)
    assert per_char == {"alice": "Alice's per-character style sample."}
    # Nothing declares a shared block, so there is no shared block.
    assert load_shared_examples(cfg) is None
    assert GENRE_SENTINEL not in "".join(per_char.values())


# ── Declared voice and example files (feature 009) ───────────────────────────
#
# A character's voice spec and style examples are DECLARED by its roster entry
# and resolved by following a path. What this replaced was a three-step name
# rule — exact, then first name, then the unique key beginning with the first
# name plus `_` or `-` — plus a fall-through that sent every unmatched example
# file to EVERY narrator.
#
# Both halves failed the same way and for the same reason. `Grygum` renamed to
# `Gyrgum` stopped resolving and told nobody (campaigns#175); the obvious
# one-line repair then converted that silent drop into a silent bleed; and the
# detector added for the bleed (#301) could not see a rename either (#315). A
# path cannot fail that way. It is there, or it is named in a refusal.


def _declaring_party(tmp_path: Path, *, alice_voice=True, alice_examples=True,
                     bob_voice=True, shared=()) -> Path:
    """A roster for the Alice/Bob plan, with declared files on disk."""
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "voice").mkdir(exist_ok=True)
    (tmp_path / "examples").mkdir(exist_ok=True)
    for who in ("Alice", "Bob"):
        (tmp_path / "docs" / f"{who}.md").write_text(
            f"---\nname: {who}\nspecies: Human\nclass_level: Rogue 4\n"
            f"subclass: ''\n---\n# {who}\n", encoding="utf-8")
    # Deliberately NOT named after the characters: under the deleted rule the
    # filename's shape was load-bearing; under declarations it is arbitrary.
    (tmp_path / "voice" / "a_new_pipeline.md").write_text(ALICE_VOICE, encoding="utf-8")
    (tmp_path / "voice" / "b_new_pipeline.md").write_text(BOB_VOICE, encoding="utf-8")
    (tmp_path / "examples" / "a.md").write_text(ALICE_STYLE, encoding="utf-8")
    for i, text in enumerate(shared):
        (tmp_path / "examples" / f"shared_{i}.md").write_text(text, encoding="utf-8")

    lines = ["characters:"]
    lines += ["- name: Alice", "  sheet: docs/Alice.md"]
    if alice_voice:
        lines.append("  voice: voice/a_new_pipeline.md")
    if alice_examples:
        lines.append("  examples: examples/a.md")
    lines += ["- name: Bob", "  sheet: docs/Bob.md"]
    if bob_voice:
        lines.append("  voice: voice/b_new_pipeline.md")
    if shared:
        lines.append("shared_examples:")
        lines += [f"- examples/shared_{i}.md" for i in range(len(shared))]
    cfg = tmp_path / "party.yaml"
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cfg


ALICE_VOICE = "Alice speaks flatly, in short sentences."
BOB_VOICE = "Bob speaks in long, hedging paragraphs."
HOUSE_STYLE_2 = "The deadpan lands in its own one-line paragraph."


def _run(monkeypatch, tmp_path, *extra):
    paths = _write_fixtures(tmp_path)
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", _base_argv(paths, *extra))
    sd_narrate.main()
    return fake_stream


# ── each narrator gets what its own entry names, and nothing else ───────────


def test_declared_voice_reaches_only_its_own_narrator(monkeypatch, tmp_path):
    cfg = _declaring_party(tmp_path)
    stream = _run(monkeypatch, tmp_path, "--party-config", str(cfg))

    assert ALICE_VOICE in stream.calls[0]["system"]
    assert ALICE_VOICE not in stream.calls[1]["system"]
    assert BOB_VOICE in stream.calls[1]["system"]
    assert BOB_VOICE not in stream.calls[0]["system"]


def test_declared_examples_reach_only_their_own_narrator(monkeypatch, tmp_path):
    """The #301 bleed, structurally impossible now: Alice's examples are named
    by Alice's entry and by nothing else, so there is no path by which they
    reach Bob."""
    cfg = _declaring_party(tmp_path)
    stream = _run(monkeypatch, tmp_path, "--party-config", str(cfg))

    assert ALICE_STYLE in stream.calls[0]["system"]
    assert ALICE_STYLE not in stream.calls[1]["system"]


def test_the_filename_shape_no_longer_matters(monkeypatch, tmp_path):
    """`a_new_pipeline.md` resolves for `Alice` because the roster says so —
    not because the stem starts with the narrator's first name."""
    cfg = _declaring_party(tmp_path)
    stream = _run(monkeypatch, tmp_path, "--party-config", str(cfg))
    assert ALICE_VOICE in stream.calls[0]["system"]


def test_a_character_that_declares_nothing_gets_nothing(monkeypatch, tmp_path):
    """Stated, not inferred. Bob declares no examples, so Bob has none — and
    nothing wanders in from a file that happens to look related."""
    cfg = _declaring_party(tmp_path)
    stream = _run(monkeypatch, tmp_path, "--party-config", str(cfg))
    assert ALICE_STYLE not in stream.calls[1]["system"]


# ── shared_examples: the campaign-wide block, by declaration ────────────────


def test_shared_examples_reach_every_narrator(monkeypatch, tmp_path):
    """toee's six house-style files are a real configuration. The change is
    that a human wrote down that they are shared."""
    cfg = _declaring_party(tmp_path, shared=(HOUSE_STYLE_2,))
    stream = _run(monkeypatch, tmp_path, "--party-config", str(cfg))
    for call in stream.calls:
        assert HOUSE_STYLE_2 in call["system"]


def test_an_undeclared_file_reaches_nobody(monkeypatch, tmp_path, capsys):
    """The orphan a rename leaves behind. Under the deleted rule it joined the
    GLOBAL block and reached EVERY narrator; now it reaches none, and the run
    says so rather than letting it sit there unused and invisible."""
    cfg = _declaring_party(tmp_path)
    (tmp_path / "examples" / "grygum.md").write_text(
        "An orphan from before the rename.", encoding="utf-8")
    stream = _run(monkeypatch, tmp_path, "--party-config", str(cfg),
                  "--examples", str(tmp_path / "examples"))

    for call in stream.calls:
        assert "An orphan from before the rename." not in call["system"]
    err = capsys.readouterr().err
    assert "grygum.md" in err
    assert "declared by nobody" in err


def test_no_declarations_at_all_is_a_legitimate_mode(monkeypatch, tmp_path):
    """A campaign that declares nothing renders without specs, exactly as
    omitting --voice-dir always has. Refusing here would turn "no specs
    wanted" into an error."""
    cfg = _write_party_config(tmp_path)
    stream = _run(monkeypatch, tmp_path, "--party-config", str(cfg))
    assert len(stream.calls) == 2


# ── the pre-flight refuses before the first API call ────────────────────────


def test_a_declared_voice_file_that_is_absent_stops_the_run(monkeypatch, tmp_path, capsys):
    """The Gyrgum case. The roster names a file, the file is not there, and the
    run refuses — naming both the character and the path."""
    cfg = _declaring_party(tmp_path)
    (tmp_path / "voice" / "a_new_pipeline.md").unlink()
    paths = _write_fixtures(tmp_path)
    fake_stream = FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", fake_stream)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--party-config", str(cfg)))

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()
    assert exc.value.code == 1
    assert not fake_stream.calls          # before the first API call
    err = capsys.readouterr().err
    assert "Alice" in err
    assert "a_new_pipeline.md" in err


def test_a_narrator_missing_from_the_roster_stops_the_run(monkeypatch, tmp_path, capsys):
    """The plan and the roster disagree about a name — which is exactly what a
    rename produces, and what three earlier detectors could not see."""
    cfg = _declaring_party(tmp_path)
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("name: Bob", "name: Robert"),
                   encoding="utf-8")
    paths = _write_fixtures(tmp_path)
    monkeypatch.setattr(sd_narrate, "stream_api",
                        FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION]))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--party-config", str(cfg)))

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Bob" in err
    assert "not a character in party.yaml" in err


def test_a_character_declaring_no_voice_stops_the_run_once_others_do(
    monkeypatch, tmp_path, capsys,
):
    """Silence is only worth reporting once the campaign has started
    declaring. Bob's missing entry is a gap; a campaign with no entries at all
    is a choice (see test_no_declarations_at_all_is_a_legitimate_mode)."""
    cfg = _declaring_party(tmp_path, bob_voice=False)
    paths = _write_fixtures(tmp_path)
    monkeypatch.setattr(sd_narrate, "stream_api",
                        FakeStreamAPI([SCENE1_NARRATION, SCENE2_NARRATION]))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", _base_argv(paths, "--party-config", str(cfg)))

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Bob" in err
    assert "declares no voice file" in err


def test_a_narrator_filtered_out_of_this_render_is_not_required(monkeypatch, tmp_path):
    """The pre-flight runs AFTER --narrator/--scene filtering: a broken
    declaration for somebody not being rendered must not block the render."""
    cfg = _declaring_party(tmp_path, bob_voice=False)
    paths = _write_fixtures(tmp_path)
    stream = FakeStreamAPI([SCENE1_NARRATION])
    monkeypatch.setattr(sd_narrate, "stream_api", stream)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", _base_argv(
        paths, "--party-config", str(cfg), "--narrator", "Alice"))
    sd_narrate.main()
    assert len(stream.calls) == 1


# ── voice.py / examples.py in isolation ─────────────────────────────────────


def test_get_voice_note_is_an_exact_match():
    from session_doc.voice import get_voice_note as gvn
    voices = {"alice": "Flat."}
    assert gvn(voices, "Alice") == "Flat."
    assert gvn(voices, " ALICE ") == "Flat."
    # No first-name step, no prefix step: `Alice Smith` is a different name.
    assert gvn(voices, "Alice Smith") is None


def test_get_char_examples_is_an_exact_match():
    from session_doc.examples import get_char_examples as gce
    per_char = {"alice": "Sample."}
    assert gce(per_char, "Alice") == "Sample."
    assert gce(per_char, "Alice Smith") is None


def test_get_char_examples_survives_an_empty_narrator():
    """`parse_plan` accepts a bare `narrator:` line as "", and it reaches Pass
    5 — which used to raise IndexError and take the render down with a stack
    trace instead of a message (#301)."""
    from session_doc.examples import get_char_examples as gce
    assert gce({"alice": "x"}, "") is None
    assert gce({}, "") is None


def test_undeclared_files_lists_only_orphans(tmp_path):
    from session_doc.examples import undeclared_files
    d = tmp_path / "examples"
    d.mkdir()
    kept = d / "alice.md"
    kept.write_text("x", encoding="utf-8")
    orphan = d / "grygum.md"
    orphan.write_text("x", encoding="utf-8")
    (d / "_genre.md").write_text("x", encoding="utf-8")

    found = undeclared_files(d, [kept])
    assert found == [orphan]


def test_undeclared_files_tolerates_a_missing_directory():
    from session_doc.examples import undeclared_files
    assert undeclared_files(None, []) == []
    assert undeclared_files(Path("/nonexistent/nowhere"), []) == []


def test_load_voice_files_still_scans_a_directory(tmp_path):
    """Kept deliberately: `polish.py` enumerates a directory, and the orphan
    report needs the census. It is no longer how a narrator finds its spec."""
    d = tmp_path / "voice"
    d.mkdir()
    (d / "alice_voice.md").write_text("Flat.", encoding="utf-8")
    (d / "_genre.md").write_text("shared", encoding="utf-8")
    voices = load_voice_files(d)
    assert voices == {"alice": "Flat."}
