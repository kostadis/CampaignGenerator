from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

import pytest

from campaignlib.planning_config import PlanningNoteSelector
from pipelines.summary_native.authority import (
    AuthorityError,
    AuthorityLedger,
    AudienceGrant,
    Classification,
    EffectiveInterval,
    NoteRecord,
    Projection,
    SubjectRef,
    validate_record_identity,
    write_ledger,
)
from pipelines.summary_native.authority_apply import authority_lock, prepare_transaction
from pipelines.summary_native.authority_inputs import build_manifest, resolve_anchored_records, resolve_selection
from pipelines.summary_native.cli import main
from pipelines.summary_native.freshness import audience_slug


def _note(
    *,
    grants: set[str] | frozenset[str] = frozenset({"gm"}),
    source: str = "notes/plan.md",
    subject: SubjectRef | None = None,
) -> NoteRecord:
    return NoteRecord(
        id="commission-current-plan",
        kind="note",
        revision=1,
        classification=Classification.PREP,
        subject=subject or SubjectRef(kind="thread", id="neverwinter-commission"),
        effective=EffectiveInterval(horizon="future"),
        audience=AudienceGrant(grants=grants),
        projections={Projection.PLANNING},
        status="active",
        recorded_at="2026-10-09T00:00:00Z",
        recorded_by="GM",
        source={"path": source, "anchor": "current-plan"},
        content_digest=hashlib.sha256(
            b"<!-- anchor: current-plan -->\nGM ONLY PLAN\n"
        ).hexdigest(),
        planning_date="chapter-54",
        selection_label="Current plan",
    )


def _campaign_with_ledger(tmp_path: Path, record: NoteRecord | None = None) -> AuthorityLedger:
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "plan.md").write_bytes(
        b"<!-- anchor: current-plan -->\nGM ONLY PLAN\n"
    )
    registry = tmp_path / "docs" / "thread_registry.yaml"
    registry.parent.mkdir()
    registry.write_text("threads:\n  - id: neverwinter-commission\n")
    ledger = AuthorityLedger(version=1, campaign="fixture", revision=1, records=[] if record is None else [record])
    write_ledger(tmp_path, ledger)
    return ledger


def test_gm_default_and_character_grants_are_exact():
    gm_record = _note()
    characters_record = _note(grants={"characters"})
    named_record = _note(grants={"character:ara"})

    assert gm_record.audience.allows("gm")
    assert not gm_record.audience.allows("players")
    assert characters_record.audience.allows("character:ara")
    assert characters_record.audience.allows("character:borin")
    assert not characters_record.audience.allows("players")
    assert named_record.audience.allows("character:ara")
    assert not named_record.audience.allows("character:borin")


def test_players_all_characters_and_named_character_grants_remain_distinct_across_intervals():
    players = _note(grants={"players"}).model_copy(update={"effective": EffectiveInterval(from_chapter=1, through_chapter=10)})
    all_characters = _note(grants={"characters"}).model_copy(update={"effective": EffectiveInterval(from_chapter=11, through_chapter=20)})
    named = _note(grants={"character:ara"}).model_copy(update={"effective": EffectiveInterval(from_chapter=21, through_chapter=30)})
    assert players.audience.allows("players") and not players.audience.allows("character:ara")
    assert all_characters.audience.allows("character:ara") and all_characters.audience.allows("character:borin")
    assert named.audience.allows("character:ara") and not named.audience.allows("players")
    assert not players.effective.overlaps(all_characters.effective)
    assert not all_characters.effective.overlaps(named.effective)


def test_named_audience_artifact_namespaces_preserve_exact_target_identity():
    targets = ("character:A B", "character:A-B", "character:a b", "character:a-b")
    slugs = [audience_slug(target) for target in targets]
    assert len(set(slugs)) == len(targets)
    assert all(slug.startswith("character-a-b-") for slug in slugs)


def test_identity_validation_requires_exact_registered_entity_thread_and_character_ids():
    fixture = Path(__file__).parent / "fixtures" / "summary_native" / "authority"
    for entity_id in ("Lucan", "Nightmask", "Neverwinter", "Sunblade"):
        validate_record_identity(fixture, _note(subject=SubjectRef(kind="entity", id=entity_id)))
    validate_record_identity(fixture, _note(subject=SubjectRef(kind="thread", id="neverwinter-commission")))
    # The grant names the character from the typed player's `plays` relation,
    # never the human player's own stable identifier.
    validate_record_identity(fixture, _note(grants={"character:ara"}))

    for record in (
        _note(subject=SubjectRef(kind="entity", id="unknown-npc")),
        _note(subject=SubjectRef(kind="thread", id="unknown-thread")),
        _note(grants={"character:ara-player"}),
        _note(grants={"character:unknown-player"}),
    ):
        with pytest.raises(AuthorityError, match="unknown|missing|identity"):
            validate_record_identity(fixture, record)


def test_identity_validation_allows_explicit_unregistered_topics():
    fixture = Path(__file__).parent / "fixtures" / "summary_native" / "authority"
    validate_record_identity(fixture, _note(subject=SubjectRef(kind="topic", id="unregistered-but-deliberate")))


