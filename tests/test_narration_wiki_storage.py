import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from session_doc.narration_wiki.collect import collect
from session_doc.narration_wiki.measure import measure
from session_doc.narration_wiki.models import StateError
from session_doc.narration_wiki.paths import resolve_scope
from session_doc.narration_wiki.storage import (
    _transaction_id,
    read_json,
    record_conflict_ruling,
    record_pattern_ruling,
    recover_transactions,
)


FIXTURES = Path(__file__).parent / "fixtures" / "narration_wiki" / "gate1"


def prepared_scope(tmp_path: Path):
    campaign = tmp_path / "campaign"
    session = campaign / "sessions" / "one"
    (campaign / "config").mkdir(parents=True)
    (campaign / "voice").mkdir()
    (campaign / "voice" / "_genre.md").write_text("# Rules\n")
    (campaign / "config" / "session_doc.yaml").write_text(yaml.safe_dump({"paths": {"genre_file": "voice/_genre.md"}}))
    (session / "narration").mkdir(parents=True)
    (session / "narration" / "Aria.md").write_text("## Aria — One\n\nA concrete scene consequence.\n")
    scope = resolve_scope(campaign, session, "iter-001")
    collect(scope)
    measure(scope, "before")
    drafts = scope.iteration_root / "drafts"
    conflicts = scope.iteration_root / "conflict-drafts"
    drafts.mkdir()
    conflicts.mkdir()
    shutil.copy2(FIXTURES / "distinct-bookkeeping.md", drafts / "distinct-bookkeeping.md")
    shutil.copy2(FIXTURES / "seed-voice.json", conflicts / "seed-voice.json")
    return scope


def test_conflict_blocks_gate1_until_one_durable_gm_ruling(tmp_path):
    scope = prepared_scope(tmp_path)
    with pytest.raises(StateError, match="unresolved"):
        record_pattern_ruling(scope, "distinct-bookkeeping", "accept", tier="campaign")
    result = record_conflict_ruling(scope, "seed-voice", "Use campaign source", "Campaign authority wins here")
    durable = scope.campaign_root / result["ruling"]["path"]
    assert durable.is_file()
    accepted = record_pattern_ruling(scope, "distinct-bookkeeping", "accept", tier="campaign")
    assert accepted["status"] == "accepted"
    assert (scope.campaign_wiki_root / "patterns" / "distinct-bookkeeping.md").is_file()
    assert "distinct-bookkeeping" in (scope.campaign_wiki_root / "index.md").read_text()
    with pytest.raises(StateError, match="already"):
        record_pattern_ruling(scope, "distinct-bookkeeping", "reject", tier=None)


def test_recovery_commits_a_fully_written_nonterminal_journal_idempotently(tmp_path):
    scope = prepared_scope(tmp_path)
    record_conflict_ruling(scope, "seed-voice", "Use campaign source", "Because this campaign owns the rule")
    journal = next((scope.iteration_root / "transactions").glob("*.json"))
    value = read_json(journal)
    value["state"] = "target_done"
    journal.write_text(__import__("json").dumps(value, sort_keys=True, indent=2) + "\n")
    assert recover_transactions(scope) is None
    assert read_json(journal)["state"] == "committed"
    assert recover_transactions(scope) is None


def test_rejecting_a_pattern_does_not_require_its_conflicts_to_be_ruled_first(tmp_path):
    """A rejection is not blocked by an open conflict, so it must not crash on one.

    Only an acceptance inherits the conflict, and building the ruling references
    unconditionally raised a bare KeyError that the CLI reported as exit 70 and
    the router as a 500 -- leaving a GM unable to reject until every conflict the
    pattern names had already been ruled.
    """
    scope = prepared_scope(tmp_path)
    result = record_pattern_ruling(scope, "distinct-bookkeeping", "reject", tier=None)
    assert result["decision"] == "reject"
    ruling = read_json(scope.iteration_root / "gate1.json")["rulings"][0]
    assert ruling["ruling"] == "rejected"
    assert ruling["conflict_ruling_refs"] == []


def test_truncated_transaction_ids_stay_distinct(tmp_path):
    """Two subjects sharing a 64-character prefix must not share one journal."""
    scope = prepared_scope(tmp_path)
    long_scope = replace(scope, iteration_id="i" * 40)
    shared = "a" * 40
    first = _transaction_id(long_scope, "gate1-campaign", f"{shared}-one")
    second = _transaction_id(long_scope, "gate1-campaign", f"{shared}-two")
    assert len(first) <= 64 and len(second) <= 64
    assert first != second
