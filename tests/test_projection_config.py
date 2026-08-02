"""Schema + load/save tests for campaignlib/projection_config.py.

Phase 2 (Foundational) of specs/006-state-projection-service. Pure model
tests — no service, no HTTP, no filesystem beyond a tmp_path round-trip.
Mirrors tests/test_ensemble_config_shared.py's shape.
"""

from __future__ import annotations

import sys
import typing
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel

from campaignlib.projection_config import (
    ProjectionConfig,
    ProjectionInputs,
    ProjectionOutput,
    ProjectionStores,
    load_projection_config,
    save_projection_config,
)


# ── Strictness: unknown keys must not accumulate unread ─────────────────────

class TestStrict:
    def test_unknown_root_key_rejected(self):
        with pytest.raises(Exception):
            ProjectionConfig.model_validate({"nonsense": 1})

    def test_unknown_stores_key_rejected(self):
        with pytest.raises(Exception):
            ProjectionStores.model_validate({"extra_store": "x"})

    def test_unknown_inputs_key_rejected(self):
        with pytest.raises(Exception):
            ProjectionInputs.model_validate({"extra_input": "x"})

    def test_unknown_output_key_rejected(self):
        with pytest.raises(Exception):
            ProjectionOutput.model_validate({"extra_output": "x"})

    def test_unknown_nested_key_rejected_via_root(self):
        with pytest.raises(Exception):
            ProjectionConfig.model_validate({"stores": {"bogus": "x"}})


# ── output.draft validator (data-model.md §1 validation rule 2) ────────────

class TestDraftValidator:
    def test_draft_without_doc_placeholder_rejected(self):
        with pytest.raises(Exception):
            ProjectionOutput.model_validate({"draft": "docs/projections/draft.md"})

    def test_draft_with_doc_placeholder_accepted(self):
        out = ProjectionOutput.model_validate(
            {"draft": "docs/projections/{doc}_draft.md"}
        )
        assert out.draft == "docs/projections/{doc}_draft.md"

    def test_draft_validator_fires_through_the_root_model(self):
        with pytest.raises(Exception):
            ProjectionConfig.model_validate({"output": {"draft": "no_placeholder.md"}})

    def test_default_draft_satisfies_its_own_validator(self):
        """The shipped default must not be the thing the validator rejects."""
        assert "{doc}" in ProjectionOutput().draft


# ── Round-trip ────────────────────────────────────────────────────────────

class TestLoadSave:
    def test_missing_file_is_all_defaults_not_an_error(self, tmp_path):
        assert load_projection_config(tmp_path / "nope.yaml") == ProjectionConfig()

    def test_empty_file_reads_as_defaults(self, tmp_path):
        p = tmp_path / "projections.yaml"
        p.write_text("", encoding="utf-8")
        assert load_projection_config(p) == ProjectionConfig()

    def test_null_document_reads_as_defaults(self, tmp_path):
        p = tmp_path / "projections.yaml"
        p.write_text("---\n", encoding="utf-8")
        assert load_projection_config(p) == ProjectionConfig()

    def test_malformed_yaml_raises_valueerror(self, tmp_path):
        p = tmp_path / "projections.yaml"
        p.write_text("stores: [unclosed\n", encoding="utf-8")
        with pytest.raises(ValueError):
            load_projection_config(p)

    def test_paths_round_trip_exactly_as_authored(self, tmp_path):
        """No absolutisation anywhere in load/save — a relative path written
        by the GM must come back byte-identical, not resolved against cwd or
        the config file's own location (research D14)."""
        p = tmp_path / "cfg" / "projections.yaml"
        cfg = ProjectionConfig.model_validate({
            "stores": {
                "events": "custom/events.jsonl",
                "thread_registry": "custom/threads.yaml",
                "thread_proposals": "custom/proposals.yaml",
                "tracking": "custom/tracking*.txt",
            },
            "inputs": {
                "dossiers": "custom/dossiers",
                "dossiers_fallback": "custom/dossiers_fallback",
                "narrative_importance": "custom/importance.yaml",
                "party": "custom/party.md",
                "planning_notes": "custom/planning_notes.md",
                "speculations": "custom/speculations.md",
            },
            "output": {
                "sections_dir": "custom/sections",
                "draft": "custom/{doc}_draft.md",
                "legacy_draft": "custom/{doc}_legacy.md",
                "recent_events": "custom/recent_events.md",
                "recent_events_window": 6,
            },
        })
        save_projection_config(p, cfg)
        loaded = load_projection_config(p)
        assert loaded == cfg
        assert loaded.stores.events == "custom/events.jsonl"
        assert loaded.output.draft == "custom/{doc}_draft.md"
        assert loaded.output.recent_events_window == 6

    def test_save_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "deep" / "nested" / "projections.yaml"
        save_projection_config(p, ProjectionConfig())
        assert p.exists()

    def test_saved_file_is_plain_readable_yaml(self, tmp_path):
        p = tmp_path / "projections.yaml"
        save_projection_config(p, ProjectionConfig())
        raw = p.read_text(encoding="utf-8")
        assert "!!python" not in raw
        assert isinstance(yaml.safe_load(raw), dict)

    def test_save_leaves_no_tmp_file_behind(self, tmp_path):
        p = tmp_path / "projections.yaml"
        save_projection_config(p, ProjectionConfig())
        assert list(tmp_path.glob("*.tmp*")) == []

    def test_defaults_match_data_model_md(self):
        """Transcribed from data-model.md §1's example YAML. If this drifts,
        the spec and the code have quietly diverged."""
        cfg = ProjectionConfig()
        assert cfg.stores.events == "docs/ensemble/events.jsonl"
        assert cfg.stores.thread_registry == "docs/thread_registry.yaml"
        assert cfg.stores.thread_proposals == "docs/ensemble/thread_proposals.yaml"
        assert cfg.stores.tracking == "docs/tracking*.txt"
        assert cfg.inputs.dossiers == "docs/ensemble/merged_dossiers"
        assert cfg.inputs.dossiers_fallback == "docs/ensemble/state_dossiers"
        assert cfg.inputs.narrative_importance == "docs/ensemble/narrative_importance.yaml"
        assert cfg.inputs.party == "docs/party.md"
        assert cfg.inputs.planning_notes == "docs/planning_notes.md"
        assert cfg.inputs.speculations == "notes/thread_speculations.md"
        assert cfg.output.sections_dir == "docs/grounding_sections"
        assert cfg.output.draft == "docs/projections/{doc}_draft.md"
        assert cfg.output.legacy_draft == "docs/{doc}_draft.md"
        assert cfg.output.recent_events == "docs/recent_events.md"
        assert cfg.output.recent_events_window == 0
        assert cfg.selection.is_empty()


