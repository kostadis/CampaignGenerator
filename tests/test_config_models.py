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
    VttSummarySection,
)


class TestVttSummaryCoercion:
    def test_empty_strings_normalize_to_none(self):
        s = VttSummarySection(input="", output=" ", extract_dir="x")
        assert s.input is None
        assert s.output is None
        assert s.extract_dir == "x"

    def test_unknown_field_preserved_as_extra(self):
        # extra="allow" lets sections grow without model edits during
        # transition. Pages can read both typed and extra fields.
        s = VttSummarySection(some_new_field="hi")
        dumped = s.model_dump()
        assert dumped["some_new_field"] == "hi"


class TestUIState:
    def test_default_version_is_schema_version(self):
        assert UIState().version == SCHEMA_VERSION

    def test_section_names_match_ui_attributes(self):
        # The migrator validates section names against UI_SECTION_NAMES;
        # they must stay in sync with the model fields.
        assert "vtt_summary" in UI_SECTION_NAMES
        assert "experimental" in UI_SECTION_NAMES
        # session_doc/profiles moved out of ui_state.yaml entirely in the
        # session-editor config isolation (Phase 5) — they now live in the
        # Session Doc Editor's own <config>/session_doc.yaml, so they must
        # NOT be writable typed UI sections any more.
        assert "session_doc" not in UI_SECTION_NAMES
        assert "profiles" not in UI_SECTION_NAMES

    def test_round_trip_preserves_typed_values(self):
        original = UIState()
        original.ui.vtt_summary.session_summary = "session-summary.md"
        original.ui.grounding.summaries = "summaries.md"
        dumped = original.model_dump(mode="json")
        round_tripped = UIState.model_validate(dumped)
        assert round_tripped.ui.vtt_summary.session_summary == "session-summary.md"
        assert round_tripped.ui.grounding.summaries == "summaries.md"

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
                "vtt_summary": {"input": "x.vtt"},
            },
        }
        state = UIState.model_validate(raw)
        assert state.ui.vtt_summary.input == "x.vtt"
        assert not hasattr(state.ui, "session_doc")
        assert not hasattr(state.ui, "profiles")
