"""Tests for the chapter picker: /api/ensemble/chapters resolution + the
multi-chapter extract contract (select all / select one / subset)."""

import json
import asyncio
import inspect

from fastapi import Request
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from server.main import app
from server.ensemble_config_service import EnsembleConfigService
import server.routers.ensemble as ensemble_router
from pipelines.ensemble.narrate_chapter import render_narrative_md
from campaignlib import split_frontmatter

client = TestClient(app)


def _make_chapters(tmp_path):
    d = tmp_path / "docs/chapters"
    d.mkdir(parents=True)
    for n in ("01", "02", "10"):
        (d / f"chapter_{n}.md").write_text(f"# chapter {n}")


def test_chapters_resolves_glob_with_extracted_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_chapters(tmp_path)
    # chapter_02 already has a merged.json → must be flagged extracted.
    pc = tmp_path / "docs/ensemble/per_chapter/chapter_02"
    pc.mkdir(parents=True)
    (pc / "merged.json").write_text(json.dumps({"facts": []}))

    body = client.get("/api/ensemble/chapters",
                      params={"glob": "docs/chapters/chapter_*.md"}).json()
    assert body["count"] == 3
    by_stem = {c["stem"]: c for c in body["chapters"]}
    assert set(by_stem) == {"chapter_01", "chapter_02", "chapter_10"}
    assert by_stem["chapter_02"]["extracted"] is True
    assert by_stem["chapter_01"]["extracted"] is False
    # Paths are workspace-relative.
    assert by_stem["chapter_01"]["path"] == "docs/chapters/chapter_01.md"


def test_chapters_unions_multiple_globs_and_dedupes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_chapters(tmp_path)
    body = client.get(
        "/api/ensemble/chapters",
        params=[("glob", "docs/chapters/chapter_01.md"),
                ("glob", "docs/chapters/chapter_0*.md")],  # overlaps chapter_01
    ).json()
    stems = sorted(c["stem"] for c in body["chapters"])
    assert stems == ["chapter_01", "chapter_02"]  # 01 not duplicated


def test_chapters_empty_when_nothing_matches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_chapters(tmp_path)
    body = client.get("/api/ensemble/chapters",
                      params={"glob": "docs/chapters/nope_*.md"}).json()
    assert body == {"chapters": [], "count": 0}


def test_chapters_confined_to_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_chapters(tmp_path)
    # An escaping glob resolves to nothing inside the workspace, never leaks.
    body = client.get("/api/ensemble/chapters",
                      params={"glob": "../*.md"}).json()
    assert body["count"] == 0


def test_chapters_bare_directory_glob_raises_400(tmp_path, monkeypatch):
    """A glob that matches a directory (e.g. the user typed the chapters dir
    itself, not a file pattern) must fail loudly with an actionable message,
    never silently auto-expand to the directory's contents."""
    monkeypatch.chdir(tmp_path)
    _make_chapters(tmp_path)
    r = client.get("/api/ensemble/chapters", params={"glob": "docs/chapters"})
    assert r.status_code == 400
    assert "docs/chapters/*.md" in r.json()["detail"]

    # The corrected glob still works and returns all 3 chapter files.
    r2 = client.get("/api/ensemble/chapters", params={"glob": "docs/chapters/*.md"})
    assert r2.status_code == 200
    assert r2.json()["count"] == 3


def _direct_request(path: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [],
        "app": app,
    })


