"""Staleness of the chunked notes and the audit (spec 033 T009). No model call."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipelines.summary_native import freshness, schema


@pytest.fixture
def world(tmp_path):
    range_dir = tmp_path / "out" / "ch002-005"
    (range_dir / schema.STATE_DIR / "notes").mkdir(parents=True)
    (range_dir / "manifest.json").write_text('{"corpus": 1}', encoding="utf-8")
    registry = tmp_path / "entity_registry.yaml"
    registry.write_text("version: 1\nentities: []\n", encoding="utf-8")
    players = tmp_path / "players.yaml"
    players.write_text("players: []\n", encoding="utf-8")
    t1, t2 = tmp_path / "tracking.txt", tmp_path / "tracking2.txt"
    t1.write_text("- one\n", encoding="utf-8")
    t2.write_text("- two\n", encoding="utf-8")
    return range_dir, registry, players, [t1, t2]


def _write_notes_manifest(range_dir, registry, players, **override):
    m = {"kind": "state_notes", **freshness.notes_manifest_facts(range_dir, registry, players), **override}
    p = range_dir / schema.STATE_DIR / "notes" / "manifest.json"
    p.write_text(json.dumps(m, sort_keys=True), encoding="utf-8")
    return p


class TestNotesFresh:
    def test_no_manifest_names_the_extract_command(self, world):
        range_dir, registry, players, _ = world
        msg = freshness.check_notes_fresh(range_dir, registry, players)
        assert msg and "summary_native extract" in msg and "no checked notes" in msg

    def test_matching_manifest_is_fresh(self, world):
        range_dir, registry, players, _ = world
        _write_notes_manifest(range_dir, registry, players)
        assert freshness.check_notes_fresh(range_dir, registry, players) is None

    @pytest.mark.parametrize("which,what", [("corpus", "corpus"), ("registry", "registry"), ("players", "players")])
    def test_each_input_changing_makes_it_stale_and_names_the_command(self, world, which, what):
        range_dir, registry, players, _ = world
        _write_notes_manifest(range_dir, registry, players)
        target = {"corpus": range_dir / "manifest.json", "registry": registry, "players": players}[which]
        target.write_text(target.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        msg = freshness.check_notes_fresh(range_dir, registry, players)
        assert msg and what in msg and "summary_native extract" in msg

    def test_an_absent_registry_and_players_are_a_stable_none(self, world):
        range_dir, _, _, _ = world
        _write_notes_manifest(range_dir, None, None)
        assert freshness.check_notes_fresh(range_dir, None, None) is None
        # a registry appearing later is a change
        reg = range_dir.parent / "new_registry.yaml"
        reg.write_text("version: 1\nentities: []\n", encoding="utf-8")
        assert "registry" in freshness.check_notes_fresh(range_dir, reg, None)

    def test_an_unreadable_or_foreign_manifest_refuses(self, world):
        range_dir, registry, players, _ = world
        p = _write_notes_manifest(range_dir, registry, players)
        p.write_text("{not json", encoding="utf-8")
        assert "unreadable" in freshness.check_notes_fresh(range_dir, registry, players)
        p.write_text(json.dumps({"kind": "npc_link"}), encoding="utf-8")
        assert "not a state-notes manifest" in freshness.check_notes_fresh(range_dir, registry, players)

    def test_dossiers_are_deliberately_not_an_input(self, world):
        range_dir, registry, players, _ = world
        facts = freshness.notes_manifest_facts(range_dir, registry, players)
        assert set(facts) == {"corpus_manifest_sha256", "registry_sha256", "players_sha256"}


def _write_items(range_dir, tracks, notes_sha, **override):
    d = range_dir / schema.STATE_DIR / "audit"
    d.mkdir(parents=True, exist_ok=True)
    m = {"track_files_sha256": freshness.track_files_facts(tracks), "notes_manifest_sha256": notes_sha, **override}
    (d / "items.json").write_text(json.dumps(m, sort_keys=True), encoding="utf-8")


class TestAuditFresh:
    def test_no_audit_is_not_a_refusal(self, world):
        """Absent means "Audit not run for this range"; only a stale one refuses."""
        range_dir, _, _, tracks = world
        assert freshness.check_audit_fresh(range_dir, tracks) is None
        assert freshness.audit_exists(range_dir) is False

    def test_matching_is_fresh(self, world):
        range_dir, registry, players, tracks = world
        p = _write_notes_manifest(range_dir, registry, players)
        _write_items(range_dir, tracks, freshness.sha_file(p))
        assert freshness.audit_exists(range_dir)
        assert freshness.check_audit_fresh(range_dir, tracks) is None

    def test_a_changed_track_file_refuses_naming_audit(self, world):
        range_dir, registry, players, tracks = world
        p = _write_notes_manifest(range_dir, registry, players)
        _write_items(range_dir, tracks, freshness.sha_file(p))
        tracks[1].write_text("- two\n- three\n", encoding="utf-8")
        msg = freshness.check_audit_fresh(range_dir, tracks)
        assert msg and "tracking2.txt" in msg and "summary_native audit" in msg

    def test_an_added_or_removed_track_file_refuses(self, world):
        range_dir, registry, players, tracks = world
        p = _write_notes_manifest(range_dir, registry, players)
        _write_items(range_dir, tracks, freshness.sha_file(p))
        assert "summary_native audit" in freshness.check_audit_fresh(range_dir, tracks[:1])
        extra = range_dir.parent / "tracking3.txt"
        extra.write_text("- x\n", encoding="utf-8")
        assert "summary_native audit" in freshness.check_audit_fresh(range_dir, [*tracks, extra])

    def test_new_notes_refuse(self, world):
        range_dir, registry, players, tracks = world
        p = _write_notes_manifest(range_dir, registry, players)
        _write_items(range_dir, tracks, freshness.sha_file(p))
        _write_notes_manifest(range_dir, registry, players, chunks=["re-extracted"])
        msg = freshness.check_audit_fresh(range_dir, tracks)
        assert msg and "notes" in msg and "summary_native audit" in msg

    def test_the_facts_are_stable_and_order_independent(self, world):
        _, _, _, tracks = world
        a = freshness.track_files_facts(tracks)
        b = freshness.track_files_facts(list(reversed(tracks)))
        assert a == b == sorted(a)
        assert all(not Path(name).is_absolute() for name, _ in a)
