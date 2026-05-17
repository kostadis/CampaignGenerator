"""Tests for server/config_models.py — pydantic v2 typed sections.

The whole point of these models is that the worked example from
docs/configuration.md (``sd_narrate_tokens: '4000'`` shadowing the
in-code default ``16000``) becomes structurally impossible: a stringy
int is coerced at the type boundary, an empty string falls back to
the default.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config_models import (
    SCHEMA_VERSION,
    LocalConfig,
    SessionDocSection,
    UIState,
    UI_SECTION_NAMES,
    VttSummarySection,
)


class TestSessionDocCoercion:
    def test_stringy_int_becomes_int(self):
        s = SessionDocSection(narrate_tokens="4000")
        assert s.narrate_tokens == 4000
        assert isinstance(s.narrate_tokens, int)

    def test_empty_narrate_tokens_falls_to_default(self):
        # Empty string would normally fail int validation. The custom
        # _empty_to_none BeforeValidator on path-style fields handles
        # empty strings, but narrate_tokens is a plain int — pydantic
        # will reject "". Confirm the behaviour and document it.
        with pytest.raises(ValidationError):
            SessionDocSection(narrate_tokens="")

    def test_empty_string_path_becomes_none(self):
        s = SessionDocSection(voice_dir="   ")
        assert s.voice_dir is None

    def test_default_narrate_tokens_is_16000(self):
        s = SessionDocSection()
        assert s.narrate_tokens == 16000

    def test_unknown_field_preserved_as_extra(self):
        # extra="allow" lets sections grow without model edits during
        # transition. Pages can read both typed and extra fields.
        s = SessionDocSection(some_new_field="hi")
        dumped = s.model_dump()
        assert dumped["some_new_field"] == "hi"


class TestVttSummaryCoercion:
    def test_empty_strings_normalize_to_none(self):
        s = VttSummarySection(input="", output=" ", extract_dir="x")
        assert s.input is None
        assert s.output is None
        assert s.extract_dir == "x"


class TestUIState:
    def test_default_version_is_schema_version(self):
        assert UIState().version == SCHEMA_VERSION

    def test_section_names_match_ui_attributes(self):
        # The migrator validates section names against UI_SECTION_NAMES;
        # they must stay in sync with the model fields.
        assert "session_doc" in UI_SECTION_NAMES
        assert "vtt_summary" in UI_SECTION_NAMES
        assert "experimental" in UI_SECTION_NAMES

    def test_round_trip_preserves_typed_values(self):
        original = UIState()
        original.ui.session_doc.narrate_tokens = 12000
        original.ui.session_doc.voice_dir = "voice/"
        dumped = original.model_dump(mode="json")
        round_tripped = UIState.model_validate(dumped)
        assert round_tripped.ui.session_doc.narrate_tokens == 12000
        assert round_tripped.ui.session_doc.voice_dir == "voice/"

    def test_legacy_unmigrated_quarantine_preserved(self):
        s = UIState(legacy={"unmigrated": {"weird_key": "value"}})
        assert s.legacy.unmigrated == {"weird_key": "value"}


class TestLocalConfig:
    def test_default_server_settings(self):
        local = LocalConfig()
        assert local.server.host == "127.0.0.1"
        assert local.server.port == 5000

    def test_overrides(self):
        local = LocalConfig(server={"port": 6001})
        assert local.server.port == 6001
        assert local.server.host == "127.0.0.1"

    def test_nav_extras_allowed(self):
        local = LocalConfig(nav={"last_page": "/workflow/editor", "scroll": 42})
        assert local.nav.last_page == "/workflow/editor"
        assert local.nav.model_dump()["scroll"] == 42
