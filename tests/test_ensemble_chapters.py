"""Tests for the chapter picker: /api/ensemble/chapters resolution + the
multi-chapter extract contract (select all / select one / subset)."""

import json

from fastapi.testclient import TestClient

from server.main import app

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
