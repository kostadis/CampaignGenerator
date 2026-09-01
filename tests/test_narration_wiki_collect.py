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
