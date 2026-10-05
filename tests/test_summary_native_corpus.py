"""Corpus build tests for summary_native (T010): deterministic, lossless, guarded."""

from __future__ import annotations

import filecmp
import json
import shutil
from pathlib import Path

import pytest

from pipelines.summary_native import schema
from pipelines.summary_native.corpus import CorpusError, build_corpus, guard_out_dir
from pipelines.summary_native.validate import scan

FIX = Path(__file__).parent / "fixtures" / "summary_native"


def _build(corpus, out, since=None, until=None, force=False, **kw):
    report = scan(FIX / corpus, FIX, since, until)
    assert report.blocking_count == 0
    return build_corpus(FIX / corpus, FIX, report, out, force=force, **kw)


def _tree(root: Path):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_build_byte_stable(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _build("clean", a)
    _build("clean", b)
    assert _tree(a) == _tree(b)
    for rel in _tree(a):
        assert filecmp.cmp(a / rel, b / rel, shallow=False), rel


def test_chronology_order_and_ids(tmp_path):
    out = tmp_path / "o"
    _build("clean", out)
    text = (out / "chronology.md").read_text()
    ids = [ln.split(" ")[1] for ln in text.splitlines() if ln.startswith("### 0")]
    assert ids == ["002.01", "002.02", "002.03", "003.01", "003.02", "005.01", "005.02"]
    assert "## Chapter 002 — 2026-01-10" in text
    assert "### 002.01 — Arrival at the Gate" in text
    assert "- Synopsis: Daz acts at the outer gate, changing what the party can do next." in text
    assert "- Provenance: clean/002-the-gate.md; chapter 2; scene 002.01 (line 7)" in text
    assert text.index("## Chapter 003") < text.index("## Chapter 005")


def test_memorable_moments_verbatim(tmp_path):
    out = tmp_path / "o"
    _build("clean", out)
    text = (out / "memorable_moments.md").read_text()
    src = (FIX / "clean" / "002-the-gate.md").read_text()
    body = src.split("## Memorable Moments\n", 1)[1].split("\n## NPCs", 1)[0]
    assert body in text
    assert "clean/002-the-gate.md" in text


def test_dossier_observation_provenance_fields(tmp_path):
    out = tmp_path / "o"
    _build("clean", out)
    text = (out / "dossiers" / "npc_manshoon.md").read_text()
    assert text.startswith("---\n")
    assert "subject: Manshoon" in text and "type: npc" in text
    assert "n_facts: 2" in text and "chapters: 2-5" in text
    assert "source_kind: summary_native" in text
    assert "# NPCs — Manshoon" in text
    assert "## Chapter 002 — Manshoon" in text and "## Chapter 005 — Manshoon" in text
    assert "- Source: clean/002-the-gate.md (line " in text
    assert "- Scene: none" in text
    assert "A Zhentarim archmage whose agents are moving through the keep." in text
    assert "grouped_by" not in text


def test_dossiers_load_via_read_dossiers(tmp_path):
    from pipelines.ensemble.synthesise_world_state import read_dossiers

    out = tmp_path / "o"
    _build("clean", out)
    paths = sorted((out / "dossiers").glob("*.md"))
    assert paths
    dossiers, n_missing = read_dossiers(paths)
    assert n_missing == 0
    by = {d.stem: d for d in dossiers}
    assert by["npc_manshoon"].n_facts == 2 and by["npc_manshoon"].last_chapter == 5


def test_same_name_different_category_never_combined(tmp_path):
    out = tmp_path / "o"
    shutil.copytree(FIX / "aliases", tmp_path / "src")
    report = scan(tmp_path / "src", tmp_path, None, None)
    build_corpus(tmp_path / "src", tmp_path, report, out, force=False)
    names = {p.name for p in (out / "dossiers").glob("*.md")}
    assert "item_staff_of_power.md" in names and "spell_staff_of_power.md" in names
    # identical-text-only grouping: look-alikes stay separate in US1
    assert {"npc_manshoon.md", "npc_manshon.md", "npc_lord_manshoon.md"} <= names


def test_range_excludes_out_of_range_content(tmp_path):
    out = tmp_path / "o"
    _build("out_of_range", out, until=5)
    for p in [*out.rglob("*.md"), *out.rglob("*.json")]:
        t = p.read_text()
        assert "008.01" not in t and "late-session" not in t and "misnumbered" not in t.lower()
    m = json.loads((out / "manifest.json").read_text())
    assert [f["chapter"] for f in m["files"]] == [2, 3, 5]
    assert m["range"] == {"since": 2, "until": 5, "gaps": [4]}


def test_refuses_ensemble_out_dir(tmp_path):
    for marker in ("merged.json", "facts_01.json", "extract_02.md"):
        d = tmp_path / marker.replace(".", "_")
        d.mkdir()
        (d / marker).write_text("{}")
        with pytest.raises(CorpusError):
            guard_out_dir(d, force=True)
    for sub in ("state_dossiers", "merged_dossiers"):
        d = tmp_path / sub
        (d / sub).mkdir(parents=True)
        with pytest.raises(CorpusError):
            guard_out_dir(d, force=True)
    with pytest.raises(CorpusError):
        _build("clean", tmp_path / "merged_json")


def test_refuses_foreign_manifest_and_unmanifested_files(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"kind": "ensemble"}))
    with pytest.raises(CorpusError):
        guard_out_dir(d, force=True)
    e = tmp_path / "y"
    e.mkdir()
    (e / "notes.txt").write_text("x")
    with pytest.raises(CorpusError):
        guard_out_dir(e, force=True)
    f = tmp_path / "z"
    f.mkdir()
    (f / "validation_report.md").write_text("r")
    (f / "validation_report.json").write_text("{}")
    guard_out_dir(f, force=False)  # report files alone are fine


