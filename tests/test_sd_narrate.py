"""Tests for sd_narrate.py's --batch path (spec 004-claude-api-batch, T020).

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
