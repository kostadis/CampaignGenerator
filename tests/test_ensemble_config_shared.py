"""Schema + load/save tests for server/ensemble_config_shared.py.

Phase 1 of docs/config/ensemble-isolation.md. Pure model tests — no service,
no HTTP, no filesystem beyond a tmp_path round-trip.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.ensemble_config_shared import (
    EnsembleBackend,
    EnsembleConfig,
    EnsemblePlanning,
    load_ensemble_config,
    save_ensemble_config,
)


# ── Defaults: the values Phase 3 deletes from the route signatures ─────────

class TestDefaults:
    def test_all_defaults_construct(self):
        cfg = EnsembleConfig()
        assert cfg.chapters_selected == []

    def test_path_defaults_match_the_shipped_route_literals(self):
        """Phase 1 must not change behavior — these are transcribed from
        server/routers/ensemble.py's route signatures. If Phase 3 changes one
        of these, that is a behavior change and this test should be the thing
        that notices."""
        p = EnsembleConfig().paths
        assert p.chapters_glob == "docs/chapters/chapter_*.md"
        assert p.per_chapter_dir == "docs/ensemble/per_chapter"
        assert p.corpus_glob == "docs/ensemble/per_chapter/*/merged.json"
        assert p.merged_out == "docs/ensemble/merged.json"
        assert p.state_dossiers_dir == "docs/ensemble/state_dossiers"
        assert p.dossiers_glob == "docs/ensemble/merged_dossiers/*.md"
        assert p.threads_out == "docs/ensemble/threads.md"
        assert p.recent_events_out == "docs/recent_events.md"

    def test_inventory_path_defaults_to_empty_string(self):
        """Empty means 'don't pass --inventory', not 'unset'."""
        assert EnsembleConfig().paths.inventory == ""

    def test_tuning_defaults_match_the_shipped_route_literals(self):
        t = EnsembleConfig().tuning
        assert t.chapter_parallel == 3
        assert t.chunk_parallel == 4
        assert t.dossier_min_facts == 10
        assert t.entity_parallel == 0
        assert t.recent_events_window == 0

    def test_bundle_and_threads_min_facts_stay_distinct(self):
        """/run/bundle defaults to 3, /run/threads to 2. Collapsing them into
        one field would be a silent behavior change."""
        t = EnsembleConfig().tuning
        assert t.bundle_min_facts == 3
        assert t.threads_min_facts == 2

    def test_backend_default_is_anthropic_with_no_endpoints(self):
        b = EnsembleConfig().extract
        assert b.backend == "anthropic"
        assert b.endpoints == []
        assert b.model is None

    def test_extract_and_synthesize_are_independent_instances(self):
        cfg = EnsembleConfig()
        cfg.extract.endpoints.append("http://spark:8001/v1")
        assert cfg.synthesize.endpoints == []


# ── Strictness: the whole point of the new schema ──────────────────────────

class TestStrict:
    def test_unknown_root_key_rejected(self):
        with pytest.raises(Exception):
            EnsembleConfig.model_validate({"nonsense": 1})

    def test_the_six_legacy_planning_keys_are_rejected_at_the_root(self):
        """These are exactly what EnsembleSynthesize.vue wrote into the loose
        ui.ensemble section. They belong under `planning` now; at the root
        they must fail rather than accumulate unread."""
        for key in (
            "planning_synth_mode", "planning_npc", "planning_arc_scores",
            "planning_context", "planning_depth", "planning_force_include",
        ):
            with pytest.raises(Exception):
                EnsembleConfig.model_validate({key: "whatever"})

    def test_singular_endpoint_rejected(self):
        """config_models.BackendProfile's singular `endpoint` is the shape the
        system stopped using. EnsembleBackend declares the plural one, and the
        singular must not silently pass through."""
        with pytest.raises(Exception):
            EnsembleBackend.model_validate({"endpoint": "http://spark:8001/v1"})

    def test_campaign_dir_rejected(self):
        """Platform-tier value; Phase 0 deleted the ensemble copy."""
        with pytest.raises(Exception):
            EnsembleConfig.model_validate({"campaign_dir": "/tmp/x"})

    def test_bad_backend_literal_rejected(self):
        with pytest.raises(Exception):
            EnsembleBackend.model_validate({"backend": "ollama"})

    @pytest.mark.parametrize("field,bad", [("synth_mode", "auto"), ("depth", "deep")])
    def test_planning_literals_enforced(self, field, bad):
        with pytest.raises(Exception):
            EnsemblePlanning.model_validate({field: bad})


