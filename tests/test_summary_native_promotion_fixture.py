from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import yaml

from pipelines.summary_native.authority import load_ledger
from pipelines.summary_native.authority_apply import validate_ledger_tip
from pipelines.summary_native.pointers import check_paths
from pipelines.summary_native.review.documents import _check_document, create_document_review
from pipelines.summary_native.review.store import load_campaign_identity, read_snapshot


SCRIPT = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
SPEC = importlib.util.spec_from_file_location("promotion_fixture_factory", SCRIPT)
assert SPEC and SPEC.loader
FACTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FACTORY)


def _tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def test_legacy_fixture_is_complete_deterministic_and_has_diff_shapes(tmp_path: Path):
    first = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    second = FACTORY.create_campaign(tmp_path / "same" / "campaign", baseline="legacy")
    # Review identity deliberately binds the canonical root; all other fixture
    # bytes are stable regardless of where a disposable copy is created.
    left, right = _tree(first), _tree(second)
    left.pop("docs/reviews/campaign.json")
    right.pop("docs/reviews/campaign.json")
    assert left == right

    drafts = first / "docs/summary_native/ch001-003/state/drafts"
    assert {p.name for p in drafts.glob("*.draft.md")} == {
        "world_state.draft.md", "campaign_state.draft.md", "party.draft.md", "planning.draft.md"
    }
    assert 190_000 <= (drafts / "planning.draft.md").stat().st_size <= 230_000
    assert (drafts / "canon_events_timeline.md").is_file()
    assert (drafts / "reference/nested/deeper/provenance.md").is_file()
    assert {
        "factions.md", "npcs.md", "locations.md", "items.md", "threats.md",
        "threads.md", "party.md", "threads_unratified.md",
    } <= {path.name for path in (drafts / "reference").glob("*.md")}
    for document in FACTORY.DOCUMENTS:
        assert (first / f"docs/summary_native/ch001-003/state/runs/run-{document}/record.json").is_file()

    metadata = json.loads((first / "fixture.json").read_text())
    assert metadata["changed_members"] and metadata["removed_members"] and metadata["added_members"]
    assert (first / "docs/reference/obsolete/old-watch.md").is_file()
    assert not (drafts / "reference/obsolete/old-watch.md").exists()
    assert (drafts / "reference/new/eastern-survey.md").is_file()
    assert not (first / "docs/reference/new/eastern-survey.md").exists()

    assert load_ledger(first).version == 2
    validate_ledger_tip(first)
    assert load_campaign_identity(first).campaign_id == FACTORY.CAMPAIGN_ID
    config = yaml.safe_load((first / "config/config.yaml").read_text())
    assert config["campaign"] == "promotion-fixture"
    assert config["documents"] == [
        {"label": "world_state", "path": "../docs/world_state.md"},
        {"label": "campaign_state", "path": "../docs/campaign_state.md"},
        {"label": "party", "path": "../docs/party.md"},
        {"label": "planning", "path": "../docs/planning.md"},
    ]
    for document in FACTORY.DOCUMENTS:
        assert check_paths(first / f"docs/{document}.md", first) == []

    create_document_review(
        first, "document-validation", first / "selections/promotion-documents.json", created_by="fixture-test"
    )
    _manifest, _custody, items = read_snapshot(first, "document-validation")
    checked = {_check_document(first, item)[2]["doc"] for item in items}
    assert checked == set(FACTORY.DOCUMENTS)


def test_pristine_fixture_has_no_live_managed_members(tmp_path: Path):
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="pristine")
    assert not any((root / "docs" / f"{name}.md").exists() for name in FACTORY.DOCUMENTS)
    assert not (root / "docs/canon_events_timeline.md").exists()
    assert not (root / "docs/reference").exists()
    assert (root / "docs/summary_native/ch001-003/state/drafts/reference/nested/deeper/provenance.md").is_file()


def test_factory_refuses_nonempty_destination(tmp_path: Path):
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "keep.txt").write_text("do not replace")
    try:
        FACTORY.create_campaign(root)
    except ValueError as exc:
        assert "not empty" in str(exc)
    else:
        raise AssertionError("factory replaced a nonempty destination")
    assert (root / "keep.txt").read_text() == "do not replace"
