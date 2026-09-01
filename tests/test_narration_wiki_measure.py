from pathlib import Path

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
