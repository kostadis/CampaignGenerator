"""Integration tests for the Session Doc Editor router + config service.

Phase 5 of ``docs/config/session-editor-isolation.md``: storage is a
dedicated ``<config>/session_doc.yaml`` the service owns exclusively — an
editor write never touches ``ui_state.yaml``. Phase 3b's single write door
(the flat-body compat shim is gone; the router just forwards the request
body to ``SessionEditorConfigService.update_config``) and Phase 2's
module-global ``scene_editor.CONFIG`` removal still hold: every route reads
a request-scoped ``ResolvedEditorConfig``
(``server/session_editor_config_service.py``) injected via FastAPI
``Depends``. These tests verify:

  - ``GET /api/editor/config`` returns the grouped, resolved shape.
  - ``PUT /api/editor/config`` accepts a grouped partial, writes through
    ``SessionEditorConfigService`` to ``session_doc.yaml`` (NOT
    ``ui_state.yaml``), and the value survives a simulated restart (a
    second app / service instance reading the same campaign dir) — the bug
    from VttSummary.vue:70-71 that nothing-without-an-explicit-save-call
    goes to disk.
  - ``session_doc`` is no longer a valid section on the generic
    ``/api/config/section/{name}`` door (404 — Task 3).
  - Without a config service wired (``app.state.platform is None``),
    editor routes return 503 (mirrors ``config_routes._require_service``)
    rather than silently falling back to an in-memory default.
  - A double-prefix regression guard for the router mount.
  - O3 — the editor-local anthropic/claude-code model override:
    ``backends.<active>.model`` wins over ``runtime.default_model`` when
    set, and falls back to it when unset.
"""

from __future__ import annotations

import asyncio
import dataclasses
import sys
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.migrate_common import UI_STATE_NAME
from server.platform_config_service import PlatformConfigService, TRACKED_CONFIG_NAME
from server.routers import config_routes, scene_editor
from server.session_editor_config_service import SessionEditorConfigService
from server.session_editor_config_shared import (
    EditorPaths,
    SessionEditorConfig,
    save_session_editor_config,
)

# Service reads/writes its documents under <campaign>/<config_dir>/ (config_dir="config").
CONFIG_SUBDIR = "config"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def fresh_campaign(tmp_path):
    _write(
        tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME,
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
    )
    return tmp_path


def _make_app(campaign_dir: Path | None) -> FastAPI:
    app = FastAPI()
    app.include_router(scene_editor.router, prefix="/api/editor")
    app.include_router(config_routes.router, prefix="/api/config")
    if campaign_dir is not None:
        app.state.platform = PlatformConfigService(campaign_dir)
    else:
        app.state.platform = None
    return app


EDITOR_DETAIL_PLAN = """\
## Section 1
narrator: Alice
chunks: 1-1
scene: Scene One
focus: opening
"""

RAW_EXTRACTION = "raw editor content\n"
SMOOTHED_EXTRACTION = "smoothed narrate content\n"


def _write_editor_detail_session(
    tmp_path: Path,
    *,
    raw_body: str | None = RAW_EXTRACTION,
    smoothed_body: str | None = None,
    smoothed_bytes: bytes | None = None,
    raw_dir_name: str = "scene_extractions_new",
) -> tuple[Path, Path, Path]:
    session_dir = tmp_path / "summaries" / "session1"
    raw_dir = session_dir / raw_dir_name
    smoothed_dir = session_dir / "scene_extractions_smoothed"
    narration_dir = session_dir / "narration"

    _write(tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME, "documents: []\n")
    _write(session_dir / "gm-assist.md", "# Recap\n")
    _write(session_dir / "session-summary.md", "# Summary\n")
    _write(narration_dir / "plan.md", EDITOR_DETAIL_PLAN)
    raw_dir.mkdir(parents=True)
    if raw_body is not None:
        _write(
            raw_dir / "01_scene_one.md",
            f"---\nscene: Scene One\n---\n\n{raw_body}",
        )
    if smoothed_body is not None or smoothed_bytes is not None:
        smoothed_dir.mkdir()
        smoothed_file = smoothed_dir / "01_scene_one.md"
        if smoothed_bytes is not None:
            smoothed_file.write_bytes(smoothed_bytes)
        else:
            _write(
                smoothed_file,
                f"---\nscene: Scene One\n---\n\n{smoothed_body}",
            )

    save_session_editor_config(
        tmp_path / CONFIG_SUBDIR / "session_doc.yaml",
        SessionEditorConfig(
            paths=EditorPaths(
                session_recap="gm-assist.md",
                session_summary="session-summary.md",
                scene_extractions_dir=raw_dir_name,
                narration_dir="narration",
            ),
        ),
    )
    return session_dir, raw_dir, smoothed_dir


def _editor_detail_cfg(tmp_path: Path):
    session_dir = tmp_path / "summaries" / "session1"
    platform = PlatformConfigService(
        tmp_path,
        boot_overrides={"runtime.session_dir": str(session_dir)},
    )
    return SessionEditorConfigService(platform).resolved_editor_config()


def _get_editor_detail(tmp_path: Path) -> dict:
    body = scene_editor.api_get_extraction(1, _editor_detail_cfg(tmp_path))
    assert isinstance(body, dict)
    return body


def _get_editor_detail_scene(tmp_path: Path, scene_index: int) -> dict:
    body = scene_editor.api_get_extraction(scene_index, _editor_detail_cfg(tmp_path))
    assert isinstance(body, dict)
    return body


MULTI_SCENE_PLAN = """\
## Section 1
narrator: Alice
chunks: 1-1
scene: Scene One
focus: opening

## Section 2
narrator: Bob
chunks: 2-2
scene: Scene Two
focus: middle

## Section 3
narrator: Cara
chunks: 3-3
scene: Scene Three
focus: ending
"""

SCENE_NAMES = {
    1: "Scene One",
    2: "Scene Two",
    3: "Scene Three",
}

SCENE_SLUGS = {
    1: "scene_one",
    2: "scene_two",
    3: "scene_three",
}


def _write_scene_file(directory: Path, scene_index: int, body: str) -> Path:
    path = directory / f"{scene_index:02d}_{SCENE_SLUGS[scene_index]}.md"
    _write(path, f"---\nscene: {SCENE_NAMES[scene_index]}\n---\n\n{body}")
    return path


def _write_multiscene_editor_session(
    tmp_path: Path,
    *,
    raw_scenes: dict[int, str] | None = None,
    smoothed_scenes: dict[int, str | bytes] | None = None,
    create_raw_dir: bool = True,
    raw_dir_name: str = "scene_extractions_new",
) -> tuple[Path, Path, Path]:
    session_dir = tmp_path / "summaries" / "session1"
    raw_dir = session_dir / raw_dir_name
    smoothed_dir = session_dir / "scene_extractions_smoothed"
    narration_dir = session_dir / "narration"

    _write(tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME, "documents: []\n")
    _write(session_dir / "gm-assist.md", "# Recap\n")
    _write(session_dir / "session-summary.md", "# Summary\n")
    _write(narration_dir / "plan.md", MULTI_SCENE_PLAN)

    if create_raw_dir:
        raw_dir.mkdir(parents=True)
    for scene_index, body in (raw_scenes or {}).items():
        _write_scene_file(raw_dir, scene_index, body)

    if smoothed_scenes is not None:
        smoothed_dir.mkdir(parents=True)
        for scene_index, body in smoothed_scenes.items():
            path = smoothed_dir / f"{scene_index:02d}_{SCENE_SLUGS[scene_index]}.md"
            if isinstance(body, bytes):
                path.write_bytes(body)
            else:
                _write(path, f"---\nscene: {SCENE_NAMES[scene_index]}\n---\n\n{body}")

    save_session_editor_config(
        tmp_path / CONFIG_SUBDIR / "session_doc.yaml",
        SessionEditorConfig(
            paths=EditorPaths(
                session_recap="gm-assist.md",
                session_summary="session-summary.md",
                scene_extractions_dir=raw_dir_name,
                narration_dir="narration",
            ),
        ),
    )
    return session_dir, raw_dir, smoothed_dir


async def _collect_stream_body(response) -> str:
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(chunk)
    return "".join(chunks)


