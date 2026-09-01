import json
from pathlib import Path

import pytest
import yaml

jsonschema = pytest.importorskip("jsonschema")
ROOT = Path(__file__).parents[1]
CONTRACTS = ROOT / "specs/020-narration-wiki/contracts"


def _schema(name):
    return json.loads((CONTRACTS / name).read_text())


def test_companion_fixture_validates_against_checked_in_schema():
    value = yaml.safe_load((ROOT / "tests/fixtures/narration_wiki/portable/capabilities-valid.yaml").read_text())
    jsonschema.validate(value, _schema("companion-capability.schema.json"))


def test_usability_contract_pins_viewport_and_panel_minimum():
    schema = _schema("usability-result.schema.json")
    viewport = schema["properties"]["viewport"]["properties"]
    panel = schema["properties"]["minimum_panel"]["properties"]
    assert viewport["width"]["const"] == 1280 and viewport["height"]["const"] == 720
    assert panel["width"]["const"] == 320 and panel["height"]["const"] == 160


def test_representative_runtime_artifacts_validate(tmp_path):
    from session_doc.narration_wiki.storage import record_conflict_ruling
    from tests.test_narration_wiki_storage import prepared_scope

    scope = prepared_scope(tmp_path)
    jsonschema.validate(
        json.loads((scope.iteration_root / "trace-manifest.json").read_text()),
        _schema("manifest.schema.json"),
    )
    jsonschema.validate(
        json.loads((scope.iteration_root / "measurement-before.json").read_text()),
        _schema("measurement.schema.json"),
    )
    result = record_conflict_ruling(
        scope, "seed-voice", "Use the campaign source", "The campaign owns named guidance",
    )
    jsonschema.validate(
        json.loads((scope.campaign_root / result["ruling"]["path"]).read_text()),
        _schema("conflict-ruling.schema.json"),
    )


def test_persisted_usability_result_validates():
    value = json.loads((ROOT / "specs/020-narration-wiki/validation/usability-result.json").read_text())
    jsonschema.validate(value, _schema("usability-result.schema.json"), format_checker=jsonschema.FormatChecker())