# ── No scope creep: the two fields this schema must never grow ─────────────

class TestNoScopeCreep:
    """Guards research D6/FR-013 (no `corpus`) and FR-014 (no `sections`/
    `specs`) against a later, well-meaning "completion" of this schema.

    `corpus` stays a required CLI argument on every consumer precisely so
    there is no config default that means "everything" (Constitution X) — a
    `stores.corpus` or `inputs.corpus` field would manufacture exactly that
    default by the back door. `sections`/`specs` stays in Python (which
    sections exist, and which document each belongs to) rather than becoming
    data, per FR-014 — a config field here would let the section map drift
    from the code that actually renders it.

    Field names are inspected recursively via `model_fields` on every nested
    BaseModel reachable from ProjectionConfig, not via a string search over
    the source — a field renamed to dodge a grep would still be caught.
    """

    FORBIDDEN = {"corpus", "sections", "specs"}

    @staticmethod
    def _unwrap(annotation: object) -> list[object]:
        """Flatten Optional[...]/list[...]/etc. down to their leaf types."""
        origin = typing.get_origin(annotation)
        if origin is None:
            return [annotation]
        leaves: list[object] = []
        for arg in typing.get_args(annotation):
            leaves.extend(TestNoScopeCreep._unwrap(arg))
        return leaves

    @classmethod
    def _reachable_models(cls, model: type[BaseModel]) -> set[type[BaseModel]]:
        seen: set[type[BaseModel]] = set()
        stack = [model]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            for field in current.model_fields.values():
                for leaf in cls._unwrap(field.annotation):
                    if isinstance(leaf, type) and issubclass(leaf, BaseModel):
                        stack.append(leaf)
        return seen

    def test_no_corpus_or_sections_field_anywhere(self):
        models = self._reachable_models(ProjectionConfig)
        assert len(models) >= 4, (
            "sanity check: expected to reach ProjectionConfig, ProjectionStores, "
            "ProjectionInputs, ProjectionOutput (and ModelSelection); "
            f"only found {[m.__name__ for m in models]}"
        )
        offenders: dict[str, set[str]] = {}
        for model_cls in models:
            hit = self.FORBIDDEN & set(model_cls.model_fields)
            if hit:
                offenders[model_cls.__name__] = hit
        assert not offenders, (
            f"forbidden fields present: {offenders} — corpus stays a required "
            "CLI arg (research D6/FR-013) and the section map stays in code "
            "(FR-014); neither belongs in projections.yaml"
        )

    def test_guard_detects_a_violation(self):
        """The guard above is only meaningful if it can actually fail."""

        class _Bad(BaseModel):
            corpus: str = "docs/**/*.md"

        assert self._reachable_models(_Bad) == {_Bad}
        assert self.FORBIDDEN & set(_Bad.model_fields) == {"corpus"}
