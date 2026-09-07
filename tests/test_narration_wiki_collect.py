from pathlib import Path

import pytest
import yaml

from session_doc.narration_wiki.collect import collect
from session_doc.narration_wiki.models import StateError
from session_doc.narration_wiki.paths import resolve_scope
from session_doc.narration_wiki.storage import read_json


def _scope(tmp_path: Path):
    campaign = tmp_path / "campaign"
    session = campaign / "sessions" / "001"
    (campaign / "config").mkdir(parents=True)
    (campaign / "voice").mkdir()
    (campaign / "voice" / "_genre.md").write_text("# Rules\n")
    (campaign / "config" / "session_doc.yaml").write_text(yaml.safe_dump({"paths": {"genre_file": "voice/_genre.md"}}))
    (session / "narration").mkdir(parents=True)
    (session / "narration" / "Aria.md").write_text("## Aria — Scene 01\n\nConcrete choice.\n")
    (session / "critique.md").write_text("# Critique\n")
    (session / "scene_extractions_new").mkdir()
    (session / "scene_extractions_new" / "Blaise.md").write_text("## Blaise — Scene 01\n\nAnother choice.\n")
    return resolve_scope(campaign, session, "iter-001")


def test_collect_is_stable_explicit_and_never_changes_source_bytes(tmp_path):
    scope = _scope(tmp_path)
    before = {path: path.read_bytes() for path in scope.session_root.rglob("*") if path.is_file()}
    result = collect(scope)
    manifest = read_json(scope.iteration_root / "trace-manifest.json")
    assert result["corpus_id"] == manifest["corpus_id"]
    assert manifest["layouts"] == sorted(manifest["layouts"])
    assert [row["path"] for row in manifest["artifacts"]] == sorted(row["path"] for row in manifest["artifacts"])
    assert all(not Path(row["path"]).is_absolute() for row in manifest["artifacts"])
    assert before == {path: path.read_bytes() for path in before}
    with pytest.raises(StateError, match="already exists"):
        collect(scope)


def test_collect_records_missing_roles_instead_of_treating_them_as_clean(tmp_path):
    scope = _scope(tmp_path)
    collect(scope)
    missing = read_json(scope.iteration_root / "trace-manifest.json")["missing"]
    assert {row["kind"] for row in missing} >= {"gm_assist", "scrub_manifest"}


def test_measurement_corpus_uses_only_final_current_narration(tmp_path):
    scope = _scope(tmp_path)
    narration = scope.session_root / "narration"
    (narration / "Aria.md").write_text(
        "---\nnarrator: Declared Aria\n---\n\nFinal prose.\n"
    )
    (narration / "plan.md").write_text("## Scene 1\nnarrator: Aria\n")
    (narration / "Aria.knobs.json").write_text('{"temperature": 0.4}\n')
    (narration / "draft-v2.md").write_text(
        "---\nnarrator: Declared Aria\n---\n\nAlternate prose.\n"
    )
    (narration / "voice_critique_scene_01_aria.md").write_text("# Critique\n")
    (narration / "voice_fixes_session.md").write_text("# Fixes\n")
    (scope.session_root / "scene_extractions_new" / "Blaise.md").write_text(
        "Legacy duplicate prose.\n"
    )

    collect(scope)
    manifest = read_json(scope.iteration_root / "trace-manifest.json")

    assert manifest["measurement_corpus"] == ["narration/Aria.md"]
    rows = {row["path"]: row for row in manifest["artifacts"]}
    assert rows["narration/Aria.md"]["narrator"] == "Declared Aria"
    assert rows["narration/plan.md"]["kind"] == "generation_settings"
    assert rows["narration/Aria.knobs.json"]["kind"] == "generation_settings"
    assert rows["narration/draft-v2.md"]["kind"] == "narration"
    assert rows["narration/voice_critique_scene_01_aria.md"]["kind"] == "critique"
    assert rows["narration/voice_fixes_session.md"]["kind"] == "critique"


def test_measurement_corpus_prefers_smoothed_historical_narration(tmp_path):
    scope = _scope(tmp_path)
    for path in (scope.session_root / "narration").iterdir():
        path.unlink()
    raw = scope.session_root / "scene_extractions"
    smoothed = scope.session_root / "scene_extractions_smoothed"
    raw.mkdir()
    smoothed.mkdir()
    (raw / "Aria.md").write_text("Raw prose.\n")
    (raw / "logs").mkdir()
    (raw / "logs" / "run.md").write_text("# Run log\n")
    (smoothed / "Aria.md").write_text("Smoothed prose.\n")

    collect(scope)
    manifest = read_json(scope.iteration_root / "trace-manifest.json")

    assert manifest["measurement_corpus"] == ["scene_extractions_smoothed/Aria.md"]
    rows = {row["path"]: row for row in manifest["artifacts"]}
    assert rows["scene_extractions/logs/run.md"]["kind"] == "source_record"
