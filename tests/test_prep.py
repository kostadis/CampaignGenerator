"""Tests for campaignlib, prep.py, and session_doc logic."""

import asyncio
import io
import sys
import pytest
from pathlib import Path

from fastapi import Request
from starlette.responses import PlainTextResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import campaignlib
from pipelines.session_prep import prep, transform
import session_doc
from server.routers import prep as prep_router
from server.platform_config_service import ResolvedSelection


def _request(path: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [],
    })

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_workspace(tmp_path):
    """Minimal workspace with absolute paths in config."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "world_state.md").write_text("# World\nSome lore.", encoding="utf-8")
    (docs / "mechanics.md").write_text("# Mechanics\nSome rules.", encoding="utf-8")
    (tmp_path / "system_prompt.md").write_text("You are a DM assistant.", encoding="utf-8")

    (tmp_path / "config.yaml").write_text(f"""\
system_prompt: {tmp_path}/system_prompt.md
log_dir: {tmp_path}/logs
agents:
  lore_oracle: {tmp_path}/agents/lore_oracle.md
  encounter_architect: {tmp_path}/agents/encounter_architect.md
  voice_keeper: {tmp_path}/agents/voice_keeper.md
documents:
  - label: world_state
    path: {docs}/world_state.md
  - label: mechanics
    path: {docs}/mechanics.md
""", encoding="utf-8")
    return tmp_path


@pytest.fixture
def tmp_workspace_relative(tmp_path):
    """Workspace where doc paths are relative to the config file."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "world_state.md").write_text("# World\nRelative lore.", encoding="utf-8")
    (tmp_path / "system_prompt.md").write_text("System prompt.", encoding="utf-8")

    (tmp_path / "config.yaml").write_text("""\
system_prompt: system_prompt.md
log_dir: logs
agents:
  lore_oracle: agents/lore_oracle.md
  encounter_architect: agents/encounter_architect.md
  voice_keeper: agents/voice_keeper.md
documents:
  - label: world_state
    path: docs/world_state.md
""", encoding="utf-8")
    return tmp_path


# ── campaignlib.load_config ───────────────────────────────────────────────────

def test_load_config_returns_dict_and_path(tmp_workspace):
    config, base_dir = campaignlib.load_config(str(tmp_workspace / "config.yaml"))
    assert isinstance(config, dict)
    assert base_dir == tmp_workspace


def test_load_config_missing_file():
    with pytest.raises(FileNotFoundError):
        campaignlib.load_config("/nonexistent/path/config.yaml")


# ── campaignlib.load_file ─────────────────────────────────────────────────────

def test_load_file_absolute(tmp_workspace):
    content = campaignlib.load_file(str(tmp_workspace / "docs" / "world_state.md"))
    assert "Some lore" in content


def test_load_file_relative_resolved_against_base(tmp_workspace):
    content = campaignlib.load_file("docs/world_state.md", base_dir=tmp_workspace)
    assert "Some lore" in content


def test_load_file_missing_exits():
    with pytest.raises(SystemExit):
        campaignlib.load_file("/nonexistent/file.md")


def test_load_file_relative_missing_exits(tmp_workspace):
    with pytest.raises(SystemExit):
        campaignlib.load_file("docs/missing.md", base_dir=tmp_workspace)


# ── campaignlib.assemble_docs ─────────────────────────────────────────────────

def test_assemble_docs_includes_content(tmp_workspace):
    config, base_dir = campaignlib.load_config(str(tmp_workspace / "config.yaml"))
    result = campaignlib.assemble_docs(config, ["world_state", "mechanics"], base_dir)
    assert "## world_state" in result
    assert "Some lore" in result
    assert "## mechanics" in result
    assert "Some rules" in result


def test_assemble_docs_skips_doc_with_no_path(tmp_path):
    (tmp_path / "world_state.md").write_text("Lore.", encoding="utf-8")
    config = {
        "documents": [
            {"label": "world_state", "path": str(tmp_path / "world_state.md")},
            {"label": "mechanics"},
        ]
    }
    result = campaignlib.assemble_docs(config, ["world_state", "mechanics"])
    assert "## world_state" in result
    assert "## mechanics" not in result


def test_assemble_docs_unknown_label_exits(tmp_workspace):
    config, base_dir = campaignlib.load_config(str(tmp_workspace / "config.yaml"))
    with pytest.raises(SystemExit):
        campaignlib.assemble_docs(config, ["nonexistent"], base_dir)


def test_assemble_docs_relative_paths(tmp_workspace_relative):
    config, base_dir = campaignlib.load_config(str(tmp_workspace_relative / "config.yaml"))
    result = campaignlib.assemble_docs(config, ["world_state"], base_dir)
    assert "Relative lore" in result


# ── campaignlib.find_default_config ──────────────────────────────────────────

def test_find_default_config_prefers_cwd(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = campaignlib.find_default_config("/some/script.py")
    assert result == str(tmp_path / "config.yaml")


def test_find_default_config_falls_back_to_script_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no config.yaml here
    script = "/home/user/CampaignGenerator/npc_table.py"
    result = campaignlib.find_default_config(script)
    assert result == "/home/user/CampaignGenerator/config/config.yaml"


# ── prep.assemble_user_prompt ─────────────────────────────────────────────────

def test_assemble_user_prompt_includes_beat(tmp_workspace):
    config, base_dir = campaignlib.load_config(str(tmp_workspace / "config.yaml"))
    result = prep.assemble_user_prompt(config, "The party enters the dungeon", base_dir)
    assert "The party enters the dungeon" in result
    assert "## Session Beat" in result


def test_assemble_user_prompt_includes_docs(tmp_workspace):
    config, base_dir = campaignlib.load_config(str(tmp_workspace / "config.yaml"))
    result = prep.assemble_user_prompt(config, "A beat", base_dir)
    assert "## world_state" in result
    assert "Some lore" in result


# ── prep.parse_session_beats ──────────────────────────────────────────────────

def test_parse_beats_period():
    beats = prep.parse_session_beats("1. Travel\n2. Confront\n3. Reveal")
    assert beats == ["Travel", "Confront", "Reveal"]


def test_parse_beats_paren():
    assert prep.parse_session_beats("1) First\n2) Second") == ["First", "Second"]


def test_parse_beats_colon():
    assert prep.parse_session_beats("1: First\n2: Second") == ["First", "Second"]


def test_parse_beats_multiline():
    beats = prep.parse_session_beats("1. First beat\n   continued here\n2. Second beat")
    assert len(beats) == 2
    assert "continued here" in beats[0]


def test_parse_beats_empty_returns_empty():
    assert prep.parse_session_beats("") == []


def test_parse_beats_single():
    assert prep.parse_session_beats("1. Only one beat") == ["Only one beat"]


# ── prep.py --batch: sequential one-item batches, order preserved ───────────
# prep's 5 stream_api call sites (3 chained pipeline stages, run_single,
# run_session's single-mode loop) are order-dependent — Encounter Architect
# reads the Lore Oracle's response, Voice Keeper reads the Architect's — so
# --batch must never group them. These tests patch prep's own `run_single_batch`
# / `stream_api` / `client_from_args` bindings directly (prep imports them by
# name, same pattern as the existing test_sd_plan_writes_plan_md above) and
# assert call order + per-call arguments rather than grouping.

class _FakeRunSingleBatch:
    def __init__(self, responses=None, fail_at=None):
        self.calls = []
        self._responses = responses
        self._fail_at = fail_at

    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        idx = len(self.calls)
        self.calls.append({"system": system, "user": user, "model": model, "max_tokens": max_tokens})
        if self._fail_at is not None and idx == self._fail_at:
            raise RuntimeError("batch item 'single' did not succeed: status=errored error=boom")
        if self._responses is not None:
            return self._responses[idx]
        return f"[batch-{idx}]"


class _FakeStreamAPI:
    def __init__(self):
        self.calls = []

    def __call__(self, client, system, user, model, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model, **kwargs})
        return "[stream response]"