# ── Round-trip ─────────────────────────────────────────────────────────────

class TestLoadSave:
    def test_missing_file_is_all_defaults_not_an_error(self, tmp_path):
        assert load_ensemble_config(tmp_path / "nope.yaml") == EnsembleConfig()

    def test_empty_file_reads_as_defaults(self, tmp_path):
        """The 'emptied file reads back as 400' bug planning-isolation.md had
        to fix twice — not re-introduced here."""
        p = tmp_path / "ensemble.yaml"
        p.write_text("", encoding="utf-8")
        assert load_ensemble_config(p) == EnsembleConfig()

    def test_null_document_reads_as_defaults(self, tmp_path):
        p = tmp_path / "ensemble.yaml"
        p.write_text("---\n", encoding="utf-8")
        assert load_ensemble_config(p) == EnsembleConfig()

    def test_malformed_yaml_raises_valueerror(self, tmp_path):
        p = tmp_path / "ensemble.yaml"
        p.write_text("paths: [unclosed\n", encoding="utf-8")
        with pytest.raises(ValueError):
            load_ensemble_config(p)

    def test_round_trip_preserves_every_group(self, tmp_path):
        p = tmp_path / "cfg" / "ensemble.yaml"
        cfg = EnsembleConfig.model_validate({
            "chapters_selected": ["docs/chapters/chapter_01.md"],
            "extract": {"backend": "dgx", "endpoints": ["http://spark:8001/v1",
                                                        "http://spark2:8001/v1"]},
            "synthesize": {"backend": "anthropic", "model": "claude-opus-5"},
            "paths": {"chapters_glob": "book/ch_*.md",
                      "inventory": "docs/background/inv.md"},
            "tuning": {"chapter_parallel": 6},
            "planning": {"synth_mode": "flat", "depth": "full",
                         "npc": ["docs/npcs/npc_a.md"]},
        })
        save_ensemble_config(p, cfg)
        assert load_ensemble_config(p) == cfg

    def test_save_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "deep" / "nested" / "ensemble.yaml"
        save_ensemble_config(p, EnsembleConfig())
        assert p.exists()

    def test_saved_file_is_plain_readable_yaml(self, tmp_path):
        """Hand-editable, like every other config in this repo — no python
        object tags, no flow style."""
        p = tmp_path / "ensemble.yaml"
        save_ensemble_config(p, EnsembleConfig())
        raw = p.read_text(encoding="utf-8")
        assert "!!python" not in raw
        assert isinstance(yaml.safe_load(raw), dict)

    def test_save_leaves_no_tmp_file_behind(self, tmp_path):
        p = tmp_path / "ensemble.yaml"
        save_ensemble_config(p, EnsembleConfig())
        assert list(tmp_path.glob("*.tmp*")) == []

    def test_inventory_path_round_trips(self, tmp_path):
        p = tmp_path / "ensemble.yaml"
        cfg = EnsembleConfig.model_validate(
            {"paths": {"inventory": "docs/background/inv.md"}}
        )
        save_ensemble_config(p, cfg)
        assert load_ensemble_config(p).paths.inventory == "docs/background/inv.md"


# ── Legacy pruning: the migrate-and-delete shim for pre-migration files ────

class TestLegacyPruning:
    def test_legacy_known_names_and_aliases_path_load_successfully(self, tmp_path):
        """A pre-migration ensemble.yaml carrying the retired known_names/
        aliases_path keys must still load — the model is extra="forbid", so
        without pruning this would 400 every config/run route."""
        p = tmp_path / "ensemble.yaml"
        p.write_text(
            "known_names: [docs/names.md]\n"
            "aliases_path: docs/ensemble/aliases.json\n",
            encoding="utf-8",
        )
        cfg = load_ensemble_config(p)
        assert not hasattr(cfg, "known_names")
        assert not hasattr(cfg, "aliases_path")

    def test_saving_a_pruned_legacy_config_writes_a_clean_file(self, tmp_path):
        """Read-only prune: load doesn't rewrite the file, but the next save
        (a PUT) leaves it without the retired keys."""
        p = tmp_path / "ensemble.yaml"
        p.write_text(
            "known_names: [docs/names.md]\n"
            "aliases_path: docs/ensemble/aliases.json\n",
            encoding="utf-8",
        )
        cfg = load_ensemble_config(p)
        save_ensemble_config(p, cfg)
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert "known_names" not in raw
        assert "aliases_path" not in raw