def test_player_generation_receives_only_exact_player_grants(tmp_path: Path):
    ledger = _campaign_with_ledger(tmp_path, _note(grants={"players"}))
    assert [record.id for record in resolve_anchored_records(ledger, audience="players")] == ["commission-current-plan"]
    assert not resolve_anchored_records(ledger, audience="characters")


def test_player_preview_hides_external_paths_and_record_metadata(tmp_path: Path, capsys):
    external = tmp_path.parent / "external-player-note.md"
    content = b"<!-- anchor: current-plan -->\nPlayer plan.\n"
    external.write_bytes(content)
    record = _note(grants={"players"}, source=str(external))
    _campaign_with_ledger(tmp_path, record)
    # The explicit selector is deliberately external; players receive a
    # success/failure coverage answer, never the path or record identifier.
    assert main([
        "authority", "notes", "preview", "--campaign-dir", str(tmp_path),
        "--selector", f"outside={external}", "--audience", "players", "--json",
    ]) == 0
    payload = __import__("json").loads(capsys.readouterr().out)["data"]
    assert payload["members"] == [{"authorized": True, "reason": "selected support"}]
    assert str(external) not in str(payload)


def test_manifest_hashes_current_source_bytes_and_filtered_payload(tmp_path: Path):
    record = _note()
    _campaign_with_ledger(tmp_path, record)
    first = build_manifest(tmp_path, audience="gm")
    source = tmp_path / "notes" / "plan.md"
    source.write_bytes(b"<!-- anchor: current-plan -->\nGM ONLY PLAN, REVISED\n")
    ledger = AuthorityLedger(
        version=1,
        campaign="fixture",
        revision=2,
        records=[
            record.model_copy(
                update={
                    "revision": 2,
                    "content_digest": hashlib.sha256(
                        b"<!-- anchor: current-plan -->\nGM ONLY PLAN, REVISED\n"
                    ).hexdigest(),
                }
            )
        ],
    )
    write_ledger(tmp_path, ledger)
    second = build_manifest(tmp_path, audience="gm")

    assert first["records"][0]["source_sha256"] == hashlib.sha256(
        b"<!-- anchor: current-plan -->\nGM ONLY PLAN\n"
    ).hexdigest()
    assert second["records"][0]["source_sha256"] == hashlib.sha256(
        b"<!-- anchor: current-plan -->\nGM ONLY PLAN, REVISED\n"
    ).hexdigest()
    assert first["filtered_payload_sha256"] != second["filtered_payload_sha256"]


@pytest.mark.parametrize("source", ["notes/missing.md", "notes"])
def test_manifest_refuses_missing_or_unreadable_record_source(tmp_path: Path, source: str):
    _campaign_with_ledger(tmp_path, _note(source=source))
    with pytest.raises(AuthorityError, match="source.*missing|source.*unreadable|source.*not a file"):
        build_manifest(tmp_path, audience="gm")


def test_manifest_read_waits_for_writer_lock_and_refuses_pending_transaction(tmp_path: Path):
    _campaign_with_ledger(tmp_path, _note())
    completed = threading.Event()

    def reader() -> None:
        build_manifest(tmp_path, audience="gm")
        completed.set()

    with authority_lock(tmp_path, exclusive=True):
        thread = threading.Thread(target=reader)
        thread.start()
        time.sleep(0.05)
        assert not completed.is_set()
    thread.join(timeout=1)
    assert completed.is_set()

    target = tmp_path / "docs" / "summaries" / "chapter-001.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    prepare_transaction(tmp_path, proposal_id="rule-r1", proposal_sha256="a" * 64, targets=[(target, b"before", b"after")])
    with pytest.raises(AuthorityError, match="recover"):
        build_manifest(tmp_path, audience="gm")


def test_selector_globs_union_aliases_and_disclose_external_members(tmp_path: Path):
    (tmp_path / "notes").mkdir()
    note = tmp_path / "notes" / "commission.md"
    note.write_text("Commission plan")
    alias = tmp_path / "notes" / "commission-alias.md"
    alias.symlink_to(note)
    external = tmp_path.parent / "authority-external-note.md"
    external.write_text("External but selected")
    selectors = [
        PlanningNoteSelector(id="primary", path="notes/*.md", record_ids={"one"}),
        PlanningNoteSelector(id="alias", path="notes/commission-alias.md", record_ids={"two"}),
        PlanningNoteSelector(id="external", path=str(external), record_ids={"outside"}),
    ]

    snapshot = resolve_selection(tmp_path, selectors)
    assert len(snapshot.members) == 2
    selected = next(member for member in snapshot.members if Path(member.resolved_path) == note.resolve())
    assert selected.record_ids == ("one", "two")
    assert selected.selector_id == "alias,primary"
    assert next(member for member in snapshot.members if member.external).resolved_path == str(external.resolve())


@pytest.mark.parametrize("selector", [
    PlanningNoteSelector(id="missing", path="notes/missing.md"),
    PlanningNoteSelector(id="empty-glob", path="notes/*.md"),
])
def test_configured_selector_missing_or_zero_match_refuses(tmp_path: Path, selector: PlanningNoteSelector):
    with pytest.raises(AuthorityError, match="matched no notes|unreadable"):
        resolve_selection(tmp_path, [selector])