@pytest.fixture
def pipeline_workspace(tmp_path):
    """Workspace with real agent prompt files so run_pipeline_encounter's
    three load_repo_file() calls succeed."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "world_state.md").write_text("# World\nSome lore.", encoding="utf-8")
    (tmp_path / "system_prompt.md").write_text("You are a DM assistant.", encoding="utf-8")

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "lore_oracle.md").write_text("You are the Lore Oracle.", encoding="utf-8")
    (agents_dir / "encounter_architect.md").write_text("You are the Encounter Architect.", encoding="utf-8")
    (agents_dir / "voice_keeper.md").write_text("You are the Voice Keeper.", encoding="utf-8")

    (tmp_path / "config.yaml").write_text(f"""\
system_prompt: {tmp_path}/system_prompt.md
log_dir: {tmp_path}/logs
agents:
  lore_oracle: {agents_dir}/lore_oracle.md
  encounter_architect: {agents_dir}/encounter_architect.md
  voice_keeper: {agents_dir}/voice_keeper.md
documents:
  - label: world_state
    path: {docs}/world_state.md
""", encoding="utf-8")
    return tmp_path


def test_batch_flag_routes_pipeline_stages_through_sequential_one_item_batches(
    monkeypatch, pipeline_workspace
):
    """--mode pipeline, --batch: all 3 stages route through run_single_batch,
    in order, each fed the previous stage's response (never grouped)."""
    fake = _FakeRunSingleBatch(responses=["oracle output", "architect output", "voice output"])
    monkeypatch.setattr(prep, "run_single_batch", fake)
    monkeypatch.setattr(prep, "client_from_args", lambda args: object())

    monkeypatch.setattr(sys, "argv", [
        "prep",
        "--config", str(pipeline_workspace / "config.yaml"),
        "--mode", "pipeline",
        "--beat", "The party enters the dungeon",
        "--no-log",
        "--batch",
    ])
    prep.main()

    assert len(fake.calls) == 3
    assert fake.calls[0]["system"] == "You are the Lore Oracle."
    assert fake.calls[1]["system"] == "You are the Encounter Architect."
    assert fake.calls[2]["system"] == "You are the Voice Keeper."
    # Dependency chaining: each stage's user prompt carries the prior stage's output.
    assert "oracle output" in fake.calls[1]["user"]
    assert "architect output" in fake.calls[2]["user"]
    # max_tokens ceiling matches stream_api's own default in both branches.
    assert all(c["max_tokens"] == 8096 for c in fake.calls)


def test_batch_flag_routes_session_beats_sequentially(monkeypatch, pipeline_workspace, tmp_path):
    """--session with --batch: each beat is its own one-item batch, submitted
    in outline order (call site inside run_session's single-mode loop)."""
    fake = _FakeRunSingleBatch(responses=["beat1 result", "beat2 result"])
    monkeypatch.setattr(prep, "run_single_batch", fake)
    monkeypatch.setattr(prep, "client_from_args", lambda args: object())

    session_file = tmp_path / "outline.md"
    session_file.write_text("1. First beat\n2. Second beat\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", [
        "prep",
        "--config", str(pipeline_workspace / "config.yaml"),
        "--session", str(session_file),
        "--mode", "single",
        "--no-log",
        "--batch",
    ])
    prep.main()

    assert len(fake.calls) == 2
    assert "First beat" in fake.calls[0]["user"]
    assert "Second beat" in fake.calls[1]["user"]


def test_batch_item_failure_exits_nonzero(monkeypatch, pipeline_workspace, capsys):
    """A non-succeeding batch item (run_single_batch raises RuntimeError) must
    print `Error: batch item failed: <e>` to stderr and exit non-zero."""
    fake = _FakeRunSingleBatch(fail_at=0)
    monkeypatch.setattr(prep, "run_single_batch", fake)
    monkeypatch.setattr(prep, "client_from_args", lambda args: object())

    monkeypatch.setattr(sys, "argv", [
        "prep",
        "--config", str(pipeline_workspace / "config.yaml"),
        "--mode", "single",
        "--beat", "The party enters the dungeon",
        "--no-log",
        "--batch",
    ])
    with pytest.raises(SystemExit) as exc_info:
        prep.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: batch item failed:" in captured.err


def test_default_no_batch_path_uses_stream_api_only(monkeypatch, pipeline_workspace):
    """FR-011 regression guard: without --batch, prep must still call
    stream_api exclusively and never touch run_single_batch."""
    fake_stream = _FakeStreamAPI()
    fake_batch = _FakeRunSingleBatch()
    monkeypatch.setattr(prep, "stream_api", fake_stream)
    monkeypatch.setattr(prep, "run_single_batch", fake_batch)
    monkeypatch.setattr(prep, "client_from_args", lambda args: object())

    monkeypatch.setattr(sys, "argv", [
        "prep",
        "--config", str(pipeline_workspace / "config.yaml"),
        "--mode", "single",
        "--beat", "The party enters the dungeon",
        "--no-log",
    ])
    prep.main()

    assert len(fake_stream.calls) == 1
    assert len(fake_batch.calls) == 0