def test_narrate_chapter_route_forwards_one_selected_chapter_and_codex(
    tmp_path, monkeypatch
):
    """Per-chapter narration is disk-backed and leaves approval to a human."""
    monkeypatch.chdir(tmp_path)
    chapter = tmp_path / "docs/chapters/chapter_02.md"
    chapter.parent.mkdir(parents=True)
    chapter.write_text("# Chapter 02\nThe party reaches the gate.\n", encoding="utf-8")
    output = tmp_path / "docs/ensemble/per_chapter/chapter_02/narrative.md"
    captured = {}

    def capture(stage, cmd, *args, **kwargs):
        captured["cmd"] = cmd
        return PlainTextResponse("captured")

    def backend_args(backend, model, request, **kwargs):
        args = ["--backend", backend]
        if model:
            args += ["--model", model]
        return args

    monkeypatch.setattr(ensemble_router, "_run_locked", capture)
    monkeypatch.setattr(ensemble_router, "_backend_args", backend_args)
    endpoint = next(
        route.endpoint
        for route in ensemble_router.router.routes
        if getattr(route, "path", "") == "/run/narrate-chapter"
    )
    response = endpoint(
        _direct_request("/run/narrate-chapter"),
        chapter=str(chapter),
        output=str(output),
        backend="codex-cli",
        model=None,
        service=EnsembleConfigService(tmp_path / "config"),
    )
    if inspect.isawaitable(response):
        response = asyncio.run(response)

    assert response.status_code == 200
    cmd = captured["cmd"]
    assert "narrate_chapter" in cmd[0]
    assert str(chapter) in cmd
    assert cmd[cmd.index("--output") + 1] == str(output)
    assert cmd[cmd.index("--backend") + 1] == "codex-cli"
    assert "--model" not in cmd
    assert "--approve" not in cmd
    assert "--force" not in cmd
    assert "chapter_01.md" not in cmd


def test_narration_artifact_keeps_approval_false_until_human_review(tmp_path):
    """The route's disk output cannot implicitly cross the review checkpoint."""
    chapter = tmp_path / "chapter_02.md"
    chapter.write_text("# Chapter 02\n", encoding="utf-8")
    artifact = render_narrative_md(
        "chapter_02", chapter, [("The Gate", "The party reaches the gate.")], "scene"
    )
    frontmatter, body = split_frontmatter(artifact)
    assert frontmatter["approved"] is False
    assert "The party reaches the gate." in body


def test_narrate_chapter_is_explicit_per_chapter_review_action():
    """Narration is selected one chapter at a time and never auto-approves."""
    paths = app.openapi()["paths"]
    path = "/api/ensemble/run/narrate-chapter"
    assert path in paths
    operation = next(iter(paths[path].values()))
    names = {p["name"] for p in operation.get("parameters", [])}
    assert {"chapter", "output", "backend", "model"} <= names
    # ``narrate_chapter`` always writes approved:false; approval is a later
    # human edit, not a route argument that can silently cross the checkpoint.
    assert "approval" not in names
    assert "approve" not in names


# ── Principle X: no silent "all" ─────────────────────────────────────────────

def test_extract_refuses_empty_selection(tmp_path, monkeypatch):
    """An empty selection must be refused, never expanded to the full glob."""
    monkeypatch.chdir(tmp_path)
    _make_chapters(tmp_path)
    # No chapters param at all → must refuse with a clear message, not run.
    r = client.get("/api/ensemble/run/extract")
    assert r.status_code == 200  # SSE channel opens, but carries a refusal
    assert "No chapters selected" in r.text
    assert '"returncode": 1' in r.text
    # An explicitly empty list is refused identically (no glob fallback).
    r2 = client.get("/api/ensemble/run/extract", params={"chapters": ""})
    assert "No chapters selected" in r2.text


def test_extract_codex_forwards_only_explicit_chapter_selection(tmp_path, monkeypatch):
    """Codex extraction never turns an omitted/empty selection into all chapters."""
    monkeypatch.chdir(tmp_path)
    _make_chapters(tmp_path)
    captured = {}

    def capture(stage, cmd, *args, **kwargs):
        captured["stage"] = stage
        captured["cmd"] = cmd
        return PlainTextResponse("captured")

    monkeypatch.setattr(ensemble_router, "_run_locked", capture)
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/ensemble/run/extract",
        "query_string": b"",
        "headers": [],
        "app": app,
    })
    response = ensemble_router.run_extract(
        request,
        chapters=["chapter_02.md"],
        endpoints=[],
        batch=False,
        backend="codex-cli",
        model="gpt-5-codex",
        service=EnsembleConfigService(tmp_path / "config"),
    )

    assert response.status_code == 200
    assert captured["stage"] == "extract"
    cmd = captured["cmd"]
    chapter_index = cmd.index("--chapters") + 1
    assert cmd[chapter_index] == "chapter_02.md"
    assert cmd[chapter_index + 1] == "--per-chapter-dir"
    assert "chapter_01.md" not in cmd
    assert "chapter_10.md" not in cmd
    assert cmd[cmd.index("--backend") + 1] == "codex-cli"
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"
