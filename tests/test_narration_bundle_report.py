"""File-shape and atomic run-report contracts for bundled narration."""

import json
from pathlib import Path

import pytest

from session_doc.narrate import BundleSelection, NarrationScene
from session_doc import sd_narrate


def _scene(tmp_path: Path, index: int = 1, *, source_kind: str = "base",
           output_existed: bool = False) -> NarrationScene:
    return NarrationScene(
        index=index, scene_name="Arrival", narrator="Alice", focus="water",
        source_path=tmp_path / "sources" / f"{index:02d}_arrival.md",
        source_kind=source_kind, scene_events="entered", moments='Alice: "Wait."',
        voice_note=None, character_examples=None, previous_narrator=None,
        previous_voice_sample=None, estimated_output_tokens=500,
        output_path=tmp_path / "out" / f"session_doc_scene_{index:02d}_arrival.md",
        output_existed=output_existed,
    )


def test_shared_path_formatter_and_atomic_writer_preserve_legacy_file_shape(tmp_path):
    path = sd_narrate._narration_output_path(tmp_path, 2, "The Bargain", "Bob")
    assert path.name == "session_doc_scene_02_the_bargain.md"

    sd_narrate._write_narration_output(
        path, index=2, scene_name="The Bargain", narrator="Bob",
        session_id="20260905", narration="  I paid the price.  ",
    )

    assert path.read_text(encoding="utf-8") == (
        "---\nscene: 02\nslug: the_bargain\nnarrator: Bob\n"
        "scene_name: The Bargain\nsession: 20260905\n---\n\nI paid the price.\n"
    )
    assert list(tmp_path.glob("*.tmp.*")) == []


def test_scene_source_kind_is_explicit_provenance_not_a_directory_guess(tmp_path):
    with pytest.raises(ValueError, match="source_kind"):
        _scene(tmp_path, source_kind="smoothed")


def test_explicit_report_stem_is_run_id_and_schema_records_base_override(tmp_path):
    base = _scene(tmp_path, 1)
    override = _scene(tmp_path, 2, source_kind="override", output_existed=True)
    selection = BundleSelection((base, override), bundle_ceiling=32000)
    report = tmp_path / "reports" / "editor-nonce-42.json"

    sd_narrate._write_bundle_report(
        report, status="success", exit_code=0, backend="claude-code",
        model="model", selection=selection, exchange_count=1,
        written=[base, override], message="done",
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["run_id"] == "editor-nonce-42"
    assert payload["mode"] == "bundle"
    assert [item["source_kind"] for item in payload["requested"]] == [
        "base", "override"
    ]
    assert [item["index"] for item in payload["replaced"]] == [2]
    assert [item["index"] for item in payload["written"]] == [1, 2]
    assert "source_kind" not in payload["written"][0]
    assert payload["exchange_count"] == 1
    assert payload["report_path"] == str(report.resolve())
    assert not report.with_name(f"{report.name}.tmp").exists()


@pytest.mark.parametrize(
    ("status", "exit_code", "exchange_count", "missing", "rejected"),
    [
        ("partial", 3, 1, [{"index": 1, "reason": "empty"}], []),
        ("unreconcilable", 4, 1, [], [{"code": "OUT_OF_ORDER"}]),
        ("refused", 1, 0, [], [{"code": "CAPACITY"}]),
        ("failed", 1, 1, [], [{"code": "BACKEND"}]),
    ],
)
def test_terminal_reports_cover_partial_refusal_protocol_and_backend_failures(
    tmp_path, status, exit_code, exchange_count, missing, rejected,
):
    scene = _scene(tmp_path)
    report = tmp_path / f"{status}.json"
    sd_narrate._write_bundle_report(
        report, status=status, exit_code=exit_code, backend="test", model=None,
        selection=BundleSelection((scene,), 1000), exchange_count=exchange_count,
        written=[], missing=missing, rejected=rejected, message=status,
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == status
    assert payload["exit_code"] == exit_code
    assert payload["exchange_count"] == exchange_count
    assert payload["written"] == []
    assert payload["missing"] == missing
    assert payload["rejected"] == rejected


def test_default_latest_report_gets_generated_run_id(tmp_path):
    scene = _scene(tmp_path)
    report = tmp_path / "sd_narrate_bundle_latest.json"
    sd_narrate._write_bundle_report(
        report, status="partial", exit_code=3, backend="test", model=None,
        selection=BundleSelection((scene,), 1000), exchange_count=1,
        written=[], missing=[{"index": 1, "reason": "incomplete"}],
    )

    run_id = json.loads(report.read_text(encoding="utf-8"))["run_id"]
    assert run_id
    assert run_id != report.stem