def _run_narrate_and_capture_cmd(monkeypatch, tmp_path: Path, scene_index: int) -> list[str]:
    captured: dict[str, list[str]] = {}

    async def fake_stream_subprocess(cmd, *, cwd=None, on_complete=None):
        captured["cmd"] = list(cmd)
        captured["cwd"] = cwd
        if on_complete is not None:
            on_complete(0)
        yield "data: done\n\n"

    monkeypatch.setattr(scene_editor, "stream_subprocess", fake_stream_subprocess)

    async def run_route() -> None:
        response = await scene_editor.api_narrate(
            scene_index, None, _editor_detail_cfg(tmp_path)
        )
        await _collect_stream_body(response)

    asyncio.run(run_route())
    assert "cmd" in captured, "Narrate route should launch the subprocess"
    return captured["cmd"]


def _run_blocked_narrate(monkeypatch, tmp_path: Path, scene_index: int) -> str:
    launched = False

    async def fake_stream_subprocess(cmd, *, cwd=None, on_complete=None):
        nonlocal launched
        launched = True
        yield "data: should not launch\n\n"

    monkeypatch.setattr(scene_editor, "stream_subprocess", fake_stream_subprocess)

    async def run_route() -> str:
        response = await scene_editor.api_narrate(
            scene_index, None, _editor_detail_cfg(tmp_path)
        )
        return await _collect_stream_body(response)

    body = asyncio.run(run_route())
    assert launched is False
    return body


def _assert_candidate(
    candidate: dict,
    *,
    layer: str,
    directory: Path,
    directory_exists: bool,
    path: Path | None,
    exists: bool,
    readable: bool | None,
    reason: str | None = None,
) -> None:
    assert set(candidate) == {
        "layer",
        "directory",
        "directory_exists",
        "path",
        "filename",
        "exists",
        "readable",
        "reason",
    }
    assert candidate["layer"] == layer
    assert candidate["directory"] == str(directory.resolve())
    assert candidate["directory_exists"] is directory_exists
    assert candidate["path"] == (str(path.resolve()) if path else None)
    assert candidate["filename"] == (path.name if path else None)
    assert candidate["exists"] is exists
    assert candidate["readable"] is readable
    if reason is None:
        assert candidate["reason"] is None
    else:
        assert reason in candidate["reason"]


def _assert_active_contract(
    source: dict,
    *,
    scene_index: int,
    scene_name: str,
    active_layer: str | None,
    active_file: Path | None,
    status: str,
    available: bool,
    fallback_to_raw: bool,
    message_contains: str,
) -> None:
    assert set(source) == {
        "scene_index",
        "scene_name",
        "smoothed",
        "raw",
        "active_layer",
        "active_file",
        "status",
        "available",
        "fallback_to_raw",
        "message",
    }
    assert source["scene_index"] == scene_index
    assert source["scene_name"] == scene_name
    assert source["active_layer"] == active_layer
    assert source["active_file"] == (str(active_file.resolve()) if active_file else None)
    assert source["status"] == status
    assert source["available"] is available
    assert source["fallback_to_raw"] is fallback_to_raw
    assert message_contains in source["message"]


# ── GET /api/editor/extraction/{n} — narrate_source projection ─────────────


class TestExtractionDetailNarrateSource:
    def test_smoothed_first_state_preserves_top_level_raw_editor_fields(
        self, tmp_path,
    ):
        session_dir, raw_dir, smoothed_dir = _write_editor_detail_session(
            tmp_path, smoothed_body=SMOOTHED_EXTRACTION)

        body = _get_editor_detail(tmp_path)

        assert body["exists"] is True
        assert body["content"].endswith(RAW_EXTRACTION)
        assert SMOOTHED_EXTRACTION not in body["content"]

        source = body["narrate_source"]
        _assert_active_contract(
            source,
            scene_index=1,
            scene_name="Scene One",
            active_layer="smoothed",
            active_file=session_dir / "scene_extractions_smoothed" / "01_scene_one.md",
            status="ready",
            available=True,
            fallback_to_raw=False,
            message_contains="smoothed",
        )
        _assert_candidate(
            source["smoothed"],
            layer="smoothed",
            directory=smoothed_dir,
            directory_exists=True,
            path=smoothed_dir / "01_scene_one.md",
            exists=True,
            readable=True,
        )
        _assert_candidate(
            source["raw"],
            layer="raw",
            directory=raw_dir,
            directory_exists=True,
            path=raw_dir / "01_scene_one.md",
            exists=True,
            readable=True,
        )

    def test_raw_fallback_state_keeps_raw_exists_and_content_when_smoothed_absent(
        self, tmp_path,
    ):
        _session_dir, raw_dir, smoothed_dir = _write_editor_detail_session(tmp_path)

        body = _get_editor_detail(tmp_path)

        assert body["exists"] is True
        assert body["content"].endswith(RAW_EXTRACTION)

        source = body["narrate_source"]
        _assert_active_contract(
            source,
            scene_index=1,
            scene_name="Scene One",
            active_layer="raw",
            active_file=raw_dir / "01_scene_one.md",
            status="ready",
            available=True,
            fallback_to_raw=True,
            message_contains="raw",
        )
        _assert_candidate(
            source["smoothed"],
            layer="smoothed",
            directory=smoothed_dir,
            directory_exists=False,
            path=None,
            exists=False,
            readable=None,
            reason="does not exist",
        )
        _assert_candidate(
            source["raw"],
            layer="raw",
            directory=raw_dir,
            directory_exists=True,
            path=raw_dir / "01_scene_one.md",
            exists=True,
            readable=True,
        )

    def test_unreadable_smoothed_state_blocks_without_changing_raw_editor_fields(
        self, tmp_path,
    ):
        _session_dir, raw_dir, smoothed_dir = _write_editor_detail_session(
            tmp_path, smoothed_bytes=b"\xff\xfe\x00")

        body = _get_editor_detail(tmp_path)

        assert body["exists"] is True
        assert body["content"].endswith(RAW_EXTRACTION)

        source = body["narrate_source"]
        _assert_active_contract(
            source,
            scene_index=1,
            scene_name="Scene One",
            active_layer=None,
            active_file=None,
            status="unreadable",
            available=False,
            fallback_to_raw=False,
            message_contains=str((smoothed_dir / "01_scene_one.md").resolve()),
        )
        _assert_candidate(
            source["smoothed"],
            layer="smoothed",
            directory=smoothed_dir,
            directory_exists=True,
            path=smoothed_dir / "01_scene_one.md",
            exists=True,
            readable=False,
            reason="not readable UTF-8",
        )
        _assert_candidate(
            source["raw"],
            layer="raw",
            directory=raw_dir,
            directory_exists=True,
            path=raw_dir / "01_scene_one.md",
            exists=True,
            readable=True,
        )

    def test_unreadable_raw_editor_still_returns_valid_smoothed_source(
        self, tmp_path,
    ):
        session_dir, raw_dir, _smoothed_dir = _write_editor_detail_session(
            tmp_path, smoothed_body=SMOOTHED_EXTRACTION)
        raw_file = raw_dir / "01_scene_one.md"
        raw_file.write_bytes(b"\xff\xfe\x00")

        body = _get_editor_detail(tmp_path)

        assert body["exists"] is True
        assert body["content"] == ""
        assert body["editor_readable"] is False
        assert str(raw_file.resolve()) in body["editor_error"]
        assert "not readable UTF-8" in body["editor_error"]

        source = body["narrate_source"]
        _assert_active_contract(
            source,
            scene_index=1,
            scene_name="Scene One",
            active_layer="smoothed",
            active_file=session_dir / "scene_extractions_smoothed" / "01_scene_one.md",
            status="ready",
            available=True,
            fallback_to_raw=False,
            message_contains="smoothed",
        )
        _assert_candidate(
            source["raw"],
            layer="raw",
            directory=raw_dir,
            directory_exists=True,
            path=raw_file,
            exists=True,
            readable=False,
            reason="not readable UTF-8",
        )

    def test_unreadable_raw_without_smoothed_returns_source_state_not_error(
        self, tmp_path,
    ):
        _session_dir, raw_dir, _smoothed_dir = _write_editor_detail_session(tmp_path)
        raw_file = raw_dir / "01_scene_one.md"
        raw_file.write_bytes(b"\xff\xfe\x00")

        body = _get_editor_detail(tmp_path)

        assert body["exists"] is True
        assert body["content"] == ""
        assert body["editor_readable"] is False
        assert str(raw_file.resolve()) in body["editor_error"]
        _assert_active_contract(
            body["narrate_source"],
            scene_index=1,
            scene_name="Scene One",
            active_layer=None,
            active_file=None,
            status="unreadable",
            available=False,
            fallback_to_raw=False,
            message_contains=str(raw_file.resolve()),
        )

    def test_missing_state_names_both_locations_and_keeps_raw_editor_empty(
        self, tmp_path,
    ):
        _session_dir, raw_dir, smoothed_dir = _write_editor_detail_session(
            tmp_path, raw_body=None)

        body = _get_editor_detail(tmp_path)

        assert body["exists"] is False
        assert body["content"] == ""

        source = body["narrate_source"]
        _assert_active_contract(
            source,
            scene_index=1,
            scene_name="Scene One",
            active_layer=None,
            active_file=None,
            status="missing",
            available=False,
            fallback_to_raw=False,
            message_contains=str(smoothed_dir.resolve()),
        )
        _assert_candidate(
            source["smoothed"],
            layer="smoothed",
            directory=smoothed_dir,
            directory_exists=False,
            path=None,
            exists=False,
            readable=None,
            reason="does not exist",
        )
        _assert_candidate(
            source["raw"],
            layer="raw",
            directory=raw_dir,
            directory_exists=True,
            path=None,
            exists=False,
            readable=None,
            reason="no eligible 01_*.md scene extraction",
        )
        assert str(smoothed_dir.resolve()) in source["message"]
        assert str(raw_dir.resolve()) in source["message"]

    def test_projection_uses_cfg_session_dir_for_absent_smoothed_and_custom_raw_dir(
        self, tmp_path,
    ):
        session_dir, raw_dir, smoothed_dir = _write_editor_detail_session(
            tmp_path, raw_dir_name="custom_scene_sources")

        body = _get_editor_detail(tmp_path)

        assert body["exists"] is True
        assert body["content"].endswith(RAW_EXTRACTION)
        source = body["narrate_source"]
        _assert_active_contract(
            source,
            scene_index=1,
            scene_name="Scene One",
            active_layer="raw",
            active_file=raw_dir / "01_scene_one.md",
            status="ready",
            available=True,
            fallback_to_raw=True,
            message_contains="raw",
        )
        _assert_candidate(
            source["smoothed"],
            layer="smoothed",
            directory=session_dir / "scene_extractions_smoothed",
            directory_exists=False,
            path=None,
            exists=False,
            readable=None,
            reason="does not exist",
        )
        _assert_candidate(
            source["raw"],
            layer="raw",
            directory=raw_dir,
            directory_exists=True,
            path=raw_dir / "01_scene_one.md",
            exists=True,
            readable=True,
        )
        assert source["smoothed"]["directory"] == str(smoothed_dir.resolve())

    def test_projection_re_reads_disk_after_add_rename_and_remove_events(
        self, tmp_path,
    ):
        _session_dir, raw_dir, smoothed_dir = _write_editor_detail_session(tmp_path)

        first = _get_editor_detail(tmp_path)["narrate_source"]
        _assert_active_contract(
            first,
            scene_index=1,
            scene_name="Scene One",
            active_layer="raw",
            active_file=raw_dir / "01_scene_one.md",
            status="ready",
            available=True,
            fallback_to_raw=True,
            message_contains="raw",
        )

        added = smoothed_dir / "01_scene_one_added.md"
        _write(added, "---\nscene: Scene One\n---\n\nfresh smoothed\n")
        after_add = _get_editor_detail(tmp_path)["narrate_source"]
        _assert_active_contract(
            after_add,
            scene_index=1,
            scene_name="Scene One",
            active_layer="smoothed",
            active_file=added,
            status="ready",
            available=True,
            fallback_to_raw=False,
            message_contains="smoothed",
        )

        renamed = smoothed_dir / "01_scene_one_renamed_away.txt"
        added.rename(renamed)
        after_rename = _get_editor_detail(tmp_path)["narrate_source"]
        _assert_active_contract(
            after_rename,
            scene_index=1,
            scene_name="Scene One",
            active_layer="raw",
            active_file=raw_dir / "01_scene_one.md",
            status="ready",
            available=True,
            fallback_to_raw=True,
            message_contains="raw",
        )

        added_again = smoothed_dir / "01_scene_one_added_again.md"
        _write(added_again, "---\nscene: Scene One\n---\n\nfresh smoothed again\n")
        added_again.unlink()
        after_remove = _get_editor_detail(tmp_path)["narrate_source"]
        _assert_active_contract(
            after_remove,
            scene_index=1,
            scene_name="Scene One",
            active_layer="raw",
            active_file=raw_dir / "01_scene_one.md",
            status="ready",
            available=True,
            fallback_to_raw=True,
            message_contains="raw",
        )