def test_refuses_existing_without_force_and_force_rewrites(tmp_path):
    out = tmp_path / "o"
    _build("clean", out)
    with pytest.raises(CorpusError):
        _build("clean", out)
    stale = out / "dossiers" / "npc_stale.md"
    stale.write_text("x")
    (out / "validation_report.md").write_text("keep")
    _build("clean", out, force=True)
    assert not stale.exists()
    assert (out / "validation_report.md").read_text() == "keep"
    assert (out / "chronology.md").exists()


def test_no_absolute_paths_in_artifacts(tmp_path):
    out = tmp_path / "o"
    _build("clean", out)
    for rel in _tree(out):
        t = (out / rel).read_text()
        assert str(FIX) not in t and str(tmp_path) not in t and "/home/" not in t, rel
        assert "timestamp" not in t.lower()


def test_absent_optional_sections_in_manifest(tmp_path):
    out = tmp_path / "o"
    _build("clean", out)
    m = json.loads((out / "manifest.json").read_text())
    assert m["kind"] == "summary_native" and m["schema"] == 1
    assert m["absent_optional_sections"]["Abilities"] == [2, 3, 5]
    assert m["absent_optional_sections"]["Memorable Moments"] == []
    assert m["counts"]["scenes"] == 7
    assert m["canon"] == {"registry_sha256": None, "canon_sha256": None}
    assert all(len(f["sha256"]) == 64 for f in m["files"])


def test_unknown_section_preserved_and_reported(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    text = (FIX / "clean" / "002-the-gate.md").read_text()
    (src / "002-the-gate.md").write_text(text + "\n## Foreshadowing\n\nA raven watches.\n")
    report = scan(src, tmp_path, None, None)
    assert [f.code for f in report.findings] == [schema.UNKNOWN_SECTION]
    out = tmp_path / "o"
    build_corpus(src, tmp_path, report, out, force=False)
    assert "A raven watches." in (out / "other_sections.md").read_text()
    m = json.loads((out / "manifest.json").read_text())
    assert m["unknown_sections"] == [
        {"chapter": 2, "name": "Foreshadowing", "path": "src/002-the-gate.md"}
    ]


def test_other_sections_omitted_when_none(tmp_path):
    out = tmp_path / "o"
    _build("clean", out)
    assert not (out / "other_sections.md").exists()


def test_grouper_is_a_parameter(tmp_path):
    def grouper(category, heading):
        return ("Manshoon" if heading.startswith("Manshoon") else heading), ["test"]

    out = tmp_path / "o"
    shutil.copytree(FIX / "aliases", tmp_path / "src")
    report = scan(tmp_path / "src", tmp_path, None, None)
    build_corpus(tmp_path / "src", tmp_path, report, out, force=False, grouper=grouper)
    text = (out / "dossiers" / "npc_manshoon.md").read_text()
    assert "grouped_by:\n- test" in text
    assert "Manshoon (Simulacrum)" in text
