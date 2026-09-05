from pathlib import Path

import pytest
import yaml

from session_doc.narration_wiki.collect import collect
from session_doc.narration_wiki.measure import measure
from session_doc.narration_wiki.paths import resolve_scope
from session_doc.narration_wiki.storage import read_json


def _scope(tmp_path: Path):
    campaign = tmp_path / "campaign"
    session = campaign / "sessions" / "one"
    (campaign / "config").mkdir(parents=True)
    (campaign / "voice").mkdir()
    (campaign / "voice" / "_genre.md").write_text(
        "# Rules\n\n```yaml voice_lint\nbookkeeping:\n  licensed: [aria]\n  unlicensed: [blaise]\n  per_section_cap: 1\n  doc_sections_cap: 2\n```\n"
    )
    (campaign / "config" / "session_doc.yaml").write_text(yaml.safe_dump({"paths": {"genre_file": "voice/_genre.md"}}))
    (session / "narration").mkdir(parents=True)
    shared = "the silver bell crossed the empty room"
    (session / "narration" / "Aria.md").write_text(f"## Aria — One\n\nI file this. {shared}.\n")
    (session / "narration" / "Blaise.md").write_text(f"## Blaise — One\n\nThe shape of fear — {shared}.\n")
    return resolve_scope(campaign, session, "iter-001")


def test_d4_measurement_is_byte_identical_and_evidence_only(tmp_path):
    scope = _scope(tmp_path)
    collect(scope)
    first = measure(scope, "before")
    raw = (scope.iteration_root / "measurement-before.json").read_bytes()
    second = measure(scope, "before")
    assert raw == (scope.iteration_root / "measurement-before.json").read_bytes()
    snapshot = read_json(scope.iteration_root / "measurement-before.json")
    assert {row["key"] for row in snapshot["checks"]} == {
        "shape_of", "portable_portrait", "taxonomy", "filing_sections", "bookkeeping_per_narrator", "em_dash",
    }
    assert any(row["verdict"] == "breach" for row in snapshot["checks"])
    assert snapshot["cross_narrator_reuse"]
    assert read_json(scope.iteration_root / "iteration.json")["state"] == "measured_before"


def test_scene_headings_never_become_narrator_identities(tmp_path):
    """The manifest declares the narrator; a "## ..." line is a section, not a speaker.

    Reading an identity off a heading filed each scene of a document as its own
    narrator, so two scenes by the same narrator were reported as cross-narrator
    voice bleed and occurrence rows carried scene titles as speaker names.
    """
    campaign = tmp_path / "campaign"
    session = campaign / "sessions" / "one"
    (campaign / "config").mkdir(parents=True)
    (campaign / "voice").mkdir()
    (campaign / "voice" / "_genre.md").write_text(
        "# Rules\n\n```yaml voice_lint\nbookkeeping:\n  licensed: [aria]\n  unlicensed: []\n"
        "  per_section_cap: 1\n  doc_sections_cap: 2\n```\n"
    )
    (campaign / "config" / "session_doc.yaml").write_text(yaml.safe_dump({"paths": {"genre_file": "voice/_genre.md"}}))
    (session / "narration").mkdir(parents=True)
    shared = "the silver bell crossed the empty room"
    (session / "narration" / "Aria.md").write_text(
        f"## The Cavern\n\nI file this. {shared}.\n\n## Scene Two\n\nAgain: {shared}.\n"
    )
    scope = resolve_scope(campaign, session, "iter-001")
    collect(scope)
    measure(scope, "before")
    snapshot = read_json(scope.iteration_root / "measurement-before.json")

    assert snapshot["cross_narrator_reuse"] == []
    narrators = {
        row["narrator"]
        for check in snapshot["checks"]
        for row in check["occurrences"]
    }
    assert narrators <= {"Aria"}


def test_a_conflict_ruling_also_freezes_the_baseline(tmp_path):
    """Conflict rulings bind the baseline hash, so they must guard it too.

    record_conflict_ruling writes conflict-rulings.json, never gate1.json, so a
    guard that consulted gate1.json alone let a re-measure rewrite the baseline
    and leave every persisted ConflictRuling.baseline pointing at a dead hash.
    """
    import shutil

    from session_doc.narration_wiki.models import StateError
    from session_doc.narration_wiki.storage import record_conflict_ruling

    fixtures = Path(__file__).parent / "fixtures" / "narration_wiki" / "gate1"
    scope = _scope(tmp_path)
    collect(scope)
    measure(scope, "before")
    (scope.iteration_root / "conflict-drafts").mkdir()
    shutil.copy2(fixtures / "seed-voice.json", scope.iteration_root / "conflict-drafts" / "seed-voice.json")
    record_conflict_ruling(scope, "seed-voice", "Use campaign source", "The campaign owns this rule")

    # The corpus is hash-pinned to the manifest, so the baseline moves when the
    # rulebook the measurement is taken against does.
    genre = scope.campaign_root / "voice" / "_genre.md"
    genre.write_text(genre.read_text() + "\nOne more hand-edited rule.\n")
    with pytest.raises(StateError, match="baseline drift"):
        measure(scope, "before")


def test_collected_evidence_survives_deleted_live_narration(tmp_path):
    """Collected evidence remains addressable by its exact hash after rerenders."""
    scope = _scope(tmp_path)
    collect(scope)
    before = measure(scope, phase="before")
    manifest = read_json(scope.iteration_root / "trace-manifest.json")
    for relative in manifest["measurement_corpus"]:
        (scope.session_root / relative).unlink()
    after = measure(scope, phase="before")
    assert before == after