def test_narrate_sse_forwards_smoothed_active_file_from_fresh_detail(
    monkeypatch, tmp_path,
):
    _session_dir, raw_dir, smoothed_dir = _write_editor_detail_session(
        tmp_path, smoothed_body=SMOOTHED_EXTRACTION)
    cfg = _editor_detail_cfg(tmp_path)
    detail = scene_editor.api_get_extraction(1, cfg)
    assert isinstance(detail, dict)
    active_file = detail["narrate_source"]["active_file"]
    assert active_file == str((smoothed_dir / "01_scene_one.md").resolve())

    captured: dict[str, list[str]] = {}

    async def fake_stream_subprocess(cmd, *, cwd=None, on_complete=None):
        captured["cmd"] = list(cmd)
        captured["cwd"] = cwd
        if on_complete is not None:
            on_complete(0)
        yield "data: done\n\n"

    monkeypatch.setattr(scene_editor, "stream_subprocess", fake_stream_subprocess)

    async def run_route() -> None:
        response = await scene_editor.api_narrate(1, None, cfg)
        async for _chunk in response.body_iterator:
            pass

    asyncio.run(run_route())

    cmd = captured["cmd"]
    assert cmd[cmd.index("--scene-extractions") + 1] == str(raw_dir.resolve())
    assert "--scene-extraction-file" in cmd
    assert cmd[cmd.index("--scene-extraction-file") + 1] == active_file


