from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from pipelines.summary_native.authority import (
    AuthorityError, AuthorityLedger, AudienceGrant, Classification,
    EffectiveInterval, NoteRecord, Projection, SubjectRef, canonical_bytes, load_ledger,
)


def _note(record_id: str = "commission-current-plan") -> NoteRecord:
    return NoteRecord(
        id=record_id, kind="note", revision=1, classification=Classification.PREP,
        subject=SubjectRef(kind="thread", id="neverwinter-commission"),
        effective=EffectiveInterval(horizon="future"), audience=AudienceGrant(grants={"gm"}),
        projections={Projection.PLANNING}, status="active", recorded_at="2026-10-09T00:00:00Z",
        recorded_by="GM", source={"path": "notes/plan.md", "anchor": "current-plan"},
        content_digest="a" * 64, planning_date="chapter-54", selection_label="Current plan",
    )


def test_note_model_rejects_unknown_fields_and_empty_audience():
    with pytest.raises(Exception):
        _note().model_copy(update={"unexpected": True}).model_validate({**_note().model_dump(), "unexpected": True})
    with pytest.raises(Exception):
        AudienceGrant(grants=set())


def test_ledger_refuses_duplicate_records_and_bad_intervals():
    note = _note()
    with pytest.raises(Exception, match="duplicate authority record"):
        AuthorityLedger(version=2, campaign="fixture", revision=1, records=[note, note])
    with pytest.raises(Exception, match="before"):
        EffectiveInterval(from_chapter=4, through_chapter=3)


def test_duplicate_yaml_key_refuses(tmp_path: Path):
    path = tmp_path / "docs" / "authority.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("version: 1\ncampaign: fixture\ncampaign: duplicate\nrevision: 1\nrecords: []\nconflicts: []\n")
    with pytest.raises(AuthorityError, match="duplicate YAML key"):
        load_ledger(tmp_path)


def test_authority_fixture_is_a_strict_mixed_classification_workspace():
    fixture = Path(__file__).parent / "fixtures" / "summary_native" / "authority"
    ledger = load_ledger(fixture, expected_campaign="authority-fixture")
    assert {record.classification for record in ledger.records} == {
        Classification.RULED,
        Classification.CANON,
        Classification.TABLE,
        Classification.PREP,
        Classification.OVERLAY,
        Classification.OPEN,
    }
    assert {projection for record in ledger.records for projection in record.projections} == set(Projection)


def test_character_grant_does_not_grant_players_but_allows_each_character():
    audience = AudienceGrant(grants={"characters"})
    assert audience.allows("character:ara")
    assert not audience.allows("players")


def test_canonical_bytes_sorts_audience_grants_across_hash_seeds():
    """Canonical serialized objects cannot inherit frozenset iteration order."""
    script = """
from pipelines.summary_native.authority import AudienceGrant, canonical_bytes
print(canonical_bytes(AudienceGrant(grants=frozenset({'gm', 'players', 'characters', 'character:ara'}))).decode(), end='')
"""
    outputs = []
    for seed in ("1", "2", "1007"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(Path.cwd())}
        outputs.append(subprocess.check_output([sys.executable, "-c", script], cwd=Path.cwd(), env=env))

    assert outputs[0] == outputs[1] == outputs[2]
    assert outputs[0] == canonical_bytes(AudienceGrant(grants={"gm", "players", "characters", "character:ara"}))