def test_codex_prep_preserves_request_boundary_and_output_path(
    monkeypatch, pipeline_workspace, tmp_path
):
    """A Codex prep request keeps the selected model and writes the normal
    single-beat artifact at the caller-selected path."""
    fake_stream = _FakeStreamAPI()
    monkeypatch.setattr(prep, "stream_api", fake_stream)
    monkeypatch.setattr(prep, "client_from_args", lambda args: object())
    output = tmp_path / "prep.md"

    monkeypatch.setattr(sys, "argv", [
        "prep",
        "--config", str(pipeline_workspace / "config.yaml"),
        "--mode", "single",
        "--beat", "The party enters the dungeon",
        "--backend", "codex-cli",
        "--model", "gpt-5-codex",
        "--output", str(output),
        "--no-log",
    ])
    prep.main()

    assert len(fake_stream.calls) == 1
    assert fake_stream.calls[0]["model"] == "gpt-5-codex"
    assert "The party enters the dungeon" in fake_stream.calls[0]["user"]
    assert output.read_text(encoding="utf-8") == "[stream response]\n"


# ── transform.py --batch: single call via run_single_batch ──────────────────

def test_transform_batch_flag_routes_through_run_single_batch(monkeypatch, capsys):
    fake = _FakeRunSingleBatch(responses=["1. Outline beat one\n2. Outline beat two"])
    monkeypatch.setattr(transform, "run_single_batch", fake)
    monkeypatch.setattr(transform, "client_from_args", lambda args: object())

    # `input` is positional and expected to be a file path; omit it and feed
    # the dossier via stdin instead, matching transform's own no-path mode.
    monkeypatch.setattr(sys, "argv", ["transform", "--batch"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("A dossier of campaign notes."))

    transform.main()

    assert len(fake.calls) == 1
    assert fake.calls[0]["user"] == "A dossier of campaign notes."
    assert fake.calls[0]["max_tokens"] == 1024


def test_transform_batch_failure_exits_nonzero(monkeypatch, capsys):
    fake = _FakeRunSingleBatch(fail_at=0)
    monkeypatch.setattr(transform, "run_single_batch", fake)
    monkeypatch.setattr(transform, "client_from_args", lambda args: object())

    monkeypatch.setattr(sys, "argv", ["transform", "--batch"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("A dossier of campaign notes."))

    with pytest.raises(SystemExit) as exc_info:
        transform.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: batch item failed:" in captured.err


def test_transform_default_no_batch_path_uses_stream_api_only(monkeypatch):
    fake_stream = _FakeStreamAPI()
    fake_batch = _FakeRunSingleBatch()
    monkeypatch.setattr(transform, "stream_api", fake_stream)
    monkeypatch.setattr(transform, "run_single_batch", fake_batch)
    monkeypatch.setattr(transform, "client_from_args", lambda args: object())

    monkeypatch.setattr(sys, "argv", ["transform"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("A dossier of campaign notes."))

    transform.main()

    assert len(fake_stream.calls) == 1
    assert len(fake_batch.calls) == 0


def test_codex_transform_preserves_request_boundary_and_output_path(
    monkeypatch, tmp_path
):
    """Transform's Codex call receives the dossier unchanged and preserves
    the explicit output destination, including a new parent directory."""
    fake_stream = _FakeStreamAPI()
    monkeypatch.setattr(transform, "stream_api", fake_stream)
    monkeypatch.setattr(transform, "client_from_args", lambda args: object())
    dossier = tmp_path / "dossier.md"
    dossier.write_text("A dossier of campaign notes.", encoding="utf-8")
    output = tmp_path / "artifacts" / "outline.md"

    monkeypatch.setattr(sys, "argv", [
        "transform", str(dossier),
        "--backend", "codex-cli",
        "--model", "gpt-5-codex",
        "--output", str(output),
    ])
    transform.main()

    assert len(fake_stream.calls) == 1
    assert fake_stream.calls[0]["model"] == "gpt-5-codex"
    assert fake_stream.calls[0]["user"] == "A dossier of campaign notes."
    assert output.read_text(encoding="utf-8") == "[stream response]\n"


def test_transform_route_forwards_selected_dossier_and_codex_without_inventing_model(
    monkeypatch, tmp_path
):
    """The Session Prep transform face is an explicit, human-gated launch.

    A Codex subscription owns its model default.  When the selector resolves
    an omitted model the route must therefore leave ``--model`` out of argv,
    while preserving the selected dossier and review output path.  This calls
    the route endpoint directly so the assertion stays bounded even when the
    full application's TestClient startup is unavailable.
    """
    dossier = tmp_path / "dossier.md"
    output = tmp_path / "review" / "outline.md"
    captured = {}

    def capture(cmd):
        captured["cmd"] = cmd
        return PlainTextResponse("captured")

    def resolve(_request, *, request_model=None, **_kwargs):
        return ResolvedSelection(
            model=request_model,
            backend="codex-cli",
            model_origin="request" if request_model else "platform",
            backend_origin="platform",
        )

    monkeypatch.setattr(prep_router, "_sse_response", capture, raising=False)
    monkeypatch.setattr(prep_router, "resolve_selection", resolve, raising=False)
    route = next(
        route.endpoint
        for route in prep_router.router.routes
        if getattr(route, "path", "") == "/run/transform"
    )

    result = asyncio.run(route(
        _request("/run/transform"),
        input=str(dossier),
        output=str(output),
        single=False,
        model=None,
    ))
    assert result.status_code == 200
    cmd = captured["cmd"]
    assert "transform" in cmd[0]
    assert str(dossier) in cmd
    assert cmd[cmd.index("--output") + 1] == str(output)
    assert cmd[cmd.index("--backend") + 1] == "codex-cli"
    assert "--model" not in cmd


def test_transform_route_forwards_explicit_codex_model_without_auto_advance(
    monkeypatch, tmp_path
):
    """Typing a model forwards it, but transform still only writes its output."""
    captured = {}

    def capture(cmd):
        captured["cmd"] = cmd
        return PlainTextResponse("captured")

    def resolve(_request, *, request_model=None, **_kwargs):
        return ResolvedSelection(
            model=request_model,
            backend="codex-cli",
            model_origin="request",
            backend_origin="platform",
        )

    monkeypatch.setattr(prep_router, "_sse_response", capture, raising=False)
    monkeypatch.setattr(prep_router, "resolve_selection", resolve, raising=False)
    route = next(
        route.endpoint
        for route in prep_router.router.routes
        if getattr(route, "path", "") == "/run/transform"
    )

    result = asyncio.run(route(
        _request("/run/transform"),
        input="docs/dossier.md",
        output="docs/prep/outline.md",
        single=True,
        model="gpt-5-codex",
    ))
    assert result.status_code == 200
    cmd = captured["cmd"]
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"
    assert "--single" in cmd
    # The route does not run prep or mark any downstream stage approved.
    assert "transform" in cmd[0]
    assert "--session" not in cmd and "--beat" not in cmd


# ── Fixtures for session_doc tests ───────────────────────────────────────────

RECAP_WITH_SCENES = """\
## Summary

The party climbed the mountain.

## Scenes

### The Stone Giants
The party encountered three stone giants blocking the pass.
Vukradin used intimidation to drive them back.

### The Whispering Glacier
Soma transformed into an eagle to scout ahead.
Ice cracked beneath Brewbarry's feet.

### Carving a Path
The party reached the summit. Soma reshaped the mountain.
Brewbarry held the rear as rocks fell.

## NPCs

- Stone Giant Leader
"""

# ── session_doc.extract_scene_text ────────────────────────────────────────────

def test_extract_scene_text_returns_target_scene():
    text = session_doc.extract_scene_text(RECAP_WITH_SCENES, "The Stone Giants")
    assert "Vukradin used intimidation" in text
    assert "stone giants blocking the pass" in text


def test_extract_scene_text_excludes_adjacent_scenes():
    """Sending adjacent scene content is the 'too much data' bug (Bug 7)."""
    text = session_doc.extract_scene_text(RECAP_WITH_SCENES, "The Stone Giants")
    assert "Soma transformed" not in text
    assert "Whispering Glacier" not in text
    assert "Carving a Path" not in text


def test_extract_scene_text_middle_scene_excludes_neighbours():
    text = session_doc.extract_scene_text(RECAP_WITH_SCENES, "The Whispering Glacier")
    assert "eagle to scout ahead" in text
    assert "Vukradin used intimidation" not in text  # from previous scene
    assert "Soma reshaped the mountain" not in text  # from next scene


def test_extract_scene_text_last_scene():
    text = session_doc.extract_scene_text(RECAP_WITH_SCENES, "Carving a Path")
    assert "Soma reshaped the mountain" in text
    assert "Ice cracked" not in text  # from Glacier


def test_extract_scene_text_unknown_scene_returns_empty():
    """Empty result means the extraction prompt will have no scope — hallucination risk."""
    text = session_doc.extract_scene_text(RECAP_WITH_SCENES, "Nonexistent Scene")
    assert text == ""


def test_extract_scene_text_case_insensitive():
    text = session_doc.extract_scene_text(RECAP_WITH_SCENES, "the stone giants")
    assert "Vukradin used intimidation" in text


def test_extract_scene_text_no_scenes_section():
    recap_no_scenes = "## Summary\n\nThe party did things.\n\n## NPCs\n\n- Someone\n"
    text = session_doc.extract_scene_text(recap_no_scenes, "The Stone Giants")
    assert text == ""


# ── sd_plan.main writes plan.md ───────────────────────────────────────────────

def test_sd_plan_writes_plan_md(tmp_path, monkeypatch):
    """sd_plan.py is the post-Phase-5 successor to --plan-only: it must
    persist plan.md so per-scene Narrate can reuse it.

    Regression on the old code: the save block once sat after
    `if args.plan_only: return`, so Plan & Check produced narrators+focus
    in memory but never wrote them to disk — per-scene Narrate then
    re-ran Pass 3 from scratch. The new sd_plan.py always writes.
    """
    import session_doc.sd_plan as sd_plan

    sx_dir = tmp_path / "scene_extractions"
    sx_dir.mkdir()
    (sx_dir / "01_stone_giants.md").write_text(
        "---\nscene: The Stone Giants\n---\n\nVukradin stared down the giants.\n",
        encoding="utf-8",
    )
    (sx_dir / "02_glacier.md").write_text(
        "---\nscene: The Whispering Glacier\n---\n\nSoma scouted as an eagle.\n",
        encoding="utf-8",
    )

    out_path = tmp_path / "plan.md"

    fake_plan = (
        "## Section 1\n"
        "narrator: Vukradin\n"
        "chunks: 1-1\n"
        "scene: The Stone Giants\n"
        "focus: holding the line against the giants\n\n"
        "## Section 2\n"
        "narrator: Soma\n"
        "chunks: 2-2\n"
        "scene: The Whispering Glacier\n"
        "focus: scouting the route ahead\n"
    )

    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(sd_plan, "stream_api", lambda *a, **kw: fake_plan)

    monkeypatch.setattr(
        sys, "argv",
        [
            "sd_plan.py",
            "--scene-extractions", str(sx_dir),
            "--characters", "Vukradin, Soma",
            "--out", str(out_path),
        ],
    )

    sd_plan.main()

    assert out_path.exists(), "plan.md must be written"
    plan_text = out_path.read_text(encoding="utf-8")
    assert "narrator: Vukradin" in plan_text
    assert "narrator: Soma" in plan_text
    assert "focus: holding the line against the giants" in plan_text
    assert "focus: scouting the route ahead" in plan_text


# ── session_doc.parse_plan ────────────────────────────────────────────────────

PLAN_SECTION_FORMAT = """\
## Section 1
narrator: Vukradin
chunks: 1
focus: Faces the giants.

## Section 2
narrator: Soma
chunks: 2
focus: Reshapes the mountain.
"""

PLAN_SCENE_FORMAT = """\
## Scene 1
narrator: Vukradin
chunks: 1
scene: The Stone Giants
focus: Faces the giants.

## Scene 2
narrator: Soma
chunks: 2
scene: Carving a Path
focus: Reshapes the mountain.
"""


def test_parse_plan_section_format():
    sections = session_doc.parse_plan(PLAN_SECTION_FORMAT, total_chunks=2)
    assert len(sections) == 2
    assert sections[0]["narrator"] == "Vukradin"
    assert sections[1]["narrator"] == "Soma"


def test_parse_plan_scene_format():
    """Bug 2 regression: parse_plan must handle ## Scene N headings."""
    sections = session_doc.parse_plan(PLAN_SCENE_FORMAT, total_chunks=2)
    assert len(sections) == 2
    assert sections[0]["scene"] == "The Stone Giants"
    assert sections[1]["scene"] == "Carving a Path"


def test_parse_plan_chunk_range():
    plan = "## Section 1\nnarrator: A\nchunks: 1-2\nfocus: x\n"
    sections = session_doc.parse_plan(plan, total_chunks=2)
    assert sections[0]["chunk_start"] == 1
    assert sections[0]["chunk_end"] == 2


def test_parse_plan_chunk_clamped_to_total():
    plan = "## Section 1\nnarrator: A\nchunks: 5\nfocus: x\n"
    sections = session_doc.parse_plan(plan, total_chunks=2)
    assert sections[0]["chunk_start"] == 2
    assert sections[0]["chunk_end"] == 2


def test_parse_plan_skips_blocks_with_no_narrator():
    plan = "## Scene 1\nchunks: 1\nfocus: x\n\n## Scene 2\nnarrator: B\nchunks: 2\nfocus: y\n"
    sections = session_doc.parse_plan(plan, total_chunks=2)
    assert len(sections) == 1
    assert sections[0]["narrator"] == "B"


# ── session_doc.build_narrate_system — dialogue handling ─────────────────────

def test_chunk_mode_mandates_dialogue():
    """Chunk mode: strong dialogue mandate (full sessions usually have dialogue)."""
    system = session_doc.build_narrate_system(None, scene=None)
    assert "THE DIALOGUE IS THE STORY" in system
    assert "DO NOT invent" not in system


def test_scene_mode_dialogue_is_conditional():
    """Scene mode: dialogue is conditional — don't mandate it when it may not exist."""
    system = session_doc.build_narrate_system(None, scene="The Whispering Glacier")
    assert "THE DIALOGUE IS THE STORY" not in system
    assert "USE DIALOGUE IF PRESENT" in system
    assert "DO NOT invent" in system


def test_scene_mode_no_dialogue_instruction_allows_action_only():
    """Scene mode prompt must explicitly allow action-beat-only narration."""
    system = session_doc.build_narrate_system(None, scene="The Glacier Crossing")
    assert "action beats" in system.lower() or "action beat" in system.lower()
    assert "no dialogue" in system.lower() or "no verbatim" in system.lower() or "no dialogue" in system.lower()


# ── scene index filtering (the --scene flag logic) ───────────────────────────

def _make_sections():
    return [
        {"narrator": "Vukradin", "chunk_start": 1, "chunk_end": 1,
         "scene": "The Stone Giants", "focus": "a"},
        {"narrator": "Soma",     "chunk_start": 1, "chunk_end": 1,
         "scene": "The Glacier",    "focus": "b"},
        {"narrator": "Brewbarry","chunk_start": 2, "chunk_end": 2,
         "scene": "Carving a Path", "focus": "c"},
    ]

def test_scene_filter_selects_correct_sections():
    sections = _make_sections()
    wanted = [3, 1]
    result = [(n, sections[n - 1]) for n in wanted]
    narrators = [s["narrator"] for _, s in result]
    assert narrators == ["Brewbarry", "Vukradin"]

def test_scene_filter_preserves_original_index():
    """The original 1-based index must be preserved so per-scene filenames stay consistent."""
    sections = _make_sections()
    result = [(n, sections[n - 1]) for n in [2]]
    i, s = result[0]
    assert i == 2
    assert s["narrator"] == "Soma"

def test_scene_filter_single():
    sections = _make_sections()
    result = [(n, sections[n - 1]) for n in [3]]
    assert len(result) == 1
    assert result[0][1]["narrator"] == "Brewbarry"


# ── session_doc.estimate_narration_tokens ────────────────────────────────────

def test_estimate_uses_higher_expansion_for_dialogue():
    with_dialogue    = '**Scene**\nVukradin: "We do not leave."\nHe stood firm.' * 10
    without_dialogue = '**Scene**\nThe glacier stretched ahead. Cold wind. Silence.' * 10
    assert session_doc.estimate_narration_tokens(with_dialogue) > \
           session_doc.estimate_narration_tokens(without_dialogue)

def test_estimate_rounds_to_nearest_250():
    result = session_doc.estimate_narration_tokens("x" * 400)
    assert result % 250 == 0

def test_estimate_minimum_500():
    assert session_doc.estimate_narration_tokens("short") == 500

def test_estimate_grows_with_content_length():
    short = "**Beat**\nSomething happened. The party moved on carefully.\n" * 5
    long  = "**Beat**\nSomething happened. The party moved on carefully.\n" * 50
    assert session_doc.estimate_narration_tokens(long) > \
           session_doc.estimate_narration_tokens(short)


# ── campaignlib.save_log ────────────────────────────────────────────────────

def test_save_log_creates_file(tmp_path):
    log_file = campaignlib.save_log(
        str(tmp_path), [("Heading", "Content here.")], stem="test"
    )
    assert log_file.exists()
    assert log_file.name.endswith("_test.md")


def test_save_log_contains_sections(tmp_path):
    log_file = campaignlib.save_log(
        str(tmp_path),
        [("System Prompt", "You are a DM."), ("Response", "The encounter begins.")],
        stem="session",
    )
    text = log_file.read_text(encoding="utf-8")
    assert "## System Prompt" in text
    assert "You are a DM." in text
    assert "## Response" in text
    assert "The encounter begins." in text


def test_save_log_creates_directory(tmp_path):
    nested = tmp_path / "deep" / "logs"
    log_file = campaignlib.save_log(str(nested), [("A", "B")])
    assert log_file.exists()
    assert nested.exists()


# ── session_doc.extract_character_roster ────────────────────────────────────

PARTY_TEXT = """\
## Soma
**Tortle Druid 5, Player: Wade**

Some backstory about Soma.

## Vukradin
**Goliath Barbarian 5, Player: Kostadis**

Some backstory about Vukradin.

## Valphine
**Elf Wizard 5**

No player listed.
"""


def test_extract_character_roster_basic():
    roster = session_doc.extract_character_roster(PARTY_TEXT)
    assert "Soma (Wade): Tortle Druid 5" in roster
    assert "Vukradin (Kostadis): Goliath Barbarian 5" in roster


def test_extract_character_roster_no_player():
    """Characters without Player: field but with valid class line are included."""
    text = "## Valphine\n**Elf Wizard 5, Bladesinger**\n"
    roster = session_doc.extract_character_roster(text)
    assert "Valphine: Elf Wizard 5, Bladesinger" in roster
    assert "Valphine (" not in roster


def test_extract_character_roster_empty():
    assert session_doc.extract_character_roster("") == ""


def test_extract_character_roster_multi_player():
    text = "## Soma\n**Tortle Druid 5, Player: Wade/Kostadis**\n"
    roster = session_doc.extract_character_roster(text)
    assert "Wade/Kostadis" in roster


# ── campaignlib.extract_player_character_map ───────────────────────────────

def test_extract_player_character_map_basic():
    import campaignlib
    m = campaignlib.extract_player_character_map(PARTY_TEXT)
    assert m["Wade"] == "Soma"
    assert m["Kostadis"] == "Vukradin"
    # Valphine has no player → no entry for her
    assert "Valphine" not in m


def test_extract_player_character_map_multi_player():
    import campaignlib
    text = "## Soma\n**Tortle Druid 5, Player: Wade/Kostadis**\n"
    m = campaignlib.extract_player_character_map(text)
    assert m == {"Wade": "Soma", "Kostadis": "Soma"}


def test_extract_player_character_map_empty():
    import campaignlib
    assert campaignlib.extract_player_character_map("") == {}


def test_extract_player_character_map_new_format():
    """party.py writes ### headings with `**Player:** Name` in a pipe-separated info line."""
    import campaignlib
    text = (
        "### Daz — Wizard (Evoker) 7\n"
        "**Class/Level:** Wizard 7 | **Species:** Elf | **Player:** Mike Hall\n"
        "\n"
        "### Vukradin\n"
        "**Class/Level:** Bard 5 | **Species:** Aasimar | **Player:** kostadis1\n"
    )
    m = campaignlib.extract_player_character_map(text)
    assert m["Mike Hall"] == "Daz"
    assert m["kostadis1"] == "Vukradin"


def test_extract_player_character_map_first_name_alias():
    """A multi-token player name also registers under its first name when unambiguous."""
    import campaignlib
    text = (
        "### Daz\n"
        "**Class/Level:** Wizard 7 | **Player:** Mike Hall\n"
        "\n"
        "### Thorin\n"
        "**Class/Level:** Fighter 7 | **Player:** Joe Beda\n"
    )
    m = campaignlib.extract_player_character_map(text)
    assert m["Mike Hall"] == "Daz"
    assert m["Mike"] == "Daz"
    assert m["Joe Beda"] == "Thorin"
    assert m["Joe"] == "Thorin"


def test_extract_player_character_map_first_name_collision():
    """If two players share a first name, drop the ambiguous alias."""
    import campaignlib
    text = (
        "### Daz\n"
        "**Class/Level:** Wizard 7 | **Player:** Mike Hall\n"
        "\n"
        "### Thorin\n"
        "**Class/Level:** Fighter 7 | **Player:** Mike Smith\n"
    )
    m = campaignlib.extract_player_character_map(text)
    assert m["Mike Hall"] == "Daz"
    assert m["Mike Smith"] == "Thorin"
    assert "Mike" not in m


def test_extract_player_character_map_skips_placeholders():
    """`(Not specified)` / `[not specified]` / `N/A` mean no player — must not be mapped."""
    import campaignlib
    text = (
        "### Grygum\n"
        "**Class/Level:** Cleric 7 | **Species:** Half-Orc | **Player:** (Not specified)\n"
        "\n"
        "### Zalthir\n"
        "**Class/Level:** Monk 7 | **Species:** Dragonborn | **Player:** [not specified]\n"
        "\n"
        "### Thorin\n"
        "**Class/Level:** Fighter 7 | **Species:** Dwarf | **Player:** N/A\n"
    )
    m = campaignlib.extract_player_character_map(text)
    assert m == {}


# ── Issue #260: three previously-broken layouts (unified onto party_md) ─────


def test_extract_player_character_map_phandalin_unlabeled_pipe():
    """Phandalin's `| Player: X**` shape used to return {} — the legacy branch
    required `, Player:` and this uses `| Player:` instead."""
    import campaignlib
    text = (
        "### Brewbarry\n"
        "**Barbarian 6 (Path of the Giant) | Goliath | Player: Stephane Boudreau**\n"
        "\n"
        "### Soma\n"
        "**Druid 6 (Circle of the Moon) | Tortle | Player: Wade Brown**\n"
    )
    m = campaignlib.extract_player_character_map(text)
    assert m["Stephane Boudreau"] == "Brewbarry"
    assert m["Wade Brown"] == "Soma"


def test_extract_player_character_map_hillsfar_em_dash():
    """Hillsfar's `**Class N** — player: X` shape used to return {} — that
    branch required the line to END with `**`; here player sits outside it."""
    import campaignlib
    text = (
        "### Akritas\n**High Elf Ranger 11** — player: kostadis1\n"
        "\n"
        "### Bramgrim Stoutale\n**Hill Dwarf Life Cleric 11** — player: kostadis1\n"
    )
    m = campaignlib.extract_player_character_map(text)
    assert m["kostadis1"] == "Bramgrim Stoutale"


def test_extract_player_character_map_oota_heading_embedded():
    """out-of-the-abyss carries the player field inside the `###` heading
    itself, `·`-separated — the old parser only ever scanned body lines."""
    import campaignlib
    text = (
        "### Zalthir — Monk 8 (Warrior of Shadow) · Bronze Dragonborn · Player: Gabe\n"
        "### Thorin — Fighter 8 (Battle Master) · Dwarf (Giant Foundling) · Player: Joe Beda\n"
    )
    m = campaignlib.extract_player_character_map(text)
    assert m["Gabe"] == "Zalthir"
    assert m["Joe Beda"] == "Thorin"


# ── campaignlib.player_map_from_config (issue #265) ─────────────────────────
#
# Per the GM ruling in docs/design/PartyRosterCanonicalFormat.md: the D&D
# Beyond sheet is canonical, party.yaml only references it. Fixtures are
# built entirely under tmp_path — never against ~/src/campaigns.

def _pmfc_write_sheet(tmp_path, filename, *, name, player, species="Elf",
                       class_level="Wizard 7"):
    """A sheet whose `player:` line says ``player``.

    Feature 009 stopped reading that line — it is a rendered copy this pipeline
    writes, and reading a copy back makes it an authority (FR-023). The
    fixtures keep writing it precisely so the tests below can prove it is
    ignored.
    """
    from campaignlib.party_config import ResolvedCharacter
    path = tmp_path / filename
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"player: {player}\n"
        f"species: {species}\n"
        f"class_level: {class_level}\n"
        "subclass: ''\n"
        "---\n"
        f"# {name}\n\n## Identity\n- **Player:** {player}\n",
        encoding="utf-8",
    )
    return ResolvedCharacter(name=name, sheet=path)


def _pmfc_players(*pairs):
    from campaignlib.players_config import Player, PlayersConfig
    return PlayersConfig(players=[
        Player(id=person.split()[0].lower(), name=person,
               display_names=[person], plays=[character])
        for person, character in pairs
    ])


def test_speaker_map_from_configs_basic(tmp_path):
    from campaignlib.party_config import ResolvedPartyConfig
    from campaignlib.players_config import speaker_map_from_configs
    daz = _pmfc_write_sheet(tmp_path, "daz.md", name="Daz", player="Mike Hall")
    thorin = _pmfc_write_sheet(tmp_path, "thorin.md", name="Thorin", player="Joe Beda")
    cfg = ResolvedPartyConfig(characters=[daz, thorin])
    m = speaker_map_from_configs(
        _pmfc_players(("Mike Hall", "Daz"), ("Joe Beda", "Thorin")), cfg
    )
    # display name -> the label the transcript line becomes.
    assert m["Mike Hall"] == "Daz"
    assert m["Joe Beda"] == "Thorin"


def test_speaker_map_ignores_the_sheets_player_line(tmp_path):
    """The sheet says one person, the entity says another. The entity wins,
    and the sheet's line is never consulted."""
    from campaignlib.party_config import ResolvedPartyConfig
    from campaignlib.players_config import speaker_map_from_configs
    daz = _pmfc_write_sheet(tmp_path, "daz.md", name="Daz", player="kostadis1")
    cfg = ResolvedPartyConfig(characters=[daz])
    m = speaker_map_from_configs(_pmfc_players(("Mike Hall", "Daz")), cfg)
    assert m == {"Mike Hall": "Daz"}


def test_speaker_map_refuses_when_a_character_has_no_player(tmp_path, capsys):
    """FR-024. A partial map would leave that character's lines carrying a raw
    transcript label, which is the silent half of the failure feature 009
    removes — so the run does not start."""
    from campaignlib.party_config import ResolvedPartyConfig
    from campaignlib.players_config import speaker_map_from_configs
    daz = _pmfc_write_sheet(tmp_path, "daz.md", name="Daz", player="Mike Hall")
    thorin = _pmfc_write_sheet(tmp_path, "thorin.md", name="Thorin", player="Joe Beda")
    cfg = ResolvedPartyConfig(characters=[daz, thorin])
    assert speaker_map_from_configs(_pmfc_players(("Mike Hall", "Daz")), cfg) is None
    err = capsys.readouterr().err
    assert "Thorin" in err
    # Every unbound character, not just the first.
    assert "Daz" not in err.split("no player bound")[1].split("->")[0]


def test_speaker_map_empty_is_not_a_failure(tmp_path):
    """Hillsfar's state: every character is bound, nobody has a display name.
    Nothing to rewrite is a real configuration, distinct from a broken one."""
    from campaignlib.party_config import ResolvedPartyConfig
    from campaignlib.players_config import (
        Player, PlayersConfig, speaker_map_from_configs,
    )
    daz = _pmfc_write_sheet(tmp_path, "daz.md", name="Daz", player="")
    cfg = ResolvedPartyConfig(characters=[daz])
    players = PlayersConfig(players=[Player(id="mike", name="Mike", plays=["Daz"])])
    assert speaker_map_from_configs(players, cfg) == {}


def test_speaker_map_none_players_is_a_refusal(tmp_path):
    from campaignlib.party_config import ResolvedPartyConfig
    from campaignlib.players_config import speaker_map_from_configs
    daz = _pmfc_write_sheet(tmp_path, "daz.md", name="Daz", player="Mike")
    cfg = ResolvedPartyConfig(characters=[daz])
    assert speaker_map_from_configs(None, cfg) is None


# ── campaignlib.normalize_vtt_speakers ─────────────────────────────────────


def test_normalize_vtt_speakers_rewrites_player_to_character():
    import campaignlib
    vtt = "Mike Hall: We can put her in the bag of holding.\nThorin: Let's roll.\n"
    out = campaignlib.normalize_vtt_speakers(vtt, {"Mike Hall": "Daz"})
    assert out.startswith("Daz: We can put her")
    # Existing character-named line is untouched
    assert "Thorin: Let's roll." in out


def test_normalize_vtt_speakers_rewrites_the_gm_to_GM():
    """The GM label arrives in the map like any other, built from the entity's
    `gm` flag rather than from a separate --gm-player string."""
    import campaignlib
    vtt = "Kostadis: The cave grows colder.\nDaz: I draw my axe.\n"
    out = campaignlib.normalize_vtt_speakers(vtt, {"Kostadis": "GM"})
    assert out.startswith("GM: The cave grows colder.")
    assert "Daz: I draw my axe." in out


def test_normalize_vtt_speakers_longer_names_match_first():
    """A player named "Mike" must not steal lines from "Mike Hall"."""
    import campaignlib
    vtt = "Mike Hall: stealth.\nMike: perception.\n"
    out = campaignlib.normalize_vtt_speakers(
        vtt, {"Mike": "Bob", "Mike Hall": "Daz"}
    )
    lines = out.splitlines()
    assert lines[0] == "Daz: stealth."
    assert lines[1] == "Bob: perception."


def test_normalize_vtt_speakers_only_label_not_body():
    """Player names appearing inside the dialogue body are NOT rewritten."""
    import campaignlib
    vtt = 'Mike Hall: I tell Mike Hall I love him.\n'
    out = campaignlib.normalize_vtt_speakers(vtt, {"Mike Hall": "Daz"})
    assert out == "Daz: I tell Mike Hall I love him."


def test_normalize_vtt_speakers_no_op_without_inputs():
    import campaignlib
    vtt = "Foo: bar\n"
    assert campaignlib.normalize_vtt_speakers(vtt) == vtt


# ── session_doc.load_voice_files ────────────────────────────────────────────

def test_load_voice_files(tmp_path):
    (tmp_path / "vukradin_voice.md").write_text("Gruff, terse.", encoding="utf-8")
    (tmp_path / "soma.md").write_text("Gentle, wise.", encoding="utf-8")
    voices = session_doc.load_voice_files(tmp_path)
    assert voices["vukradin"] == "Gruff, terse."
    assert voices["soma"] == "Gentle, wise."


def test_load_voice_files_empty_dir(tmp_path):
    voices = session_doc.load_voice_files(tmp_path)
    assert voices == {}


# ── session_doc.get_voice_note ──────────────────────────────────────────────

def test_get_voice_note_found():
    voices = {"vukradin": "Gruff.", "soma": "Gentle."}
    assert session_doc.get_voice_note(voices, "Vukradin") == "Gruff."


def test_get_voice_note_does_not_match_on_a_first_name():
    """The rule feature 009 deleted. ``Soma the Tortle`` resolving to ``soma``
    is a similarity-based identity assertion — the same reasoning that made a
    renamed ``Grygum`` resolve to nothing and say so to nobody. A character's
    voice file is named by its roster entry; if the plan and the roster
    disagree about the name, that disagreement is the finding."""
    voices = {"soma": "Gentle."}
    assert session_doc.get_voice_note(voices, "Soma the Tortle") is None


def test_get_voice_note_is_whitespace_and_case_insensitive():
    voices = {"soma": "Gentle."}
    assert session_doc.get_voice_note(voices, "  SOMA ") == "Gentle."


def test_get_voice_note_missing():
    voices = {"vukradin": "Gruff."}
    assert session_doc.get_voice_note(voices, "Brewbarry") is None


# ── session_doc.extract_contrast_sample ─────────────────────────────────────

def test_extract_contrast_sample_skips_headings_and_caption():
    """First substantive paragraph wins; markdown chrome is ignored."""
    text = (
        "# Vukradin — Voice Reference Passages\n"
        "*Verbatim excerpts from the campaign bible.*\n\n"
        "---\n\n"
        "## From chapter 3: The Stone Pit\n\n"
        "The trap was the same one. They always were. "
        "I dropped through anyway because that is what you do.\n\n"
        "## From chapter 5: The Climb\n\n"
        "Different scene, also irrelevant for this test."
    )
    sample = session_doc.extract_contrast_sample(text)
    assert "Verbatim excerpts" not in sample
    assert "Voice Reference Passages" not in sample
    assert "From chapter 3" not in sample
    assert sample.startswith("The trap was the same one.")
    assert "Different scene" not in sample  # only first substantive paragraph


def test_extract_contrast_sample_caps_sentences():
    text = "A. B. C. D. E. F. G."
    assert session_doc.extract_contrast_sample(text, max_sentences=3) == "A. B. C."


def test_extract_contrast_sample_empty_returns_empty():
    assert session_doc.extract_contrast_sample("") == ""
    assert session_doc.extract_contrast_sample("# Heading only\n\n---\n\n## Another heading") == ""


# ── session_doc.load_extractions ────────────────────────────────────────────

def test_load_extractions_sorted(tmp_path):
    (tmp_path / "extract_002.md").write_text("Second", encoding="utf-8")
    (tmp_path / "extract_001.md").write_text("First", encoding="utf-8")
    (tmp_path / "notes.md").write_text("Ignored", encoding="utf-8")
    result = session_doc.load_extractions(tmp_path)
    assert len(result) == 2
    assert result[0] == ("extract_001.md", "First")
    assert result[1] == ("extract_002.md", "Second")


def test_load_extractions_empty_dir(tmp_path):
    assert session_doc.load_extractions(tmp_path) == []


# ── session_doc.format_extractions ──────────────────────────────────────────

def test_format_extractions_basic():
    exts = [("extract_001.md", "Dialogue here"), ("extract_002.md", "More dialogue")]
    result = session_doc.format_extractions(exts, "Roleplay Extractions")
    assert "## Roleplay Extractions" in result
    assert "### Chunk 1" in result
    assert "### Chunk 2" in result
    assert "Dialogue here" in result
    assert "---" in result


def test_format_extractions_single_chunk():
    exts = [("extract_001.md", "Only chunk")]
    result = session_doc.format_extractions(exts, "Test")
    assert "### Chunk 1" in result
    assert "---" not in result.split("## Test\n\n", 1)[1]  # no separator with single chunk


# ── session_doc.build_narrate_prompt ────────────────────────────────────────

def test_build_narrate_prompt_basic():
    result = session_doc.build_narrate_prompt(
        narrator="Vukradin",
        focus="Faces the stone giants",
        char_moments="**The Giants**\nVukradin: \"We do not leave.\"",
        party=None,
        handoff="",
    )
    assert "## Narrator: Vukradin" in result
    assert "Faces the stone giants" in result
    assert "We do not leave" in result


def test_build_narrate_prompt_includes_party():
    result = session_doc.build_narrate_prompt(
        narrator="Soma", focus="focus", char_moments="moments",
        party="## Soma\nTortle Druid", handoff=""
    )
    assert "## Party Document" in result
    assert "Tortle Druid" in result


def test_build_narrate_system_includes_voice_note():
    """Voice notes live in the system prompt under the authoritative spec heading."""
    system = session_doc.build_narrate_system(
        None, scene=None, narrator="Soma", voice_note="Gentle and wise."
    )
    assert "AUTHORITATIVE VOICE SPEC — Soma" in system
    assert "Gentle and wise." in system


def test_build_narrate_prompt_no_longer_takes_voice_note():
    """Voice notes were hoisted to the system prompt; user prompt no longer carries them."""
    result = session_doc.build_narrate_prompt(
        narrator="Soma", focus="focus", char_moments="moments",
        party=None, handoff=""
    )
    assert "Voice Notes" not in result


def test_build_narrate_prompt_includes_handoff():
    result = session_doc.build_narrate_prompt(
        narrator="Soma", focus="focus", char_moments="moments",
        party=None, handoff="The mountain loomed ahead."
    )
    assert "Handoff" in result
    assert "The mountain loomed ahead." in result


def test_build_narrate_prompt_no_handoff_when_empty():
    result = session_doc.build_narrate_prompt(
        narrator="Soma", focus="focus", char_moments="moments",
        party=None, handoff=""
    )
    assert "Handoff" not in result


def test_build_narrate_prompt_includes_roster():
    result = session_doc.build_narrate_prompt(
        narrator="Soma", focus="focus", char_moments="moments",
        party=None, handoff="", roster="- Soma: Tortle Druid 5"
    )
    assert "Character Classes" in result
    assert "Tortle Druid 5" in result






def test_speaker_map_for_a_roster_of_nobody_is_empty_not_a_refusal():
    """A roster with no characters has nobody to leave unbound, so there is
    nothing for the speaker map to refuse. The empty-roster refusal belongs to
    ``roster_from_config``, which is what renders the "never contradict these"
    block — see tests/test_roster.py."""
    from campaignlib.party_config import ResolvedPartyConfig
    from campaignlib.players_config import PlayersConfig, speaker_map_from_configs
    assert speaker_map_from_configs(
        PlayersConfig(), ResolvedPartyConfig(characters=[])
    ) == {}