class TestNarrateRouteUs3SourceEdges:
    def test_raw_only_route_keeps_existing_command_shape(self, monkeypatch, tmp_path):
        _session_dir, raw_dir, _smoothed_dir = _write_multiscene_editor_session(
            tmp_path,
            raw_scenes={1: "raw one\n"},
            smoothed_scenes=None,
        )

        detail = _get_editor_detail_scene(tmp_path, 1)
        _assert_active_contract(
            detail["narrate_source"],
            scene_index=1,
            scene_name="Scene One",
            active_layer="raw",
            active_file=raw_dir / "01_scene_one.md",
            status="ready",
            available=True,
            fallback_to_raw=True,
            message_contains="raw",
        )

        cmd = _run_narrate_and_capture_cmd(monkeypatch, tmp_path, 1)

        assert cmd[cmd.index("--scene-extractions") + 1] == str(raw_dir.resolve())
        assert "--scene-extraction-file" not in cmd

    def test_smoothed_only_route_is_available_and_uses_smoothed_parent(
        self, monkeypatch, tmp_path,
    ):
        _session_dir, raw_dir, smoothed_dir = _write_multiscene_editor_session(
            tmp_path,
            raw_scenes={},
            smoothed_scenes={1: "smoothed one\n"},
            create_raw_dir=False,
        )

        detail = _get_editor_detail_scene(tmp_path, 1)
        assert detail["exists"] is False
        assert detail["content"] == ""
        _assert_active_contract(
            detail["narrate_source"],
            scene_index=1,
            scene_name="Scene One",
            active_layer="smoothed",
            active_file=smoothed_dir / "01_scene_one.md",
            status="ready",
            available=True,
            fallback_to_raw=False,
            message_contains="smoothed",
        )
        _assert_candidate(
            detail["narrate_source"]["raw"],
            layer="raw",
            directory=raw_dir,
            directory_exists=False,
            path=None,
            exists=False,
            readable=None,
            reason="does not exist",
        )

        cmd = _run_narrate_and_capture_cmd(monkeypatch, tmp_path, 1)

        assert cmd[cmd.index("--scene-extractions") + 1] == str(smoothed_dir.resolve())
        assert cmd[cmd.index("--scene-extraction-file") + 1] == str(
            (smoothed_dir / "01_scene_one.md").resolve()
        )

    def test_partial_smoothed_layer_falls_back_per_scene(
        self, monkeypatch, tmp_path,
    ):
        _session_dir, raw_dir, smoothed_dir = _write_multiscene_editor_session(
            tmp_path,
            raw_scenes={
                1: "raw one\n",
                2: "raw two\n",
                3: "raw three\n",
            },
            smoothed_scenes={
                1: "smoothed one\n",
                3: "smoothed three\n",
            },
        )

        first = _get_editor_detail_scene(tmp_path, 1)["narrate_source"]
        second = _get_editor_detail_scene(tmp_path, 2)["narrate_source"]
        third = _get_editor_detail_scene(tmp_path, 3)["narrate_source"]
        assert first["active_file"] == str(
            (smoothed_dir / "01_scene_one.md").resolve()
        )
        _assert_active_contract(
            second,
            scene_index=2,
            scene_name="Scene Two",
            active_layer="raw",
            active_file=raw_dir / "02_scene_two.md",
            status="ready",
            available=True,
            fallback_to_raw=True,
            message_contains="raw",
        )
        assert second["smoothed"]["path"] is None
        assert third["active_file"] == str(
            (smoothed_dir / "03_scene_three.md").resolve()
        )

        cmd = _run_narrate_and_capture_cmd(monkeypatch, tmp_path, 2)

        assert cmd[cmd.index("--scene-extractions") + 1] == str(raw_dir.resolve())
        assert "--scene-extraction-file" not in cmd

    def test_unreadable_smoothed_blocks_even_when_raw_exists(
        self, monkeypatch, tmp_path,
    ):
        _session_dir, raw_dir, smoothed_dir = _write_multiscene_editor_session(
            tmp_path,
            raw_scenes={1: "raw one\n"},
            smoothed_scenes={1: b"\xff\xfe\x00"},
        )

        detail = _get_editor_detail_scene(tmp_path, 1)
        _assert_active_contract(
            detail["narrate_source"],
            scene_index=1,
            scene_name="Scene One",
            active_layer=None,
            active_file=None,
            status="unreadable",
            available=False,
            fallback_to_raw=False,
            message_contains=str((smoothed_dir / "01_scene_one.md").resolve()),
        )
        _assert_candidate(
            detail["narrate_source"]["raw"],
            layer="raw",
            directory=raw_dir,
            directory_exists=True,
            path=raw_dir / "01_scene_one.md",
            exists=True,
            readable=True,
        )

        body = _run_blocked_narrate(monkeypatch, tmp_path, 1)

        assert "Narrate source unreadable" in body
        assert str((smoothed_dir / "01_scene_one.md").resolve()) in body
        assert str((raw_dir / "01_scene_one.md").resolve()) not in body

    def test_neither_source_route_message_names_both_checked_locations(
        self, monkeypatch, tmp_path,
    ):
        _session_dir, raw_dir, smoothed_dir = _write_multiscene_editor_session(
            tmp_path,
            raw_scenes={},
            smoothed_scenes=None,
        )

        detail = _get_editor_detail_scene(tmp_path, 1)
        _assert_active_contract(
            detail["narrate_source"],
            scene_index=1,
            scene_name="Scene One",
            active_layer=None,
            active_file=None,
            status="missing",
            available=False,
            fallback_to_raw=False,
            message_contains=str(smoothed_dir.resolve()),
        )
        assert str(raw_dir.resolve()) in detail["narrate_source"]["message"]

        body = _run_blocked_narrate(monkeypatch, tmp_path, 1)

        assert "No Narrate source found" in body
        assert str(smoothed_dir.resolve()) in body
        assert str(raw_dir.resolve()) in body

    def test_live_removed_smoothed_file_recomputes_to_raw_fallback(
        self, monkeypatch, tmp_path,
    ):
        _session_dir, raw_dir, smoothed_dir = _write_multiscene_editor_session(
            tmp_path,
            raw_scenes={1: "raw one\n"},
            smoothed_scenes={1: "smoothed one\n"},
        )
        before = _get_editor_detail_scene(tmp_path, 1)["narrate_source"]
        assert before["active_layer"] == "smoothed"

        (smoothed_dir / "01_scene_one.md").unlink()

        after = _get_editor_detail_scene(tmp_path, 1)["narrate_source"]
        _assert_active_contract(
            after,
            scene_index=1,
            scene_name="Scene One",
            active_layer="raw",
            active_file=raw_dir / "01_scene_one.md",
            status="ready",
            available=True,
            fallback_to_raw=True,
            message_contains="raw",
        )

        cmd = _run_narrate_and_capture_cmd(monkeypatch, tmp_path, 1)

        assert cmd[cmd.index("--scene-extractions") + 1] == str(raw_dir.resolve())
        assert "--scene-extraction-file" not in cmd


# ── GET /api/editor/config — grouped resolved shape ─────────────────────────


