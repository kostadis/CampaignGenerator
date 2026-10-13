"""Promotion accepts the run records ``summary_native synth`` really writes.

The promotion fixture writes ``check: "passed"`` and always a thread-registry digest. Real synth
records ``check`` as ``{"complete": ..., "problems": [...]}`` and a null thread digest when it ran
with no registry, so a real bundle was refused as "retained run record is incomplete" and
"run record has no valid thread registry digest".
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from pipelines.summary_native.promotion.errors import PromotionPathError
from pipelines.summary_native.promotion.gates import synth_record_complete
from pipelines.summary_native.promotion.manifest import _record_and_dependencies


FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
FACTORY_SPEC = importlib.util.spec_from_file_location("promotion_synth_records_fixture_factory", FACTORY_PATH)
assert FACTORY_SPEC and FACTORY_SPEC.loader
FACTORY = importlib.util.module_from_spec(FACTORY_SPEC)
FACTORY_SPEC.loader.exec_module(FACTORY)


@pytest.mark.parametrize("check, expected", [
    ({"complete": True, "problems": []}, True),
    ({"complete": False, "problems": ["## Locations: missing"]}, False),
    ({"complete": True, "problems": ["## Locations: missing"]}, False),
    ({"complete": False, "error": "model call failed"}, False),
    ("not run", False),
    ("passed", True),
])
def test_synth_record_complete_reads_the_check_synth_writes(check, expected):
    assert synth_record_complete({"step": "synth", "check": check}) is expected


def test_a_record_from_another_step_is_never_complete():
    assert synth_record_complete({"step": "extract", "check": {"complete": True, "problems": []}}) is False


@pytest.fixture
def campaign_state_with_null_thread_digest(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    state = root / "docs/summary_native/ch001-003/state"
    record_path = state / "runs/run-campaign_state/record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["inputs"]["thread_registry_sha256"] = None
    record["check"] = {"complete": True, "problems": []}
    record_path.write_text(json.dumps(record), encoding="utf-8")
    return root, state / "drafts/campaign_state.draft.md", state


def test_a_null_thread_digest_binds_while_there_is_still_no_registry(campaign_state_with_null_thread_digest):
    root, draft, state = campaign_state_with_null_thread_digest
    (root / "docs/thread_registry.yaml").unlink()
    _, dependencies = _record_and_dependencies(root, draft, state)
    assert "docs/thread_registry.yaml" not in {item.path for item in dependencies}


def test_a_null_thread_digest_is_stale_once_a_registry_exists(campaign_state_with_null_thread_digest):
    root, draft, state = campaign_state_with_null_thread_digest
    with pytest.raises(PromotionPathError, match="thread registry dependency is stale"):
        _record_and_dependencies(root, draft, state)
