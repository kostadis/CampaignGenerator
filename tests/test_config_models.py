"""Tests for server/config_models.py — pydantic v2 typed sections.

The whole point of these models is that the worked example from
docs/configuration.md (``sd_narrate_tokens: '4000'`` shadowing the
in-code default ``16000``) becomes structurally impossible: a stringy
int is coerced at the type boundary, an empty string falls back to
the default.

The session-editor config isolation (Phase 5,
docs/config/session-editor-isolation.md) removed ``session_doc``/
``profiles`` from ``UISection`` — that data now lives in the Session Doc
Editor's own ``<config>/session_doc.yaml`` (see
``server/session_editor_config_shared.py`` /
``tests/test_session_editor_config_service.py``), not in
``server/config_models.py``. The stringy-int / empty-string-path coercion
behavior this module's motivating example describes is demonstrated below
against fields that are still part of ``UISection``.

The platform config isolation (Phase 2, docs/config/platform-isolation.md)
moved ``LocalConfig``/``ServerSection``/``NavSection`` out of this module
entirely, to ``server/platform_config_shared.py`` — see
``tests/test_platform_config_service.py`` for their (now strict) coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config_models import (
    SCHEMA_VERSION,
    UIState,
    UI_SECTION_NAMES,
)
from server.grounding_config_shared import GroundingRun


class TestOptStrCoercion:
    """``OptStr``'s ``_empty_to_none`` BeforeValidator. Exercised through
    whichever model still uses the annotated type — first ``VttSummarySection``,
    then ``GroundingSection``, both now retired; the coercion is a property of
    the type, not of any one section. ``GroundingRun`` (grounding.yaml) is the
    current host."""

    def test_empty_strings_normalize_to_none(self):
        assert GroundingRun(input="").input is None
        assert GroundingRun(input=" ").input is None
        assert GroundingRun(input="x").input == "x"

    def test_strict_model_rejects_unknown_field(self):
        # Unlike the extra="allow" ui.<section> blobs it replaced,
        # GroundingConfig's models are strict: a typo is an error at the
        # boundary, not unvalidated overflow nothing ever reads.
        with pytest.raises(ValidationError):
            GroundingRun(some_new_field="hi")


class TestUIState:
    def test_default_version_is_schema_version(self):
        assert UIState().version == SCHEMA_VERSION

    def test_section_names_match_ui_attributes(self):
        # The migrator validates section names against UI_SECTION_NAMES;
        # they must stay in sync with the model fields.
        assert "query" in UI_SECTION_NAMES
        assert "experimental" in UI_SECTION_NAMES
        # The five grounding sections moved to <config>/grounding.yaml in
        # Phase 10 of the grounding isolation. A PUT to any of them must 404
        # rather than write a section nothing reads — two of them
        # (campaign_state, distill) were never written by the UI at all.
        for retired in ("grounding", "campaign_state", "distill", "party", "planning"):
            assert retired not in UI_SECTION_NAMES
        # session_doc/profiles moved out of ui_state.yaml entirely in the
        # session-editor config isolation (Phase 5) — they now live in the
        # Session Doc Editor's own <config>/session_doc.yaml, so they must
        # NOT be writable typed UI sections any more.
        assert "session_doc" not in UI_SECTION_NAMES
        assert "profiles" not in UI_SECTION_NAMES
        # Retired with the vtt_summary chain — a PUT to it must 404 rather
        # than silently create a section nothing reads.
        assert "vtt_summary" not in UI_SECTION_NAMES

    def test_stale_vtt_summary_block_loads_and_is_ignored(self):
        """An unmigrated campaign's ``ui.vtt_summary:`` must not break boot.

        ``UISection`` is not ``extra="allow"``, so pydantic's default
        ``ignore`` drops the retired block instead of raising — the same
        non-breaking path ``ui.session_doc``/``ui.ensemble`` took.
        """
        s = UIState.model_validate(
            {"ui": {"vtt_summary": {"input": "session.vtt"}, "query": {}}}
        )
        assert not hasattr(s.ui, "vtt_summary")
        assert "vtt_summary" not in s.ui.model_dump(mode="json")

    def test_round_trip_preserves_typed_values(self):
        original = UIState()
        original.ui.query.input = "summaries.md"
        dumped = original.model_dump(mode="json")
        round_tripped = UIState.model_validate(dumped)
        assert round_tripped.ui.query.input == "summaries.md"

    def test_legacy_unmigrated_quarantine_preserved(self):
        s = UIState(legacy={"unmigrated": {"weird_key": "value"}})
        assert s.legacy.unmigrated == {"weird_key": "value"}

    def test_old_ui_state_with_session_doc_loads_and_drops_it(self):
        # extra="ignore" (pydantic v2 default) on UISection means an old
        # ui_state.yaml carrying ui.session_doc / ui.profiles still loads
        # without error — those keys are just dropped, not preserved.
        raw = {
            "version": 2,
            "ui": {
                "session_doc": {"narrate_tokens": 4000},
                "profiles": {"profiles": [{"name": "Fast"}], "active": "Fast"},
                "query": {"input": "summaries.md"},
            },
        }
        state = UIState.model_validate(raw)
        assert state.ui.query.input == "summaries.md"
        assert not hasattr(state.ui, "session_doc")
        assert not hasattr(state.ui, "profiles")