class TestGetEditorConfig:
    def test_returns_grouped_shape(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.get("/api/editor/config")
        assert resp.status_code == 200
        body = resp.json()
        # This is an EXHAUSTIVE lock on the wire shape, deliberately: a key
        # appearing or vanishing unnoticed is how the two producers of this
        # shape would drift. `paths_stored` and `warnings` were added by
        # feature 017 (specs/017-session-dir-repoint/contracts/
        # editor-config.md C-01..C-04) as a deliberate additive change, so
        # the lock grows with them. Nothing else changed name or meaning.
        assert set(body.keys()) == {
            "paths", "paths_stored", "warnings", "extract", "narrate", "backends",
            "session_name", "profiles", "active_profile", "model",
            "work_dir", "campaign_dir", "config_dir", "vtt", "session_dir",
            "genre", "batch_scenes_effective",
        }
        # Defaults: strict grouped schema, backends keyed by name (incl.
        # the hyphenated claude-code alias).
        assert body["backends"]["active"] == "anthropic"
        assert "claude-code" in body["backends"]
        assert list(body["backends"]).count("codex-cli") == 1
        assert body["extract"]["tokens"] == 8192
        assert body["narrate"]["tokens"] == 16000
        # The genre rulebook is a file (#276 fix 2): no path configured yet, so
        # the injected read-only summary says "nothing resolved" rather than
        # carrying a pasted default.
        assert body["genre"] == {
            "path": None, "exists": False, "lines": 0, "chars": 0,
            "preview": "", "sha256": "", "error": None,
        }
        assert "genre" not in body["narrate"]
        # 013/DM-20 — the resolved batched default the editor pre-selects
        # from. Top-level, never inside "extract" (that key is the
        # persisted extra="forbid" ExtractKnobs).
        assert body["batch_scenes_effective"] is False  # fresh campaign: anthropic
        assert "batch_scenes_effective" not in body["extract"]

    def test_batch_scenes_effective_is_actually_computed_not_just_declared(
        self, fresh_campaign
    ):
        """The seam that shipped broken: service computes it, dataclass
        carries it, UI reads it — and `_serialize_resolved` never sent it.

        Every layer's own tests passed. The route tests set the field with
        `dataclasses.replace`, so they never exercised the computation; the
        key-set test above pins what IS serialized, not what SHOULD be, so a
        field added to the dataclass and forgotten here stayed consistent.
        The only thing that catches it is asserting the VALUE the endpoint
        returns for a known backend.

        Symptom if it regresses: the checkbox silently never pre-selects on
        the subscription backend, and nothing anywhere reports it.
        """
        client = TestClient(_make_app(fresh_campaign))

        # metered backend, no pin -> False
        assert client.get("/api/editor/config").json()["batch_scenes_effective"] is False

        # subscription backend, no pin -> True (DM-18 step 3)
        client.put("/api/editor/config", json={"backends": {"active": "claude-code"}})
        body = client.get("/api/editor/config").json()
        assert body["backends"]["active"] == "claude-code"
        assert body["extract"]["batch_scenes"] is None, "must still be unpinned"
        assert body["batch_scenes_effective"] is True

        # an explicit pin beats the backend default, both ways (DM-18 step 2)
        client.put("/api/editor/config", json={"extract": {"batch_scenes": False}})
        assert client.get("/api/editor/config").json()["batch_scenes_effective"] is False

        client.put("/api/editor/config", json={"backends": {"active": "anthropic"}})
        client.put("/api/editor/config", json={"extract": {"batch_scenes": True}})
        assert client.get("/api/editor/config").json()["batch_scenes_effective"] is True

        # Application-level scene grouping is independent of provider message
        # batching: both subscription backends keep the default enabled.
        client.put("/api/editor/config", json={"backends": {"active": "codex-cli"}})
        assert client.get("/api/editor/config").json()["batch_scenes_effective"] is True
        client.put("/api/editor/config", json={"extract": {"batch_scenes": False}})
        assert client.get("/api/editor/config").json()["batch_scenes_effective"] is False

    def test_loads_pre_existing_session_doc_yaml_with_legacy_scrub_block(
        self, fresh_campaign
    ):
        """FR-005/#010: a session_doc.yaml written before this change (every
        campaign that has ever opened the config drawer, since the service
        dumps the full model including defaults) has a persisted top-level
        ``scrub:`` block on disk already. Reading that file must not fail —
        the retired field is dropped on load
        (``SessionEditorConfig._drop_retired_fields``), not rejected by
        ``extra="forbid"``."""
        _write(
            fresh_campaign / CONFIG_SUBDIR / "session_doc.yaml",
            "narrate:\n  tokens: 9000\n"
            "scrub:\n  enabled: true\n  tokens: 8000\n",
        )
        client = TestClient(_make_app(fresh_campaign))
        resp = client.get("/api/editor/config")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "scrub" not in body
        assert body["narrate"]["tokens"] == 9000

    def test_loads_old_four_profile_document_and_exposes_codex(self, fresh_campaign):
        _write(
            fresh_campaign / CONFIG_SUBDIR / "session_doc.yaml",
            "backends:\n"
            "  active: openrouter\n"
            "  anthropic:\n"
            "    model: claude-sonnet-4\n"
            "  dgx:\n"
            "    endpoint: http://dgx.local:8000\n"
            "    model: Qwen/Qwen3-32B\n"
            "  openrouter:\n"
            "    model: anthropic/claude-3.7-sonnet\n"
            "  claude-code:\n"
            "    model: claude-opus-4-1\n",
        )
        body = TestClient(_make_app(fresh_campaign)).get(
            "/api/editor/config"
        ).json()
        assert body["backends"]["active"] == "openrouter"
        assert body["backends"]["anthropic"]["model"] == "claude-sonnet-4"
        assert body["backends"]["dgx"]["model"] == "Qwen/Qwen3-32B"
        assert body["backends"]["openrouter"]["model"] == (
            "anthropic/claude-3.7-sonnet"
        )
        assert body["backends"]["claude-code"]["model"] == "claude-opus-4-1"
        assert body["backends"]["codex-cli"]["model"] is None


# ── PUT /api/editor/config — flat payload, single write door ────────────────


class TestPutPersistsViaService:
    def test_put_editor_config_persists_through_service(self, fresh_campaign):
        # First server: PUT a grouped partial via the editor endpoint — the
        # single write door (the flat-body compat shim was retired in
        # Phase 3b, now that the frontend sends the grouped shape).
        client_a = TestClient(_make_app(fresh_campaign))
        resp = client_a.put(
            "/api/editor/config",
            json={"narrate": {"tokens": 12000}, "paths": {"voice_dir": "voice/"}},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Verify the service wrote it to its OWN file, not ui_state.yaml.
        assert (fresh_campaign / CONFIG_SUBDIR / "session_doc.yaml").exists()
        assert not (fresh_campaign / CONFIG_SUBDIR / UI_STATE_NAME).exists()

        # Second server (simulates a restart): no in-memory state carried
        # over, but the service reloads session_doc.yaml.
        client_b = TestClient(_make_app(fresh_campaign))
        editor_cfg = client_b.get("/api/editor/config").json()
        assert editor_cfg["narrate"]["tokens"] == 12000
        assert editor_cfg["paths"]["voice_dir"].endswith("voice")  # absolute via resolve

    def test_put_editor_config_backend_fields(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={
                "backends": {
                    "active": "dgx",
                    "dgx": {"endpoint": "http://localhost:8000", "model": "llama-3-70b"},
                },
            },
        )
        assert resp.status_code == 200

        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["backends"]["active"] == "dgx"
        assert editor_cfg["backends"]["dgx"]["endpoint"] == "http://localhost:8000"
        assert editor_cfg["backends"]["dgx"]["model"] == "llama-3-70b"
        assert "scrub" not in editor_cfg

    def test_put_codex_profile_round_trips_without_mutating_anthropic(self, fresh_campaign):
        client_a = TestClient(_make_app(fresh_campaign))
        assert client_a.put(
            "/api/editor/config",
            json={"backends": {"anthropic": {"model": "claude-sonnet-4"}}},
        ).status_code == 200
        response = client_a.put(
            "/api/editor/config",
            json={
                "backends": {
                    "active": "codex-cli",
                    "codex-cli": {"model": "gpt-5-codex"},
                }
            },
        )
        assert response.status_code == 200, response.text

        # A second app instance proves the YAML alias and model survive a
        # service reload, while the pre-existing profile remains untouched.
        body = TestClient(_make_app(fresh_campaign)).get(
            "/api/editor/config"
        ).json()
        assert body["backends"]["active"] == "codex-cli"
        assert body["backends"]["codex-cli"]["model"] == "gpt-5-codex"
        assert body["backends"]["anthropic"]["model"] == "claude-sonnet-4"
        on_disk = yaml.safe_load(
            (fresh_campaign / CONFIG_SUBDIR / "session_doc.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert "codex-cli" in on_disk["backends"]
        assert "codex_cli" not in on_disk["backends"]

    def test_put_editor_config_narrate_batch_is_retired(self, fresh_campaign):
        """005-ui-batch-selection T029: `narrate.batch` was the bespoke
        checkbox's own store, superseded by `backends.<name>.batch`
        (test_ui_batch_service_selection.py's editor coverage). A stray
        `narrate.batch` key — e.g. from a pre-T029 session_doc.yaml, or a
        stale client still sending the old shape — is stripped before
        `extra="forbid"` sees it (NarrateKnobs._drop_retired_fields),
        mirroring EditorPaths' RETIRED_PATH_FIELDS precedent: the PUT still
        succeeds, but the field is simply absent afterward rather than
        persisted."""
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put("/api/editor/config", json={"narrate": {"batch": True}})
        assert resp.status_code == 200, resp.text

        editor_cfg = client.get("/api/editor/config").json()
        assert "batch" not in editor_cfg["narrate"]

    def test_scrub_top_level_group_is_retired(self, fresh_campaign):
        """Issue #010: the mechanics-scrub CLI (`session_doc/scrub_mechanics.py`)
        was retired in favor of the `/scrub` Claude Code skill, and
        `ScrubKnobs`/`scrub` no longer exist on `SessionEditorConfig`. A
        top-level `scrub:` block — e.g. from a session_doc.yaml written before
        this change (the service used to dump the full model, defaults
        included, so every campaign that had opened the config drawer already
        has one on disk) — is stripped before `extra="forbid"` sees it
        (`SessionEditorConfig._drop_retired_fields`), same pattern as
        `test_put_editor_config_narrate_batch_is_retired` above: the PUT still
        succeeds, the field is simply absent afterward, and nothing about the
        rest of the config is disturbed."""
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={"scrub": {"enabled": True, "tokens": 8000}},
        )
        assert resp.status_code == 200, resp.text

        editor_cfg = client.get("/api/editor/config").json()
        assert "scrub" not in editor_cfg

    def test_put_editor_config_rejects_extraneous_top_level_keys(self, fresh_campaign):
        # The flat compat shim (_flat_body_to_grouped / _IGNORED_FLAT_KEYS)
        # used to silently drop CONFIG-only keys like work_dir/output_dir.
        # Now that the router forwards the body straight to
        # SessionEditorConfig's strict (extra="forbid") schema, unknown
        # top-level keys are a validation error instead.
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={"work_dir": "/somewhere", "output_dir": "/elsewhere"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["ok"] is False

    def test_put_editor_config_invalid_shape_returns_400(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={"narrate": {"tokens": "not-an-int"}},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["ok"] is False


class TestPutGroupedBody:
    """Phase 3b: the flat-body compat shim (_flat_body_to_grouped) is gone —
    PUT /api/editor/config only accepts a grouped SessionEditorConfig
    partial, written through SessionEditorConfigService.update_config."""

    def test_put_editor_config_grouped_body_persists(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={"narrate": {"tokens": 9000}},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["narrate"]["tokens"] == 9000

    def test_put_editor_config_grouped_body_merges_multiple_groups(self, fresh_campaign):
        # A partial touching two different top-level groups in one PUT
        # merges into both without clobbering the rest of the config.
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={
                "paths": {"voice_dir": "voice/"},
                "narrate": {"tokens": 12345},
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["paths"]["voice_dir"].endswith("voice")
        assert editor_cfg["narrate"]["tokens"] == 12345


class TestSectionDoorNoLongerHandlesSessionDoc:
    """Phase 5: session_doc left ui_state.yaml entirely, so the generic
    `/api/config/section/{name}` door no longer recognizes it — the editor
    is reachable ONLY through GET/PUT /api/editor/config now (single write
    door, single read door)."""

    def test_section_session_doc_is_404(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/config/section/session_doc",
            json={"values": {"narrate_tokens": 9999}},
        )
        assert resp.status_code == 404

    def test_section_door_write_does_not_reach_editor_config(self, fresh_campaign):
        # Even though the section door 404s, confirm the editor config is
        # untouched (defense in depth — no silent partial write).
        client = TestClient(_make_app(fresh_campaign))
        client.put(
            "/api/config/section/session_doc",
            json={"values": {"narrate_tokens": 9999}},
        )
        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["narrate"]["tokens"] == 16000


# ── Phase 4 — boot unification: --session-dir populates the editor ──────────
# server/main.py no longer builds a second, main.py-local derivation of
# session paths (the old `config` dict + `init_editor_config` seed). The
# only boot-time input is `runtime.session_dir` (via boot_overrides), and
# SessionEditorConfigService.resolved_editor_config() is responsible for
# threading it through its own path resolution — see the docstring on
# resolved_editor_config() for why that must be explicit rather than
# relying on PlatformConfigService's persisted-value fallback.


class TestSessionDirBootOverride:
    def test_relative_scene_extractions_dir_resolves_under_boot_session_dir(
        self, fresh_campaign
    ):
        session_dir = fresh_campaign / "summaries" / "session1"
        session_dir.mkdir(parents=True)
        save_session_editor_config(
            fresh_campaign / CONFIG_SUBDIR / "session_doc.yaml",
            SessionEditorConfig(
                paths=EditorPaths(scene_extractions_dir="scene_extractions")
            ),
        )

        platform = PlatformConfigService(
            fresh_campaign,
            boot_overrides={"runtime.session_dir": str(session_dir)},
        )
        service = SessionEditorConfigService(platform)
        cfg = service.resolved_editor_config()

        expected_session_dir = str(session_dir.resolve())
        assert cfg.session_dir == expected_session_dir
        assert cfg.paths.scene_extractions_dir == str(
            (session_dir / "scene_extractions").resolve()
        )


class TestSessionDirFallback:
    """``scene_editor._session_dir`` fallback order: ``session_recap``'s
    parent, then ``cfg.session_dir`` (populated at boot from
    ``runtime.session_dir`` even before any recap has been saved), then
    ``cfg.work_dir`` (the campaign root) as a last resort."""

    def test_falls_back_to_cfg_session_dir_when_no_recap(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        service = SessionEditorConfigService(platform)
        cfg = service.resolved_editor_config()
        assert cfg.paths.session_recap is None

        cfg = dataclasses.replace(cfg, session_dir="/some/session/dir")
        assert scene_editor._session_dir(cfg) == Path("/some/session/dir")

    def test_prefers_session_recap_parent_over_session_dir(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        service = SessionEditorConfigService(platform)
        cfg = service.resolved_editor_config()
        cfg = dataclasses.replace(
            cfg,
            paths=cfg.paths.model_copy(
                update={"session_recap": "/recap/dir/gm-assist.md"}
            ),
            session_dir="/some/other/dir",
        )
        assert scene_editor._session_dir(cfg) == Path("/recap/dir")


# ── No config service wired → 503, not a silent in-memory default ───────────


class TestNoServiceReturns503:
    def test_get_editor_config_503_without_service(self):
        client = TestClient(_make_app(None))
        resp = client.get("/api/editor/config")
        assert resp.status_code == 503

    def test_put_editor_config_503_without_service(self):
        client = TestClient(_make_app(None))
        resp = client.put("/api/editor/config", json={"narrate_tokens": 1000})
        assert resp.status_code == 503

    def test_scenes_503_without_service(self):
        client = TestClient(_make_app(None))
        resp = client.get("/api/editor/scenes")
        assert resp.status_code == 503


# ── Double-prefix mount regression guard ─────────────────────────────────────


class TestRouteMounting:
    def test_double_prefix_guard(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        # Correct path resolves...
        assert client.get("/api/editor/config").status_code == 200
        # ...and the double-prefixed path does NOT exist.
        assert client.get("/api/editor/api/editor/config").status_code == 404

    def test_us4_scene_editor_faces_are_mounted_without_auto_advance(
        self, fresh_campaign
    ):
        """US4 adds distinct, human-triggered audit/compare/polish faces.

        Inspecting FastAPI's flattened route table keeps this guard bounded in
        environments where TestClient startup can block; the route handlers'
        focused builder tests live in ``test_editor_pipeline.py``.
        """
        paths = _make_app(fresh_campaign).openapi()["paths"]

        assert "/api/editor/consistency" in paths
        assert "get" in paths["/api/editor/consistency"]
        assert "/api/editor/voice-compare" in paths
        assert "get" in paths["/api/editor/voice-compare"]
        assert "/api/editor/polish" in paths
        assert "post" in paths["/api/editor/polish"]
        # The three actions are separate controls. No route is allowed to
        # collapse them into the existing plan/narrate chain.
        assert (
            paths["/api/editor/consistency"]["get"]["operationId"]
            != paths["/api/editor/plan"]["get"]["operationId"]
        )


# ── O3 — editor-local anthropic/claude-code model override ──────────────────


class TestO3ModelResolution:
    """O3's editor-local model override, preserved through feature 003.

    003 replaced ``_model_args`` + ``_backend_flags`` with a single
    ``_selection_args`` call into the one resolution seam. The *reach* of the
    editor's override is unchanged — its own backend profile still wins over
    the platform's pick — so these assertions are the same guarantee against
    the new helper.
    """

    def test_anthropic_override_wins_then_falls_back_to_default_model(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        service = SessionEditorConfigService(platform)

        # Editor-local override (backends.anthropic.model) wins when set.
        service.update_config(
            {"backends": {"active": "anthropic", "anthropic": {"model": "claude-opus-4-9"}}}
        )
        cfg = service.resolved_editor_config()
        assert scene_editor._selection_args(None, cfg) == ["--model", "claude-opus-4-9"]

        # Falls back to runtime.default_model (the global sidebar picker)
        # when the editor-local override is unset.
        service.update_config({"backends": {"active": "anthropic", "anthropic": {"model": None}}})
        cfg2 = service.resolved_editor_config()
        default_model = platform.resolved()["runtime"]["default_model"]
        assert scene_editor._selection_args(None, cfg2) == ["--model", default_model]

    def test_dgx_selection_forwards_backend_and_no_claude_model(self, fresh_campaign):
        """Pre-003 this asserted ``_model_args(cfg) == []`` — the anthropic
        model was suppressed for dgx because ``_backend_flags`` supplied its
        own. One helper now emits both halves, so the assertion moves from
        "no model args" to what actually matters: the dgx backend is
        forwarded, and no Claude id rides along with it (the pairing rule —
        a tier that picks a different backend does not inherit the platform's
        model).
        """
        platform = PlatformConfigService(fresh_campaign)
        service = SessionEditorConfigService(platform)
        service.update_config({"backends": {"active": "dgx"}})
        cfg = service.resolved_editor_config()
        args = scene_editor._selection_args(None, cfg)
        assert "--backend" in args and args[args.index("--backend") + 1] == "dgx"
        assert not any(a.startswith("claude-") for a in args)

    def test_plan_routes_still_suppress_the_dgx_adapter(self, fresh_campaign):
        """``allow_openai_compat=False`` is preserved verbatim: the plan
        routes fall back to the script's own default rather than being
        retargeted at DGX, whose OpenAI-compat shape cannot serve routes that
        may use tool-use.
        """
        platform = PlatformConfigService(fresh_campaign)
        service = SessionEditorConfigService(platform)
        service.update_config({"backends": {"active": "dgx"}})
        cfg = service.resolved_editor_config()
        assert scene_editor._selection_args(None, cfg, allow_openai_compat=False) == []


# ── 017: paths_stored / warnings on the wire ────────────────────────────
#
# specs/017-session-dir-repoint/contracts/editor-config.md C-01..C-06.
# Additive only: no existing key changes name, type or meaning. The editor
# binds `paths_stored` and echoes THAT back — never `paths` — which is what
# makes it impossible for a session switch to pin the session just left.


class TestPathsStoredWireShape:
    def _campaign_with_session(self, tmp_path, name="sess1"):
        _write(
            tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME,
            "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        )
        session_dir = tmp_path / "summaries" / name
        session_dir.mkdir(parents=True)
        return tmp_path, session_dir

    def test_get_config_carries_paths_stored_and_warnings(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        body = client.get("/api/editor/config").json()

        # C-04: always present, always a list, empty on a healthy config.
        assert body["warnings"] == []
        # C-02: same keys as `paths`.
        assert set(body["paths_stored"]) == set(body["paths"])

    def test_paths_stored_is_relative_while_paths_is_absolute(self, tmp_path):
        campaign, session_dir = self._campaign_with_session(tmp_path)
        app = _make_app(campaign)
        client = TestClient(app)
        client.put(
            "/api/config/runtime", json={"values": {"session_dir": str(session_dir)}}
        )
        client.put(
            "/api/editor/config",
            json={"paths": {"scene_extractions_dir": "scene_extractions"}},
        )

        body = client.get("/api/editor/config").json()
        assert body["paths_stored"]["scene_extractions_dir"] == "scene_extractions"
        assert body["paths"]["scene_extractions_dir"] == str(
            (session_dir / "scene_extractions").resolve()
        )

    def test_resolve_invariant_on_the_wire(self, tmp_path):
        """C-02: paths[k] == resolve(paths_stored[k]) for every key."""
        campaign, session_dir = self._campaign_with_session(tmp_path)
        client = TestClient(_make_app(campaign))
        client.put(
            "/api/config/runtime", json={"values": {"session_dir": str(session_dir)}}
        )
        client.put(
            "/api/editor/config",
            json={
                "paths": {
                    "session_recap": "gm-assist.md",
                    "scene_extractions_dir": "scene_extractions",
                    "voice_dir": "voice",
                }
            },
        )
        body = client.get("/api/editor/config").json()
        service = SessionEditorConfigService(
            PlatformConfigService(campaign)
        )
        session_fields = {
            "session_recap", "session_summary",
            "scene_extractions_dir", "narration_dir", "output_dir",
        }
        for key, stored in body["paths_stored"].items():
            base = "session" if key in session_fields else "campaign"
            assert body["paths"][key] == service.platform.resolve_path(
                stored, base=base, session_dir=str(session_dir)
            ), key

    def test_get_is_idempotent_and_does_not_write(self, tmp_path):
        """C-06: two GETs are byte-identical and leave the document alone."""
        campaign, session_dir = self._campaign_with_session(tmp_path)
        client = TestClient(_make_app(campaign))
        client.put(
            "/api/config/runtime", json={"values": {"session_dir": str(session_dir)}}
        )
        client.put(
            "/api/editor/config",
            json={"paths": {"scene_extractions_dir": "scene_extractions"}},
        )
        doc = campaign / CONFIG_SUBDIR / "session_doc.yaml"
        before = doc.read_bytes()

        first = client.get("/api/editor/config").json()
        second = client.get("/api/editor/config").json()

        assert first == second
        assert doc.read_bytes() == before


class TestSessionSwitchRepoints:
    """017 US1 (FR-001, FR-013) — the switch takes, end to end over HTTP.

    The service-level equivalent already existed
    (test_session_editor_config_service.py's
    "Switching session_dir alone must retrack the relative value"), which is
    why this feature is a frontend/wire fix rather than a service fix. This
    class locks the same guarantee at the route boundary, where the editor
    actually reads it, and additionally pins `paths_stored` — the value the
    editor binds — so a regression that re-points `paths` but not
    `paths_stored` cannot pass.
    """

    def _campaign(self, tmp_path):
        _write(
            tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME,
            "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        )
        a = tmp_path / "summaries" / "20260811"
        b = tmp_path / "summaries" / "20260825"
        a.mkdir(parents=True)
        b.mkdir(parents=True)
        return tmp_path, a, b

    def test_switch_repoints_every_session_path(self, tmp_path):
        campaign, session_a, session_b = self._campaign(tmp_path)
        client = TestClient(_make_app(campaign))
        client.put(
            "/api/config/runtime", json={"values": {"session_dir": str(session_a)}}
        )
        client.put(
            "/api/editor/config",
            json={
                "paths": {
                    "session_recap": "gm-assist.md",
                    "session_summary": "session-summary.md",
                    "scene_extractions_dir": "scene_extractions",
                    "narration_dir": "narration",
                    "voice_dir": "voice",
                    "party": "docs/party.md",
                }
            },
        )
        before = client.get("/api/editor/config").json()
        assert all(
            str(session_a.resolve()) in before["paths"][f]
            for f in ("session_recap", "scene_extractions_dir", "narration_dir")
        )

        client.put(
            "/api/config/runtime", json={"values": {"session_dir": str(session_b)}}
        )
        after = client.get("/api/editor/config").json()

        # Every session-scoped path moved...
        for f in ("session_recap", "session_summary",
                  "scene_extractions_dir", "narration_dir"):
            assert str(session_b.resolve()) in after["paths"][f], f
            assert str(session_a.resolve()) not in after["paths"][f], f
        # ...and the value the EDITOR binds carries no session identity at all.
        for f in ("session_recap", "session_summary",
                  "scene_extractions_dir", "narration_dir"):
            assert "20260811" not in (after["paths_stored"][f] or ""), f
            assert "20260825" not in (after["paths_stored"][f] or ""), f

        # FR-013: campaign-scoped paths did not move.
        assert after["paths"]["voice_dir"] == before["paths"]["voice_dir"]
        assert after["paths"]["party"] == before["paths"]["party"]

    def test_switch_needs_no_write_to_take_effect(self, tmp_path):
        """FR-001: re-pointing is a property of the read, not of a save."""
        campaign, session_a, session_b = self._campaign(tmp_path)
        client = TestClient(_make_app(campaign))
        client.put(
            "/api/config/runtime", json={"values": {"session_dir": str(session_a)}}
        )
        client.put(
            "/api/editor/config",
            json={"paths": {"scene_extractions_dir": "scene_extractions"}},
        )
        doc = campaign / CONFIG_SUBDIR / "session_doc.yaml"
        before_bytes = doc.read_bytes()

        client.put(
            "/api/config/runtime", json={"values": {"session_dir": str(session_b)}}
        )
        after = client.get("/api/editor/config").json()

        assert after["paths"]["scene_extractions_dir"] == str(
            (session_b / "scene_extractions").resolve()
        )
        # session_doc.yaml was never touched by the switch.
        assert doc.read_bytes() == before_bytes


class TestSwitchNeverPinsTheOldSession:
    """017 US2 (FR-002, FR-003, contract C-09/C-11) — the write side.

    The damage mechanism this locks out: the editor used to hold the
    RESOLVED absolute paths and PUT them back. After a switch those
    absolutes point into the previous session, relativize_path cannot
    collapse a path that is not under the current session_dir, so it stored
    them verbatim as "genuine out-of-tree overrides" -- and the field never
    tracked session_dir again. A relative name carries no session identity,
    which is why echoing paths_stored makes this unrepresentable.
    """

    def _campaign(self, tmp_path):
        _write(
            tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME,
            "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        )
        dirs = []
        for name in ("20260811", "20260825", "20260901"):
            d = tmp_path / "summaries" / name
            d.mkdir(parents=True)
            dirs.append(d)
        return tmp_path, dirs

    def _stored(self, campaign):
        return (campaign / CONFIG_SUBDIR / "session_doc.yaml").read_text(
            encoding="utf-8"
        )

    def test_echoing_paths_stored_after_a_switch_pins_nothing(self, tmp_path):
        campaign, (a, b, _) = self._campaign(tmp_path)
        client = TestClient(_make_app(campaign))
        client.put("/api/config/runtime", json={"values": {"session_dir": str(a)}})
        client.put(
            "/api/editor/config",
            json={"paths": {"scene_extractions_dir": "scene_extractions",
                            "narration_dir": "narration"}},
        )
        # Switch, then do what the editor does: read, then echo back the
        # value it binds along with an unrelated knob change.
        client.put("/api/config/runtime", json={"values": {"session_dir": str(b)}})
        stored = client.get("/api/editor/config").json()["paths_stored"]
        client.put(
            "/api/editor/config",
            json={"paths": stored, "narrate": {"tokens": 12345}},
        )

        on_disk = self._stored(campaign)
        assert "20260811" not in on_disk
        assert "20260825" not in on_disk
        # And it still resolves under the CURRENT session.
        after = client.get("/api/editor/config").json()
        assert after["paths"]["scene_extractions_dir"] == str(
            (b / "scene_extractions").resolve()
        )

    def test_both_write_orders_converge(self, tmp_path):
        """FR-002 scenario 2 — the Session Config save writes two documents;
        neither order may leave a value anchored to the session being left."""
        campaign, (a, b, _) = self._campaign(tmp_path)
        client = TestClient(_make_app(campaign))
        client.put("/api/config/runtime", json={"values": {"session_dir": str(a)}})
        client.put(
            "/api/editor/config",
            json={"paths": {"scene_extractions_dir": "scene_extractions"}},
        )

        # Order 1: session_dir first, then the paths (the order 017 adopts).
        client.put("/api/config/runtime", json={"values": {"session_dir": str(b)}})
        client.put(
            "/api/editor/config",
            json={"paths": {"scene_extractions_dir": "scene_extractions"}},
        )
        order_1 = client.get("/api/editor/config").json()

        # Order 2: paths first, then session_dir.
        client.put("/api/config/runtime", json={"values": {"session_dir": str(a)}})
        client.put(
            "/api/editor/config",
            json={"paths": {"scene_extractions_dir": "scene_extractions"}},
        )
        client.put("/api/config/runtime", json={"values": {"session_dir": str(b)}})
        order_2 = client.get("/api/editor/config").json()

        assert order_1["paths"] == order_2["paths"]
        assert order_1["paths_stored"] == order_2["paths_stored"]

    def test_three_switches_leave_only_the_last(self, tmp_path):
        """US2 scenario 3 — no accumulation across repeated switches."""
        campaign, (a, b, c) = self._campaign(tmp_path)
        client = TestClient(_make_app(campaign))
        client.put(
            "/api/editor/config",
            json={"paths": {"scene_extractions_dir": "scene_extractions"}},
        )
        for d in (a, b, c):
            client.put("/api/config/runtime", json={"values": {"session_dir": str(d)}})
            stored = client.get("/api/editor/config").json()["paths_stored"]
            client.put("/api/editor/config", json={"paths": stored})

        on_disk = self._stored(campaign)
        assert "20260811" not in on_disk
        assert "20260825" not in on_disk
        assert "20260901" not in on_disk
        assert client.get("/api/editor/config").json()["paths"][
            "scene_extractions_dir"
        ] == str((c / "scene_extractions").resolve())

    def test_echoing_the_resolved_paths_is_what_pinned_the_old_session(self, tmp_path):
        """Characterization of the 017 defect — deliberately asserts the BAD
        outcome, so the reason contract C-09 exists cannot be lost.

        This is what the editor did before 017: it held `paths` (absolute,
        resolved against the session it was showing) and PUT that back. If a
        future change "simplifies" the client into sending `paths` again,
        the behaviour below is what it will get -- and the field will stop
        tracking session_dir permanently. There is no frontend test runner in
        this repo, so this server-side test is the closest thing to a guard
        on that client obligation.
        """
        campaign, (a, b, _) = self._campaign(tmp_path)
        client = TestClient(_make_app(campaign))
        client.put("/api/config/runtime", json={"values": {"session_dir": str(a)}})
        client.put(
            "/api/editor/config",
            json={"paths": {"scene_extractions_dir": "scene_extractions"}},
        )
        # The old client read the ABSOLUTE block...
        resolved_under_a = client.get("/api/editor/config").json()["paths"]
        assert str(a.resolve()) in resolved_under_a["scene_extractions_dir"]

        # ...then the session switched, and the debounce echoed it back.
        client.put("/api/config/runtime", json={"values": {"session_dir": str(b)}})
        client.put("/api/editor/config", json={"paths": resolved_under_a})

        # The damage: session A is now pinned into stored config verbatim,
        # because it is not under session B and has no relative form.
        on_disk = self._stored(campaign)
        assert "20260811" in on_disk, "the pin is the defect this feature removes"

        # 017's read-side healing (US3) is what recovers from this state;
        # US2's client change is what stops it being created. Both are needed.


class TestRepointedPathsReportExistence:
    """017 US4 (FR-008, FR-009) — the backend half, automated.

    US4 needs no new product code: PathField and MultiPathField already
    probe GET /api/config/path-status and render per-path existence. They
    reported the wrong thing before this feature only because the value they
    were handed was stale. What IS worth locking here is the contract those
    components depend on (C-14): after a switch, the resolved path is the
    one under the NEW session, and path-status answers about that path.

    The visual half — the ✅/❌ marker, and it clearing when the GM edits the
    field — has no test runner in this repo and stays a manual step in
    quickstart.md §4.
    """

    def _campaign(self, tmp_path):
        _write(
            tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME,
            "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        )
        old = tmp_path / "summaries" / "20260811"
        new = tmp_path / "summaries" / "20260901"
        old.mkdir(parents=True)
        new.mkdir(parents=True)
        # The old session has a recap; the new one does not yet.
        (old / "gm-assist.md").write_text("old recap", encoding="utf-8")
        return tmp_path, old, new

    def test_missing_target_is_reported_missing_not_blanked(self, tmp_path):
        campaign, old, new = self._campaign(tmp_path)
        client = TestClient(_make_app(campaign))
        client.put("/api/config/runtime", json={"values": {"session_dir": str(old)}})
        client.put(
            "/api/editor/config", json={"paths": {"session_recap": "gm-assist.md"}}
        )
        # Present under the old session.
        before = client.get("/api/editor/config").json()
        assert client.get(
            "/api/config/path-status", params={"path": before["paths"]["session_recap"]}
        ).json()["exists"] is True

        client.put("/api/config/runtime", json={"values": {"session_dir": str(new)}})
        after = client.get("/api/editor/config").json()

        # FR-008: the name survives the switch — not blanked, not
        # auto-discovered into something else.
        assert after["paths_stored"]["session_recap"] == "gm-assist.md"
        # ...and it now resolves under the new session, where it is missing.
        assert after["paths"]["session_recap"] == str((new / "gm-assist.md").resolve())
        assert client.get(
            "/api/config/path-status", params={"path": after["paths"]["session_recap"]}
        ).json()["exists"] is False

    def test_existing_target_is_reported_present(self, tmp_path):
        campaign, _, new = self._campaign(tmp_path)
        (new / "scene_extractions").mkdir()
        client = TestClient(_make_app(campaign))
        client.put("/api/config/runtime", json={"values": {"session_dir": str(new)}})
        client.put(
            "/api/editor/config",
            json={"paths": {"scene_extractions_dir": "scene_extractions"}},
        )
        body = client.get("/api/editor/config").json()
        assert client.get(
            "/api/config/path-status",
            params={"path": body["paths"]["scene_extractions_dir"]},
        ).json()["exists"] is True
